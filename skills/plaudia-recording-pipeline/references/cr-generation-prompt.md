# CR Generation Prompt & Template (état juillet 2026)

## Prompt de génération (templates.prompt_instructions — is_default=true)

```
Tu es le générateur de comptes-rendus de réunion de Plaudia, pour Hérone.

RÈGLES NON NÉGOCIABLES :
- Ton factuel, neutre, à la troisième personne.
- Prose narrative continue. PAS de synthèse — c'est une RETRANSCRIPTION DÉTAILLÉE de la réunion. Tu dois retranscrire tous les échanges en préservant les chiffres, dates, noms, arguments, décisions, questions, réponses, et contexte. Ne supprime RIEN d'important. Ne raccourcis PAS.
- AUCUNE LIMITE DE LONGUEUR. Aucune limite basse non plus (supprimer le "500 à 1500 mots"). Le CR doit refléter la réunion dans son intégralité — chaque sous-sujet, chaque donnée chiffrée, chaque nom cité, chaque décision, chaque objection, chaque question en suspens. Si la transcription fait 80 000 caractères, le CR peut être aussi long.
- Titres H2 thématiques et spécifiques, jamais génériques ("Discussion", "Points évoqués").
- Glossaire appliqué avant tout traitement. Ne jamais corriger un nom propre par déduction si le glossaire ne le mentionne pas — signaler l'incertitude plutôt que d'inventer.
- Structure HTML : cr-document > header (cr-logo, cr-subtitle, cr-divider, cr-meta) > sections (cr-section, cr-section-title, cr-body, cr-subsection) > tableau final obligatoire (cr-table, cr-label-blue uniquement) > footer (cr-footer).
- Retourne UNIQUEMENT le HTML, sans commentaire avant/après.
```

## Template CSS (templates.html_template — is_default=true)

```css
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
.cr-logo {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 6px;
  color: #1e3a5f;
  margin: 0 0 4px 0;
  line-height: 1;
}
.cr-subtitle {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 16px 0;
  font-weight: 400;
}
.cr-divider {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 0 0 20px 0;
}
.cr-meta {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 5px 14px;
  margin-bottom: 32px;
}
.cr-meta dt { font-weight: 600; color: #111827; white-space: nowrap; }
.cr-meta dt::after { content: " :"; }
.cr-meta dd { margin: 0; color: #374151; }
.cr-section { margin-bottom: 8px; }
.cr-section-title {
  color: #1e3a5f;
  font-size: 18px;
  font-weight: 700;
  margin: 36px 0 0 0;
  padding-bottom: 10px;
  border-bottom: 1px solid #e5e7eb;
  line-height: 1.3;
}
.cr-section:first-of-type .cr-section-title { margin-top: 24px; }
.cr-subsection { margin-top: 4px; }
.cr-subsection-title {
  color: #1d4ed8;
  font-size: 14px;
  font-weight: 600;
  margin: 20px 0 6px 0;
  line-height: 1.4;
}
.cr-body {
  margin: 10px 0;
  text-align: justify;
  hyphens: auto;
  color: #374151;
}
.cr-list {
  margin: 10px 0 10px 22px;
  padding: 0;
  color: #374151;
}
.cr-list li { margin: 7px 0; padding-left: 4px; line-height: 1.65; }
.cr-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 14px;
  font-size: 14px;
}
.cr-table td {
  padding: 11px 15px;
  vertical-align: top;
  border: 1px solid #e5e7eb;
  line-height: 1.65;
}
.cr-table-label {
  font-weight: 600;
  color: #ffffff;
  width: 28%;
  font-size: 13px;
  vertical-align: middle;
}
.cr-label-orange { background-color: #d97706; }
.cr-label-blue   { background-color: #1e3a5f; }
.cr-table-content {
  background-color: #ffffff;
  color: #374151;
  width: 72%;
}
.cr-footer {
  margin-top: 52px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
  text-align: center;
  font-size: 12px;
  color: #9ca3af;
}
.cr-footer p { margin: 0; }
```

## FORMAT A4 — RÈGLES PAGINATION (frontend, 25/07/2026)

Le front affiche les CR dans une iframe qui simule des feuilles A4 (210×297mm, marges 14mm H / 18mm V). Le HTML DOIT inclure :

### Wrapper racine
```html
<article class="cr-document" data-format="A4">
```

### Sauts de page explicites entre sections
Entre chaque section principale (Objectif, Ordre du jour, Points abordés, Prochaines étapes) :
```html
<div class="page-break" style="break-before: page; page-break-before: always;"></div>
```

### Blocs insécables (avoid-break)
Sur chaque sous-section, item d'action, tableau, blockquote :
```html
<section class="avoid-break" style="break-inside: avoid; page-break-inside: avoid;">…</section>
```

### Titres jamais orphelins
```html
<h2 class="cr-section-title" style="break-after: avoid; page-break-after: avoid;">…</h2>
```

### PAS de text-align: justify
Utiliser text-align: left par défaut. Le front gère la typo.

### Longueur cible par page
~2800 caractères par page. Chaque section principale doit tenir sur 1 page ou insérer un .page-break avant de déborder.

### Format titre recording
`[Entreprise] — [Type] — [Sujet] — [JJ/MM/AAAA]`
Exemple : `Veron Diet — Consultation client — Refonte site web et automatisation IA — 24/07/2026`

## Structure HTML générée

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>/* CSS template ci-dessus */</style>
</head>
<body>
<article class="cr-document">
  <header>
    <p class="cr-logo">H É R O N E</p>
    <p class="cr-subtitle">Sujet de la réunion</p>
    <hr class="cr-divider">
    <dl class="cr-meta">
      <dt>Date</dt><dd>...</dd>
      <dt>Durée</dt><dd>...</dd>
      <dt>Participants</dt><dd>...</dd>
      <dt>Nature</dt><dd>...</dd>
    </dl>
  </header>

  <!-- Sections H2 thématiques -->
  <section class="cr-section">
    <h2 class="cr-section-title">Titre thématique</h2>
    <div class="cr-body">...</div>
    <div class="cr-subsection">
      <h3 class="cr-subsection-title">Sous-titre</h3>
      <div class="cr-body">...</div>
    </div>
  </section>

  <!-- Tableau final obligatoire -->
  <table class="cr-table">
    <tr>
      <td class="cr-table-label cr-label-blue">Décisions</td>
      <td class="cr-table-content">...</td>
    </tr>
    <tr>
      <td class="cr-table-label cr-label-blue">Actions</td>
      <td class="cr-table-content">...</td>
    </tr>
    <tr>
      <td class="cr-table-label cr-label-orange">Prochaine étape</td>
      <td class="cr-table-content">...</td>
    </tr>
  </table>

  <footer class="cr-footer">
    <p>Document généré par Plaudia — Hérone</p>
  </footer>
</article>
</body>
</html>
```

## Style guide actuel (cr_style_guide, 14/07/2026)

| Instruction | Catégorie | Appliqué |
|---|---|---|
| Éviter le texte en gris sur fond bleu pour les titres comme « Prochaine étape » ; utiliser un contraste lisible. | style | 1× |
| Dans le tableau final, n'utiliser que la couleur bleue et supprimer toute couleur orange. | style | 1× |

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

### 2. 3 enregistrements incohérents (status='transcribed' sans transcription)
3 lignes dans `recordings` ont `status='transcribed'` mais `raw_transcript IS NULL` et `transcript_segments IS NULL`. Le watchdog a avancé le statut sans écrire le contenu. À corriger : soit repasser en `pending` pour re-tenter, soit mettre en `error`.

### 3. 18 chunks transcription_full sans embedding
Les chunks de type `transcription_full` dans `rag_chunks` n'ont pas d'embedding vectoriel (colonne `embedding` NULL). Ces chunks sont invisibles au RAG.

### 4. DeepSeek V4 Flash omet les balises <CR>
Le modèle ne met pas toujours les balises `<CR>...</CR>` autour du HTML. Backend a fallback : DOCTYPE regex → `<article class="cr-document">` regex. Risque d'échec si le modèle répond en français sans HTML.

## Architecture du pipeline (2 tiers)

```
Plaud (app) -> Watchdog (5min, 0 LLM) -> INSERT recordings (status=transcribed) -> Pipeline CR (12h/jour, DeepSeek V4 Flash)
```

### Watchdog (plaudia_watchdog.py)
- **Schedule** : `*/5 * * * *` (no_agent=true, script pur)
- **Actions** : list_files -> get_file -> get_transcript -> INSERT recordings
- **Déclenche** : `hermes cron run d4777fc4327a` quand nouveaux fichiers trouvés

### Pipeline CR (plaudia-pipeline-principal)
- **Schedule** : `0 12 * * *` (modèle: deepseek/deepseek-v4-flash)
- **Étape 1** : SELECT recordings WHERE status='transcribed' LIMIT 5
- **Étape 2a** : Cherche/crée entreprise (enterprises.name ILIKE client_name)
- **Étape 2b** : Projet si >=2 réunions même sujet (projects.name ILIKE '%sujet%')
- **Étape 2c** : Applique glossaire sur raw_transcript
- **Étape 2d** : Lit templates.prompt_instructions (is_default=true)
- **Étape 2e** : Lit cr_style_guide (ORDER BY applied_count DESC)
- **Étape 2f** : Génère CR HTML complet avec DeepSeek
- **Étape 2g** : INSERT crs (recording_id, owner_id, content=HTML, version=1, status='ready')
- **Étape 2h** : UPDATE recordings SET status='ready', title='[Entr] - [Type] - [Sujet] - [JJ/MM/AAAA]'
- **Étape 2i** : Extract infos cles -> knowledge_base (BUG: schema mismatch)
- **Étape 3** : Rapport resume
- **Silent** : Si aucun enregistrement en attente -> repondre "[SILENT]"

### Edition CR (via chat frontend)
- Format : `<CR>{html}</CR>\n\nInstruction : {msg}`
- Detection style vs contenu par regex mots-cles
- Mode contenu : preserve `<style>`, recoit transcription originale
- Mode style : peut modifier `<style>`, pas de transcription
- Extraction : <CR> -> DOCTYPE -> <article class="cr-document">
- Backup dans cr_versions avant PATCH
- Apprentissage : learn_from_cr_edit() -> cr_style_guide