# CR Generation Prompt & Template (état juillet 2026)

## Prompt de génération (templates.prompt_instructions — is_default=true)

```
Tu es le générateur de comptes-rendus de réunion de Plaudia, pour Hérone.

RÈGLES NON NÉGOCIABLES :
- Ton factuel, neutre, à la troisième personne.
- Prose narrative continue. PAS de synthèse — c'est une RETRANSCRIPTION DÉTAILLÉE de la réunion. Tu dois retranscrire tous les échanges en préservant les chiffres, dates, noms, arguments, décisions, questions, réponses, et contexte. Ne supprime RIEN d'important. Ne raccourcis PAS.
- AUCUNE LIMITE DE LONGUEUR. Le CR doit refléter la réunion dans son intégralité.
- Titres H2 thématiques et spécifiques, jamais génériques ("Discussion", "Points évoqués").
- Glossaire appliqué avant tout traitement.

STRUCTURE HTML OBLIGATOIRE (plate, PAS de sections imbriquées) :
<body>
  <!-- En-tête -->
  <h1>Titre du CR — Client — Date</h1>
  <p class="cr-meta">Client · Date · Durée · Participants · Nature</p>

  <!-- Sections : chaque H2 + ses contenus sont des frères directs -->
  <h2>Titre thématique</h2>
  <p>…</p>
  <p>…</p>

  <h2>Titre suivant</h2>
  <p>…</p>
  <ul>
    <li>…</li>
    <li>…</li>
  </ul>

  ...

  <!-- Tableau final : décisions, actions, prochaines étapes -->
  <table class="cr-table">
    <tr><td class="cr-table-label">Décisions</td><td>…</td></tr>
    <tr><td class="cr-table-label">Actions</td><td>…</td></tr>
    <tr><td class="cr-table-label">Prochaine étape</td><td>…</td></tr>
  </table>

  <!-- Footer -->
  <p class="cr-footer">Document généré par Plaudia — Hérone</p>
</body>

RÈGLES DE STRUCTURE :
- PAS de <section>, PAS de <article>, PAS de <div class="cr-section">, PAS de <div class="cr-body">. Les <h2>, <p>, <ul>, <table> sont des FRÈRES DIRECTS dans le <body>.
- Chaque H2 doit porter style="break-after: avoid; page-break-after: avoid;" en inline.
- Chaque tableau doit porter style="break-inside: avoid; page-break-inside: avoid;" en inline.
- Aucun bloc ne doit dépasser ~900px de haut. Si un sujet est long, découper en plusieurs <p>.
- <div class="page-break" style="break-before: page; page-break-before: always;"></div> entre les grandes sections si besoin.
- PAS de text-align: justify. PAS de word-break: break-all.
- Retourne UNIQUEMENT le HTML à partir de <body>, sans commentaire avant/après.
- Le CSS est fourni dans le <head> par le système — ne pas inclure de <style>.
- Tableau final : fond blanc, bordures noires, texte noir. Pas de couleur de fond.
- Footer : juste le texte "Document généré par Plaudia — Hérone", pas de logo HÉRONE.
```

## Template CSS (templates.html_template — is_default=true)

```css
body {
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  color: #374151;
  max-width: 760px;
  margin: 0 auto;
  padding: 52px 60px;
  font-size: 14px;
  line-height: 1.75;
  background: #ffffff;
}
h1 {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 6px;
  color: #1e3a5f;
  margin: 0 0 8px 0;
  line-height: 1.2;
}
.cr-meta {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 32px 0;
  padding-bottom: 16px;
  border-bottom: 1px solid #e5e7eb;
}
h2 {
  color: #1e3a5f;
  font-size: 18px;
  font-weight: 700;
  margin: 36px 0 12px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
  line-height: 1.3;
}
p {
  margin: 10px 0;
  color: #374151;
}
ul {
  margin: 10px 0 10px 22px;
  padding: 0;
  color: #374151;
}
ul li {
  margin: 7px 0;
  padding-left: 4px;
  line-height: 1.65;
}
.cr-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 14px;
}
.cr-table td {
  padding: 11px 15px;
  vertical-align: top;
  border: 1px solid #000000;
  color: #000000;
  line-height: 1.65;
}
.cr-table-label {
  font-weight: 600;
  color: #000000;
  width: 28%;
  font-size: 13px;
  vertical-align: middle;
  background-color: #ffffff;
}
.cr-footer {
  margin-top: 52px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
}
.page-break {
  break-before: page;
  page-break-before: always;
}
```

## FORMAT A4 — RÈGLES PAGINATION (frontend, 25/07/2026)

Le front affiche les CR dans un paginateur qui découpe le HTML en feuilles A4. Pour que ça marche, la structure doit être **plate** :

### Structure attendue
- `<h1>` titre, `<p class="cr-meta">` meta, puis des `<h2>`, `<p>`, `<ul>`, `<table>` comme frères directs
- PAS de wrapper unique englobant tout le CR (`<article>`, `<section>`, `<div class="cr-content">`)
- Le paginateur coupe au niveau des blocs frères. Si tout est dans 1 seul bloc géant, il ne coupe pas.

### Limite par bloc
- Aucun `<p>`, `<ul>` ou `<table>` ne doit dépasser ~900px de haut (≈ hauteur A4)
- Si un sujet est long, découper en plusieurs `<p>` consécutifs

### Titres jamais orphelins
```html
<h2 style="break-after: avoid; page-break-after: avoid;">Titre</h2>
```

### Tableaux insécables
```html
<table class="cr-table" style="break-inside: avoid; page-break-inside: avoid;">
```

### Sauts de page explicites (optionnels)
```html
<div class="page-break"></div>
```

### PAS de text-align: justify ni word-break: break-all

### Format titre recording
`[Entreprise] — [Type] — [Sujet] — [JJ/MM/AAAA]`
Exemple : `Veron Diet — Consultation client — Refonte site web et automatisation IA — 24/07/2026`

## Style guide actuel (cr_style_guide, 28/07/2026)

| Instruction | Catégorie | Appliqué |
|---|---|---|
| Le tableau final ne doit avoir AUCUNE couleur de fond — juste bordures noires et texte noir, sur fond blanc. Pas de cr-label-blue, pas de cr-label-orange. | style | 1× |
| Footer simplifié : pas de logo HÉRONE, juste le texte "Document généré par Plaudia — Hérone". | style | 1× |

## Glossaire actuel (glossary, 14/07/2026)

| Terme brut | Corrigé | Propriétaire |
|---|---|---|
| Eron | Hérone | partagé |
| INX | Hynix | partagé |
| Ati | Hati | partagé |
| Xombo | Lixogo | partagé |
| Ouigo | Ewigo | partagé |

## Bugs connus

### 1. knowledge_base schema mismatch
Le pipeline (étape i) tente d'insérer dans `knowledge_base (enterprise_id, project_id, recording_id, key, value, source, owner_id)`. **La table réelle n'a que** `id, category, value, notes, created_at, updated_at`. L'étape échoue systématiquement. À corriger : soit ajouter les colonnes manquantes, soit modifier la consigne du pipeline.

### 2. DeepSeek V4 Flash produit parfois une structure avec sections au lieu de plate
Le modèle a tendance à générer `<article>` ou `<section>` par habitude. Les instructions "structure plate" sont renforcées dans le prompt.

## Architecture du pipeline (2 tiers)

```
Plaud (app) -> Watchdog (5min, 0 LLM) -> INSERT recordings (status=transcribed) -> Pipeline CR (12h/jour, DeepSeek V4 Flash)
```

### Watchdog (plaudia_watchdog.py)
- **Schedule** : `*/5 * * * *` (no_agent=true, script pur)
- **Actions** : list_files -> get_file -> get_transcript -> INSERT recordings
- **Déclenche** : `hermes cron run d4777fc4327a` quand nouveaux fichiers trouvés
- **Phase B retry** : réessaie get_transcript pour les fichiers avec raw_transcript=NULL
- **Détection entreprise** : titre uniquement (pas le transcript)

### Pipeline CR (plaudia-pipeline-principal)
- **Schedule** : `0 12 * * *` (modèle: deepseek/deepseek-v4-flash)
- **Étape 1** : SELECT recordings WHERE status='transcribed' LIMIT 5
- **Étape 2a** : Cherche/crée entreprise (enterprises.name ILIKE client_name)
- **Étape 2b** : Projet si >=2 réunions même sujet (projects.name ILIKE '%sujet%')
- **Étape 2c** : Applique glossaire sur raw_transcript
- **Étape 2d** : Lit templates.prompt_instructions (is_default=true)
- **Étape 2e** : Lit cr_style_guide (ORDER BY applied_count DESC)
- **Étape 2f** : Génère CR HTML complet avec DeepSeek (structure plate)
- **Étape 2g** : INSERT crs (recording_id, owner_id, content=HTML, version=1, status='ready')
- **Étape 2h** : UPDATE recordings SET status='ready', title='[Entr] - [Type] - [Sujet] - [JJ/MM/AAAA]'
- **Étape 2i** : Extract infos cles -> knowledge_base (BUG: schema mismatch)
- **Étape 3** : Rapport resume
- **Silent** : Si aucun enregistrement en attente -> repondre "[SILENT]"

### Edition CR (via chat frontend)
- Format : `<CR>{html}</CR>\n\nInstruction : {msg}`
- Backup dans cr_versions avant PATCH
- Apprentissage : learn_from_cr_edit() -> cr_style_guide