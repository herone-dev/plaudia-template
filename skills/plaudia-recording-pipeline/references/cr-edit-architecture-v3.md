# CR Edit Architecture — V3 (15/07/2026)

## Content/Template Separation

Le backend extrait le `<article>` du HTML complet avant de l'envoyer à DeepSeek, puis re-wrapper avec le template CSS après. DeepSeek ne manipule JAMAIS le `<style>` ni le CDN Chart.js.

```
Frontend → <CR>{DOCTYPE+STYLE+CONTENU}</CR>\n\nInstruction : {msg}
  ↓
Backend → extract_article() → <article>...</article> seul
  ↓
DeepSeek → modifie UNIQUEMENT le <article>
  ↓
Backend → render_cr() → re-wrapper avec template CSS + CDN Chart.js
  ↓
Stocké dans crs.content (HTML complet)
```

## Fonctions clés dans main.py

### `extract_article(html: str) -> str`
Extrait le `<article>...</article>` du HTML complet par regex. Si aucun article trouvé, retourne le HTML original.

### `render_cr(content: str) -> str`
Enveloppe le contenu avec le template shell complet (DOCTYPE + head + CSS + CDN Chart.js + body). Appelle `get_template_shell()`.

### `get_template_shell() -> str`
Récupère le template depuis la table `templates` (is_default=true). Cache en mémoire 5 min. Construit le shell HTML complet avec `{{CONTENT}}` comme placeholder.

## Chart.js Integration

- Le template inclut : `<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js">`
- Le LLM génère des `<canvas>` + `<script>` dans le `<article>`
- Les graphiques utilisent `<div class="chart-container" style="max-width:320px">`
- Canvas max-height: 200px
- Palette Hérone : `["#1e3a5f","#3b82f6","#93c5fd","#bfdbfe","#dbeafe"]`

## Extraction du HTML de DeepSeek — Fallback à 5 niveaux

DeepSeek omet souvent les balises `<CR>`. Ordre des fallbacks dans le CR edit flow :

1. `<CR>...</CR>` (format attendu)
2. ```html ... ``` (Markdown code block)
3. `<!DOCTYPE html...` (DOCTYPE présent)
4. `<html>...</html>` (tag HTML)
5. `<article>...</article>` (contenu article)

## Règles critiques pour les graphiques

- **N'INVENTE JAMAIS** de chiffres, durées, montants ou pourcentages qui ne sont pas dans la transcription
- Si la transcription ne contient AUCUNE donnée chiffrée exploitable, ne génère PAS de graphique
- Les `<script>` Chart.js sont bloqués par `dangerouslySetInnerHTML` → le frontend DOIT utiliser `<iframe srcDoc={crContent}>`

## Correction d'orthographe via glossaire

Patterns regex dans `detect_glossary_correction()` :
```python
r"\b(écrit|corrige|correction|orthographe|renomme|appelle|s'appelle)\b"
r"\b(on écrit|il faut écrire|doit s'écrire)\b"
r"\b(c'est\s+\S+\s+pas\s+|c'est\s+\S+\s+et\s+non\s+|c'était\s+\S+\s+pas\s+)\b"
r"\b(pas\s+\S+\s+mais\s+|appelle-moi\s+|nomme\s+)\b"
```

Voir `GLOSSARY_DETECT_PROMPT` dans main.py pour les exemples.

## Keepalive

Le cron `plaudia-keepalive` (toutes les minutes) vérifie `healthz` sur le port 8000 et relance le backend + tunnel Cloudflare si nécessaires. Les modifications du code sont relues depuis le fichier au redémarrage. Tuer un process uvicorn le fait redémarrer dans les 60s.