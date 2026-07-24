#!/usr/bin/env python3
"""Wrap tous les CRs existants dans un HTML complet avec CSS embarqué.
Usage: python3 /opt/data/scripts/plaudia_css_backfill.py
Lit tous les CRs sans DOCTYPE, les wrappe avec le CSS du template, UPDATE en base.
Exécuté après migration v13 pour backfill CRs existants."""
import json
import urllib.request

SUPABASE_ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
SUPABASE_QUERY_URL = f"https://api.supabase.com/v1/projects/{os.environ.get('SUPABASE_PROJECT_ID', '')}/database/query"

CSS = """<style>
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
.cr-body { margin: 10px 0; text-align: justify; hyphens: auto; color: #374151; }
.cr-list { margin: 10px 0 10px 22px; padding: 0; color: #374151; }
.cr-list li { margin: 7px 0; padding-left: 4px; line-height: 1.65; }
.cr-table { width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 14px; }
.cr-table td { padding: 11px 15px; vertical-align: top; border: 1px solid #e5e7eb; line-height: 1.65; }
.cr-table-label { font-weight: 600; color: #ffffff; width: 28%; font-size: 13px; vertical-align: middle; }
.cr-label-orange { background-color: #d97706; }
.cr-label-blue   { background-color: #1e3a5f; }
.cr-table-content { background-color: #ffffff; color: #374151; width: 72%; }
.cr-footer { margin-top: 52px; padding-top: 16px; border-top: 1px solid #e5e7eb; text-align: center; font-size: 12px; color: #9ca3af; }
.cr-footer p { margin: 0; }
</style>"""

DOCTYPE_HEAD = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
""" + CSS + """
</head>
<body>
"""
FOOTER = "\n</body>\n</html>"


def supabase_query(sql):
    data = json.dumps({"query": sql}).encode("utf-8")
    req = urllib.request.Request(
        SUPABASE_QUERY_URL, data=data,
        headers={"Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
                 "Content-Type": "application/json",
                 "User-Agent": "curl/8.5.0"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    rows = supabase_query(
        "SELECT id, recording_id, content, version FROM crs WHERE content NOT LIKE '<!DOCTYPE%' ORDER BY created_at")
    print(f"🔍 {len(rows)} CRs à mettre à jour")
    count = 0
    for row in rows:
        cid = row["id"]
        new_content = DOCTYPE_HEAD + row["content"] + FOOTER
        escaped = new_content.replace("'", "''")
        supabase_query(f"UPDATE crs SET content = '{escaped}', version = {row['version']} WHERE id = '{cid}';")
        count += 1
        print(f"  [{count}] {row['recording_id'][:8]} — {len(row['content'])} → {len(new_content)} chars")
    print(f"\n✅ {count} CRs mis à jour avec CSS embarqué")

if __name__ == "__main__":
    main()