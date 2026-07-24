# Plaudia — Architecture technique

## Vue d'ensemble

```
                    ┌──────────────────────────────────────┐
                    │            Frontend Lovable          │
                    │         (React + TypeScript)         │
                    │                                      │
                    │  ┌─ CRListView  ─────────────────┐   │
                    │  │  Lectures CRS via Supabase     │   │
                    │  └────────────────────────────────┘   │
                    │  ┌─ CRDetailView ────────────────┐   │
                    │  │  Écriture CR via Hermes API   │   │
                    │  └────────────────────────────────┘   │
                    │  ┌─ EnterprisesView ─────────────┐   │
                    │  │  Lectures via Supabase         │   │
                    │  └────────────────────────────────┘   │
                    └──────────┬───────────────────────────┘
                               │
              ┌────────────────┼────────────────────┐
              │                │                    │
         Lectures          Écritures           Écritures
         (GET)            (POST/PATCH)          (POST)
              │                │                    │
              ▼                ▼                    ▼
     ┌──────────────┐  ┌──────────────┐     ┌──────────────┐
     │   Supabase   │  │   Hermes     │     │  Plaud API   │
     │  (PostgREST) │  │   Backend    │     │ (watchdog)   │
     │              │  │  (FastAPI)   │     └──────────────┘
     │  • lectures  │  │              │
     │  • RLS       │  │  • chat      │
     │  • auth      │  │  • validate  │
     │              │  │  • restore   │
     │              │  │  • export    │
     │              │  │  • email     │
     │              │  │  • create    │
     │              │  │  • glossary  │
     └──────────────┘  └──────┬───────┘
                              │
                              ▼
                     ┌──────────────┐
                     │  DeepSeek    │
                     │  (via OR)    │
                     └──────────────┘
```

## Flux de données

### 1. Watchdog (toutes les 5 min)
```
Plaud API → Script Python → INSERT recordings (Supabase)
```

### 2. Pipeline (quotidien 12h)
```
Cron Hermes → Lit recordings.status='transcribed'
           → Détecte entreprise/projet
           → Appelle DeepSeek → Génère CR HTML
           → INSERT dans crs (Supabase)
           → UPDATE recordings.status='ready'
```

### 3. RAG Chat
```
Frontend → POST /v1/chat/completions
        → Backend récupère embedding (OpenAI)
        → match_rag_chunks() (cosine similarity)
        → DeepSeek synthétise réponse
        → Stocke dans chat_sessions / chat_messages
```

### 4. Édition CR
```
Frontend → <CR>html</CR>\n\nInstruction : {msg}
        → Backend extrait <article>
        → DeepSeek modifie uniquement l'article
        → Backend re-wrappe avec template CSS
        → Sauvegarde dans crs (version incrémentée)
```

## Tables Supabase

| Table | Rôle | Lignes | Clé |
|-------|------|--------|-----|
| `recordings` | Enregistrements Plaud | 21 | `id` (UUID) |
| `crs` | Comptes-rendus | 18 | `id` (UUID) |
| `cr_versions` | Historique des versions | 43 | `id` (UUID) |
| `enterprises` | Entreprises clientes | 8 | `id` (UUID) |
| `projects` | Projets par entreprise | 11 | `id` (UUID) |
| `rag_chunks` | Chunks vectorisés (RAG) | 160 | `id` (UUID) |
| `glossary` | Corrections ortho auto-apprenantes | 9 | `id` (UUID) |
| `templates` | Templates HTML des CRs | 1 | `id` (UUID) |
| `cr_style_guide` | Leçons apprises des éditions | 19 | `id` (UUID) |
| `chat_sessions` | Sessions de chat RAG | 10 | `id` (UUID) |
| `chat_messages` | Messages des sessions | 37 | `id` (UUID) |
| `action_items` | Actions à faire (pas encore utilisé) | 0 | `id` (UUID) |
| `participants` | Participants aux réunions | 0 | `id` (UUID) |
| `knowledge_base` | Base de connaissances | 0 | `id` (UUID) |
| `user_profiles` | Profils utilisateurs | 1 | `id` (UUID) |
| `oauth_tokens` | Tokens OAuth (Google) | 0 | `id` (UUID) |

## Endpoints API

### Backend Hermes (écritures uniquement — ~20 endpoints)

```
POST   /v1/chat/completions              → RAG Chat + édition CR
POST   /v1/crs/{id}/validate             → Valider CR + brouillon Gmail
POST   /v1/crs/{id}/restore              → Restaurer version antérieure
PATCH  /v1/crs/{id}                      → Attribution entreprise/projet
DELETE /v1/crs/{id}                      → Supprimer CR
POST   /v1/enterprises                   → Créer entreprise + projet "Général"
DELETE /v1/enterprises/{id}              → Supprimer entreprise
POST   /v1/enterprises/{id}/assignments  → Attribution bulk CRs + projets
POST   /v1/projects                      → Créer projet (optionnel: cr_ids[])
PATCH  /v1/projects/{id}                 → Éditer projet
DELETE /v1/projects/{id}                 → Supprimer projet
POST   /v1/projects/{id}/crs             → Rattacher CRs à un projet
PATCH  /v1/recordings/{id}               → Renommer CR + meta
DELETE /v1/recordings/{id}               → Supprimer enregistrement
POST   /v1/glossary                      → Ajouter correction ortho
POST   /v1/cr/export-doc                 → Exporter Google Doc
POST   /v1/cr/send-email                 → Envoyer email
GET    /v1/cr/{id}/email-defaults        → Pré-remplissage email
POST   /v1/recordings/check-new          → Vérification Plaud on-demand
PATCH  /v1/chat/sessions/{id}            → Mettre à jour session
DELETE /v1/chat/sessions/{id}            → Supprimer session
GET    /v1/process-stream                → SSE streaming
```

### Lectures directes Supabase (pas de backend)

Les lectures suivantes vont directement de Supabase au frontend :
- `SELECT * FROM crs WHERE ...` (liste CRs, détail CR)
- `SELECT * FROM enterprises` (liste entreprises)
- `SELECT * FROM enterprises, projects(*)` (entreprises + projets)
- `SELECT * FROM projects` (liste projets)
- `SELECT * FROM cr_versions WHERE cr_id = ...` (versions d'un CR)
- `SELECT * FROM chat_sessions` (sessions RAG)
- `SELECT * FROM chat_messages` (messages RAG)
- `SELECT * FROM enterprise_counts` (compteurs, vue matérialisée)
- `SELECT * FROM glossary` (corrections ortho)

## Endpoints supprimés (anciennement dans le backend)

Ces endpoints wrappaient juste Supabase et ont été retirés pour le CQRS :
- `GET /v1/crs`, `GET /v1/crs/{id}`, `GET /v1/crs/{id}/versions`
- `GET /v1/enterprises`, `GET /v1/enterprises-with-projects`, `GET /v1/enterprises/{id}/projects`
- `GET /v1/chat/sessions`, `GET /v1/chat/sessions/{id}`, `GET /v1/chat/sessions/{id}/messages`
- `GET /v1/rag/duration-stats`
- `GET /v1/enterprises/with-counts`, `GET /v1/crs/{id}/current-version`