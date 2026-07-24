# Chart.js dans les CRs — Amélioration fond et forme

## Chart.js dans les CRs

Depuis juillet 2026, les CRs peuvent contenir des graphiques Chart.js générés automatiquement par le LLM.

### Comment ça marche

1. Le template `prompt_instructions` dit au LLM d'inclure le CDN Chart.js dans le `<head>` :
   `<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>`

2. Le LLM génère des `<div class="chart-container">` avec un `<canvas>` et un `<script>` inline :
   ```html
   <div class="chart-container" style="max-width:320px">
     <canvas id="chart-xxx"></canvas>
   </div>
   <script>
     new Chart(document.getElementById("chart-xxx"), {
       type: "bar",
       data: { labels: [...], datasets: [{ data: [...],
         backgroundColor: ["#1e3a5f", "#3b82f6", "#93c5fd", "#bfdbfe", "#dbeafe"] }] },
       options: { responsive: true, maintainAspectRatio: true,
         plugins: { legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } } } }
     });
   </script>
   ```

3. Le template CSS inclut les styles de dimensionnement :
   - `.chart-container { margin: 16px auto; max-width: 320px; text-align: center; }`
   - `.chart-container canvas { width: 100% !important; height: auto !important; max-height: 200px; }`
   - `.charts-row` pour l'affichage côte à côte (flex-wrap, gap 16px, flex 1 1 240px)

### Palette Hérone
```python
["#1e3a5f", "#3b82f6", "#93c5fd", "#bfdbfe", "#dbeafe", "#1e40af"]
```
Pour les doughnuts prioritaires/décisions : `["#1e3a5f", "#d97706", "#9ca3af"]`

### Guide des types de graphiques

| Donnée | Type Chart.js | Usage |
|--------|:------------:|-------|
| Budget / répartition | `doughnut` ou `pie` | Parts d'un budget |
| Comparaison montants | `bar` (vertical) | Paliers tarifaires |
| Timeline, jalons | `bar` (horizontal, indexAxis:'y') | Planning |
| Évolution | `line` | Progression |
| Décisions (oui/non/report) | `doughnut` 2-3 parts | Bilan décisions |
| Taux, pourcentages | `radar` | Comparaison multi-critères |

### Pitfalls

- **DeepSeek omet les balises `<CR>`** — le backend a un fallback extraction à 6 niveaux (ordre précis) : `<CR>` → code block ``` → `<!DOCTYPE html>` → `<html>` → `<article class="cr-document">` → n'importe quel `<article>`. Voir `main.py` lignes ~892-917.
- **Chart.js ne fonctionne pas dans un `dangerouslySetInnerHTML`** — le frontend doit utiliser un `<iframe>` avec `srcDoc` pour que les scripts s'exécutent.
- **Taille des graphiques** — toujours contraindre avec `max-width: 320px` ET `max-height: 200px` dans le style du container ET dans le CSS template. Le LLM a tendance à générer trop grand (500px+).
- **Le LLM peut générer du code Chart.js incohérent** — toujours utiliser `responsive: true, maintainAspectRatio: true` dans les options.
- **Palette Hérone** — toujours expliciter dans le prompt. Ne pas laisser le LLM choisir ses propres couleurs.
- **Ne pas générer de chart pour des données vagues** — le LLM invente des données pour remplir un graphique. Le prompt doit explicitement interdire.
- **Le CDN doit être dans le prompt système, pas seulement dans le template HTML** — sinon DeepSeek l'omet.
- **Le format `data-chart-config` (JSON dans l'attribut) est documenté mais DeepSeek préfère le `<script>` inline** — les deux sont supportés, le template CSS couvre les deux classes (`.chart-container` ET `.cr-chart-container`).

## Amélioration du fond des CRs (exhaustivité)

Le prompt de génération CR (`templates.prompt_instructions`) a été renforcé avec :

### Structure obligatoire du CR (dans cet ordre)
1. **HEADER** : logo HÉRONE, sous-titre, métadonnées (Date, Durée, Participants, Nature)
2. **RÉSUMÉ EXÉCUTIF** : 3-4 phrases synthétisant l'essentiel (décisions clés + prochaines étapes)
3. **SECTIONS THÉMATIQUES** : chaque thème a son H2 spécifique. Pour chaque sujet : contexte, arguments, chiffres, décision
4. **FRICTIONS / LIMITES** : liste à puces si 3+ items
5. **TABLEAU FINAL** : décisions (label bleu) + actions (label orange) avec Responsable + Échéance
6. **PROCHAINE RÉUNION** : si une date est mentionnée dans la transcription
7. **FOOTER** : "Synthèse générée par Plaudia — Hérone"

### Méthode "parcours" pour l'exhaustivité
Le prompt dit explicitement au LLM de :
- Après la rédaction, RELIRE la transcription **segment par segment**
- Pour chaque segment, vérifier qu'il est traité dans le CR
- Ne laisser AUCUN passage non traité
- Pas de limite de mots — 2000-3000+ mots si la réunion est riche

### Post-édition : apprentissage automatique
La fonction `learn_from_cr_edit()` dans `main.py` analyse chaque édition de CR :
1. Extrait l'instruction de modification
2. Appelle DeepSeek pour déterminer si c'est une leçon de style ou une correction ponctuelle
3. Si leçon de style → l'ajoute à `cr_style_guide` avec dédup et compteur
4. Les leçons les plus fréquentes sont injectées dans le prompt de génération suivant

## Backend : extraction du HTML (fallback)

Le CR edit flow dans `main.py` (endpoint `POST /v1/chat/completions`) doit extraire le HTML de la réponse de DeepSeek. Le LLM ne met pas toujours les balises attendues. La stratégie de fallback (lignes ~892-917) par ordre de précision :

```python
match = re.search(r"<CR>([\s\S]*?)</CR>", claude_reply)
if not match:
    # 1. Markdown code block
    code_match = re.search(r"```(?:html)?\s*([\s\S]*?)```", ...)
    # 2. DOCTYPE → tout le reste
    doctype_match = re.search(r"(<!DOCTYPE\s+html[\s\S]*)", ...)
    # 3. <html> tag
    html_match = re.search(r"(<html[\s\S]*?</html>)", ...)
    # 4. <article class="cr-document">
    article_match = re.search(r"(<article\b[^>]*class\s*=\s*[\"'][^\"']*cr-document[\"']...)", ...)
    # 5. N'importe quel <article>
    article_any = re.search(r"(<article[\s\S]*?</article>)", ...)
```

Si tous les fallbacks échouent, le debug log suivant permet de voir la réponse brute :
```python
print(f"[CR-EDIT FAIL] claude_reply length={len(claude_reply)} preview={claude_reply[:500]}")
```

## Bugs backend connus

### `request.json()` coroutine dans un endpoint sync
Le endpoint `POST /v1/crs/{cr_id}/restore` (sync def) utilise `request.json()` qui est une coroutine asynchrone → `'coroutine' object has no attribute 'get'`. Solution :
```python
try:
    raw = request.body()
    import asyncio
    if hasattr(raw, '__await__'):
        raw = asyncio.new_event_loop().run_until_complete(raw)
    body_data = json.loads(raw) if raw else {}
except Exception:
    body_data = {}
```

### ANON_KEY tronquée dans main.py
Le fichier `main.py` peut contenir une ANON_KEY placeholder tronquée (`"eyJhbG...PBj4"`) au lieu de la vraie clé. Toujours vérifier avec :
```python
mcp_supabase_get_publishable_keys(project_id="ezqbxfmafvdjtgrrxcxy")
```

### keepalive conflict
Le script `plaudia_keepalive.sh` (cron `* * * * *`) relance le backend s'il est down. Après un `pkill` manuel, le keepalive peut reprendre le port 8000 avant le nouveau process manuel. Utiliser `terminal(background=true)` ou arrêter temporairement le keepalive pendant les modifications backend.