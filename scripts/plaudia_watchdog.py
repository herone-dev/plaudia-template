#!/usr/bin/env python3
"""
Plaudia watchdog — 0-token free check.

Runs as a no_agent cron job (pure script, no LLM invocation). Calls the Plaud
MCP endpoint and the Supabase Management API directly via HTTP (no hermes
agent loop, no token cost), compares the last 20 Plaud recordings against the
`recordings` table by plaud_file_id, and:
  - if nothing new: prints nothing (silent, per no_agent contract)
  - if new recordings found: prints a short report AND triggers the real
    LLM-driven pipeline job via `hermes cron run <job_id>` so the actual
    transcript+CR generation (which legitimately needs an LLM) only runs
    when there's real work to do.

Refreshes the Plaud OAuth token via refresh_token grant if the cached
access_token is expired (plain HTTP, still 0 LLM tokens).
"""
import json
import subprocess
import sys
import time
import urllib.request

PLAUD_TOKEN_PATH = "/opt/data/mcp-tokens/plaud.json"
PLAUD_CLIENT_PATH = "/opt/data/mcp-tokens/plaud.client.json"
PLAUD_META_PATH = "/opt/data/mcp-tokens/plaud.meta.json"
PLAUD_MCP_URL = "https://mcp.plaud.ai/mcp"

SUPABASE_PROJECT_ID = "ezqbxfmafvdjtgrrxcxy"
SUPABASE_ACCESS_TOKEN = "sbp_1dc29f31b802ecebb16c2249b06e8c1615e275a0"
SUPABASE_QUERY_URL = f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT_ID}/database/query"

# The real LLM pipeline job (only run when the watchdog finds something new).
LLM_JOB_ID = "d4777fc4327a"

N_RECENT = 20


def http_post_json(url, headers, body, timeout=20):
    data = json.dumps(body).encode("utf-8")
    # Supabase's edge (Cloudflare) blocks the default Python urllib User-Agent
    # with a 403/"error code: 1010" — always send an explicit UA.
    headers = {"User-Agent": "curl/8.5.0", **headers}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def load_plaud_token():
    with open(PLAUD_TOKEN_PATH) as f:
        tok = json.load(f)
    if tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    # refresh
    with open(PLAUD_CLIENT_PATH) as f:
        client = json.load(f)
    with open(PLAUD_META_PATH) as f:
        meta = json.load(f)
    body = urllib.parse_encode = None
    import urllib.parse
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


def list_recent_plaud_files(token, n=N_RECENT):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "list_files",
            "arguments": {"page": 1, "page_size": n},
        },
    }
    raw = http_post_json(
        PLAUD_MCP_URL,
        {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        body,
    )
    # SSE-style "event: message\ndata: {...}" or plain JSON
    line = raw.strip().splitlines()[-1]
    if line.startswith("data:"):
        line = line[len("data:"):].strip()
    outer = json.loads(line)
    result = outer["result"]
    # MCP tool call result: {"content":[{"type":"text","text":"..json.."}], ...}
    if isinstance(result, dict) and "content" in result:
        text = result["content"][0]["text"]
        payload = json.loads(text)
    else:
        payload = result
    items = payload.get("data", payload) if isinstance(payload, dict) else payload
    return items


def get_existing_recording_ids(file_ids):
    if not file_ids:
        return set()
    ids_sql = ",".join(f"'{fid}'" for fid in file_ids)
    query = f"select plaud_file_id from recordings where plaud_file_id in ({ids_sql});"
    raw = http_post_json(
        SUPABASE_QUERY_URL,
        {
            "Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        {"query": query},
    )
    rows = json.loads(raw)
    return {r["plaud_file_id"] for r in rows}


def trigger_llm_pipeline():
    subprocess.run(
        ["hermes", "cron", "run", LLM_JOB_ID],
        check=False,
        capture_output=True,
        timeout=30,
    )


def main():
    try:
        token = load_plaud_token()
        files = list_recent_plaud_files(token, N_RECENT)
        file_ids = [f["id"] for f in files]
        existing = get_existing_recording_ids(file_ids)
        new_ids = [fid for fid in file_ids if fid not in existing]
    except Exception as e:
        # Fail loud but don't spam every 5 minutes for a transient error —
        # print so the user sees it once, but this is rare (network/auth).
        print(f"[plaudia-watchdog] Erreur de vérification: {e}")
        return

    if not new_ids:
        return  # silent — nothing to report, no LLM triggered

    names_by_id = {f["id"]: f["name"] for f in files}
    lines = [f"[plaudia-watchdog] {len(new_ids)} nouvel(aux) enregistrement(s) Plaud détecté(s), déclenchement du pipeline complet :"]
    for fid in new_ids:
        lines.append(f"  - {names_by_id.get(fid, fid)} ({fid})")
    print("\n".join(lines))
    trigger_llm_pipeline()


if __name__ == "__main__":
    main()
