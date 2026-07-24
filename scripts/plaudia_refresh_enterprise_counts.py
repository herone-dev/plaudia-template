#!/usr/bin/env python3
"""Refresh the enterprise_counts materialized view every 15 minutes."""
import json, urllib.request, urllib.error
import os

# Ces variables doivent être dans /opt/data/.env
PROJECT_ID = os.environ.get("SUPABASE_PROJECT_ID", "")
SUPABASE_ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")

if not PROJECT_ID or not SUPABASE_ACCESS_TOKEN:
    print("[enterprise-counts] Missing SUPABASE_PROJECT_ID or SUPABASE_ACCESS_TOKEN")
    exit(1)

URL = f"https://api.supabase.com/v1/projects/{PROJECT_ID}/database/query"
body = json.dumps({"query": "REFRESH MATERIALIZED VIEW enterprise_counts;"}).encode()
headers = {
    "Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
    "Content-Type": "application/json",
    "User-Agent": "python-urllib/3.13",
}
req = urllib.request.Request(URL, data=body, headers=headers, method="POST")
try:
    with urllib.request.urlopen(req, timeout=15):
        pass  # success, silent per no_agent contract
except urllib.error.HTTPError as e:
    print(f"[enterprise-counts] Refresh failed: {e}: {e.read().decode()[:200]}")
except Exception as e:
    print(f"[enterprise-counts] Error: {e}")

