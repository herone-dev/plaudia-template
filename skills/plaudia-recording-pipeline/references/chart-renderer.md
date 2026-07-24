# Chart Renderer — matplotlib SVG inline

## Architecture

**Problème résolu (15/07/2026)** : Chart.js nécessite `<script>` → bloqué par `dangerouslySetInnerHTML` dans le frontend React. DeepSeek invente des données pour les graphiques.

**Solution** : SVG inline généré par matplotlib côté serveur. DeepSeek ne fait que structurer les données en JSON, le rendu est fait par matplotlib.

## Flux

```
Utilisateur : "crée-moi un graphique pour la section tarifs"
         ↓
DeepSeek reçoit la transcription + le CR + l'instruction
         ↓
DeepSeek détecte les données chiffrées dans la transcription
         ↓
DeepSeek génère un marqueur JSON dans le CR :
  <script type="application/json" class="chart-embed">
  {"type":"bar","title":"Paliers tarifaires","labels":["Free","Intermédiaire","Premium"],
   "datasets":[{"data":[0,55,99]}],"unit":"€/mois"}
  </script>
         ↓
Backend (render_charts_in_cr) détecte le marqueur et appelle chart_renderer.py
         ↓
chart_renderer.py (matplotlib) génère un SVG aux couleurs Hérone
         ↓
Le marqueur est remplacé par le SVG inline dans le HTML du CR
         ↓
Le CR est stocké avec le SVG inline → visible avec innerHTML (zéro JS)
```

## Source

- **Backend** : `/opt/data/projects/plaudia/rag_backend/main.py` — fonction `render_charts_in_cr()` (ligne ~775)
- **Renderer** : `/opt/data/projects/plaudia/rag_backend/chart_renderer.py` — script Python autonome
- **Python** : `/opt/data/dwg-env/bin/python3` (Python 3.11, car `/opt/hermes/.venv` est read-only)
- **Appel** : `subprocess.run(["/opt/data/dwg-env/bin/python3", "/opt/data/projects/plaudia/rag_backend/chart_renderer.py"], input=data_json)`

## Fonction render_charts_in_cr()

```python
def render_charts_in_cr(html: str) -> str:
    """Remplace les marqueurs chart-embed par des SVG inline."""
    pattern = r'<script\s+type="application/json"\s+class="chart-embed">(.*?)</script>'
    return re.sub(pattern, _replace_chart, html, flags=re.DOTALL)
```

## chart_renderer.py — API

### Entrée (stdin, JSON)

```json
{
  "type": "bar",           // "bar" | "doughnut" | "line"
  "title": "Titre",        // optionnel, affiché en haut à gauche
  "labels": ["A", "B"],    // catégories
  "datasets": [{"data": [10, 20]}],  // valeurs
  "unit": "€",             // optionnel, affiché sur l'axe Y
  "colors": ["#1e3a5f"],   // optionnel, défaut = palette Hérone
  "indexAxis": "y"         // optionnel, "y" = barres horizontales
}
```

### Types supportés

| type | Description | Usage |
|:----:|:------------|:------|
| `bar` | Barres verticales | Comparaisons, montants |
| `bar` + `indexAxis:"y"` | Barres horizontales | Timeline, durées |
| `doughnut` | Camembert troué | Répartition, budget |
| `line` | Courbe avec marqueurs | Évolution temporelle |

### Palette Hérone

```python
HERONE = {
    'primary': '#1e3a5f',   # marine (couleur principale)
    'blue': '#3b82f6',      # bleu (secondaire)
    'light': '#93c5fd',     # bleu clair (tertiaire)
    'lighter': '#bfdbfe',   # très clair
    'lightest': '#dbeafe',  # le plus clair
    'deep': '#1e40af',      # bleu foncé
    'orange': '#d97706',    # orange (réservé doughnuts prioritaires)
    'gray': '#6b7280',      # gris texte
    'text': '#374151',      # texte principal
    'line': '#e5e7eb',      # bordures
}
```

## Pitfalls

- **DeepSeek invente des données** si le prompt ne l'interdit pas explicitement. Le prompt d'édition inclut maintenant : "N'invente JAMAIS de données. Utilise UNIQUEMENT les valeurs EXTRAITES de la transcription."
- **Ne JAMAIS déclarer un test "réussi" sans vérifier le contenu** — les tests mécaniques (version incrémentée, pas d'erreur) ne garantissent PAS que les données du graphique sont correctes.
- **matplotlib n'est pas disponible dans `/opt/hermes/.venv/`** (permissions read-only). Utiliser `/opt/data/dwg-env/bin/python3`.
- **Le SVG est stocké inline dans le CR** — pas de JS, pas d'iframe, fonctionne avec `dangerouslySetInnerHTML`.
- **Le keepalive `plaudia-keepalive.sh`** redémarre le backend toutes les minutes. Après un `pkill`, attendre 15-30s.