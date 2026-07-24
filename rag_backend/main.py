#!/usr/bin/env python3
"""
Plaudia RAG-chat backend - OpenAI-compatible endpoint consumed by the Lovable frontend.

Architecture CQRS : seules les ecritures avec logique metier passent par ce backend.
Les lectures (GET) vont directement de Supabase au frontend via PostgREST.
"""
import os

import re
import json
import time
import subprocess
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from google_integration import export_cr_to_google_doc, send_or_draft_email
from auth import (
    extract_user_context, get_service_token, get_service_owner_id,
    sb_headers as _sb_headers_service, SUPABASE_URL, SUPABASE_ANON_KEY as ANON_KEY,
)

# ============================================================
# Configuration — TOUTES en variables d'environnement
# ============================================================
# Variables requises :
#   SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_EMAIL,
#   SUPABASE_SERVICE_PASSWORD, OPENAI_API_KEY, OPENROUTER_API_KEY
# ============================================================

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
# DeepSeek V4 Flash via OpenRouter
OPUS_MODEL = "deepseek/deepseek-v4-flash"
OPENAI_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# How many prior exchanges (user+assistant pairs) get replayed to Claude as context.
_HISTORY_TURNS = 4

app = FastAPI(title="Plaudia RAG Chat Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate limiting: simple in-memory sliding window per client IP. ---
_RATE_LIMIT_MAX = 500
_RATE_LIMIT_WINDOW = 60
_rate_buckets: dict[str, deque] = defaultdict(deque)


def check_rate_limit(client_ip: str):
    now = time.time()
    bucket = _rate_buckets[client_ip]
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Trop de requêtes — réessaie dans une minute.")
    bucket.append(now)


# ============================================================
# JWT Auth — remplacer le shared key par le token Supabase Auth
# ============================================================
# Le frontend envoie le JWT dans le header Authorization: Bearer <token>
# Le backend extrait user_id, email, et role du token.
# Pour les endpoints internes (cron, pipeline), on utilise le service account.
# ============================================================

def get_current_user(request: Request, require_auth: bool = True) -> dict:
    """Extract user context from JWT in Authorization header.
    
    Returns dict with: user_id, email, role, is_service
    Falls back to service account if no JWT and require_auth=False.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        ctx = extract_user_context(token)
        if ctx:
            return ctx
    
    # Fallback: try X-Plaudia-Key (legacy support pour les crons)
    # Si une clé partagée est configurée dans l'env, on l'accepte
    legacy_key = os.environ.get("PLAUDIA_SHARED_KEY", "")
    if legacy_key:
        provided = request.headers.get("x-plaudia-key", "")
        if provided == legacy_key:
            return {
                "user_id": get_service_owner_id(),
                "email": "service@plaudia.local",
                "role": "admin",
                "is_service": True,
            }
    
    if require_auth:
        raise HTTPException(
            status_code=401,
            detail="Authentification requise — envoie un token Supabase Auth dans Authorization: Bearer <token>"
        )
    
    # Default: service account
    return {
        "user_id": get_service_owner_id(),
        "email": "service@plaudia.local",
        "role": "admin",
        "is_service": True,
    }


def sb_headers(user_token: str = None):
    """Headers for Supabase REST API calls.
    
    If user_token is provided, use it (respects RLS).
    Otherwise, use service account (bypasses RLS — for cron/pipeline).
    """
    if user_token:
        return {
            "apikey": ANON_KEY,
            "Authorization": f"Bearer {user_token}",
            "Content-Type": "application/json",
        }
    return _sb_headers_service()


def http_json(method, url, headers=None, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} calling {url}: {e.read().decode()[:500]}")


_enterprises_cache = {"list": None, "fetched_at": 0}


def get_known_enterprises():
    """Retourne [(enterprise_id, name)] depuis la table enterprises (pas recordings)."""
    now = time.time()
    if _enterprises_cache["list"] is not None and now - _enterprises_cache["fetched_at"] < 300:
        return _enterprises_cache["list"]
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/enterprises?owner_id=eq.{get_service_owner_id()}&select=id,name",
        headers=sb_headers(),
    )
    enterprises = [(r["id"], r["name"]) for r in (rows or []) if r.get("name")]
    _enterprises_cache["list"] = enterprises
    _enterprises_cache["fetched_at"] = now
    return enterprises


def detect_enterprise(question: str) -> tuple[Optional[str], Optional[str]]:
    """Détecte l'enterprise dans la question. Retourne (enterprise_id, enterprise_name)."""
    q_lower = question.lower()
    for eid, name in get_known_enterprises():
        if name.lower() in q_lower:
            return (eid, name)
    return (None, None)


def embed(text: str):
    d = http_json(
        "POST", "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        body={"model": "text-embedding-3-small", "input": text},
        timeout=30,
    )
    return d["data"][0]["embedding"]


def match_rag_chunks(embedding, client_name: Optional[str] = None, match_count: int = 20,
                     enterprise_id: Optional[str] = None, project_id: Optional[str] = None):
    return http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/rpc/match_rag_chunks",
        headers=sb_headers(),
        body={
            "query_embedding": embedding,
            "filter_client_name": client_name,
            "match_count": match_count,
            "filter_enterprise_id": enterprise_id,
            "filter_project_id": project_id,
        },
        timeout=30,
    )


def match_rag_chunks_hybrid(embedding, question: str, client_name: Optional[str] = None,
                            match_count: int = 20, enterprise_id: Optional[str] = None,
                            project_id: Optional[str] = None):
    """Hybrid search: vector similarity + full-text search combined."""
    return http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/rpc/match_rag_chunks_hybrid",
        headers=sb_headers(),
        body={
            "query_embedding": embedding,
            "search_query": question,
            "match_count": match_count,
            "vector_weight": 0.6,
            "fts_weight": 0.4,
            "filter_client_name": client_name,
            "filter_enterprise_id": enterprise_id,
            "filter_project_id": project_id,
        },
        timeout=30,
    )


GLOSSARY_DETECT_PROMPT = """Tu es un détecteur de corrections orthographiques. L'utilisateur écrit un message.
Analyse s'il s'agit d'une instruction de correction d'orthographe ou de nom.
Exemples de corrections :
- "on écrit Anti Hati" → correction: le terme "Anti" doit devenir "Hati"
- "le client s'appelle Dupont Menuiserie pas Dupont" → correction: "Dupont" → "Dupont Menuiserie"
- "c'est Hati avec un H" → correction: "Ati" → "Hati"
- "HATI s'écrit en majuscules" → correction: "Hati" → "HATI"
- "corrige le nom du client en Hérone" → correction: pas de terme brut → "Hérone"
- "c'est Lixogo pas XOGO" → correction: "XOGO" → "Lixogo"
- "c'est Hati et non Ati" → correction: "Ati" → "Hati"
- "on dit Ewigo pas Ouigo" → correction: "Ouigo" → "Ewigo"
- "le client s'appelle Hynix" → correction: "Hynix" est le nom correct (pas de terme brut)

Réponds UNIQUEMENT au format JSON :
  {"is_correction": true, "term_raw": "mot_brut", "term_corrected": "mot_corrigé"}
  {"is_correction": false}

Si c'est une correction :
- term_raw = le mot/terme incorrect (tel qu'il apparaît actuellement)
- term_corrected = la version corrigée
- Ne mets PAS de guillemets ni de formatage autour du JSON."""


def detect_glossary_correction(question: str) -> Optional[dict]:
    """Check if the user's message is a spelling/name correction instruction."""
    # Quick regex pre-check: contains correction keywords
    # Catches: "écrit", "corrige", "orthographe", "c'est X pas Y", "c'est X et non Y", "on dit X"
    correction_patterns = [
        r"\b(écrit|corrige|correction|orthographe|renomme|appelle|s'appelle)\b",
        r"\b(on écrit|il faut écrire|doit s'écrire)\b",
        r"\b(c'est\s+\S+\s+pas\s+|c'est\s+\S+\s+et\s+non\s+|c'était\s+\S+\s+pas\s+)\b",
        r"\b(pas\s+\S+\s+mais\s+|appelle-moi\s+|nomme\s+)\b",
    ]
    has_hint = any(re.search(p, question, re.IGNORECASE) for p in correction_patterns)
    if not has_hint:
        return None

    try:
        reply = call_opus(GLOSSARY_DETECT_PROMPT, [{"role": "user", "content": question}], max_tokens=256)
        # Extract JSON from the response
        match = re.search(r"\{[^}]+\}", reply)
        if not match:
            return None
        result = json.loads(match.group(0))
        if result.get("is_correction") and result.get("term_raw") and result.get("term_corrected"):
            return result
    except Exception:
        return None
    return None


def apply_glossary_correction(term_raw: str, term_corrected: str, owner_id: str):
    """Insert a correction into the glossary table. The DB trigger
    (apply_glossary_correction_retroactively) will automatically rewrite
    all existing CRs with the corrected term."""
    try:
        http_json(
            "POST", f"{SUPABASE_URL}/rest/v1/glossary",
            headers={**sb_headers(), "Prefer": "return=minimal"},
            body={
                "owner_id": owner_id,
                "term_raw": term_raw.strip(),
                "term_corrected": term_corrected.strip(),
            },
        )
        return True
    except Exception:
        return False


def _format_date(iso_date: str) -> str:
    """Format ISO date to JJ/MM/AAAA, e.g. '2026-07-08T09:10:34+00:00' → '08/07/2026'"""
    if not iso_date:
        return ""
    try:
        # Try ISO format
        import datetime
        dt = datetime.datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        # Try plain date
        if len(iso_date) >= 10:
            parts = iso_date[:10].split("-")
            if len(parts) == 3:
                return f"{parts[2]}/{parts[1]}/{parts[0]}"
        return iso_date[:10]


def _format_duration(seconds: int) -> str:
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    parts = []
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}min")
    if s: parts.append(f"{s}s")
    return " ".join(parts) if parts else "0s"


TOOLS_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_transcription",
            "description": "Récupère la transcription brute d'un enregistrement par son ID. Utile pour relire le verbatim d'une réunion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recording_id": {
                        "type": "string",
                        "description": "UUID de l'enregistrement (recordings.id)"
                    }
                },
                "required": ["recording_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_duration",
            "description": "Récupère la durée d'un enregistrement par son ID. Utile pour répondre 'combien de temps a duré la réunion ?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "recording_id": {
                        "type": "string",
                        "description": "UUID de l'enregistrement (recordings.id)"
                    }
                },
                "required": ["recording_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_recordings",
            "description": "Liste les enregistrements (réunions) disponibles, avec filtres optionnels par client. Utile pour savoir quelles réunions existent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "Nom du client pour filtrer (optionnel)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Nombre max de résultats (défaut: 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        }
    }
]


def execute_tool_call(tool_call: dict) -> str:
    """Execute a tool call and return the result as a JSON string."""
    fn_name = tool_call.get("function", {}).get("name", "")
    try:
        args = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON arguments"})

    if fn_name == "get_transcription":
        rid = args.get("recording_id", "")
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{rid}&select=raw_transcript,client_name,meeting_subject",
            headers=sb_headers(),
        ) or []
        if not rows:
            return json.dumps({"error": "Enregistrement non trouvé"})
        r = rows[0]
        transcript = r.get("raw_transcript", "")
        return json.dumps({
            "recording_id": rid,
            "client_name": r.get("client_name"),
            "meeting_subject": r.get("meeting_subject"),
            "raw_transcript": transcript[:15000] if transcript else "Transcription non disponible",
            "transcript_length": len(transcript) if transcript else 0,
        })

    elif fn_name == "get_duration":
        rid = args.get("recording_id", "")
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{rid}&select=duration_seconds,client_name,meeting_subject,recorded_at",
            headers=sb_headers(),
        ) or []
        if not rows:
            return json.dumps({"error": "Enregistrement non trouvé"})
        r = rows[0]
        secs = r.get("duration_seconds") or 0
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        parts = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}min")
        if s: parts.append(f"{s}s")
        return json.dumps({
            "recording_id": rid,
            "client_name": r.get("client_name"),
            "meeting_subject": r.get("meeting_subject"),
            "duration_seconds": secs,
            "duration_human": " ".join(parts) if parts else "0s",
            "recorded_at": r.get("recorded_at", ""),
        })

    elif fn_name == "list_recordings":
        client_name = args.get("client_name")
        limit = args.get("limit", 10)
        filters = [f"status=eq.ready", f"limit={limit}"]
        if client_name:
            filters.append(f"client_name=eq.{urllib.parse.quote(client_name)}")
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/recordings?{'&'.join(filters)}"
            f"&select=id,client_name,meeting_subject,meeting_type,duration_seconds,recorded_at,title"
            f"&order=recorded_at.desc",
            headers=sb_headers(),
        ) or []
        results = []
        for r in rows:
            secs = r.get("duration_seconds") or 0
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            parts = []
            if h: parts.append(f"{h}h")
            if m: parts.append(f"{m}min")
            if s: parts.append(f"{s}s")
            results.append({
                "id": r["id"],
                "client_name": r.get("client_name"),
                "meeting_subject": r.get("meeting_subject"),
                "meeting_type": r.get("meeting_type"),
                "duration": " ".join(parts) if parts else "0s",
                "recorded_at": r.get("recorded_at", ""),
                "title": r.get("title", ""),
            })
        return json.dumps({"recordings": results, "count": len(results)})

    return json.dumps({"error": f"Fonction inconnue: {fn_name}"})


def call_opus(system_prompt: str, messages: list[dict], max_tokens: int = 1024,
              tools: Optional[list] = None) -> str:
    """Appelle DeepSeek V4 Flash via OpenRouter (format OpenAI-compatible)."""
    chat_messages = [{"role": "system", "content": system_prompt}]
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        # Si le contenu est une liste (Anthropic blocks), on fusionne en texte
        if isinstance(content, list):
            texts = [
                b.get("text", "") if isinstance(b, dict) else str(b)
                for b in content
            ]
            content = "\n".join(texts)
        chat_messages.append({"role": role, "content": content})

    body = {
        "model": OPUS_MODEL,
        "messages": chat_messages,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools

    d = http_json(
        "POST", OPENAI_CHAT_URL,
        headers={
            "Authorization": f"Bearer {OPENAI_KEY}",
            "Content-Type": "application/json",
        },
        body=body,
        timeout=120,
    )
    msg = d.get("choices", [{}])[0].get("message", {})
    # Handle tool calls
    if msg.get("tool_calls"):
        # Add the assistant's tool-call message to the conversation
        chat_messages.append(msg)
        for tc in msg["tool_calls"]:
            result = execute_tool_call(tc)
            chat_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })
        # Second LLM call with tool results
        body["messages"] = chat_messages
        body.pop("tools", None)
        d2 = http_json(
            "POST", OPENAI_CHAT_URL,
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            body=body,
            timeout=120,
        )
        return d2.get("choices", [{}])[0].get("message", {}).get("content", "")
    return msg.get("content", "")


RAG_SYSTEM_PROMPT = """Tu es l'assistant RAG de Plaudia pour Hérone. Tu réponds UNIQUEMENT à partir des extraits \
de comptes-rendus fournis ci-dessous — jamais de connaissance générale ni d'invention. \
Les extraits contiennent des métadonnées : tu as le nom du client, la date de la réunion, ET la durée \
(par exemple "30 min") quand elle est indiquée entre crochets après la date. Utilise ces informations \
pour répondre aux questions sur le temps passé.
Si les extraits ne permettent pas de répondre, dis-le clairement plutôt que de deviner. \
Cite le client, la date ET la durée de la réunion pour chaque fait avancé. Réponds en français, de façon directe et concrète, \
sans jargon corporate. Le message le plus récent peut faire référence au contexte des échanges précédents dans \
cette même conversation (ex: "et pour Hérone ?" après une question sur Allianz) — utilise cet historique pour \
comprendre l'intention, mais fonde toujours la réponse elle-même sur les extraits fournis pour CETTE question."""


def build_context_block(chunks):
    if not chunks:
        return "(Aucun extrait pertinent trouvé dans les comptes-rendus.)"
    parts = []
    for c in chunks:
        meta = c.get("metadata") or {}
        title = meta.get("section_title", c.get("chunk_type"))
        client = c.get("client_name") or "client non classé"
        date = c.get("meeting_date") or "date inconnue"
        duration = meta.get("duration_seconds")
        duration_str = f" — {_format_duration(duration)}" if duration else ""
        parts.append(f"[{client} — {date}{duration_str} — {title}]\n{c['content']}")
    return "\n\n---\n\n".join(parts)


# --- Chat session persistence ---

def create_chat_session(owner_id: str, title: str) -> str:
    rows = http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/chat_sessions",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body={"owner_id": owner_id, "title": title[:120]},
    )
    return rows[0]["id"]


def get_session_history(session_id: str, owner_id: str, limit_turns: int = _HISTORY_TURNS):
    """Returns the last `limit_turns` exchanges (up to 2*limit_turns messages), oldest first."""
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/chat_messages?session_id=eq.{session_id}&owner_id=eq.{owner_id}"
        f"&select=role,content,created_at&order=created_at.desc&limit={limit_turns * 2}",
        headers=sb_headers(),
    ) or []
    return list(reversed(rows))


def save_chat_message(session_id: str, owner_id: str, role: str, content: str):
    http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/chat_messages",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body={"session_id": session_id, "owner_id": owner_id, "role": role, "content": content},
    )


def session_exists(session_id: str, owner_id: str) -> bool:
    rows = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&owner_id=eq.{owner_id}&select=id",
        headers=sb_headers(),
    )
    return bool(rows)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    cr_id: Optional[str] = None  # sent by CRDetailView so edit requests can write back to the right row
    session_id: Optional[str] = None  # RAG chat thread id; omit to start a new conversation
    enterprise_id: Optional[str] = None  # filtre RAG sur une entreprise (legacy, single)
    project_id: Optional[str] = None  # filtre RAG sur un projet spécifique (legacy, single)
    enterprise_ids: Optional[list[str]] = None  # multi-enterprise filter (tags)
    project_ids: Optional[list[str]] = None  # multi-project filter (tags)
    cr_ids: Optional[list[str]] = None  # multi-CR filter (tags)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def update_cr_content(cr_id: str, new_content: str):
    """Writes the new CR content back to Supabase, preserving old version in cr_versions first."""
    current = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&select=version,content,owner_id",
        headers=sb_headers(),
    )
    current_version = (current[0]["version"] if current else 0) or 0
    owner_id = current[0].get("owner_id", get_service_owner_id()) if current else get_service_owner_id()

    # Save the OLD version to cr_versions before overwriting
    if current and current[0].get("content"):
        try:
            http_json(
                "POST", f"{SUPABASE_URL}/rest/v1/cr_versions",
                headers={**sb_headers(), "Prefer": "return=minimal"},
                body={
                    "cr_id": cr_id,
                    "version": current_version,
                    "content": current[0]["content"],
                    "owner_id": owner_id,
                },
            )
        except Exception:
            pass  # Ne jamais bloquer l'édition si la sauvegarde d'historique échoue

    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body={
            "content": new_content,
            "version": current_version + 1,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        },
    )
    return current_version + 1


def learn_from_cr_edit(instruction: str, cr_id: str):
    """Analyse une instruction d'édition de CR et enregistre la leçon dans cr_style_guide.
    Appelée après chaque édition réussie — ne doit jamais lever d'exception."""
    try:
        # 1. Récupérer le CR original
        current = http_json(
            "GET", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&select=content,last_edit_instruction,version",
            headers=sb_headers(),
        )
        if not current:
            return
        cr = current[0]
        old_content = cr.get("content", "")
        old_instruction = cr.get("last_edit_instruction", "")

        # 2. Demander à Claude d'extraire la leçon
        lesson_prompt = (
            "Tu analyses une modification de compte-rendu Hérone. "
            "L'utilisateur a donné cette instruction :\n"
            f"{instruction}\n\n"
            "Extrais UNE SEULE leçon de style/rédaction à retenir pour les futurs CRs. "
            "Si l'instruction est une correction ponctuelle (orthographe, mot spécifique), réponds EXACTEMENT: SKIP\n"
            "Si c'est une préférence de style, structure, format ou ton, réponds avec UNE consigne courte et précise "
            "en français, à injecter dans le prompt de génération des futurs CRs. "
            "Format : une phrase impérative, ex: 'Toujours mettre le tableau des décisions en premier.'"
        )
        lesson = call_opus(lesson_prompt, [{"role": "user", "content": instruction}], max_tokens=256).strip()

        if lesson in ("SKIP", ""):
            return  # Correction ponctuelle, pas de leçon à retenir

        # 3. Vérifier si une instruction similaire existe déjà
        existing = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/cr_style_guide?owner_id=eq.{get_service_owner_id()}&category=eq.style&select=id,instruction,applied_count",
            headers=sb_headers(),
        )
        for row in existing:
            if lesson[:40].lower() in row["instruction"].lower() or row["instruction"][:40].lower() in lesson.lower():
                # Instruction similaire existante → incrémenter le compteur
                http_json(
                    "PATCH",
                    f"{SUPABASE_URL}/rest/v1/cr_style_guide?id=eq.{row['id']}",
                    headers={**sb_headers(), "Prefer": "return=minimal"},
                    body={"applied_count": row["applied_count"] + 1, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())},
                )
                return

        # 4. Nouvelle leçon → l'insérer
        http_json(
            "POST", f"{SUPABASE_URL}/rest/v1/cr_style_guide",
            headers={**sb_headers(), "Prefer": "return=minimal"},
            body={
                "owner_id": get_service_owner_id(),
                "category": "style",
                "instruction": lesson,
                "source_cr_id": cr_id,
                "applied_count": 1,
            },
        )
    except Exception:
        pass  # L'apprentissage ne doit jamais casser l'édition


def load_style_guide(owner_id: Optional[str] = None) -> str:
    if owner_id is None:
        owner_id = get_service_owner_id()
    """Récupère toutes les leçons de style pour enrichir le prompt de génération CR."""
    try:
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/cr_style_guide?owner_id=eq.{owner_id}&order=applied_count.desc",
            headers=sb_headers(),
        )
        if not rows:
            return ""
        lessons = [f"- {r['instruction']}" for r in rows if r.get("instruction")]
        return "\n".join(["", "Rappels de style appris des éditions précédentes :"] + lessons)
    except Exception:
        return ""


# --- Chart rendering via matplotlib SVG ---
import subprocess

_CHART_RENDERER = "/opt/data/projects/plaudia/rag_backend/chart_renderer.py"
_CHART_PYTHON = "/opt/data/dwg-env/bin/python3"


def render_charts_in_cr(html: str) -> str:
    """Remplace les marqueurs chart-embed par des SVG inline générés par matplotlib.
    Format attendu : <script type="application/json" class="chart-embed">{"type":"bar",...}</script>
    """
    def _replace_chart(match):
        try:
            data_json = match.group(1)
            proc = subprocess.run(
                [_CHART_PYTHON, _CHART_RENDERER],
                input=data_json.encode("utf-8"),
                capture_output=True, timeout=30
            )
            if proc.returncode == 0:
                svg = proc.stdout.decode("utf-8").strip()
                if svg:
                    return svg
            return f"<!-- Erreur rendu graphique: {proc.stderr.decode()[:200]} -->"
        except Exception as e:
            return f"<!-- Erreur rendu graphique: {e} -->"

    import re
    pattern = r'<script\s+type="application/json"\s+class="chart-embed">(.*?)</script>'
    return re.sub(pattern, _replace_chart, html, flags=re.DOTALL)


# Cache pour le template shell (rafraîchi toutes les 5 min)
_template_cache = {"shell": None, "fetched_at": 0}


def get_template_shell() -> str:
    """Retourne le shell HTML complet (DOCTYPE + head + style + body) avec {{CONTENT}} comme placeholder."""
    now = time.time()
    if _template_cache["shell"] and now - _template_cache["fetched_at"] < 300:
        return _template_cache["shell"]
    try:
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/templates?is_default=eq.true&select=html_template",
            headers=sb_headers(),
        )
        css_block = rows[0]["html_template"] if rows and rows[0].get("html_template") else ""
    except Exception:
        css_block = ""
    shell = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{css_block}
</head>
<body>
{{{{CONTENT}}}}
</body>
</html>"""
    _template_cache["shell"] = shell
    _template_cache["fetched_at"] = now
    return shell


def extract_article(html: str) -> str:
    """Extrait le contenu de l'article <article>...</article> du HTML complet.
    Si aucun article trouvé, retourne le HTML original."""
    m = re.search(r"(<article[\s\S]*?</article>)", html, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else html


def render_cr(content: str) -> str:
    """Enveloppe le contenu (article) avec le template shell complet."""
    shell = get_template_shell()
    return shell.replace("{{CONTENT}}", content)


def get_client_ip(request: Request) -> str:
    # Behind cloudflared, request.client.host is the tunnel's local peer for
    # every caller — use the forwarded header when present so rate limiting
    # actually applies per real visitor, not per-tunnel-connection.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest, request: Request):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    user_messages = [m for m in req.messages if m.role == "user"]
    question = user_messages[-1].content if user_messages else ""

    # DEBUG: log every frontend request to a file
    import datetime
    _debug = f"[{datetime.datetime.now().isoformat()}] cr_id={req.cr_id} session_id={req.session_id} has_cr={'<CR>' in question} has_inst={'Instruction :' in question} qlen={len(question)} preview={question[:200]}"
    with open("/tmp/plaudia_debug.log", "a") as f:
        f.write(_debug + "\n")

    # --- Glossary/orthograph correction detection ---
    # If the user says "on écrit Anti Hati", detect it's a spelling correction,
    # insert into the glossary table, and the DB trigger automatically rewrites all CRs.
    correction = detect_glossary_correction(question)
    if correction:
        owner_id = user["user_id"]
        ok = apply_glossary_correction(correction["term_raw"], correction["term_corrected"], owner_id)
        if ok:
            msg = (
                f"Correction enregistrée : '{correction['term_raw']}' -> '{correction['term_corrected']}'. "
                "Tous les comptes-rendus existants sont mis a jour automatiquement."
            )
        else:
            msg = "La correction n'a pas pu etre enregistree. Reessaie."
        return _openai_response(msg)

    # The frontend's CRDetailView wraps the CR-edit instruction in a specific format:
    # "<CR>{html}</CR>\n\nInstruction : {msg}"
    # This flow stays stateless (no history, no session persistence) — it's a one-shot
    # instruction->CR round trip, unrelated to the RAG chat thread.
    # NOW ENRICHED : on récupère la transcription originale pour que le LLM ait tout le contexte.
    # Détection style vs contenu : si l'instruction parle de visuel (couleur, police, CSS, etc.),
    # on ne bloque plus le <style>.
    is_cr_edit_request = "<CR>" in question and "Instruction :" in question
    if is_cr_edit_request:
        if not req.cr_id:
            return _openai_response(
                "Impossible d'enregistrer : identifiant du compte-rendu manquant dans la requête. "
                "Corrige le texte directement puis utilise le bouton Enregistrer."
            )

        # DEBUG LOG
        import datetime
        print(f"[CR-EDIT {datetime.datetime.now().isoformat()}] cr_id={req.cr_id} question_len={len(question)} has_cr_tags={'<CR>' in question} has_instruction={'Instruction :' in question} msg_preview={question.split('Instruction :')[-1].strip()[:100] if 'Instruction :' in question else question[:100]}")

        # --- Détection style vs contenu ---
        instruction = question.split("Instruction :")[-1].strip() if "Instruction :" in question else question
        style_keywords = [
            r"\b(couleur|couleurs|color|colors)\b",
            r"\b(police|font|typo|taille|size)\b",
            r"\b(fond|background|marge|margin|padding|espacement)\b",
            r"\b(style|css|visuel|visuelle|apparence|look|design)\b",
            r"\b(bleu|orange|rouge|vert|gris|noir|blanc|#[\da-fA-F]{3,6})\b",
            r"\b(gras|italique|bold|italic|souligner|underline)\b",
            r"\b(logo|entête|en-tête|footer|pied de page|bande)\b",
        ]
        is_style_request = any(re.search(p, instruction, re.IGNORECASE) for p in style_keywords)

        # --- Récupérer la transcription originale pour enrichir le contexte ---
        raw_transcript = None
        try:
            cr_row = http_json(
                "GET", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{req.cr_id}&select=recording_id",
                headers=sb_headers(),
            )
            if cr_row and cr_row[0].get("recording_id"):
                rec_id = cr_row[0]["recording_id"]
                rec_row = http_json(
                    "GET", f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{rec_id}&select=raw_transcript",
                    headers=sb_headers(),
                )
                if rec_row and rec_row[0].get("raw_transcript"):
                    raw_transcript = rec_row[0]["raw_transcript"]
        except Exception:
            pass  # La transcription est optionnelle — on ne bloque pas l'édition si elle est indisponible

        # --- Extraire UNIQUEMENT le contenu <article> (pas le CSS/head/DOCTYPE) ---
        # Le frontend envoie le HTML complet, mais on ne donne que l'article à DeepSeek
        # pour économiser des tokens et éviter que DeepSeek modifie le style.
        cr_html_part = question
        article_content = extract_article(cr_html_part)

        # --- Construire le prompt système ---
        edit_system_prompt = (
            "Tu édites le contenu d'un compte-rendu de réunion Hérone. "
            "Tu travailles UNIQUEMENT sur le contenu à l'intérieur de la balise <article>.</article> — "
            "tu ne dois JAMAIS générer de <style>, <head>, DOCTYPE, ou <script> CDN Chart.js. "
            "Le CSS et le CDN Chart.js sont gérés automatiquement par le système. "
            "Génère UNIQUEMENT le contenu de l'article (<article class=\"cr-document\">...</article>). "
            "PRÉSERVE les SVG <svg> existants et les <div class=\"chart-container\"> — ne les supprime pas. "
            "Applique UNIQUEMENT l'instruction demandée, ne réécris pas tout le contenu. "
            "PRÉSERVE les tableaux <table class=\"cr-table\"> existants — ne les supprime pas, ne les convertis pas en texte. "
            "RÈGLE GRAPHIQUES : si l'utilisateur fournit des données pour un graphique, utilise ce format :\n"
            '<script type="application/json" class="chart-embed">\n'
            '{"type":"bar","title":"Titre","labels":["X","Y"],"datasets":[{"data":[10,20]}],"unit":"€"}\n'
            "</script>\n"
            "Types supportés: bar (vertical), doughnut (camembert troué), line (courbe). "
            "Le système convertit automatiquement ce marqueur en un beau graphique SVG aux couleurs Hérone. "
            "EXTRACTION AUTOMATIQUE : si l'utilisateur demande un graphique sans fournir les données, "
            "tu DOIS chercher dans la transcription jointe ci-dessous s'il y a des données chiffrées exploitables "
            "(budget, répartition, montants, durées, pourcentages, comparaisons). "
            "Si tu trouves des données pertinentes dans la transcription, crée un marqueur chart-embed avec ces données. "
            "Si tu ne trouves AUCUNE donnée chiffrée exploitable, réponds 'Je n'ai pas trouvé de données chiffrées dans la transcription pour créer un graphique.' "
            "N'invente JAMAIS de données. Utilise UNIQUEMENT les valeurs EXTRACTITES de la transcription."
            "IMPORTANT : Encadre ta réponse avec les balises <CR> et </CR> comme ceci :\n"
            "<CR>\n<article class=\"cr-document\">...\n</CR>\n"
            "Ne mets RIEN d'autre que le contenu de l'article entre les balises <CR>...</CR>."
        )

        if raw_transcript:
            enriched_question = (
                f"{question}\n\n"
                f"--- Transcription originale de la réunion ---\n"
                f"{raw_transcript[:80000]}"
            )
        else:
            enriched_question = question

        try:
            claude_reply = call_opus(edit_system_prompt, [{"role": "user", "content": enriched_question}], max_tokens=8192)
        except Exception as e:
            return _openai_response(f"Erreur lors de la génération de la modification : {e}")

        # Extraction du résultat : cherche d'abord <CR>...</CR>, puis <article> en fallback
        match = re.search(r"<CR>([\s\S]*?)</CR>", claude_reply)
        if match:
            new_article = match.group(1).strip()
        else:
            # Fallback : extraire directement l'article
            article_match = re.search(r"(<article[\s\S]*?</article>)", claude_reply, re.IGNORECASE | re.DOTALL)
            if article_match:
                new_article = article_match.group(1).strip()
            else:
                print(f"[CR-EDIT FAIL] DeepSeek n'a pas retourné d'article: {claude_reply[:500]}")
                return _openai_response(
                    "La modification n'a pas pu être extraite de la réponse — rien n'a été enregistré. "
                    "Réessaie ou corrige manuellement."
                )

        # Re-wrapper avec le template complet (CSS + head + CDN Chart.js)
        new_full_html = render_cr(new_article)

        # Remplacer les marqueurs chart-embed par des SVG inline (matplotlib)
        new_full_html = render_charts_in_cr(new_full_html)

        try:
            new_version = update_cr_content(req.cr_id, new_full_html)
        except Exception as e:
            return _openai_response(f"Modification générée mais échec de l'enregistrement en base : {e}")

        # --- Apprentissage : extraire la leçon de cette édition ---
        try:
            learn_from_cr_edit(instruction, req.cr_id)
        except Exception:
            pass  # L'apprentissage ne doit jamais bloquer l'édition

        confirmation = "Compte-rendu mis à jour."
        if match:
            confirmation = claude_reply.replace(match.group(0), "").strip() or confirmation
        return _openai_response(f"{confirmation}\n\n✅ Enregistré en base (version {new_version}).")

    # --- Plain RAG question flow, with persisted history ---
    owner_id = user["user_id"]

    session_id = req.session_id
    is_new_session = False
    if session_id and not session_exists(session_id, owner_id):
        session_id = None  # stale/foreign id — start fresh rather than erroring
    if not session_id:
        session_id = create_chat_session(owner_id, title=question)
        is_new_session = True

    prior_messages = [] if is_new_session else get_session_history(session_id, owner_id)

    detected_eid, detected_ename = detect_enterprise(question)
    effective_eid = req.enterprise_id or detected_eid

    # Support multi-enterprise/project (tags system)
    # If enterprise_ids or project_ids are provided (array), use those instead of single values
    multi_enterprise_ids = None
    multi_project_ids = None
    if req.enterprise_ids and len(req.enterprise_ids) > 0:
        multi_enterprise_ids = req.enterprise_ids
    elif effective_eid:
        multi_enterprise_ids = [effective_eid]

    if req.project_ids and len(req.project_ids) > 0:
        multi_project_ids = req.project_ids
    elif req.project_id:
        multi_project_ids = [req.project_id]

    try:
        q_embedding = embed(question)
        # Hybrid search: vector similarity + full-text search
        chunks = []
        if multi_enterprise_ids:
            for eid in multi_enterprise_ids:
                try:
                    batch = match_rag_chunks_hybrid(q_embedding, question, client_name=detected_ename,
                                                    enterprise_id=eid,
                                                    project_id=multi_project_ids[0] if multi_project_ids and len(multi_project_ids) == 1 else None) or []
                    chunks.extend(batch)
                except Exception:
                    pass
        else:
            chunks = match_rag_chunks_hybrid(q_embedding, question, client_name=detected_ename,
                                              enterprise_id=None,
                                              project_id=multi_project_ids[0] if multi_project_ids and len(multi_project_ids) == 1 else None) or []
        # Sort by similarity and dedup
        chunks.sort(key=lambda c: c.get("similarity", 0), reverse=True)
        seen = set()
        deduped = []
        for c in chunks:
            cid = c.get("id")
            if cid not in seen:
                seen.add(cid)
                deduped.append(c)
        chunks = deduped[:20]  # Cap at match_count
    except Exception as e:
        return _openai_response(f"Erreur lors de la recherche RAG : {e}", session_id=session_id)

    context_block = build_context_block(chunks)
    user_prompt = (
        f"Question : {question}\n\n"
        f"Enterprise détectée : {detected_ename or '(aucune — recherche non filtrée)'}\n\n"
        f"Extraits de comptes-rendus les plus pertinents :\n\n{context_block}"
    )

    claude_messages = [{"role": m["role"], "content": m["content"]} for m in prior_messages]
    claude_messages.append({"role": "user", "content": user_prompt})

    try:
        answer = call_opus(RAG_SYSTEM_PROMPT, claude_messages, tools=TOOLS_DEFINITIONS)
    except Exception as e:
        answer = f"Erreur lors de la génération de la réponse : {e}"

    # Persist the raw question/answer (not the RAG-augmented prompt) so history stays readable.
    try:
        save_chat_message(session_id, owner_id, "user", question)
        save_chat_message(session_id, owner_id, "assistant", answer)
    except Exception:
        pass  # don't fail the response if persistence hiccups

    return _openai_response(answer, session_id=session_id)


def _openai_response(content: str, session_id: Optional[str] = None):
    body = {
        "id": "plaudia-rag-chat",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "plaudia-rag",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    if session_id:
        body["session_id"] = session_id
    return JSONResponse(body)


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    tags: Optional[list] = None


@app.patch("/v1/chat/sessions/{session_id}")
def update_chat_session(session_id: str, req: UpdateSessionRequest, request: Request, plaudia_key: str = ""):
    """Met à jour le titre et/ou les tags d'une session."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    body = {}
    if req.title is not None:
        body["title"] = req.title
    if req.tags is not None:
        body["tags"] = json.dumps(req.tags)  # JSONB array
    if not body:
        return JSONResponse({"error": "Rien à mettre à jour"}, status_code=400)
    body["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body=body,
    )
    return JSONResponse({"updated": True})


@app.delete("/v1/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, request: Request, plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True})


# --- Enterprises & Projects GET endpoints (lectures directes CQRS — frontend appelle ces endpoints) ---


@app.get("/v1/enterprises")
def list_enterprises(request: Request, plaudia_key: str = ""):
    """Liste toutes les entreprises du owner."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/enterprises?owner_id=eq.{owner_id}&select=id,name,description,created_at",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/enterprises/{enterprise_id}/projects")
def list_enterprise_projects(enterprise_id: str, request: Request, plaudia_key: str = ""):
    """Liste les projets d'une entreprise."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/projects?enterprise_id=eq.{enterprise_id}&owner_id=eq.{owner_id}&select=id,enterprise_id,name,description,keywords,created_at",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/enterprises/with-counts")
def enterprises_with_counts(request: Request, plaudia_key: str = ""):
    """Retourne les entreprises avec leurs projets imbriqués, cr_count et recording_count.
    Format attendu par le front: (Enterprise & { projects: Project[]; cr_count: number; recording_count: number })[]"""
    user = get_current_user(request)
    owner_id = user["user_id"]

    ents = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/enterprises?owner_id=eq.{owner_id}&select=id,name,description",
        headers=sb_headers(),
    ) or []
    ent_ids = [e["id"] for e in ents]

    # Batch: fetch all projects, CR counts, and recording counts in 3 queries
    proj_map = {}
    cr_count_map = {}
    rec_count_map = {}

    if ent_ids:
        ent_filter = "or=(" + ",".join(f"enterprise_id.eq.{eid}" for eid in ent_ids) + ")"
        try:
            projects = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/projects?{ent_filter}&owner_id=eq.{owner_id}&select=id,enterprise_id,name,description,keywords,created_at",
                headers=sb_headers(),
            ) or []
            for p in projects:
                eid = p.get("enterprise_id", "")
                proj_map.setdefault(eid, []).append({
                    "id": p["id"],
                    "enterprise_id": eid,
                    "name": p.get("name", ""),
                    "description": p.get("description"),
                    "keywords": p.get("keywords"),
                    "created_at": p.get("created_at"),
                })
        except Exception:
            pass

        try:
            crs = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/crs?{ent_filter}&owner_id=eq.{owner_id}&select=enterprise_id",
                headers=sb_headers(),
            ) or []
            for c in crs:
                eid = c.get("enterprise_id", "")
                cr_count_map[eid] = cr_count_map.get(eid, 0) + 1
        except Exception:
            pass

        try:
            recs = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/recordings?{ent_filter}&owner_id=eq.{owner_id}&select=enterprise_id",
                headers=sb_headers(),
            ) or []
            for r in recs:
                eid = r.get("enterprise_id", "")
                rec_count_map[eid] = rec_count_map.get(eid, 0) + 1
        except Exception:
            pass

    result = []
    for e in ents:
        eid = e["id"]
        result.append({
            "id": eid,
            "name": e.get("name", ""),
            "description": e.get("description"),
            "projects": proj_map.get(eid, []),
            "cr_count": cr_count_map.get(eid, 0),
            "recording_count": rec_count_map.get(eid, 0),
        })
    return JSONResponse(result)


# --- GET endpoints lecture (proxy Lovable) — ajoutés 20/07 car le frontend passe désormais par le proxy ---


@app.get("/v1/enterprises-with-projects")
def list_enterprises_with_projects(request: Request, plaudia_key: str = ""):
    """Retourne les entreprises avec leurs projets imbriqués.
    Appelé par le frontend Lovable qui attend `e.projects[]`."""
    user = get_current_user(request)
    owner_id = user["user_id"]
    # Supabase PostgREST supporte les embed via select=*,projects(*)
    try:
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/enterprises?owner_id=eq.{owner_id}&select=*,projects(*)",
            headers=sb_headers(),
        ) or []
        return JSONResponse(rows)
    except Exception as e:
        # Fallback: fetch separately
        ents = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/enterprises?owner_id=eq.{owner_id}&select=id,name,description,created_at",
            headers=sb_headers(),
        ) or []
        for e in ents:
            try:
                e["projects"] = http_json(
                    "GET",
                    f"{SUPABASE_URL}/rest/v1/projects?enterprise_id=eq.{e['id']}&owner_id=eq.{owner_id}&select=id,enterprise_id,name,description,keywords,created_at",
                    headers=sb_headers(),
                ) or []
            except Exception:
                e["projects"] = []
        return JSONResponse(ents)


@app.get("/v1/crs")
def list_crs(request: Request, plaudia_key: str = "",
             enterprise_id: str = "", project_id: str = "",
             status: str = "", limit: int = 50, offset: int = 0):
    """Liste les CRs avec métadonnées — batch enrichment sans Supabase embed."""
    user = get_current_user(request)
    owner_id = user["user_id"]
    filters = [f"owner_id=eq.{owner_id}", f"order=updated_at.desc", f"limit={limit}"]
    if enterprise_id:
        filters.append(f"enterprise_id=eq.{enterprise_id}")
    if project_id:
        filters.append(f"project_id=eq.{project_id}")
    if status:
        filters.append(f"status=eq.{status}")
    if offset:
        filters.append(f"offset={offset}")

    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/crs?{'&'.join(filters)}&select=id,recording_id,version,status,enterprise_id,project_id,created_at,updated_at",
        headers=sb_headers(),
    ) or []

    if not rows:
        return JSONResponse([])

    # Batch-enrich with recording data + enterprise names (2 batch queries, not N+1)
    # Use `in` filter (PostgREST native) instead of `or=(id.eq.1,id.eq.2,…)` —
    # the `or=` syntax can produce malformed URLs with many IDs.
    def _valid_uuid(v):
        return v and isinstance(v, str) and len(v) > 20

    rec_ids = sorted(set(r["recording_id"] for r in rows if _valid_uuid(r.get("recording_id"))))
    ent_ids = sorted(set(r["enterprise_id"] for r in rows if _valid_uuid(r.get("enterprise_id"))))

    rec_map = {}
    if rec_ids:
        try:
            recs = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/recordings?select=id,title,client_name,meeting_subject,meeting_type,recorded_at&id=in.({','.join(rec_ids)})",
                headers=sb_headers(),
            ) or []
            for r in recs:
                rec_map[r["id"]] = r
        except Exception:
            pass

    ent_map = {}
    if ent_ids:
        try:
            ents = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/enterprises?select=id,name&id=in.({','.join(ent_ids)})",
                headers=sb_headers(),
            ) or []
            ent_map = {e["id"]: e["name"] for e in ents if e.get("name")}
        except Exception:
            pass

    enriched = []
    for cr in rows:
        rec = rec_map.get(cr.get("recording_id")) or {}
        enriched.append({
            "id": cr["id"],
            "recording_id": cr.get("recording_id"),
            "version": cr.get("version"),
            "status": cr.get("status"),
            "enterprise_id": cr.get("enterprise_id"),
            "project_id": cr.get("project_id"),
            "created_at": cr.get("created_at"),
            "updated_at": cr.get("updated_at"),
            "title": rec.get("title") or "",
            "client_name": rec.get("client_name") or "",
            "meeting_subject": rec.get("meeting_subject") or "",
            "meeting_type": rec.get("meeting_type") or "",
            "recorded_at": rec.get("recorded_at") or "",
            "enterprise_name": ent_map.get(cr.get("enterprise_id")) or rec.get("client_name") or "",
            "display_name": (
                rec.get("title") or
                rec.get("meeting_subject") or
                "Compte rendu"
            ),
            "recording": {
                "title": rec.get("title") or "",
                "client_name": rec.get("client_name") or "",
                "meeting_subject": rec.get("meeting_subject") or "",
                "meeting_type": rec.get("meeting_type") or "",
                "recorded_at": rec.get("recorded_at") or "",
            } if rec else None,
            "enterprise": {
                "name": ent_map.get(cr.get("enterprise_id")) or rec.get("client_name") or "",
            } if cr.get("enterprise_id") else None,
        })
    return JSONResponse(enriched)


@app.get("/v1/recordings")
def list_recordings(request: Request, plaudia_key: str = "",
                    enterprise_id: str = "", status: str = "",
                    limit: int = 50, offset: int = 0):
    """Liste les enregistrements avec filtres optionnels."""
    user = get_current_user(request)
    owner_id = user["user_id"]
    filters = [f"owner_id=eq.{owner_id}", f"order=recorded_at.desc", f"limit={limit}"]
    if enterprise_id:
        filters.append(f"enterprise_id=eq.{enterprise_id}")
    if status:
        filters.append(f"status=eq.{status}")
    if offset:
        filters.append(f"offset={offset}")
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/recordings?{'&'.join(filters)}&select=id,title,client_name,meeting_type,meeting_subject,recorded_at,duration_seconds,status,enterprise_id,project_id,plaud_file_id,created_at",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/recordings/{recording_id}")
def get_recording(recording_id: str, request: Request, plaudia_key: str = ""):
    """Retourne un enregistrement complet."""
    user = get_current_user(request)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{recording_id}&select=*",
        headers=sb_headers(),
    )
    if not rows:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return JSONResponse(rows[0])


@app.get("/v1/crs/{cr_id}")
def get_cr(cr_id: str, request: Request, plaudia_key: str = ""):
    """Retourne un CR complet avec recording, enterprise, project et version courante."""
    user = get_current_user(request)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&select=*",
        headers=sb_headers(),
    )
    if not rows:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    cr = rows[0]

    # Enrich with recording
    rec = {}
    rid = cr.get("recording_id")
    if rid:
        try:
            recs = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{rid}&select=title,client_name,meeting_subject,meeting_type,recorded_at",
                headers=sb_headers(),
            )
            if recs:
                rec = recs[0]
        except Exception:
            pass

    # Enrich with enterprise
    ent = {}
    eid = cr.get("enterprise_id")
    if eid:
        try:
            ents = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/enterprises?id=eq.{eid}&select=id,name",
                headers=sb_headers(),
            )
            if ents:
                ent = {"name": ents[0].get("name", "")}
        except Exception:
            pass

    # Enrich with project
    proj = {}
    pid = cr.get("project_id")
    if pid:
        try:
            projs = http_json(
                "GET",
                f"{SUPABASE_URL}/rest/v1/projects?id=eq.{pid}&select=id,name",
                headers=sb_headers(),
            )
            if projs:
                proj = {"name": projs[0].get("name", "")}
        except Exception:
            pass

    return JSONResponse({
        "id": cr["id"],
        "recording_id": cr.get("recording_id"),
        "version": cr.get("version"),
        "status": cr.get("status"),
        "content": cr.get("content", ""),
        "enterprise_id": cr.get("enterprise_id"),
        "project_id": cr.get("project_id"),
        "created_at": cr.get("created_at"),
        "updated_at": cr.get("updated_at"),
        "title": rec.get("title") or "",
        "client_name": rec.get("client_name") or "",
        "meeting_subject": rec.get("meeting_subject") or "",
        "meeting_type": rec.get("meeting_type") or "",
        "recorded_at": rec.get("recorded_at") or "",
        "enterprise_name": ent.get("name") or rec.get("client_name") or "",
        "recording": {
            "title": rec.get("title") or "",
            "client_name": rec.get("client_name") or "",
            "meeting_subject": rec.get("meeting_subject") or "",
            "meeting_type": rec.get("meeting_type") or "",
            "recorded_at": rec.get("recorded_at") or "",
        } if rec else None,
        "enterprise": ent if ent else None,
        "project": proj if proj else None,
    })


@app.get("/v1/crs/{cr_id}/versions")
def list_cr_versions(cr_id: str, request: Request, plaudia_key: str = ""):
    """Liste les versions d'un CR."""
    user = get_current_user(request)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/cr_versions?cr_id=eq.{cr_id}&select=version,content,created_at&order=version.desc",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/chat/sessions")
def list_chat_sessions(request: Request, plaudia_key: str = ""):
    """Liste les sessions de chat RAG."""
    user = get_current_user(request)
    owner_id = user["user_id"]
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/chat_sessions?owner_id=eq.{owner_id}&select=id,title,tags,enterprise_id,project_id,created_at,updated_at&order=updated_at.desc",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/chat/sessions/{session_id}/messages")
def get_chat_session_messages(session_id: str, request: Request, plaudia_key: str = ""):
    """Liste les messages d'une session."""
    user = get_current_user(request)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/chat_messages?session_id=eq.{session_id}&select=role,content,created_at&order=created_at.asc",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


# --- CR Validation ---
@app.post("/v1/crs/{cr_id}/validate")
def validate_cr(cr_id: str, request: Request, plaudia_key: str = ""):
    """Valide un CR : passe le statut à 'validated' sur la version courante.
    Idempotent : si déjà validé, retourne 200 OK."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    # Récupérer le CR + enregistrement
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&owner_id=eq.{owner_id}&select=*,recording:recording_id(*)",
        headers=sb_headers(),
    ) or []
    if not rows:
        return JSONResponse({"error": "CR non trouvé"}, status_code=404)
    cr = rows[0]
    rec = cr.get("recording", {})
    client_name = rec.get("client_name", "Client")
    subject = rec.get("meeting_subject", "Compte-rendu de réunion")
    date_str = _format_date(rec.get("recorded_at", ""))

    # Idempotent : si déjà validé, retourner 200 OK sans refaire
    already_validated = cr.get("status") == "validated"
    if not already_validated:
        http_json(
            "PATCH",
            f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&owner_id=eq.{owner_id}",
            headers={**sb_headers(), "Prefer": "return=minimal"},
            body={"status": "validated"},
        )

    # Générer un brouillon Gmail automatique (sauf si déjà fait)
    if not already_validated:
        email_subject = f"CR — {client_name} — {subject} — {date_str}"
        email_body = cr_html_to_doc_text(cr.get("content", ""))
        try:
            draft = send_or_draft_email(
                to="",
                subject=email_subject,
                body=email_body,
                as_draft=True,
            )
            draft_status = f"Brouillon Gmail créé (id: {draft.get('draft_id', '?')})"
        except Exception as e:
            draft_status = f"E-mail non généré : {e}"
    else:
        draft_status = "Déjà validé — brouillon déjà créé"

    # Construire le nom d'affichage
    parts = [p for p in [client_name, subject, date_str] if p]
    display_name = " — ".join(parts) if parts else f"CR v{cr['version']}"

    return JSONResponse({
        "status": "validated",
        "version": cr["version"],
        "display_name": display_name,
        "email": draft_status,
    })


@app.post("/v1/crs/{cr_id}/restore")
def restore_cr_version(cr_id: str, request: Request, plaudia_key: str = ""):
    """Restaure une version spécifique d'un CR : la version devient la version courante (N+1)."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    # FastAPI sync endpoint : request.json() est une coroutine — utiliser body() directement
    try:
        raw = request.body()
        import asyncio
        if hasattr(raw, '__await__'):
            raw = asyncio.new_event_loop().run_until_complete(raw)
        body_data = json.loads(raw) if raw else {}
    except Exception:
        body_data = {}
    version = body_data.get("version")
    if not version:
        raise HTTPException(status_code=400, detail="Paramètre 'version' requis")

    # Récupérer le contenu de l'ancienne version dans cr_versions
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/cr_versions?cr_id=eq.{cr_id}&version=eq.{version}&select=content",
        headers=sb_headers(),
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Version {version} non trouvée")

    old_content = rows[0]["content"]

    # Sauvegarder la version courante dans l'historique puis écraser
    new_version = update_cr_content(cr_id, old_content)
    return JSONResponse({
        "version": new_version,
        "content": old_content,
        "message": f"Version {version} restaurée comme version {new_version}",
    })


class UpdateCRRequest(BaseModel):
    enterprise_id: Optional[str] = None
    project_id: Optional[str] = None


@app.patch("/v1/crs/{cr_id}")
def update_cr(cr_id: str, req: UpdateCRRequest, request: Request, plaudia_key: str = ""):
    """Met à jour les métadonnées d'un CR (enterprise_id, project_id).
    Validation croisée : si project_id fourni, vérifie qu'il appartient bien à enterprise_id."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    body = {}
    if req.enterprise_id is not None:
        # Vérifier que l'entreprise existe
        ent = http_json(
            "GET", f"{SUPABASE_URL}/rest/v1/enterprises?id=eq.{req.enterprise_id}&select=id",
            headers=sb_headers(),
        )
        if not ent:
            raise HTTPException(status_code=404, detail="Entreprise introuvable")
        body["enterprise_id"] = req.enterprise_id

    if req.project_id is not None:
        # Vérifier que le projet existe
        proj = http_json(
            "GET", f"{SUPABASE_URL}/rest/v1/projects?id=eq.{req.project_id}&select=id,enterprise_id",
            headers=sb_headers(),
        )
        if not proj:
            raise HTTPException(status_code=404, detail="Projet introuvable")
        # Validation croisée : le projet doit appartenir à l'entreprise du CR
        target_ent = req.enterprise_id or body.get("enterprise_id")
        if target_ent and proj[0]["enterprise_id"] != target_ent:
            raise HTTPException(status_code=400,
                                detail="Le projet n'appartient pas à l'entreprise spécifiée")
        body["project_id"] = req.project_id

    if not body:
        return JSONResponse({"error": "Rien à mettre à jour"}, status_code=400)

    body["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body=body,
    )
    return JSONResponse({"updated": True, "cr_id": cr_id})


class CreateEnterpriseRequest(BaseModel):
    name: str
    description: Optional[str] = None


@app.post("/v1/enterprises")
def create_enterprise(req: CreateEnterpriseRequest, request: Request, plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    rows = http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/enterprises",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body={"name": req.name, "description": req.description or "", "owner_id": owner_id},
    )
    # Crée automatiquement un projet "Général"
    ent_id = rows[0]["id"]
    http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/projects",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body={"enterprise_id": ent_id, "name": "Général", "description": "Projet par défaut", "owner_id": owner_id},
    )
    return JSONResponse(rows[0])


class CreateProjectRequest(BaseModel):
    enterprise_id: str
    name: str
    description: Optional[str] = None
    keywords: Optional[list[str]] = None
    cr_ids: Optional[list[str]] = None  # CRs à rattacher au projet dès sa création


@app.post("/v1/projects")
def create_project(req: CreateProjectRequest, request: Request, plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    rows = http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/projects",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body={
            "enterprise_id": req.enterprise_id,
            "name": req.name,
            "description": req.description or "",
            "keywords": req.keywords or [],
            "owner_id": owner_id,
        },
    )
    project = rows[0]
    project_id = project["id"]

    # Rattacher les CRs pré-attribués si fournis
    if req.cr_ids:
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        for cr_id in req.cr_ids:
            try:
                http_json(
                    "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&owner_id=eq.{owner_id}",
                    headers={**sb_headers(), "Prefer": "return=minimal"},
                    body={"project_id": project_id, "enterprise_id": req.enterprise_id, "updated_at": now},
                )
            except Exception:
                pass

    return JSONResponse(project)


@app.delete("/v1/enterprises/{enterprise_id}")
def delete_enterprise(enterprise_id: str, request: Request, plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/enterprises?id=eq.{enterprise_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True})


@app.delete("/v1/projects/{project_id}")
def delete_project(project_id: str, request: Request, plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True})


# --- Google Docs export + Gmail send/draft ---

class ExportDocRequest(BaseModel):
    recording_id: str
    cr_id: str


@app.post("/v1/cr/export-doc")
def export_doc(req: ExportDocRequest, request: Request):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    recording = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{req.recording_id}"
        f"&select=title,client_name,meeting_subject,recorded_at",
        headers=sb_headers(),
    )
    if not recording:
        raise HTTPException(status_code=404, detail="Enregistrement introuvable.")
    rec = recording[0]

    cr = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{req.cr_id}&select=content",
        headers=sb_headers(),
    )
    if not cr or not cr[0].get("content"):
        raise HTTPException(status_code=404, detail="Compte-rendu introuvable ou vide.")

    doc_title = " - ".join(filter(None, [rec.get("client_name"), rec.get("meeting_subject"), rec.get("title")])) \
        or "Compte-rendu Plaudia"

    try:
        result = export_cr_to_google_doc(doc_title, cr[0]["content"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur export Google Docs : {e}")

    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{req.cr_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body={"doc_url": result["url"]},
    )

    return JSONResponse({"doc_url": result["url"], "document_id": result["document_id"]})


class SendEmailRequest(BaseModel):
    recording_id: str
    cr_id: str
    to: str
    subject: str
    body: str
    as_draft: bool = True


def _detect_recipient_and_body(recording_id: str, cr_id: str):
    """Best-effort defaults for the compose form: recipient from the recording's
    participants (first one with an email on file), subject/body derived from
    the CR metadata. Never invents an address that isn't already on record."""
    participants = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/participants?recording_id=eq.{recording_id}"
        f"&email=not.is.null&select=name,email&limit=1",
        headers=sb_headers(),
    ) or []
    recipient = participants[0]["email"] if participants else ""

    recording = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{recording_id}"
        f"&select=client_name,meeting_subject,title",
        headers=sb_headers(),
    ) or [{}]
    rec = recording[0]
    subject = f"Compte-rendu — {rec.get('meeting_subject') or rec.get('title') or 'réunion'}"

    cr = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&select=doc_url",
        headers=sb_headers(),
    ) or [{}]
    doc_url = cr[0].get("doc_url")
    body_lines = [
        "Bonjour,",
        "",
        "Vous trouverez ci-joint le compte-rendu de notre échange.",
    ]
    if doc_url:
        body_lines += ["", f"Lien du document : {doc_url}"]
    body_lines += ["", "Bonne journée,", "Hérone"]

    return recipient, subject, "\n".join(body_lines)


@app.get("/v1/cr/{recording_id}/email-defaults")
def email_defaults(recording_id: str, request: Request, cr_id: str = "", plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    recipient, subject, body = _detect_recipient_and_body(recording_id, cr_id)
    return JSONResponse({"to": recipient, "subject": subject, "body": body})


@app.post("/v1/cr/send-email")
def send_email(req: SendEmailRequest, request: Request):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    if not req.to or "@" not in req.to:
        raise HTTPException(status_code=400, detail="Adresse destinataire manquante ou invalide.")

    try:
        result = send_or_draft_email(req.to, req.subject, req.body, as_draft=req.as_draft)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur envoi email : {e}")

    # Per Martin's rule: both a real send and a draft mark the CR as "processed"
    # (doc_url/email_sent_to/sent_at) and register the address in the directory.
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{req.cr_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body={"email_sent_to": [req.to], "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())},
    )

    owner_id = user["user_id"]
    existing = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/participants?recording_id=eq.{req.recording_id}"
        f"&email=eq.{urllib.parse.quote(req.to)}&select=id",
        headers=sb_headers(),
    )
    if not existing:
        http_json(
            "POST", f"{SUPABASE_URL}/rest/v1/participants",
            headers={**sb_headers(), "Prefer": "return=minimal"},
            body={"recording_id": req.recording_id, "owner_id": owner_id,
                  "name": req.to.split("@")[0], "email": req.to},
        )

    return JSONResponse(result)


@app.get("/v1/process-stream")
def process_stream(request: Request, document_id: str = "", vocal_context: str = "", plaudia_key: str = ""):
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    # Not implemented: the real Plaud->CR generation pipeline runs via cron, not
    # on-demand from the frontend today. This placeholder just tells the client
    # immediately rather than hanging, so the UI doesn't spin forever.
    message = (
        "La génération à la demande n'est pas encore branchée — le CR est "
        "produit automatiquement par le pipeline Plaudia."
    )
    payload = json.dumps({"step": "done", "message": message})

    def gen():
        yield f"data: {payload}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- On-demand "Vérifier les nouveaux enregistrements" button (0 LLM tokens) ---

PLAUD_TOKEN_PATH = "/opt/data/mcp-tokens/plaud.json"
PLAUD_CLIENT_PATH = "/opt/data/mcp-tokens/plaud.client.json"
PLAUD_META_PATH = "/opt/data/mcp-tokens/plaud.meta.json"
PLAUD_MCP_URL = "https://mcp.plaud.ai/mcp"
LLM_PIPELINE_JOB_ID = "d4777fc4327a"  # plaudia-pipeline-principal cron job
_CHECK_NEW_N = 20

# Debounce: avoid re-triggering the paid LLM pipeline if the button is mashed
# repeatedly within a short window — the check itself is free, but the trigger
# (hermes cron run) kicks off a real LLM run and shouldn't fire twice for one click.
_last_trigger_ts = {"ts": 0.0}
_TRIGGER_COOLDOWN = 120  # seconds


def _load_plaud_token() -> str:
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


def _list_recent_plaud_files(token: str, n: int = _CHECK_NEW_N) -> list[dict]:
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "list_files", "arguments": {"page": 1, "page_size": n}},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        PLAUD_MCP_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    line = raw.strip().splitlines()[-1]
    if line.startswith("data:"):
        line = line[len("data:"):].strip()
    outer = json.loads(line)
    result = outer["result"]
    if isinstance(result, dict) and "content" in result:
        payload = json.loads(result["content"][0]["text"])
    else:
        payload = result
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    return items


def _get_existing_plaud_ids(file_ids: list[str]) -> set[str]:
    if not file_ids:
        return set()
    ids_csv = ",".join(file_ids)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/recordings?plaud_file_id=in.({ids_csv})&select=plaud_file_id",
        headers=sb_headers(),
    ) or []
    return {r["plaud_file_id"] for r in rows}


def _trigger_llm_pipeline():
    # `hermes cron run` blocks until the triggered job actually finishes (can take
    # several minutes for a real transcript+CR run) — we must NOT wait for it here,
    # otherwise the button's HTTP request hangs for minutes. Fire-and-forget: spawn
    # detached, redirect output, don't wait.
    subprocess.Popen(
        ["hermes", "cron", "run", LLM_PIPELINE_JOB_ID],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


class ExportSessionRequest(BaseModel):
    session_id: str
    title: Optional[str] = None


@app.post("/v1/chat/export-session")
def export_chat_session(req: ExportSessionRequest, request: Request, plaudia_key: str = ""):
    """Exporte une conversation RAG en document de travail structuré (HTML).
    Le frontend peut ensuite l'imprimer ou le télécharger en PDF."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    # Récupérer les messages de la session
    try:
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/chat_messages?session_id=eq.{req.session_id}&owner_id=eq.{owner_id}"
            f"&select=role,content,created_at&order=created_at.asc",
            headers=sb_headers(),
        ) or []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la récupération des messages : {e}")

    if not rows:
        raise HTTPException(status_code=404, detail="Aucun message trouvé pour cette session.")

    # Récupérer le titre de la session
    session_title = req.title or "Compte-rendu de discussion"
    try:
        sess = http_json(
            "GET", f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{req.session_id}&select=title",
            headers=sb_headers(),
        )
        if sess and sess[0].get("title"):
            session_title = sess[0]["title"]
    except Exception:
        pass

    # Construire le prompt pour le LLM
    messages_text = ""
    for m in rows:
        role_label = "🧑 Utilisateur" if m["role"] == "user" else "🤖 Assistant"
        messages_text += f"\n\n### {role_label} — {m['created_at'][:16].replace('T', ' à ')}\n{m['content']}\n"

    export_system_prompt = (
        "Tu dois transformer une conversation de chat en un document de travail structuré et élégant, "
        "au format HTML complet. Le document doit être :\n"
        "- Professionnel et sobre (style Hérone)\n"
        "- Structuré avec des sections claires\n"
        "- Prêt à être imprimé ou converti en PDF (taille A4, marges adaptées)\n"
        "- En français\n\n"
        "Structure attendue :\n"
        "1. En-tête : logo HÉRONE, titre de la discussion, date\n"
        "2. Participants : qui a posé les questions, qui a répondu\n"
        "3. Synthèse de la discussion : résumé des échanges\n"
        "4. Détail des échanges : chaque question/réponse présentée clairement\n"
        "5. Points clés et décisions à retenir (s'il y en a)\n"
        "6. Pied de page : 'Document généré par Plaudia — Hérone'\n\n"
        "Style CSS embarqué : police Inter, fond blanc, texte sobre, pas de couleurs agressives, "
        "bordures fines, max-width 800px centré, footer en gris clair.\n\n"
        "IMPORTANT : Retourne UNIQUEMENT le HTML complet, sans commentaire avant/après."
    )

    user_prompt = f"Titre de la discussion : {session_title}\n\nMessages de la conversation :\n{messages_text}"

    try:
        html_doc = call_opus(export_system_prompt, [{"role": "user", "content": user_prompt}], max_tokens=8192)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la génération du document : {e}")

    # Extraire le HTML si DeepSeek le met entre des balises de code
    html_match = re.search(r"```html\s*([\s\S]*?)```", html_doc)
    if html_match:
        html_doc = html_match.group(1).strip()
    # Fallback : chercher <!DOCTYPE ou <html
    if not html_doc.startswith("<!") and not html_doc.startswith("<html"):
        doctype_fallback = re.search(r"(<!DOCTYPE[\s\S]*)", html_doc, re.IGNORECASE)
        if doctype_fallback:
            html_doc = doctype_fallback.group(1).strip()

    return JSONResponse({
        "session_id": req.session_id,
        "title": session_title,
        "html": html_doc,
        "message_count": len(rows),
    })


# ============================================================
# New endpoints — frontend migration (écritures directes → API)
# ============================================================


class UpdateRecordingRequest(BaseModel):
    client_name: Optional[str] = None
    meeting_type: Optional[str] = None
    meeting_subject: Optional[str] = None
    title: Optional[str] = None


@app.patch("/v1/recordings/{recording_id}")
def update_recording(recording_id: str, req: UpdateRecordingRequest, request: Request, plaudia_key: str = ""):
    """Met à jour les métadonnées d'un enregistrement (client_name, meeting_type, meeting_subject, title).
    Utilisé par CRDetailView pour renommer/classer un CR."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    body = {}
    for field in ("client_name", "meeting_type", "meeting_subject", "title"):
        val = getattr(req, field, None)
        if val is not None:
            body[field] = val

    if not body:
        return JSONResponse({"error": "Rien à mettre à jour"}, status_code=400)

    body["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{recording_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body=body,
    )
    return JSONResponse({"updated": True, "recording_id": recording_id})


@app.delete("/v1/recordings/{recording_id}")
def delete_recording(recording_id: str, request: Request, plaudia_key: str = ""):
    """Supprime un enregistrement (et ses CRs via cascade DB)."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/recordings?id=eq.{recording_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True, "recording_id": recording_id})


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[list[str]] = None


@app.patch("/v1/projects/{project_id}")
def update_project(project_id: str, req: UpdateProjectRequest, request: Request, plaudia_key: str = ""):
    """Met à jour les métadonnées d'un projet (nom, description, mots-clés)."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    body = {}
    if req.name is not None:
        body["name"] = req.name
    if req.description is not None:
        body["description"] = req.description
    if req.keywords is not None:
        body["keywords"] = req.keywords

    if not body:
        return JSONResponse({"error": "Rien à mettre à jour"}, status_code=400)

    body["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body=body,
    )
    return JSONResponse({"updated": True, "project_id": project_id})


class AttachCRsRequest(BaseModel):
    cr_ids: list[str]


@app.post("/v1/projects/{project_id}/crs")
def attach_crs_to_project(project_id: str, req: AttachCRsRequest, request: Request, plaudia_key: str = ""):
    """Rattache une liste de CRs à un projet existant."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    # Vérifier que le projet existe
    proj = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&owner_id=eq.{owner_id}&select=id,enterprise_id",
        headers=sb_headers(),
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    enterprise_id = proj[0]["enterprise_id"]

    if not req.cr_ids:
        return JSONResponse({"error": "Aucun CR à rattacher"}, status_code=400)

    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    updated = 0
    for cr_id in req.cr_ids:
        try:
            http_json(
                "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&owner_id=eq.{owner_id}",
                headers={**sb_headers(), "Prefer": "return=minimal"},
                body={"project_id": project_id, "enterprise_id": enterprise_id, "updated_at": now},
            )
            updated += 1
        except Exception:
            pass  # CR introuvable ou déjà attribué — on continue

    return JSONResponse({"updated": updated, "total": len(req.cr_ids), "project_id": project_id})


class BulkAssignRequest(BaseModel):
    project_ids: list[str] = []
    cr_ids: list[str] = []


@app.post("/v1/enterprises/{enterprise_id}/assignments")
def bulk_assign_to_enterprise(enterprise_id: str, req: BulkAssignRequest, request: Request, plaudia_key: str = ""):
    """Attribue en masse des projets et des CRs à une entreprise."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]

    # Vérifier que l'entreprise existe
    ent = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/enterprises?id=eq.{enterprise_id}&owner_id=eq.{owner_id}&select=id",
        headers=sb_headers(),
    )
    if not ent:
        raise HTTPException(status_code=404, detail="Entreprise introuvable")

    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    projects_updated = 0
    crs_updated = 0

    for pid in req.project_ids:
        try:
            http_json(
                "PATCH", f"{SUPABASE_URL}/rest/v1/projects?id=eq.{pid}&owner_id=eq.{owner_id}",
                headers={**sb_headers(), "Prefer": "return=minimal"},
                body={"enterprise_id": enterprise_id, "updated_at": now},
            )
            projects_updated += 1
        except Exception:
            pass

    for cid in req.cr_ids:
        try:
            http_json(
                "PATCH", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cid}&owner_id=eq.{owner_id}",
                headers={**sb_headers(), "Prefer": "return=minimal"},
                body={"enterprise_id": enterprise_id, "updated_at": now},
            )
            crs_updated += 1
        except Exception:
            pass

    return JSONResponse({
        "projects_updated": projects_updated,
        "crs_updated": crs_updated,
        "enterprise_id": enterprise_id,
    })


class CreateGlossaryRequest(BaseModel):
    term_raw: str
    term_corrected: str
    owner_id: Optional[str] = None


@app.post("/v1/glossary")
def create_glossary_entry(req: CreateGlossaryRequest, request: Request, plaudia_key: str = ""):
    """Ajoute une correction orthographique au glossaire.
    Le trigger DB glossary_retroactive_rewrite réécrit automatiquement
    tous les CRs existants concernés."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    if not req.term_raw.strip() or not req.term_corrected.strip():
        return JSONResponse({"error": "term_raw et term_corrected sont requis"}, status_code=400)

    owner_id = req.owner_id or get_service_owner_id()
    http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/glossary",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body={
            "term_raw": req.term_raw.strip(),
            "term_corrected": req.term_corrected.strip(),
            "owner_id": owner_id,
        },
    )
    return JSONResponse({"created": True, "term_raw": req.term_raw.strip(), "term_corrected": req.term_corrected.strip()})


# ============================================================
# End of new endpoints
# ============================================================


@app.post("/v1/recordings/check-new")
def check_new_recordings(request: Request, plaudia_key: str = ""):
    """On-demand replacement for waiting on the cron watchdog. Pure HTTP calls to
    Plaud + Supabase — 0 LLM tokens. Only invokes the real (paid) LLM pipeline job
    if it finds a plaud_file_id that isn't in `recordings` yet."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    try:
        token = _load_plaud_token()
        files = _list_recent_plaud_files(token, _CHECK_NEW_N)
        file_ids = [f["id"] for f in files]
        existing = _get_existing_plaud_ids(file_ids)
        new_ids = [fid for fid in file_ids if fid not in existing]
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erreur lors de la vérification Plaud : {e}")

    if not new_ids:
        return JSONResponse({
            "new_count": 0,
            "new_titles": [],
            "triggered": False,
            "message": "Aucun nouvel enregistrement — tout est déjà à jour.",
        })

    names_by_id = {f["id"]: f["name"] for f in files}
    new_titles = [names_by_id.get(fid, fid) for fid in new_ids]

    now = time.time()
    triggered = False
    if now - _last_trigger_ts["ts"] > _TRIGGER_COOLDOWN:
        _trigger_llm_pipeline()
        _last_trigger_ts["ts"] = now
        triggered = True

    return JSONResponse({
        "new_count": len(new_ids),
        "new_titles": new_titles,
        "triggered": triggered,
        "message": (
            f"{len(new_ids)} nouvel(aux) enregistrement(s) détecté(s) — traitement lancé, "
            "les comptes-rendus apparaîtront dans quelques minutes."
            if triggered else
            f"{len(new_ids)} nouvel(aux) enregistrement(s) détecté(s) — traitement déjà en cours "
            "(déclenché récemment), patiente quelques instants."
        ),
    })


# ============================================================
# Glossary CRUD
# ============================================================


class UpdateGlossaryRequest(BaseModel):
    term_raw: Optional[str] = None
    term_corrected: Optional[str] = None


@app.get("/v1/glossary")
def list_glossary(request: Request, plaudia_key: str = ""):
    """Liste toutes les entrées du glossaire."""
    user = get_current_user(request)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/glossary?select=id,owner_id,term_raw,term_corrected,uses_count,created_at&order=created_at.desc",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.patch("/v1/glossary/{entry_id}")
def update_glossary_entry(entry_id: str, req: UpdateGlossaryRequest, request: Request, plaudia_key: str = ""):
    """Met à jour une entrée du glossaire."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    body = {}
    if req.term_raw is not None:
        body["term_raw"] = req.term_raw.strip()
    if req.term_corrected is not None:
        body["term_corrected"] = req.term_corrected.strip()
    if not body:
        return JSONResponse({"error": "Rien à mettre à jour"}, status_code=400)
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/glossary?id=eq.{entry_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body=body,
    )
    return JSONResponse({"updated": True, "id": entry_id})


@app.delete("/v1/glossary/{entry_id}")
def delete_glossary_entry(entry_id: str, request: Request, plaudia_key: str = ""):
    """Supprime une entrée du glossaire."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/glossary?id=eq.{entry_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True, "id": entry_id})


# ============================================================
# Participants CRUD
# ============================================================


class CreateParticipantRequest(BaseModel):
    recording_id: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None


class UpdateParticipantRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None


@app.get("/v1/participants")
def list_participants(request: Request, plaudia_key: str = "",
                      recording_id: str = "", limit: int = 100, offset: int = 0):
    """Liste les participants, avec filtre optionnel recording_id."""
    user = get_current_user(request)
    owner_id = user["user_id"]
    filters = [f"owner_id=eq.{owner_id}", f"order=created_at.desc", f"limit={limit}"]
    if recording_id:
        filters.append(f"recording_id=eq.{recording_id}")
    if offset:
        filters.append(f"offset={offset}")
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/participants?{'&'.join(filters)}&select=id,recording_id,name,email,created_at",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.post("/v1/participants")
def create_participant(req: CreateParticipantRequest, request: Request, plaudia_key: str = ""):
    """Ajoute un participant."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    owner_id = user["user_id"]
    body = {"owner_id": owner_id}
    for field in ("recording_id", "name", "role", "email"):
        val = getattr(req, field, None)
        if val is not None:
            body[field] = val
    if not body.get("email") and not body.get("name"):
        return JSONResponse({"error": "email ou name requis"}, status_code=400)
    result = http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/participants",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body=body,
    )
    return JSONResponse(result[0] if result else {"created": True})


@app.patch("/v1/participants/{participant_id}")
def update_participant(participant_id: str, req: UpdateParticipantRequest, request: Request, plaudia_key: str = ""):
    """Met à jour un participant."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    body = {}
    for field in ("name", "email"):
        val = getattr(req, field, None)
        if val is not None:
            body[field] = val
    if not body:
        return JSONResponse({"error": "Rien à mettre à jour"}, status_code=400)
    http_json(
        "PATCH", f"{SUPABASE_URL}/rest/v1/participants?id=eq.{participant_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body=body,
    )
    return JSONResponse({"updated": True, "id": participant_id})


@app.delete("/v1/participants/{participant_id}")
def delete_participant(participant_id: str, request: Request, plaudia_key: str = ""):
    """Supprime un participant."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))
    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/participants?id=eq.{participant_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True, "id": participant_id})


# ============================================================
# Multi-user endpoints
# ============================================================


@app.get("/v1/auth/me")
def auth_me(request: Request):
    """Retourne les infos de l'utilisateur connecté."""
    user = get_current_user(request)
    # Récupérer le profil depuis Supabase (user_profiles)
    try:
        rows = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/user_profiles?id=eq.{user['user_id']}&select=id,email,name,role,created_at",
            headers=sb_headers(),
        )
        profile = rows[0] if rows else {}
    except Exception:
        profile = {}
    return JSONResponse({
        "user_id": user["user_id"],
        "email": user["email"],
        "role": profile.get("role", user["role"]),
        "name": profile.get("name", ""),
        "is_service": user["is_service"],
        "profile": profile,
    })


# --- Project sharing ---


class ShareProjectRequest(BaseModel):
    email: str
    permission: str = "view"  # view, edit, admin


@app.post("/v1/projects/{project_id}/share")
def share_project(project_id: str, req: ShareProjectRequest, request: Request):
    """Partage un projet avec un utilisateur par email."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    if req.permission not in ("view", "edit", "admin"):
        raise HTTPException(status_code=400, detail="Permission invalide: view, edit, ou admin")

    # Vérifier que le projet existe et que l'utilisateur y a accès
    proj = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&select=id,owner_id,name",
        headers=sb_headers(),
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    # Vérifier que l'utilisateur est admin ou owner du projet
    if not user["is_service"] and proj[0]["owner_id"] != user["user_id"]:
        # Vérifier s'il a déjà les droits admin sur ce projet
        shares = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/project_shares?project_id=eq.{project_id}"
            f"&shared_with_email=eq.{urllib.parse.quote(user['email'])}&permission=eq.admin",
            headers=sb_headers(),
        )
        if not shares:
            raise HTTPException(status_code=403, detail="Vous n'avez pas les droits pour partager ce projet")

    # Vérifier que le partage n'existe pas déjà
    existing = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/project_shares?project_id=eq.{project_id}"
        f"&shared_with_email=eq.{urllib.parse.quote(req.email)}&select=id",
        headers=sb_headers(),
    )
    if existing:
        # Mettre à jour le partage existant
        http_json(
            "PATCH",
            f"{SUPABASE_URL}/rest/v1/project_shares?id=eq.{existing[0]['id']}",
            headers={**sb_headers(), "Prefer": "return=minimal"},
            body={"permission": req.permission, "shared_by": user["user_id"]},
        )
        return JSONResponse({"shared": True, "project_id": project_id, "email": req.email, "permission": req.permission})

    # Créer le partage
    http_json(
        "POST",
        f"{SUPABASE_URL}/rest/v1/project_shares",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body={
            "project_id": project_id,
            "shared_with_email": req.email,
            "permission": req.permission,
            "shared_by": user["user_id"],
        },
    )
    return JSONResponse({"shared": True, "project_id": project_id, "email": req.email, "permission": req.permission})


@app.delete("/v1/projects/{project_id}/share/{share_id}")
def remove_project_share(project_id: str, share_id: str, request: Request):
    """Supprime un partage de projet."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    # Vérifier que l'utilisateur a les droits
    proj = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&select=id,owner_id",
        headers=sb_headers(),
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    if not user["is_service"] and proj[0]["owner_id"] != user["user_id"]:
        raise HTTPException(status_code=403, detail="Vous n'avez pas les droits pour gérer les partages de ce projet")

    http_json(
        "DELETE",
        f"{SUPABASE_URL}/rest/v1/project_shares?id=eq.{share_id}&project_id=eq.{project_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True, "share_id": share_id})


@app.get("/v1/projects/{project_id}/shares")
def list_project_shares(project_id: str, request: Request):
    """Liste les partages d'un projet."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    # Vérifier que l'utilisateur a accès au projet
    proj = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/projects?id=eq.{project_id}&select=id,owner_id,name",
        headers=sb_headers(),
    )
    if not proj:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    if not user["is_service"] and proj[0]["owner_id"] != user["user_id"]:
        # Vérifier s'il a un partage
        shares = http_json(
            "GET",
            f"{SUPABASE_URL}/rest/v1/project_shares?project_id=eq.{project_id}"
            f"&shared_with_email=eq.{urllib.parse.quote(user['email'])}&select=id",
            headers=sb_headers(),
        )
        if not shares:
            raise HTTPException(status_code=403, detail="Vous n'avez pas accès à ce projet")

    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/project_shares?project_id=eq.{project_id}"
        f"&select=id,shared_with_email,permission,shared_by,created_at&order=created_at.desc",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/shares/me")
def list_my_shares(request: Request):
    """Liste les projets partagés avec l'utilisateur connecté."""
    user = get_current_user(request)
    check_rate_limit(get_client_ip(request))

    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/project_shares?shared_with_email=eq.{urllib.parse.quote(user['email'])}"
        f"&select=id,project_id,permission,shared_by,created_at,project:project_id(id,name,enterprise_id,description)",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)
