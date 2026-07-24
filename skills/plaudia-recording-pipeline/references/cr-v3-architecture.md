# CR V3 — Architecture de refonte (template/contenu + graphiques)

*Décidé le 14/07/2026 — refonte en phases pour séparer la forme du fond.*

## Problème

Le CR actuel stocke tout dans le même champ `crs.content` :
```
<!DOCTYPE html><html><head><style>...CSS...</style></head><body>...contenu...</body></html>
```

Conséquences :
- Le LLM régénère le CSS à chaque CR et à chaque édition (poids inutile en tokens)
- Impossible de changer le design sans réécrire tous les CRs existants
- Le LLM peut dériver le style (d'où les leçons du style guide pour corriger les couleurs)
- 0 visuel : pas de graphiques, pas de tableaux de bord

## Solution : séparation template / contenu

```
Template (templates.html_template)
├── <head> : CSS complet Hérone + Chart.js CDN
├── <body> : shell HTML avec {{CONTENT}} placeholder
└── script : initialise Chart.js sur les .cr-chart

Contenu pur (crs.content)
├── <article class="cr-document">
│   ├── <header> métadonnées
│   ├── sections thématiques (H2)
│   └── tableaux + graphiques (canvas + script Chart.js)
└── Pas de <style> ni <head>

Backend render_cr(content):
  template.replace("{{CONTENT}}", content) → HTML complet
```

## Graphiques Chart.js

Le LLM identifie les données chartables dans la transcription et génère directement :

| Donnée | Chart.js type | Exemple |
|--------|--------------|---------|
| Budget, coûts, parts | `pie` / `doughnut` | "45K€ dev, 25K€ marketing" |
| Timeline, planning | `bar` | Jalons mars/juin/septembre |
| Décisions | `doughnut` | Validé/Refusé/À étudier |
| Comparaisons | `horizontalBar` | Option A vs B vs C |

Génération dans le HTML du CR :
```html
<div class="chart-container">
  <canvas id="chart-budget"></canvas>
</div>
<script>
  new Chart(document.getElementById('chart-budget'), {
    type: 'pie',
    data: { labels: ['Dev', 'Marketing', 'Design'],
            datasets: [{ data: [45, 25, 18] }] }
  });
</script>
```

## Prompt amélioré pour l'exhaustivité

Checklist obligatoire que le LLM doit cocher avant de rendre le CR :
- [ ] Chaque segment de la transcription est traité dans une section
- [ ] Décisions extraites (quoi, qui décide, statut)
- [ ] Montants et chiffres clés identifiés et formatés
- [ ] Participants listés avec leur rôle
- [ ] Actions identifiées (qui fait quoi, échéance)
- [ ] Prochaine réunion / calendrier
- [ ] Graphiques générés si données chiffrées présentes

## data-visualization skill (anthropics/knowledge-work-plugins)

Analyse du skill `data-visualization` du repo `anthropics/knowledge-work-plugins` :
- Skill Claude Code (format incompatible Hermes), Python-based (matplotlib/seaborn/plotly)
- Génère des fichiers PNG — pas adapté au HTML inline des CRs
- **Utile pour** : le guide de choix de chart, les principes de design (couleurs, accessibilité, chart selection guide)
- **Pas utile pour** : l'architecture Plaudia (Chart.js en CDN est la bonne approche)
- Les principes de chart selection et design sont à intégrer dans le prompt de génération CR, pas dans le pipeline
- Chart.js > matplotlib pour Plaudia car : rendu dans le navigateur, pas de dépendance serveur, inline dans le HTML, pas de fichiers PNG à stocker

## Plan de refonte (5 phases)

| Phase | Description | Fichiers impactés |
|-------|-------------|-------------------|
| 1 | Nouveau template HTML (CSS + Chart.js CDN) + fonction render_cr() | `main.py`, `templates` table |
| 2 | Prompt amélioré avec checklist + post-vérification | `templates.prompt_instructions` |
| 3 | Chart.js — LLM génère canvas + data | Prompt + template |
| 4 | Backend : fusion template/contenu dans render_cr() | `main.py` |
| 5 | Rétrofit des 18 CRs existants dans le nouveau template | Script backfill |