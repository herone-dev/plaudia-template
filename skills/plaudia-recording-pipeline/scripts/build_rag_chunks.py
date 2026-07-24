#!/usr/bin/env python3
"""
Backfill rag_chunks for Plaudia CRs: extract sections from CR HTML, embed via
OpenAI, insert via Supabase REST API. Tested pattern — copy and adapt the
constants at the top (SUPABASE_URL, ANON_KEY, EMAIL/PASSWORD or service key).

Why this shape (see supabase-schema-design skill, Step 6d):
- Talks to Supabase/OpenAI over plain REST/urllib, not mcp_supabase_execute_sql,
  so 1536-dim embedding vectors never pass through the agent's own tool-call
  context (each vector is ~15KB as text; doing this for 100+ chunks in-context
  is pure waste).
- Tolerant HTML extraction: supports both the current CR schema
  (<section class="cr-section">) and the legacy format some earlier CRs were
  generated with (<div class="cr-section">, <th> table headers, <span> label
  wrappers) — don't assume every row in an existing project uses the latest
  schema.
- `rag_chunks.owner_id` is NOT NULL — must be propagated from
  `recordings.owner_id`, it's easy to forget since chunks conceptually belong
  to the recording+cr, not directly to a user.
- POST with `Prefer: return=minimal` returns an empty body — don't json.loads
  an empty string, treat it as a `None`/success case explicitly, or you'll
  misreport successful inserts as errors.

Run via `terminal` (`python3 build_rag_chunks.py`), not `execute_code` — needs
outbound HTTPS + a real OPENAI_API_KEY from the environment.
"""
import os, re, json, urllib.request, urllib.error

SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
ANON_KEY = "YOUR_ANON_OR_PUBLISHABLE_KEY"
OPENAI_KEY = os.environ["OPENAI_API_KEY"]
EMAIL = "user@example.com"       # a real auth.users row with RLS access to the tables
PASSWORD = "..."                  # or swap get_access_token() for a service_role key + apikey header


def http(method, url, headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            if not raw.strip():
                return None  # e.g. Prefer: return=minimal -> empty 20x body, NOT an error
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:500]}")


def get_access_token():
    d = http("POST", f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
              headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
              body={"email": EMAIL, "password": PASSWORD})
    return d["access_token"]


def sb_headers(token):
    return {"apikey": ANON_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def strip_html(html):
    text = re.sub(r'<[^>]+>', ' ', html)
    for a, b in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'"), ('&nbsp;', ' ')]:
        text = text.replace(a, b)
    return re.sub(r'\s+', ' ', text).strip()


def _extract_legacy_div_sections(html):
    """Balanced-tag extraction of <div class="cr-section">...</div> blocks,
    tolerant of nested <div> tags inside (e.g. cr-body wrapper divs). Needed
    for CRs generated before the <section>/<header>/<dl> schema was locked in."""
    results = []
    for m in re.finditer(r'<div class="cr-section">', html):
        start = m.end()
        depth = 1
        pos = start
        tag_re = re.compile(r'<div\b|</div>')
        tm = None
        while depth > 0:
            tm = tag_re.search(html, pos)
            if not tm:
                break
            depth += 1 if tm.group(0) != '</div>' else -1
            pos = tm.end()
        if tm and depth == 0:
            results.append(html[start:tm.start()])
    return results


def extract_sections(html):
    sections = re.findall(r'<section class="cr-section">(.*?)</section>', html, re.DOTALL)
    if not sections:
        sections = _extract_legacy_div_sections(html)
    parsed = []
    for sec in sections:
        title_m = re.search(r'<h2 class="cr-section-title">(.*?)</h2>', sec, re.DOTALL)
        title = strip_html(title_m.group(1)) if title_m else ''
        has_table = '<table class="cr-table"' in sec
        if has_table:
            rows = re.findall(r'<td class="cr-table-label[^"]*">(.*?)</td>\s*<td class="cr-table-content">(.*?)</td>', sec, re.DOTALL)
            if not rows:
                # legacy: <tr><td><span class="cr-label-orange">Label</span></td><td>Content</td></tr>
                rows = re.findall(r'<tr>\s*<td>\s*<span class="cr-label-\w+">(.*?)</span>\s*</td>\s*<td>(.*?)</td>\s*</tr>', sec, re.DOTALL)
            table_type = 'decisions_actions'
            tl = title.lower()
            if 'prochaine' in tl or 'préparé' in tl:
                table_type = 'next_meeting'
            elif 'suspens' in tl or 'arbitrage' in tl:
                table_type = 'open_decisions'
            parts = [f"{strip_html(l)} — {strip_html(c)}" for l, c in rows]
            content_text = (f"{title} : " if title else "") + ". ".join(parts)
            parsed.append({'type': 'cr_final_table', 'title': title, 'table_type': table_type, 'text': content_text})
        else:
            body_text = strip_html(sec)
            if title and body_text.startswith(title):
                body_text = body_text[len(title):].strip()
            parsed.append({'type': 'cr_section', 'title': title, 'text': body_text})
    return parsed


def get_embeddings(texts):
    if not texts:
        return []
    req = urllib.request.Request(
        'https://api.openai.com/v1/embeddings',
        data=json.dumps({'model': 'text-embedding-3-small', 'input': texts}).encode(),
        headers={'Authorization': f'Bearer {OPENAI_KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return [item['embedding'] for item in json.loads(r.read())['data']]


def main():
    token = get_access_token()
    h = sb_headers(token)

    recs = http("GET",
        f"{SUPABASE_URL}/rest/v1/recordings?select=id,owner_id,client_name,recorded_at,is_private,status,"
        f"crs(id,content)&is_private=eq.false&status=eq.ready",
        headers=h)

    existing = http("GET", f"{SUPABASE_URL}/rest/v1/rag_chunks?select=recording_id&chunk_type=neq.transcription_full", headers=h)
    done = {c['recording_id'] for c in (existing or [])}

    inserted, processed, skipped, errors = 0, 0, 0, []
    for rec in recs or []:
        rid = rec['id']
        crs = rec.get('crs') or []
        cr = crs[0] if isinstance(crs, list) and crs else (crs if isinstance(crs, dict) else None)
        if not cr or not cr.get('content') or rid in done:
            skipped += 1
            continue
        sections = extract_sections(cr['content'])
        if not sections:
            errors.append(f"{rid}: no sections extracted")
            continue
        try:
            embeddings = get_embeddings([s['text'][:6000] for s in sections])
        except Exception as e:
            errors.append(f"{rid}: embedding error {e}")
            continue

        client_name = rec.get('client_name')
        if client_name == 'À classer':
            client_name = None
        meeting_date = (rec.get('recorded_at') or '')[:10] or None

        rows = []
        for idx, (sec, emb) in enumerate(zip(sections, embeddings)):
            meta = {'section_title': sec['title']}
            if sec['type'] == 'cr_final_table':
                meta['table_type'] = sec['table_type']
            rows.append({
                'recording_id': rid, 'cr_id': cr['id'], 'owner_id': rec['owner_id'],
                'chunk_type': sec['type'], 'chunk_index': idx + 1,
                'content': sec['text'][:6000], 'embedding': emb,
                'client_name': client_name, 'metadata': meta, 'meeting_date': meeting_date,
            })
        try:
            http("POST", f"{SUPABASE_URL}/rest/v1/rag_chunks", headers={**h, "Prefer": "return=minimal"}, body=rows)
            inserted += len(rows)
            processed += 1
        except Exception as e:
            errors.append(f"{rid}: insert error {e}")

    print(json.dumps({"processed": processed, "skipped": skipped, "chunks_inserted": inserted, "errors": errors}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
