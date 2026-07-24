# CR Edit Backend — API de modification des comptes-rendus

## Contexte

Le backend FastAPI (`/opt/data/projects/plaudia/rag_backend/main.py`) expose un endpoint
`POST /v1/chat/completions` qui gère à la fois le chat RAG et l'édition des CRs.

## Flux d'édition CR

Le frontend (`CRDetailView.tsx`) envoie :
```
<CR>{html_complet_du_cr}</CR>

Instruction : {message de l'utilisateur}
```
+ `cr_id` (UUID du CR dans la table `crs`)

## Détection de la demande d'édition

Dans `chat_completions()` :
```python
is_cr_edit_request = "<CR>" in question and "Instruction :" in question
```

## Enrichissement avec la transcription originale

Pour les demandes de **contenu** (pas style), le backend récupère le `raw_transcript` depuis
la table `recordings` via le `recording_id` du CR, et l'ajoute au prompt :
```
<CR>{html}</CR>

--- Transcription originale de la réunion ---
{raw_transcript}

Instruction : {msg}
```

## Détection Style vs Contenu

Mots-clés style (regex) : couleur, police, font, CSS, fond, marge, margin,
bleu, orange, rouge, gras, italique, logo, en-tête, footer, etc.

| Mode | Prompt système | Transcription | CSS modifiable |
|------|---------------|---------------|----------------|
| Style | "Tu PEUX modifier le bloc <style>" | Non | Oui |
| Contenu | "PRÉSERVE le bloc <style>" | Oui | Non |

## Extraction du HTML modifié

Le modèle doit répondre avec le HTML complet entre `<CR>...</CR>`.

DeepSeek V4 Flash ne met pas toujours ces balises → fallback par regex :
1. `<CR>([\s\S]*?)</CR>` (prioritaire)
2. `<!DOCTYPE html[\s\S]*` (DOCTYPE direct)
3. `<article class="cr-document">...` (article uniquement)

## Modèle utilisé

- **DeepSeek V4 Flash** (`deepseek/deepseek-v4-flash` via OpenRouter)
- Remplacé Opus 4.8 pour diviser le coût par ~10
- `max_tokens=8192` pour les éditions CR (assez pour un CR complet)
- Variable : `OPUS_MODEL` dans `main.py`

## Sauvegarde en base

- `update_cr_content()` : backup de l'ancienne version dans `cr_versions`, puis
  PATCH sur `crs` avec `content`, `version+1`, `updated_at`
- Apprentissage : `learn_from_cr_edit()` → `cr_style_guide`

## Points sensibles

- L'extraction du `<CR>` échoue si le modèle ne produit pas le format attendu
  → fallback obligatoire (surtout avec DeepSeek)
- `max_tokens` doit être suffisant (4096 trop court pour un CR complet → 8192)
- La transcription peut faire jusqu'à 80K chars → tronquer à 80 000
