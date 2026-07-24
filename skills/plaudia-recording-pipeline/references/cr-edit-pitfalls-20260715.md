# CR Edit — Pitfalls & Learnings (July 2026)

## Template/Content Separation (V2+)
Backend separates form from content during CR edits:
1. `extract_article()` — strips `<article>...</article>` from full HTML
2. Only the article content is sent to DeepSeek (no CSS/head/DOCTYPE)
3. `render_cr()` — re-wraps with template shell via `get_template_shell()`
4. Reduces tokens by ~60%, prevents CSS/style drift

## Chart.js — NEVER Let LLM Invent Data
DeepSeek hallucinates chart data. Tested and confirmed: every automated chart request produced fake numbers. The only safe approach:
- **User must provide exact data** in the edit chat message
- ✅ "ajoute un doughnut : Free=0€, Intermédiaire=55€, Premium=99€"
- ❌ "ajoute un graphique" (no data → LLM invents)
- Edit prompt enforces: "Si l'utilisateur ne fournit pas les données exactes, ne crée PAS de graphique."
- Template `prompt_instructions` no longer has automatic chart generation

## Charts Don't Render (Frontend)
The frontend uses React `dangerouslySetInnerHTML` which blocks `<script>` execution. Chart.js won't work. Must render CR in `<iframe>` with `srcDoc`:
```tsx
<iframe srcDoc={crContent} style={{width:'100%',border:'none',minHeight:'800px'}} />
```
This is a frontend change, not backend.

## Glossary Detection — "c'est X pas Y" Pattern
The `detect_glossary_correction()` regex patterns miss natural language corrections. Add these patterns:
- `r"\b(c'est\s+\S+\s+pas\s+)\b"`
- `r"\b(c'est\s+\S+\s+et\s+non\s+)\b"`
- `r"\b(pas\s+\S+\s+mais\s+)\b"`
Also update `GLOSSARY_DETECT_PROMPT` with matching examples.

## Edit Prompt Must Preserve Tables
The LLM sometimes converts `<table class="cr-table">` to plain text. The prompt must include: "PRÉSERVE les tableaux <table class=\"cr-table\"> — ne les supprime pas, ne les convertis pas en texte."

## DeepSeek V4 Flash — <CR> Tag Fallback
DeepSeek does not consistently output `<CR>...</CR>`. The backend fallback chain (in order):
1. `<CR>...</CR>` regex
2. Markdown code block ```html ... ```
3. `<!DOCTYPE html...` catch-all
4. `<html>...</html>`
5. `<article class="cr-document">...</article>`
6. Any `<article>...</article>`

## Keepalive Cron Restarts Backend
The `plaudia-keepalive` cron (* * * * *) restarts uvicorn if healthz fails. Background processes may be killed. Wait ~5-10s after pkill for keepalive to restart. Code is read from disk, so file changes are picked up.