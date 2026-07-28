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
  <!-- EN-TÊTE : logo HÉRONE en H1 -->
  <h1>H É R O N E</h1>

  <!-- Sous-titre : Client — Type — Sujet — Date -->
  <p class="cr-subtitle">AQCF — Audit — Premier rendez-vous d'audit et présentation AQCF — 28/07/2026</p>

  <!-- Meta avec sauts de ligne (<br>) entre chaque info -->
  <p class="cr-meta">
    Client : AQCF (Audit, Qualité, Conseil, Formation)<br>
    Date : 28/07/2026<br>
    Durée : 84 min<br>
    Participants : Yohann Richard (AQCF), Speaker 1, Speaker 3 (Hérone)<br>
    Nature : Premier rendez-vous d'audit
  </p>

  <hr class="cr-divider">

  <!-- Sections : chaque H2 + ses contenus sont des frères directs -->
  <h2 style="break-after:avoid;">Présentation de l'activité</h2>
  <p>...</p>
  <p>...</p>

  <h2 style="break-after:avoid;">Deuxième section</h2>
  <p>...</p>
  <ul>
    <li>...</li>
    <li>...</li>
  </ul>

  <!-- Tableau final : Décisions, Actions, Prochaine étape -->
  <table class="cr-table">
    <tr>
      <td class="cr-table-label">Décisions</td>
      <td>…</td>
    </tr>
    <tr>
      <td class="cr-table-label">Actions</td>
      <td>…</td>
    </tr>
    <tr>
      <td class="cr-table-label">Prochaine étape</td>
      <td>…</td>
    </tr>
  </table>

  <!-- Footer -->
  <p class="cr-footer">Document généré par Plaudia — Hérone</p>
</body>

RÈGLES DE STRUCTURE :
- PAS de <section>, PAS de <article>, PAS de <div class="cr-section">, PAS de <div class="cr-body">. Les h1, p.cr-subtitle, p.cr-meta, hr, h2, p, ul, table sont des FRÈRES DIRECTS dans le <body>.
- Le H1 doit être EXACTEMENT "H É R O N E" (avec espaces entre les lettres) — c'est le logo. Jamais autre chose dans le H1.
- Le p.cr-subtitle contient la description de la réunion sur UNE SEULE LIGNE (pas de <br>).
- Le p.cr-meta contient les infos avec des <br> entre chaque ligne. Jamais tout sur une même ligne.
- Chaque H2 doit porter style="break-after:avoid;" en inline.
- Chaque tableau doit porter style="break-inside:avoid;" en inline.
- Aucun bloc ne doit dépasser ~900px de haut. Si un sujet est long, découper en plusieurs <p>.
- <div class="page-break"></div> entre les grandes sections si besoin (le CSS gère le break-before).
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
  margin: 0 0 4px 0;
  line-height: 1;
}
.cr-subtitle {
  color: #6b7280;
  font-size: 13px;
  margin: 0 0 20px 0;
  font-weight: 400;
}
.cr-meta {
  color: #374151;
  font-size: 13px;
  margin: 0 0 28px 0;
  line-height: 1.8;
}
.cr-divider {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 0 0 24px 0;
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
  margin-top: 12px;
}
.cr-table td, .cr-table th {
  padding: 10px 14px;
  vertical-align: top;
  border: 1px solid #000000;
  color: #000000;
  line-height: 1.6;
}
.cr-table-label {
  font-weight: 600;
  color: #000000;
  width: 26%;
  font-size: 13px;
  vertical-align: middle;
  background-color: #ffffff;
}
.cr-footer {
  margin-top: 48px;
  padding-top: 14px;
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
- `<h1>H É R O N E</h1>` — logo en H1
- `<p class="cr-subtitle">` — description réunion sur une ligne
- `<p class="cr-meta">` — infos avec `<br>` entre chaque ligne
- `<hr class="cr-divider">` — séparateur
- `<h2 style="break-after:avoid;">`, `<p>`, `<ul>`, `<table>` comme frères directs

### Règles
- Aucun `<p>`, `<ul>` ou `<table>` ne doit dépasser ~900px de haut
- Titres H2 avec `break-after:avoid` inline
- Tableaux avec `break-inside:avoid` inline
- Sauts explicites : `<div class="page-break"></div>`
- PAS de `text-align: justify` ni `word-break: break-all`

### Format titre recording
`[Entreprise] — [Type] — [Sujet] — [JJ/MM/AAAA]`
Exemple : `Veron Diet — Consultation client — Refonte site web et automatisation IA — 24/07/2026`

## Glossaire actuel (glossary, 14/07/2026)

| Terme brut | Corrigé | Propriétaire |
|---|---|---|
| Eron | Hérone | partagé |
| INX | Hynix | partagé |
| Ati | Hati | partagé |
| Xombo | Lixogo | partagé |
| Ouigo | Ewigo | partagé |