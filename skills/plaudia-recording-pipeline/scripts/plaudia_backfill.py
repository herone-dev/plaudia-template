#!/usr/bin/env python3
"""
Backfill recordings with Plaud metadata (serial_number, plaud_created_at) 
and transcript_segments (structured JSON with per-segment timestamps).

Run when new recordings are imported without transcript_segments, 
or when the schema gains new Plaud metadata columns.

Usage:
    python3 /opt/data/scripts/plaudia_backfill.py

Requires:
    - /opt/data/mcp-tokens/plaud.json (Plaud OAuth token)
    - Supabase service key (sbp_...) in the script constants
"""
import json, os, urllib.request, sys, time

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SERVICE_KEY = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
PLAUD_MCP = "https://mcp.plaud.ai/mcp"

with open("/opt/data/mcp-tokens/plaud.json") as f:
    tok = json.load(f)
PLAUD_TOKEN = tok["access_token"]

def plaud_call(method, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": method, "arguments": args}}
    req = urllib.request.Request(PLAUD_MCP,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {PLAUD_TOKEN}",
                 "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "User-Agent": "curl/8.5.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
    for line in raw.strip().splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            result = data["result"]
            if isinstance(result, dict) and "content" in result:
                return json.loads(result["content"][0]["text"])
            return result
    return None

def supabase_query(sql):
    url = f"https://api.supabase.com/v1/projects/{os.environ.get('SUPABASE_PROJECT_ID', '')}/database/query"
    req = urllib.request.Request(url,
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {SERVICE_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "curl/8.5.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

# Get all recordings that need backfill
rows = supabase_query(
    "SELECT id, plaud_file_id, title FROM recordings "
    "WHERE plaud_file_id IS NOT NULL AND plaud_file_id != '' "
    "AND plaud_file_id NOT LIKE 'demo-%' "
    "AND (transcript_segments IS NULL OR serial_number IS NULL) "
    "ORDER BY created_at ASC"
)

print(f"🔍 {len(rows)} enregistrements à backfill")

count = 0
for row in rows:
    rid = row["id"]
    pfid = row["plaud_file_id"]
    title = row["title"][:60]
    
    print(f"\n[{count+1}/{len(rows)}] {pfid} — {title}")
    
    try:
        # 1. Get metadata from Plaud
        file_data = plaud_call("get_file", {"file_id": pfid})
        plaud_created = file_data.get("created_at")
        serial = file_data.get("serial_number")
        plaud_duration = int(file_data.get("duration", 0))
        
        # 2. Get transcript segments
        transcript_data = plaud_call("get_transcript", {"file_id": pfid})
        
        clean_segments = []
        if isinstance(transcript_data, list):
            for item in transcript_data:
                if item.get("data_type") == "transaction":
                    raw_segments = json.loads(item.get("data_content", "[]"))
                    for seg in raw_segments:
                        clean_segments.append({
                            "speaker": seg.get("speaker", seg.get("original_speaker", "Speaker")),
                            "original_speaker": seg.get("original_speaker", seg.get("speaker", "")),
                            "content": seg.get("content", ""),
                            "start_time": seg.get("start_time", 0),
                            "end_time": seg.get("end_time", 0),
                        })
        elif isinstance(transcript_data, dict) and "segments" in transcript_data:
            clean_segments = transcript_data["segments"]
        
        print(f"   📝 {len(clean_segments)} segments")
        
        # 3. Update database
        segs_json = json.dumps(clean_segments).replace("'", "''")
        serial_escaped = serial.replace("'", "''") if serial else ""
        plaud_created_escaped = plaud_created.replace("T", " ").replace("Z", "+00") if plaud_created else None
        
        update_sql = f"""
        UPDATE recordings SET
            transcript_segments = '{segs_json}'::jsonb,
            serial_number = '{serial_escaped}',
            plaud_created_at = {'TIMESTAMPTZ ' + repr(plaud_created_escaped) if plaud_created_escaped else 'NULL'},
            duration_seconds = {plaud_duration // 1000}
        WHERE id = '{rid}';
        """
        supabase_query(update_sql)
        print(f"   ✅ Mis à jour")
        count += 1
        
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    time.sleep(0.5)

print(f"\n✅ {count}/{len(rows)} enregistrements backfillés")