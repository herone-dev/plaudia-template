#!/usr/bin/env python3
"""
Plaudia RAG-chat backend — OpenAI-compatible endpoint consumed by the Lovable frontend.
Copy this file, fill in the constants below, run with:
  uvicorn rag_chat_backend:app --host 0.0.0.0 --port <port>
Then expose it (for testing) via a Cloudflare quick tunnel — see SKILL.md.

Verified working end-to-end in a real session, INCLUDING the write-back path, the
security layer, AND persistent multi-turn chat history:
  - Read-only RAG questions: client detection by substring match, embedding +
    match_rag_chunks RPC filter, Claude synthesis grounded strictly in retrieved chunks.
  - CR-edit requests (frontend's "Itération Hermès" panel): Claude applies the requested
    change only, new HTML extracted from <CR>...</CR>, PATCHed straight into crs.content
    with version+1 — confirmed via a real DB check (version incremented, marker text
    present then correctly removed on cleanup). See SKILL.md section "Closing the
    CR-edit-by-chat stub for real" before reusing. This flow stays fully STATELESS —
    no session_id, no history — see the history section below for why.
  - Shared-key auth (401 without it) + per-IP sliding-window rate limit (429 on burst,
    verified with CONCURRENT requests, not sequential — see SKILL.md "Securing the public
    RAG-chat backend").
  - Auth accepts the shared key via header (fetch-based POST calls) OR query param
    (EventSource-based SSE calls, which cannot send custom headers at all — see SKILL.md
    "Debugging a frontend-reported connection/auth error against this backend").
  - Persistent, multi-turn chat history: each RAG question/answer is saved to
    chat_sessions/chat_messages; the last N exchanges of the active session are replayed
    to Claude as context so elliptical follow-ups ("et pour Hérone ?") resolve correctly;
    a sidebar-style UI can list/reopen/delete past conversations. See SKILL.md section
    "Adding persistent, multi-turn chat history to the RAG-chat backend" for the schema
    migration this depends on and the cost tradeoff to state to the user up front.

Known simplification: single fixed service-account login, not per-user auth —
see SKILL.md section "Building the actual RAG-chat backend" before reusing as-is. All
chat history is currently stored under that one service account's owner_id too.
"""
import os
import re
import time
import json
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict, deque
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

# --- Fill these in per project ---
SUPABASE_URL = "https://<project-ref>.supabase.co"
ANON_KEY = "<anon/publishable key>"
SERVICE_EMAIL = "<service-account email, e.g. martin@herone.fr>"
SERVICE_PASSWORD = os.environ.get("PLAUDIA_SERVICE_PASSWORD", "<default password>")
OPENAI_KEY = os.environ["OPENAI_API_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]
# Shared secret the frontend must send in X-Plaudia-Key (fetch calls) or ?plaudia_key=
# (EventSource calls, which cannot set custom headers). Without it, no request reaches
# Supabase/OpenAI/Anthropic — this is what stops "anyone who finds the tunnel URL can
# rack up API costs or read data." Generate with:
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
PLAUDIA_SHARED_KEY = os.environ.get("PLAUDIA_SHARED_KEY", "")
# Value used by recordings.client_name to mean "not yet classified" — excluded from the
# known-client list used for detection.
UNCLASSIFIED_PLACEHOLDER = "À classer"
# How many prior exchanges (user+assistant pairs) get replayed to Claude as context on
# every new question in an existing chat thread. Higher = better continuity across
# elliptical follow-ups, but every question then re-pays the token cost of all those
# prior messages — state this tradeoff to the user rather than silently picking a depth.
HISTORY_TURNS = 4

app = FastAPI(title="Plaudia RAG Chat Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Rate limiting: simple in-memory sliding window per real client IP. ---
# Not distributed, resets on restart. Good enough for guarding API spend on a single
# small backend, not a substitute for a real gateway/WAF if this needs to scale.
_RATE_LIMIT_MAX = 20        # requests
_RATE_LIMIT_WINDOW = 60     # seconds
_rate_buckets: dict[str, deque] = defaultdict(deque)


def get_client_ip(request: Request) -> str:
    # Behind cloudflared (or any tunnel/proxy), request.client.host is the tunnel's
    # local peer for EVERY caller — always prefer X-Forwarded-For, or every visitor
    # shares one rate-limit bucket.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(client_ip: str):
    now = time.time()
    bucket = _rate_buckets[client_ip]
    while bucket and now - bucket[0] > _RATE_LIMIT_WINDOW:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Trop de requêtes — réessaie dans une minute.")
    bucket.append(now)


def check_shared_key(request: Request, query_key: Optional[str] = None):
    # Accepts the secret from EITHER the header (fetch-based calls) OR a query param
    # (EventSource-based SSE calls — browsers give EventSource no way to set custom
    # headers, so a header-only check silently locks that route out of auth entirely).
    if not PLAUDIA_SHARED_KEY:
        # Fail closed: no key configured server-side means refuse everything, never
        # silently run unauthenticated.
        raise HTTPException(status_code=503, detail="Backend mal configuré : clé d'accès non définie côté serveur.")
    provided = request.headers.get("x-plaudia-key", "") or query_key or ""
    if provided != PLAUDIA_SHARED_KEY:
        raise HTTPException(status_code=401, detail="Accès refusé : clé d'accès invalide ou manquante.")


_token_cache = {"token": None, "expires_at": 0, "user_id": None}
_client_names_cache = {"names": None, "fetched_at": 0}


def http_json(method, url, headers=None, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            # Empty body (e.g. Prefer: return=minimal) is not an error — don't json.loads it.
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} calling {url}: {e.read().decode()[:500]}")


def get_supabase_token():
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["token"]
    d = http_json(
        "POST", f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
        body={"email": SERVICE_EMAIL, "password": SERVICE_PASSWORD},
    )
    _token_cache["token"] = d["access_token"]
    _token_cache["user_id"] = d.get("user", {}).get("id")
    _token_cache["expires_at"] = now + int(d.get("expires_in", 3600))
    return d["access_token"]


def get_service_owner_id():
    # All chat history is currently attributed to this one service-account owner_id —
    # see the module docstring's "known simplification" note.
    if not _token_cache.get("user_id"):
        get_supabase_token()
    return _token_cache["user_id"]


def sb_headers():
    return {"apikey": ANON_KEY, "Authorization": f"Bearer {get_supabase_token()}", "Content-Type": "application/json"}


def get_known_client_names():
    now = time.time()
    if _client_names_cache["names"] is not None and now - _client_names_cache["fetched_at"] < 300:
        return _client_names_cache["names"]
    # NB: non-ASCII literals (e.g. the placeholder above) MUST be urllib.parse.quote'd
    # before going into the query string, or urllib raises UnicodeEncodeError deep in
    # http.client — not an obviously-related-looking error.
    neq = urllib.parse.quote(UNCLASSIFIED_PLACEHOLDER)
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/recordings?select=client_name&client_name=not.is.null&client_name=neq.{neq}",
        headers=sb_headers(),
    )
    names = sorted(set(r["client_name"] for r in (rows or []) if r.get("client_name")))
    _client_names_cache["names"] = names
    _client_names_cache["fetched_at"] = now
    return names


def detect_client(question: str) -> Optional[str]:
    q_lower = question.lower()
    for name in get_known_client_names():
        if name.lower() in q_lower:
            return name
    return None


def embed(text: str):
    d = http_json(
        "POST", "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"},
        body={"model": "text-embedding-3-small", "input": text},
    )
    return d["data"][0]["embedding"]


def match_rag_chunks(embedding, client_name: Optional[str], match_count: int = 8):
    return http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/rpc/match_rag_chunks",
        headers=sb_headers(),
        body={"query_embedding": embedding, "filter_client_name": client_name, "match_count": match_count},
    )


def call_claude(system_prompt: str, messages: list, max_tokens: int = 1024) -> str:
    # max_tokens matters here: the RAG-question path only needs a synthesized answer
    # (~1024 is plenty), but the CR-edit path below returns a FULL CR's HTML (often
    # 10-15KB) inside <CR>...</CR> — pass a higher value (~4096) for that call site or
    # the response gets silently truncated mid-document.
    # `messages` is now a list of {"role", "content"} dicts (prior turns + the current
    # question), not a single string — needed for history replay. For the stateless
    # CR-edit path just pass a single-item list.
    d = http_json(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        body={
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": messages,
        },
        timeout=90,
    )
    return "".join(block.get("text", "") for block in d.get("content", []))


RAG_SYSTEM_PROMPT = """Tu es l'assistant RAG de Plaudia. Tu réponds UNIQUEMENT à partir des extraits \
de comptes-rendus fournis ci-dessous — jamais de connaissance générale ni d'invention. \
Si les extraits ne permettent pas de répondre, dis-le clairement plutôt que de deviner. \
Cite le client et la date de la réunion pour chaque fait avancé. Réponds en français, de façon directe et concrète. \
Le message le plus récent peut faire référence au contexte des échanges précédents dans cette même conversation \
(ex: "et pour Hérone ?" après une question sur Allianz) — utilise cet historique pour comprendre l'intention, \
mais fonde toujours la réponse elle-même sur les extraits fournis pour CETTE question."""

EDIT_SYSTEM_PROMPT = """Tu édites un compte-rendu de réunion au format HTML strict (article.cr-document, \
header, section.cr-section, table.cr-table). Applique UNIQUEMENT l'instruction demandée, \
ne réécris pas le reste du contenu, ne raccourcis rien qui n'a pas été demandé. \
Réponds avec une courte confirmation en une phrase, puis la version complète du CR modifié \
entre balises <CR>...</CR>."""


def build_context_block(chunks):
    if not chunks:
        return "(Aucun extrait pertinent trouvé.)"
    parts = []
    for c in chunks:
        meta = c.get("metadata") or {}
        title = meta.get("section_title", c.get("chunk_type"))
        client = c.get("client_name") or "client non classé"
        date = c.get("meeting_date") or "date inconnue"
        parts.append(f"[{client} — {date} — {title}]\n{c['content']}")
    return "\n\n---\n\n".join(parts)


def update_cr_content(cr_id: str, new_content: str) -> int:
    """Writes new content to crs.content, incrementing version — same contract as the
    frontend's own manual "Enregistrer" button, so chat-driven and manual edits stay
    consistent instead of silently diverging on shape."""
    current = http_json("GET", f"{SUPABASE_URL}/rest/v1/crs?id=eq.{cr_id}&select=version", headers=sb_headers())
    current_version = (current[0]["version"] if current else 0) or 0
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


# --- Chat session persistence (schema: chat_sessions + chat_messages, see SKILL.md
# "Adding persistent, multi-turn chat history" for the migration + RLS these assume) ---

def create_chat_session(owner_id: str, title: str) -> str:
    rows = http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/chat_sessions",
        headers={**sb_headers(), "Prefer": "return=representation"},
        body={"owner_id": owner_id, "title": title[:120]},
    )
    return rows[0]["id"]


def session_exists(session_id: str, owner_id: str) -> bool:
    rows = http_json(
        "GET", f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&owner_id=eq.{owner_id}&select=id",
        headers=sb_headers(),
    )
    return bool(rows)


def get_session_history(session_id: str, owner_id: str, limit_turns: int = HISTORY_TURNS):
    """Last `limit_turns` exchanges (up to 2*limit_turns messages), oldest first."""
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/chat_messages?session_id=eq.{session_id}&owner_id=eq.{owner_id}"
        f"&select=role,content,created_at&order=created_at.desc&limit={limit_turns * 2}",
        headers=sb_headers(),
    ) or []
    return list(reversed(rows))


def save_chat_message(session_id: str, owner_id: str, role: str, content: str):
    # Persist the raw question/answer, NOT the RAG-augmented prompt with retrieved-chunk
    # padding — keeps replayed history compact and human-readable if inspected.
    # Wrapped in try/except by the caller: a persistence hiccup must never break the
    # user-visible answer, but that also means a passing chat call does NOT by itself
    # prove persistence landed — verify separately via the /messages endpoint below.
    http_json(
        "POST", f"{SUPABASE_URL}/rest/v1/chat_messages",
        headers={**sb_headers(), "Prefer": "return=minimal"},
        body={"session_id": session_id, "owner_id": owner_id, "role": role, "content": content},
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    # Sent by the frontend's CRDetailView so an edit request knows which row to write to.
    # Without it, refuse cleanly rather than guessing which CR the user meant.
    cr_id: Optional[str] = None
    # RAG chat thread id; omit to start a new conversation (server creates one and
    # returns its id in the response body). NOT used by the CR-edit flow — that stays
    # fully stateless, see chat_completions() below.
    session_id: Optional[str] = None


def _openai_response(content: str, session_id: Optional[str] = None):
    body = {
        "id": "plaudia-rag-chat", "object": "chat.completion", "created": int(time.time()),
        "model": "plaudia-rag",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
    if session_id:
        body["session_id"] = session_id
    return JSONResponse(body)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest, request: Request):
    check_shared_key(request)
    check_rate_limit(get_client_ip(request))

    user_messages = [m for m in req.messages if m.role == "user"]
    question = user_messages[-1].content if user_messages else ""

    # The frontend's CR-edit flow wraps its instruction as "...Instruction : {msg}...<CR>...</CR>"
    # (see CRDetailView.tsx's send()). This stays a ONE-SHOT, STATELESS instruction->CR
    # round trip — no session_id, no history — deliberately unrelated to the RAG chat
    # thread, so CR-edit exchanges never pollute a conversation's replayed context with
    # irrelevant CR-HTML noise. Branch out here, before any session/history logic runs.
    is_cr_edit_request = "<CR>" in question and "Instruction :" in question
    if is_cr_edit_request:
        if not req.cr_id:
            return _openai_response(
                "Impossible d'enregistrer : identifiant du compte-rendu manquant dans la requête. "
                "Corrige le texte directement puis utilise le bouton Enregistrer."
            )
        try:
            claude_reply = call_claude(EDIT_SYSTEM_PROMPT, [{"role": "user", "content": question}], max_tokens=4096)
        except Exception as e:
            return _openai_response(f"Erreur lors de la génération de la modification : {e}")

        match = re.search(r"<CR>([\s\S]*?)</CR>", claude_reply)
        if not match:
            return _openai_response(
                "La modification n'a pas pu être extraite de la réponse — rien n'a été enregistré. "
                "Réessaie ou corrige manuellement."
            )
        new_content = match.group(1).strip()
        try:
            new_version = update_cr_content(req.cr_id, new_content)
        except Exception as e:
            return _openai_response(f"Modification générée mais échec de l'enregistrement en base : {e}")

        confirmation = claude_reply.replace(match.group(0), "").strip() or "Compte-rendu mis à jour."
        # Say explicitly that it was saved — the frontend only shows this text, and the
        # user needs a positive signal that (unlike a plain question) a DB write happened.
        return _openai_response(f"{confirmation}\n\n✅ Enregistré en base (version {new_version}).")

    # --- Plain RAG question flow, with persisted multi-turn history ---
    owner_id = get_service_owner_id()

    session_id = req.session_id
    is_new_session = False
    if session_id and not session_exists(session_id, owner_id):
        session_id = None  # stale/foreign id — start fresh rather than erroring
    if not session_id:
        session_id = create_chat_session(owner_id, title=question)
        is_new_session = True

    prior_messages = [] if is_new_session else get_session_history(session_id, owner_id)

    detected_client = detect_client(question)
    try:
        chunks = match_rag_chunks(embed(question), detected_client) or []
    except Exception as e:
        return _openai_response(f"Erreur lors de la recherche RAG : {e}", session_id=session_id)

    user_prompt = (
        f"Question : {question}\n\n"
        f"Client détecté : {detected_client or '(aucun — recherche non filtrée)'}\n\n"
        f"Extraits pertinents :\n\n{build_context_block(chunks)}"
    )
    claude_messages = [{"role": m["role"], "content": m["content"]} for m in prior_messages]
    claude_messages.append({"role": "user", "content": user_prompt})

    try:
        answer = call_claude(RAG_SYSTEM_PROMPT, claude_messages)
    except Exception as e:
        answer = f"Erreur lors de la génération de la réponse : {e}"

    # Persist raw question/answer. Never let a persistence hiccup fail the user-visible
    # response — but this also means success here does NOT prove the write landed;
    # verify separately (see the verification recipe in SKILL.md).
    try:
        save_chat_message(session_id, owner_id, "user", question)
        save_chat_message(session_id, owner_id, "assistant", answer)
    except Exception:
        pass

    return _openai_response(answer, session_id=session_id)


@app.get("/v1/chat/sessions")
def list_chat_sessions(request: Request, plaudia_key: str = ""):
    check_shared_key(request, query_key=plaudia_key)
    check_rate_limit(get_client_ip(request))
    owner_id = get_service_owner_id()
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/chat_sessions?owner_id=eq.{owner_id}&select=id,title,created_at,updated_at"
        f"&order=updated_at.desc&limit=100",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.get("/v1/chat/sessions/{session_id}/messages")
def get_chat_session_messages(session_id: str, request: Request, plaudia_key: str = ""):
    check_shared_key(request, query_key=plaudia_key)
    check_rate_limit(get_client_ip(request))
    owner_id = get_service_owner_id()
    rows = http_json(
        "GET",
        f"{SUPABASE_URL}/rest/v1/chat_messages?session_id=eq.{session_id}&owner_id=eq.{owner_id}"
        f"&select=role,content,created_at&order=created_at.asc",
        headers=sb_headers(),
    ) or []
    return JSONResponse(rows)


@app.delete("/v1/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, request: Request, plaudia_key: str = ""):
    check_shared_key(request, query_key=plaudia_key)
    check_rate_limit(get_client_ip(request))
    owner_id = get_service_owner_id()
    # Cascades to chat_messages via the FK — no need to delete messages separately.
    http_json(
        "DELETE", f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}&owner_id=eq.{owner_id}",
        headers={**sb_headers(), "Prefer": "return=minimal"},
    )
    return JSONResponse({"deleted": True})


@app.get("/v1/process-stream")
def process_stream(request: Request, document_id: str = "", vocal_context: str = "", plaudia_key: str = ""):
    # EventSource (used by the frontend's streamProcess) cannot send custom headers at
    # all — the auth secret MUST be accepted via query param here, not header-only,
    # or this route is silently unauthenticated-or-broken depending on how strict the
    # check is written. See SKILL.md "Debugging a frontend-reported connection/auth error".
    check_shared_key(request, query_key=plaudia_key)
    check_rate_limit(get_client_ip(request))
    # Placeholder: the real Plaud→CR generation pipeline runs via cron, not on-demand.
    message = "La génération à la demande n'est pas encore branchée — le CR est produit automatiquement par le pipeline."
    payload = json.dumps({"step": "done", "message": message})

    def gen():
        yield f"data: {payload}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# --- Manual verification recipe (don't trust sequential curl/urllib loops for rate limits) ---
# Sequential requests against a slow upstream (an LLM call, etc.) can spread across
# minutes and never trip a "N per 60s" limiter even when it's working correctly.
# Verify with CONCURRENT requests instead:
#
#   import urllib.request, json, concurrent.futures
#   def call(i):
#       req = urllib.request.Request(
#           "http://localhost:PORT/v1/chat/completions",
#           data=json.dumps({"messages": [{"role": "user", "content": "test"}]}).encode(),
#           headers={"Content-Type": "application/json", "X-Plaudia-Key": "..."}, method="POST")
#       try:
#           with urllib.request.urlopen(req, timeout=60) as r: return r.status
#       except urllib.error.HTTPError as e: return e.code
#   with concurrent.futures.ThreadPoolExecutor(max_workers=25) as ex:
#       codes = list(ex.map(call, range(25)))
#   print(codes.count(200), codes.count(429))  # expect a real split, e.g. 15 / 10
#
# --- Manual verification recipe for persistent chat history (session + context replay) ---
#   import urllib.request, json
#   def call(payload):
#       req = urllib.request.Request(
#           "http://localhost:PORT/v1/chat/completions", data=json.dumps(payload).encode(),
#           headers={"Content-Type": "application/json", "X-Plaudia-Key": "..."}, method="POST")
#       with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read())
#   r1 = call({"messages": [{"role": "user", "content": "sur quel sujet porte la reunion Allianz ?"}]})
#   sid = r1["session_id"]
#   r2 = call({"messages": [{"role": "user", "content": "et pour Hérone ?"}], "session_id": sid})
#   assert r2["session_id"] == sid  # thread continuity
#   # then hit GET /v1/chat/sessions/{sid}/messages and confirm exactly 4 rows in order —
#   # a passing chat call does NOT by itself prove persistence landed (save is best-effort).
#   # Clean up test sessions afterward: DELETE FROM chat_sessions WHERE id = '<sid>' (cascades).
#
# --- Debugging recipe for a frontend-reported connection/auth error ---
# Before touching frontend code, verify the backend independently:
#   curl -s https://<tunnel-url>/healthz
#   curl -s -X OPTIONS https://<tunnel-url>/v1/chat/completions \
#     -H "Origin: https://<real-frontend-domain>" \
#     -H "Access-Control-Request-Method: POST" \
#     -H "Access-Control-Request-Headers: content-type" -D -
#   curl -s -X POST https://<tunnel-url>/v1/chat/completions \
#     -H "Content-Type: application/json" -H "X-Plaudia-Key: <key>" \
#     -d '{"messages":[{"role":"user","content":"test"}]}' -w "\nHTTP:%{http_code}\n"
# If all three succeed cleanly, the bug is frontend-side (stale build, wrong env var,
# EventSource header limitation) — not the backend.
