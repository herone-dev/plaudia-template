# CR Edit V3 — Content/Form Separation + SVG Charts (15/07/2026)

## Content/Form Separation

The CR edit flow now separates content from presentation:

```
Frontend sends: <CR>{full_html}</CR>\n\nInstruction : {msg}
  ↓
Backend: extract_article() → strips <style>/<head>/DOCTYPE, keeps only <article>
  ↓
DeepSeek: edits ONLY the <article> content (no CSS, no head, no CDN scripts)
  ↓
Backend: render_cr() → wraps result with template shell (DOCTYPE + CSS + head)
  ↓
Backend: render_charts_in_cr() → replaces chart-embed markers with matplotlib SVG
  ↓
Stored in crs.content as complete HTML with SVG inline
```

## Key functions in main.py

- `extract_article(html)` — regex strips everything but `<article>...</article>`
- `render_cr(content)` — wraps article with `get_template_shell()`
- `render_charts_in_cr(html)` — finds `<script class="chart-embed">` markers, replaces with SVG via subprocess
- `get_template_shell()` — fetches CSS from `templates.html_template`, builds full HTML shell
- `http_json()` — shared HTTP helper for Supabase REST calls
- `call_opus()` — calls DeepSeek V4 Flash via OpenRouter

## SVG Chart generation (matplotlib)

**Chart renderer**: `/opt/data/projects/plaudia/rag_backend/chart_renderer.py`
**Python**: `/opt/data/dwg-env/bin/python3` (matplotlib installed here, not in Hermes venv)

**Format**: User provides data in their instruction. DeepSeek outputs a JSON marker:
```html
<script type="application/json" class="chart-embed">
{"type":"bar","title":"Paliers tarifaires","labels":["Free","Intermédiaire","Premium"],
 "datasets":[{"data":[0,55,99]}],"unit":"€/mois"}
</script>
```

Supported chart types: `bar` (vertical), `bar` with `indexAxis: "y"` (horizontal), `doughnut`, `line`.

**CRITICAL RULE**: User MUST provide data. DeepSeek MUST NOT invent chart data. The edit prompt enforces this.

## DeepSeek Pitfalls

- DeepSeek V4 Flash does NOT always output `<CR>` tags — the backend has a fallback extraction chain (CR tags → DOCTYPE → html → article)
- DeepSeek invents data for charts when asked vaguely — the user must provide exact values
- DeepSeek may remove `<table class="cr-table">` during edits — the prompt now says "PRÉSERVE les tableaux"
- DeepSeek may return text before/after the HTML — the extraction handles this

## Backend lifecycle

- Keepalive (`plaudia-keepalive`, cron every minute) checks `http://127.0.0.1:8000/healthz`
- If down → restarts uvicorn from current `main.py`
- Manually started background processes are killed by keepalive after ~60s
- To stop the backend: disable the cron job first, then `pkill -f "uvicorn main:app"`
- Two cloudflared tunnels may coexist; kill the old one if needed

## Glossary Correction Detection

The `detect_glossary_correction()` function detects spelling/name corrections:
- Keywords: `écrit, corrige, orthographe, renomme, s'appelle`
- Patterns: `"c'est X pas Y"`, `"c'est X et non Y"`, `"on dit X pas Y"`
- Calls DeepSeek with GLOSSARY_DETECT_PROMPT to extract JSON: `{"is_correction": true, "term_raw": "...", "term_corrected": "..."}`
- Inserts into `glossary` table → DB trigger rewrites all existing CRs

## Testing approach

When testing CR edits, verify CONTENT not just save status:
- Check that SVG was generated (not just chart-embed marker)
- Verify table structures are preserved
- Check that chart data matches the actual transcription (not invented)
- A test that only checks "version incremented" is insufficient