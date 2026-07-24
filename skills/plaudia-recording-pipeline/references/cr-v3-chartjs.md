# CR V3 — Template/Content Separation + Chart.js (15/07/2026)

## Architecture change
The backend no longer sends the full HTML (20KB) to DeepSeek for edits. Instead:
1. `extract_article()` extracts `<article>` from the frontend's HTML
2. DeepSeek receives only the article (~5KB) — more reliable, fewer tokens
3. `render_cr()` wraps the article back with the template CSS + Chart.js CDN
4. Full HTML stored in `crs.content`

## Key functions (main.py)
- `get_template_shell()` — reads CSS from `templates.html_template`, builds DOCTYPE+head+style+body shell with `{{CONTENT}}` placeholder. Cached 5 minutes in `_template_cache`.
- `extract_article(html)` — regex `<article>...</article>`, falls back to original HTML
- `render_cr(content)` — `shell.replace("{{CONTENT}}", content)`

## Edit prompt (new, 15/07)
Tells DeepSeek to ONLY generate the `<article>` content, never `<style>`, `<head>`, DOCTYPE, or Chart.js CDN. The prompt explicitly says: "Le CSS et le CDN Chart.js sont gérés automatiquement par le système."

## Chart.js in CRs
- CDN: `chart.js@4.4.7` in `<head>` (via template)
- Palette Hérone: `#1e3a5f, #3b82f6, #93c5fd, #bfdbfe, #dbeafe`
- Max size: 320px wide, 200px tall
- Chart types: doughnut (budget), bar (comparison), horizontal bar (timeline), line (evolution)
- Format: `<div class="chart-container" style="max-width:320px"><canvas id="chart-xxx"></canvas></div><script>new Chart(...)</script>`
- **PITFALL**: frontend must use `<iframe srcDoc={crContent} />` — `dangerouslySetInnerHTML` blocks `<script>`

## Glossary detection (expanded 15/07)
New patterns for natural-language corrections:
- `"c'est X pas Y"` → X is the correct term, Y is the wrong one
- `"c'est X et non Y"` → same
- `"c'était X pas Y"` → same
- `"s'appelle X"` → X is the correct name
Regex patterns: `r"\b(c'est\s+\S+\s+pas\s+|c'est\s+\S+\s+et\s+non\s+|c'était\s+\S+\s+pas\s+)\b"`

## Martin's CR preferences
- Exhaustive: 2000-3000+ words, NO length limit
- Structure: Résumé exécutif → Sections thématiques → Frictions → Tableau décisions/actions → Prochaine réunion → Footer
- "Parcours" method: re-read transcript segment by segment after writing, verify every point is covered
- Auto Chart.js when transcript has numerical data
- Final table: decisions (blue label) + actions (orange label) with responsible + deadline

## Test results (15/07)
12/12 CR edit tests passed (100%) on real CRs (Hérone, Allianz, Lixogo, Hati, Agence H, Jérôme Lombard):
- Added Chart.js charts (doughnut, bar, timeline, Hérone palette respected)
- Added sections (résumé exécutif, prochaines étapes, points de blocage)
- Added tables (coût/délai/équipe, documents à fournir)
- Text modifications (renaming sections, numbered lists)
- Each CR modified: template CSS intact, Chart.js CDN in `<head>`, version incremented + backup

## Known pitfalls
- DeepSeek omits `<CR>` tags → fallback extraction (5 levels); V3 bypasses by sending only article
- `request.json()` in sync FastAPI endpoint is a coroutine → use `request.body()` + `json.loads()`
- `plaudia-keepalive` cron restarts uvicorn if process dies → always verify PID after restart
- ANON_KEY was truncated in source code → use `mcp_supabase_get_publishable_keys` for the real key
- No charts in PDF/email exports → Chart.js is browser-only; need server-side rendering for exports