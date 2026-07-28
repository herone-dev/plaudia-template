#!/usr/bin/env python3
"""
Plaudia watchdog — récupère les nouveaux fichiers Plaud et les insère en base.
0-LLM cost (pur script Python, pas d'appel LLM).

Utilise l'API PostgREST avec JWT du service account (pas de token Management API).

Routine :
  1. Liste les fichiers Plaud récents via l'API MCP
  2. Compare avec recordings.plaud_file_id (via PostgREST)
  3. Pour chaque nouveau fichier :
     a. get_file → metadata (created_at, serial_number, start_at, duration)
     b. get_transcript → segments avec timestamps
     c. INSERT dans recordings (status='transcribed') via PostgREST
  4. Déclenche le pipeline LLM (cron) pour générer les CRs
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional

# ── Chargement du .env pour les crons (qui n'ont pas les vars d'env) ──
_env_loaded = False
for _env_path in ["/opt/data/.env", os.path.expanduser("~/.env")]:
    if os.path.exists(_env_path):
        try:
            with open(_env_path) as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k = _k.strip()
                        _v = _v.strip().strip("\"'")
                        if _k and not os.environ.get(_k):
                            os.environ[_k] = _v
                            _env_loaded = True
        except Exception:
            pass

PLAUD_TOKEN_PATH = "/opt/data/mcp-tokens/plaud.json"
PLAUD_CLIENT_PATH = "/opt/data/mcp-tokens/plaud.client.json"
PLAUD_META_PATH = "/opt/data/mcp-tokens/plaud.meta.json"
PLAUD_MCP_URL = "https://mcp.plaud.ai/mcp"

SUPABASE_URL = "https://ezqbxfmafvdjtgrrxcxy.supabase.co"
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

OWNER_ID = "79d6876b-bc72-424b-8c23-8c485eaa1b57"

LLM_JOB_ID = "d4777fc4327a"
N_RECENT = 20

# Cache du JWT service account
_SERVICE_JWT = None
_SERVICE_JWT_EXPIRES = 0


def http_request(url, headers, body=None, method="POST", timeout=30):
    """Effectue une requête HTTP et retourne la réponse (str)."""
    headers = {"User-Agent": "curl/8.5.0", **headers}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def get_service_jwt():
    """Obtient un JWT frais via sign-in avec le service account."""
    global _SERVICE_JWT, _SERVICE_JWT_EXPIRES
    now = time.time()
    if _SERVICE_JWT and _SERVICE_JWT_EXPIRES > now + 120:
        return _SERVICE_JWT
    body = {
        "email": "martin@herone.fr",
        "password": "Herone2026test",
    }
    raw = http_request(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        {
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json",
        },
        body,
    )
    data = json.loads(raw)
    _SERVICE_JWT = data["access_token"]
    _SERVICE_JWT_EXPIRES = now + data.get("expires_in", 3600)
    return _SERVICE_JWT


def supabase_select(columns, table, filters=None):
    """SELECT via PostgREST. Retourne la liste des rows."""
    jwt = get_service_jwt()
    url = f"{SUPABASE_URL}/rest/v1/{table}?select={columns}"
    if filters:
        url += f"&{filters}"
    raw = http_request(
        url,
        {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/json",
        },
        method="GET",
    )
    return json.loads(raw)


def supabase_insert(table, row_data):
    """INSERT via PostgREST. Retourne le status code."""
    jwt = get_service_jwt()
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    raw = http_request(
        url,
        {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        row_data,
    )
    return raw


def supabase_update(table, row_data, id_filter):
    """UPDATE via PostgREST PATCH. row_data = {col: val, ...}, id_filter = 'id=eq.uuid'"""
    jwt = get_service_jwt()
    url = f"{SUPABASE_URL}/rest/v1/{table}?{id_filter}"
    http_request(
        url,
        {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        row_data,
        method="PATCH",
    )


def plaud_call(token, method, args):
    """Appelle une méthode MCP Plaud et retourne le résultat parsé."""
    body = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": method, "arguments": args},
    }
    raw = http_request(
        PLAUD_MCP_URL,
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        body,
    )
    for line in raw.strip().splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            result = data.get("result", {})
            if isinstance(result, dict) and "content" in result:
                text = result["content"][0]["text"]
                return json.loads(text)
            return result
    return None


def load_plaud_token():
    """Charge ou rafraîchit le token Plaud."""
    with open(PLAUD_TOKEN_PATH) as f:
        tok = json.load(f)
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    with open(PLAUD_CLIENT_PATH) as f:
        client = json.load(f)
    with open(PLAUD_META_PATH) as f:
        meta = json.load(f)
    form = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "client_id": client["client_id"],
    }).encode("utf-8")
    req = urllib.request.Request(
        meta["token_endpoint"], data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        new_tok = json.loads(resp.read().decode("utf-8"))
    new_tok["expires_at"] = time.time() + new_tok.get("expires_in", 86400)
    with open(PLAUD_TOKEN_PATH, "w") as f:
        json.dump(new_tok, f)
    return new_tok["access_token"]


def get_existing_file_ids():
    """Récupère les plaud_file_id déjà présents en base."""
    rows = supabase_select("plaud_file_id", "recordings", "plaud_file_id=not.is.null")
    return {r["plaud_file_id"] for r in rows}


def parse_transcript_segments(transcript_data):
    """Extrait les segments timestampés de la transcription Plaud."""
    segments = []
    if isinstance(transcript_data, list):
        for item in transcript_data:
            if item.get("data_type") == "transaction":
                raw = json.loads(item.get("data_content", "[]"))
                for seg in raw:
                    segments.append({
                        "speaker": seg.get("speaker", seg.get("original_speaker", "Speaker")),
                        "original_speaker": seg.get("original_speaker", seg.get("speaker", "")),
                        "content": seg.get("content", ""),
                        "start_time": seg.get("start_time", 0),
                        "end_time": seg.get("end_time", 0),
                    })
    return segments


def format_raw_transcript(segments):
    """Construit le texte brut : 'Speaker : content'."""
    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "Speaker")
        content = seg.get("content", "").strip()
        if content:
            lines.append(f"{speaker} : {content}")
    return "\n".join(lines)


def main():
    try:
        token = load_plaud_token()
    except Exception as e:
        print(f"[plaudia-watchdog] Erreur auth Plaud: {e}")
        return

    # Précharge la liste des entreprises et projets pour attribution
    enterprises = []
    projects = []
    try:
        rows = supabase_select("id,name", "enterprises", "order=name.asc")
        enterprises = [(r["id"], r["name"]) for r in rows]
        print(f"[plaudia-watchdog] {len(enterprises)} entreprise(s) chargée(s)")
        prows = supabase_select("id,enterprise_id,name", "projects", "order=enterprise_id,name.asc")
        projects = [(r["id"], r["enterprise_id"], r["name"]) for r in prows]
    except Exception as e:
        print(f"[plaudia-watchdog] ⚠️ Impossible de charger les entreprises: {e}")

    def detect_enterprise(title: str) -> tuple[Optional[str], Optional[str], list]:
        """Détecte l'entreprise depuis le TITRE uniquement.
        
        ATTENTION: Ne JAMAIS scanner la transcription — le transcript peut mentionner
        n'importe quelle entreprise comme sujet ou exemple (ex: 'Avenir 85' cité dans
        une conversation avec un client AQCF). Seul le titre du fichier Plaud est fiable
        car c'est l'utilisateur qui le nomme explicitement.
        """
        t = title.lower()
        for eid, ename in enterprises:
            en = ename.lower()
            if en in t:  # match dans le titre uniquement
                cand_projects = [pid for pid, peid, _ in projects if peid == eid]
                return eid, ename, cand_projects
        return None, None, []

    def detect_project(title: str, cand_ids: list) -> Optional[str]:
        t = title.lower()
        for pid, peid, pname in projects:
            if pid in cand_ids and pname.lower() in t:
                return pid
        return None

    try:
        files = plaud_call(token, "list_files", {"page": 1, "page_size": N_RECENT})
        if isinstance(files, dict) and "data" in files:
            files = files["data"]
        if not files:
            return
    except Exception as e:
        print(f"[plaudia-watchdog] Erreur list_files: {e}")
        return

    existing_ids = get_existing_file_ids()
    new_files = [f for f in files if f.get("id") not in existing_ids]

    # ── Phase A : fichiers nouveaux (jamais vus) ──
    if new_files:
        print(f"[plaudia-watchdog] {len(new_files)} nouveau(x) fichier(s) détecté(s)")

    # ── Phase B : retry transcription pour les fichiers déjà en base mais sans transcript ──
    retry_recordings = []
    try:
        retry_rows = supabase_select(
            "id,plaud_file_id,title",
            "recordings",
            "status=eq.transcribed&raw_transcript=is.null&plaud_file_id=not.is.null&duration_seconds=gt.60&order=created_at.desc&limit=10"
        )
        retry_recordings = retry_rows
    except Exception as e:
        print(f"[plaudia-watchdog] ⚠️ Erreur check retry: {e}")

    if retry_recordings:
        print(f"[plaudia-watchdog] {len(retry_recordings)} enregistrement(s) à retenter (sans transcript)")

    processed = 0
    all_to_process = []

    # Préparer les fichiers à traiter : nouveaux fichiers
    for f in new_files:
        all_to_process.append({
            "type": "new",
            "plaud_file_id": f["id"],
            "title": f.get("name", ""),
            "start_at": f.get("start_at", ""),
            "duration_ms": int(f.get("duration", 0)),
        })

    # Préparer les fichiers à retenter + réattribuer
    for r in retry_recordings:
        all_to_process.append({
            "type": "retry",
            "recording_id": r["id"],
            "plaud_file_id": r["plaud_file_id"],
            "title": r.get("title", ""),
            "start_at": "",
            "duration_ms": 0,
        })

    if not all_to_process:
        return  # SILENT — rien à faire

    for item in all_to_process:
        fid = item["plaud_file_id"]
        title = item["title"]
        start_at = item["start_at"]
        duration_ms = item["duration_ms"]
        is_retry = item["type"] == "retry"
        recording_id = item.get("recording_id")

        print(f"  → {'[RETRY]' if is_retry else '[NEW]'} {title} ({fid})")

        try:
            # Métadonnées complètes (toujours utile même pour retry)
            meta = plaud_call(token, "get_file", {"file_id": fid})
            plaud_created = meta.get("created_at", "")
            serial = meta.get("serial_number", "")

            # Pour les retry, récupérer les infos manquantes depuis Plaud
            if is_retry:
                plaud_name = meta.get("name", "")
                plaud_duration = int(meta.get("duration", 0))
                plaud_start = meta.get("start_at", "")
                if not title and plaud_name:
                    title = plaud_name
                if not start_at and plaud_start:
                    start_at = plaud_start
                if not duration_ms and plaud_duration:
                    duration_ms = plaud_duration

            # Vérifier si privé
            is_private = "[PRIVE]" in title.upper() or "[PERSO]" in title.upper()

            # Transcription
            segments = []
            if not is_private:
                try:
                    transcript_data = plaud_call(token, "get_transcript", {"file_id": fid})
                    segments = parse_transcript_segments(transcript_data)
                except Exception as e:
                    print(f"    ⚠️ get_transcript échoué: {e}")

            raw_text = format_raw_transcript(segments) if segments else None
            segs_json = json.dumps(segments, ensure_ascii=True) if segments else None

            # Détection entreprise depuis le titre uniquement (pas le transcript — trop de faux positifs)
            ent_id, ent_name, cand_projects = detect_enterprise(title)
            proj_id = detect_project(title, cand_projects) if cand_projects else None
            client_name = ent_name or ""

            # INSERT dans recordings via PostgREST
            recorded_at = start_at.replace("T", " ").replace("Z", "+00") if start_at else None
            plaud_created_esc = plaud_created.replace("T", " ").replace("Z", "+00") if plaud_created else None

            row = {
                "plaud_file_id": fid,
                "title": title[:500],
                "recorded_at": recorded_at,
                "duration_seconds": duration_ms // 1000,
                "plaud_created_at": plaud_created_esc,
                "serial_number": serial[:200] if serial else None,
                "transcript_segments": segs_json,
                "raw_transcript": raw_text[:100000] if raw_text else None,
                "is_private": is_private,
                "status": "transcribed",
                "owner_id": OWNER_ID,
                "enterprise_id": ent_id,
                "project_id": proj_id,
                "client_name": client_name or None,
            }
            # Remove None values (nulls in JSON)
            row = {k: v for k, v in row.items() if v is not None}

            try:
                if is_retry:
                    # UPDATE l'enregistrement existant (ne pas recréer)
                    upd = {k: v for k, v in row.items()
                           if v is not None and k not in ("plaud_file_id", "owner_id", "recorded_at")}
                    supabase_update("recordings", upd, f"id=eq.{recording_id}")
                    print(f"    ✅ Retry: transcription + attribution mise à jour")
                else:
                    supabase_insert("recordings", row)
                processed += 1
                if ent_id:
                    proj_name = next((p[2] for p in projects if p[0] == proj_id), "")
                    print(f"    ✅ Attribué à {ent_name}{' / ' + proj_name if proj_name else ''}")
                else:
                    print(f"    ✅ {len(segments)} segments — status=transcribed (entreprise non détectée)")
            except Exception as e:
                resp_str = str(e)
                if "409" in resp_str or "duplicate" in resp_str.lower() or "conflict" in resp_str.lower():
                    print(f"    ⏭️ Déjà présent en base (ignoré)")
                else:
                    print(f"    ❌ Erreur write: {e}")

        except Exception as e:
            print(f"    ❌ Erreur traitement: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(0.3)

    if processed > 0:
        print(f"[plaudia-watchdog] {processed} fichier(s) traité(s), déclenchement du pipeline CR...")
        subprocess.run(["hermes", "cron", "run", LLM_JOB_ID], check=False, capture_output=True, timeout=30)


if __name__ == "__main__":
    main()