#!/usr/bin/env python3
"""
Generate a CR for one or more recordings by calling OpenRouter (DeepSeek V4 Flash)
and inserting the result into the `crs` table via PostgREST.

Use this when cronjob(action='run') is blocked by "Already being fired by the
scheduler" or when the scheduler is frozen. Equivalent to what the pipeline cron
does, but as a standalone script.

Usage:
    # Single recording
    python3 generate_cr.py <recording_id>

    # Batch: all recordings in status='transcribed' with enterprise_id
    python3 generate_cr.py --batch

    # Dry-run: show what would be generated, don't insert
    python3 generate_cr.py <recording_id> --dry-run

Requires:
    - SUPABASE_URL, SUPABASE_ANON_KEY, OPENROUTER_API_KEY in env or .env
    - Service account password (default: Herone2026test, override via SUPABASE_SERVICE_PASSWORD)
"""
import json
import os
import re
import sys
import time
import urllib.request

# ── Load .env for cron sessions ──
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
        except Exception:
            pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ezqbxfmafvdjtgrrxcxy.supabase.co")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SERVICE_PASSWORD = os.environ.get("SUPABASE_SERVICE_PASSWORD", "Herone2026test")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OWNER_ID = os.environ.get("PLAUDIA_OWNER_ID", "79d6876b-bc72-424b-8c23-8c485eaa1b57")
MODEL = os.environ.get("CR_MODEL", "deepseek/deepseek-v4-flash")

_SERVICE_JWT = None
_SERVICE_JWT_EXPIRES = 0

# ── Glossary — will be augmented from DB ──
_GLOSSARY_HARDCODED = {
    "Eron": "Hérone",
    "INX": "Hynix",
    "Ati": "Hati",
    "Xombo": "Lixogo",
    "Ouigo": "Ewigo",
    "XOGO": "Lixogo",
}
_GLOSSARY_CACHE = None


def fetch_glossary_from_db():
    """Fetch glossary entries from Supabase and merge with hardcoded defaults.
    DB entries (both shared and personal) take priority over hardcoded ones.
    Cached for the lifetime of the process since the pipeline is short-lived.
    """
    global _GLOSSARY_CACHE
    if _GLOSSARY_CACHE is not None:
        return _GLOSSARY_CACHE
    merged = dict(_GLOSSARY_HARDCODED)
    try:
        jwt = get_service_jwt()
        headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {jwt}"}
        raw = http_request(
            f"{SUPABASE_URL}/rest/v1/glossary?select=term_raw,term_corrected&order=term_raw.asc",
            headers, method="GET", timeout=10,
        )
        rows = json.loads(raw)
        for g in rows:
            merged[g["term_raw"]] = g["term_corrected"]
        print(f"  Glossary: {len(rows)} DB entries + {len(_GLOSSARY_HARDCODED)} hardcoded = {len(merged)} total")
    except Exception as e:
        print(f"  ⚠️ Could not fetch glossary from DB, using hardcoded ({len(_GLOSSARY_HARDCODED)} entries): {e}")
    _GLOSSARY_CACHE = merged
    return merged


def apply_glossary(text):
    """Apply word-boundary-matched glossary corrections from merged DB + hardcoded."""
    glossary = fetch_glossary_from_db()
    for raw, corrected in glossary.items():
        text = re.sub(rf"\b{re.escape(raw)}\b", corrected, text)
    return text


def http_request(url, headers, body=None, method="POST", timeout=180):
    headers = {"User-Agent": "curl/8.5.0", **headers}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def get_service_jwt():
    global _SERVICE_JWT, _SERVICE_JWT_EXPIRES
    now = time.time()
    if _SERVICE_JWT and _SERVICE_JWT_EXPIRES > now + 120:
        return _SERVICE_JWT
    body = {"email": "martin@herone.fr", "password": SERVICE_PASSWORD}
    raw = http_request(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        body,
    )
    data = json.loads(raw)
    _SERVICE_JWT = data["access_token"]
    _SERVICE_JWT_EXPIRES = now + data.get("expires_in", 3600)
    return _SERVICE_JWT


def fetch_recording(recording_id):
    """Fetch recording details via PostgREST."""
    jwt = get_service_jwt()
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {jwt}"}
    raw = http_request(
        f"{SUPABASE_URL}/rest/v1/recordings"
        f"?select=id,plaud_file_id,title,raw_transcript,recorded_at,duration_seconds,"
        f"enterprise_id,project_id,client_name&id=eq.{recording_id}",
        headers,
        method="GET",
        timeout=15,
    )
    rows = json.loads(raw)
    if not rows:
        print(f"ERROR: recording {recording_id} not found")
        sys.exit(2)
    return rows[0]


def call_llm(system_prompt, transcript):
    """Call OpenRouter with the CR generation prompt and transcript."""
    if not OPENROUTER_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(2)

    raw = http_request(
        "https://openrouter.ai/api/v1/chat/completions",
        {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Génère le CR de cette transcription :\n\n{transcript}"},
            ],
            "temperature": 0.3,
            "max_tokens": 8000,
        },
    )
    return json.loads(raw)["choices"][0]["message"]["content"]


def extract_html(llm_response):
    """Extract CR HTML from the LLM response, handling various formats."""
    # Try <CR>...</CR> first
    m = re.search(r"<CR>(.*?)</CR>", llm_response, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Try <!DOCTYPE html> or <html>
    m = re.search(r"(<!DOCTYPE html>.*?</html>)", llm_response, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Try <article class="cr-document">
    m = re.search(r"(<article[^>]*class=\"cr-document\".*?</article>)", llm_response, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Fallback: return the whole response
    return llm_response.strip()


def build_cr_html(recording, llm_html):
    """Wrap the LLM-generated article content in full HTML document with CSS."""
    # Read the CSS template from the skill's reference
    css = """
.cr-document {
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  color: #374151;
  max-width: 760px;
  margin: 0 auto;
  padding: 52px 60px;
  font-size: 14px;
  line-height: 1.75;
  background: #ffffff;
}
.cr-logo { font-size: 26px; font-weight: 800; letter-spacing: 6px; color: #1e3a5f; margin: 0 0 4px 0; line-height: 1; }
.cr-subtitle { color: #6b7280; font-size: 13px; margin: 0 0 16px 0; font-weight: 400; }
.cr-divider { border: none; border-top: 1px solid #e5e7eb; margin: 0 0 20px 0; }
.cr-meta { display: grid; grid-template-columns: auto 1fr; gap: 5px 14px; margin-bottom: 32px; }
.cr-meta dt { font-weight: 600; color: #111827; white-space: nowrap; }
.cr-meta dt::after { content: " :"; }
.cr-meta dd { margin: 0; color: #374151; }
.cr-section { margin-bottom: 8px; }
.cr-section-title { color: #1e3a5f; font-size: 18px; font-weight: 700; margin: 36px 0 0 0; padding-bottom: 10px; border-bottom: 1px solid #e5e7eb; line-height: 1.3; }
.cr-section:first-of-type .cr-section-title { margin-top: 24px; }
.cr-subsection { margin-top: 4px; }
.cr-subsection-title { color: #1d4ed8; font-size: 14px; font-weight: 600; margin: 20px 0 6px 0; line-height: 1.4; }
.cr-body { margin: 10px 0; hyphens: auto; color: #374151; }
.cr-list { margin: 10px 0 10px 22px; padding: 0; color: #374151; }
.cr-list li { margin: 7px 0; padding-left: 4px; }
.cr-table { width: 100%; border-collapse: collapse; margin-top: 14px; }
.cr-table td { padding: 11px 15px; vertical-align: top; border: 1px solid #e5e7eb; }
.cr-table-label { font-weight: 600; color: #fff; width: 28%; font-size: 13px; vertical-align: middle; }
.cr-label-blue { background-color: #1e3a5f; }
.cr-table-content { background-color: #fff; color: #374151; width: 72%; }
.cr-footer { margin-top: 52px; padding-top: 16px; border-top: 1px solid #e5e7eb; text-align: center; font-size: 12px; color: #9ca3af; }
.cr-footer p { margin: 0; }
"""
    if llm_html.startswith("<!DOCTYPE html>"):
        return llm_html
    if llm_html.startswith("<article"):
        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>{css}</style>
</head>
<body>
{llm_html}
</body>
</html>"""
    return llm_html


def insert_cr(recording_id, html_content, enterprise_id, project_id):
    """Insert CR into `crs` table via PostgREST."""
    jwt = get_service_jwt()
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {jwt}",
               "Content-Type": "application/json", "Prefer": "return=minimal"}
    body = {
        "recording_id": recording_id,
        "owner_id": OWNER_ID,
        "content": html_content,
        "version": 1,
        "status": "ready",
    }
    if enterprise_id:
        body["enterprise_id"] = enterprise_id
    if project_id:
        body["project_id"] = project_id
    http_request(
        f"{SUPABASE_URL}/rest/v1/crs",
        headers,
        body=body,
        method="POST",
        timeout=15,
    )


def update_recording_status(recording_id, title=None):
    """Mark recording as ready and optionally update its title."""
    jwt = get_service_jwt()
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {jwt}",
               "Content-Type": "application/json", "Prefer": "return=minimal"}
    body = {"status": "ready"}
    if title:
        body["title"] = title
    http_request(
        f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{recording_id}",
        headers,
        body=body,
        method="PATCH",
        timeout=15,
    )


def process_recording(recording_id, dry_run=False):
    """Full pipeline for one recording: fetch transcript, generate CR, insert."""
    print(f"\\n{'='*60}")
    print(f"Processing recording: {recording_id}")
    print(f"{'='*60}")

    rec = fetch_recording(recording_id)
    title = rec.get("title", "?")
    raw_transcript = rec.get("raw_transcript", "")
    enterprise_id = rec.get("enterprise_id")
    project_id = rec.get("project_id")
    client_name = rec.get("client_name", "")

    print(f"  Title: {title}")
    print(f"  Enterprise: {enterprise_id or 'None'}")
    print(f"  Transcript: {len(raw_transcript) if raw_transcript else 0} chars")

    if not raw_transcript or len(raw_transcript) < 50:
        print(f"  SKIP: transcript too short or empty")
        return False

    # Apply glossary
    transcript = apply_glossary(raw_transcript)
    print(f"  Glossary applied")

    # Build system prompt
    system_prompt = f"""Tu es le générateur de comptes-rendus de réunion de Plaudia, pour Hérone.

RÈGLES NON NÉGOCIABLES :
- Ton factuel, neutre, à la troisième personne.
- Prose narrative continue. PAS de synthèse — c'est une RETRANSCRIPTION DÉTAILLÉE de la réunion. Tu dois retranscrire tous les échanges en préservant les chiffres, dates, noms, arguments, décisions, questions, réponses, et contexte. Ne supprime RIEN d'important. Ne raccourcis PAS.
- AUCUNE LIMITE DE LONGUEUR. Le CR doit refléter la réunion dans son intégralité — chaque sous-sujet, chaque donnée chiffrée, chaque nom cité, chaque décision, chaque objection, chaque question en suspens. Si la transcription fait 80 000 caractères, le CR peut faire 10 000 mots ou plus.
- Titres H2 thématiques et spécifiques, jamais génériques ("Discussion", "Points évoqués").
- Glossaire appliqué avant tout traitement.
- Structure HTML : <article class="cr-document" data-format="A4"> avec header <p class="cr-logo">H É R O N E</p> + <dl class="cr-meta"> (dt/dd) > sections (cr-section, cr-section-title, cr-body, cr-subsection avec avoid-break) > tableau final obligatoire (cr-table, cr-label-blue) > footer.
- Utilise <div class="page-break"> entre les sections principales et <section class="avoid-break"> sur les blocs insécables.
- Retourne UNIQUEMENT le HTML, sans commentaire avant/après.

CONTEXTE :
- Client : {client_name or "Non spécifié"}
- Enregistrement : {title}"""

    # Call LLM
    print(f"  Calling LLM ({MODEL})...")
    llm_response = call_llm(system_prompt, transcript)
    html = extract_html(llm_response)
    full_html = build_cr_html(rec, html)
    print(f"  HTML generated: {len(full_html)} chars")

    if dry_run:
        print(f"  [DRY-RUN] Would insert CR and update recording status")
        print(f"  HTML preview: {full_html[:200]}...")
        return True

    # Insert CR
    insert_cr(recording_id, full_html, enterprise_id, project_id)
    print(f"  CR inserted into crs")

    # Update recording
    update_recording_status(recording_id)
    print(f"  Recording status -> ready")

    # Brief pause between recordings
    time.sleep(1)
    return True


def fetch_batch():
    """Fetch all recordings ready for pipeline processing."""
    jwt = get_service_jwt()
    headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {jwt}"}
    raw = http_request(
        f"{SUPABASE_URL}/rest/v1/recordings"
        f"?select=id,title,enterprise_id,client_name,raw_transcript,recorded_at"
        f"&status=eq.transcribed&enterprise_id=not.is.null"
        f"&order=recorded_at.asc&limit=5",
        headers,
        method="GET",
        timeout=15,
    )
    return json.loads(raw)


def main():
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        sys.argv.remove("--dry-run")

    if "--batch" in sys.argv:
        recordings = fetch_batch()
        if not recordings:
            print("No recordings in status='transcribed' with enterprise_id.")
            # Also check orphans
            jwt = get_service_jwt()
            headers = {"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {jwt}"}
            orphans_raw = http_request(
                f"{SUPABASE_URL}/rest/v1/recordings"
                f"?select=id,title,raw_transcript,recorded_at,duration_seconds"
                f"&status=eq.transcribed&enterprise_id=is.null",
                headers,
                method="GET", timeout=15,
            )
            orphans = json.loads(orphans_raw)
            if orphans:
                print(f"\\n⚠️  {len(orphans)} orphan recordings (transcribed but no enterprise):")
                for o in orphans:
                    has_rt = "yes" if o.get("raw_transcript") else "NO"
                    dur = o.get("duration_seconds", 0)
                    print(f"     {o['id'][:12]}... | {o.get('title','?')} | {dur}s | transcript={has_rt}")
            return

        print(f"Found {len(recordings)} recordings to process")
        success = 0
        for rec in recordings:
            ok = process_recording(rec["id"], dry_run=dry_run)
            if ok:
                success += 1
        print(f"\\nDone: {success}/{len(recordings)} CRs generated")
    else:
        if len(sys.argv) < 2:
            print("Usage: python3 generate_cr.py <recording_id> [--dry-run]")
            print("       python3 generate_cr.py --batch [--dry-run]")
            sys.exit(1)
        recording_id = sys.argv[1]
        ok = process_recording(recording_id, dry_run=dry_run)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()