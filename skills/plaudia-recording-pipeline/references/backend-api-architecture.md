# Plaudia Backend — API Architecture (FastAPI)

## Source

- **Backend file** : `/opt/data/projects/plaudia/rag_backend/main.py` (~1500 lignes)
- **Dépendances** : fastapi, uvicorn, pydantic (disponibles dans `/opt/hermes/.venv`)
- **Process** : uvicorn sur port 8000 (PID via `ps aux | grep uvicorn`)
- **Tunnel** : `https://plaudia-api.herone.app` (Cloudflare Access, privé)
- **Auth** : clé partagée via `X-Plaudia-Key` header (configurée dans `/opt/data/.env`)
- **Gardien** : cron `plaudia-keepalive` (* * * * *, script shell) relance backend + tunnel si plantés
- **Redémarrage** : `pkill -f "uvicorn main:app"; sleep 2; cd /opt/data/projects/plaudia/rag_backend && source /opt/data/.env && export OPENAI_API_KEY ANTHROPIC_API_KEY PLAUDIA_SHARED_KEY OPENROUTER_API_KEY && /opt/hermes/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000`

## Architecture CQRS (20/07/2026)

Le backend suit le pattern **CQRS** (Command Query Responsibility Segregation) :

```
Frontend ←→ Supabase (lectures directes via PostgREST)
Frontend ←→ Backend FastAPI (écritures avec logique métier) ←→ Supabase
```

- **Lectures** : le frontend appelle Supabase directement via `heroneSupabase` (PostgREST). Scale nativement avec Postgres.
- **Écritures** : passent par le backend FastAPI pour validation, LLM, email, cross-entity checks.

## Endpoints conservés (écritures + logique métier)

| Endpoint | Méthode | Description |
|---|---|---|
| `/healthz` | GET | Health check (keepalive) |
| `POST /v1/chat/completions` | POST | Point d'entrée unique — RAG chat + CR edit + corrections glossaire |
| `PATCH /v1/chat/sessions/{id}` | PATCH | Mise à jour titre/tags d'une session |
| `DELETE /v1/chat/sessions/{id}` | DELETE | Supprimer une conversation (cascade messages) |
| `POST /v1/chat/export-session` | POST | Exporte une conversation en document structuré HTML |
| `POST /v1/crs/{cr_id}/restore` | POST | Restaurer une version ancienne |
| `POST /v1/crs/{cr_id}/validate` | POST | Marquer CR comme validé + générer brouillon Gmail |
| `PATCH /v1/crs/{cr_id}` | PATCH | Attribution enterprise_id/project_id avec validation croisée |
| `POST /v1/enterprises` | POST | Créer entreprise (+ projet "Général" auto) |
| `DELETE /v1/enterprises/{id}` | DELETE | Supprimer entreprise |
| `POST /v1/projects` | POST | Créer projet (avec cr_ids[] optionnels) |
| `DELETE /v1/projects/{id}` | DELETE | Supprimer projet |
| `PATCH /v1/projects/{id}` | PATCH | Éditer nom/description/keywords d'un projet |
| `POST /v1/projects/{id}/crs` | POST | Rattacher des CRs à un projet existant |
| `POST /v1/enterprises/{id}/assignments` | POST | Attribution bulk projets + CRs à une entreprise |
| `POST /v1/glossary` | POST | Ajouter correction ortho → trigger retroactive rewrite |
| `PATCH /v1/recordings/{id}` | PATCH | MàJ métadonnées enregistrement (client_name, type, subject, title) |
| `DELETE /v1/recordings/{id}` | DELETE | Supprimer un enregistrement |
| `POST /v1/cr/export-doc` | POST | Export Google Docs |
| `POST /v1/cr/send-email` | POST | Envoyer email ou brouillon Gmail |
| `GET /v1/cr/{recording_id}/email-defaults` | GET | Defaults email (destinataire, sujet, corps) |
| `GET /v1/process-stream` | GET | SSE placeholder |
| `POST /v1/recordings/check-new` | POST | Vérifier nouveaux enregistrements Plaud (0-LLM) |

## ⚠️ Endpoints GET : statut réel (vérifié le 22/07/2026)

**La migration CQRS n'a PAS été finalisée.** Tous ces GET endpoints sont encore présents dans `main.py`. Le frontend les appelle encore via `hermesAPI` — la migration vers Supabase direct est en attente.

| Ancien endpoint | Appel direct Supabase |
|---|---|
| `GET /v1/crs` | `heroneSupabase.from("crs").select("id,recording_id,version,status,created_at,updated_at,enterprise_id,project_id,enterprise:enterprises(name),recording:recordings(client_name,recorded_at,title,meeting_subject,meeting_type)").order("updated_at", { ascending: false }).limit(500)` |
| `GET /v1/crs/{cr_id}` | `heroneSupabase.from("crs").select("content,version,status,enterprise_id,project_id,created_at,updated_at").eq("id", cr_id).single()` |
| `GET /v1/crs/{cr_id}/versions` | `heroneSupabase.from("cr_versions").select("id,version,content,is_validated,created_at").eq("cr_id", cr_id).order("version", { ascending: false })` |
| `GET /v1/crs/{cr_id}/current-version` | `heroneSupabase.from("crs").select("version,status,updated_at").eq("id", cr_id).single()` |
| `GET /v1/enterprises` | `heroneSupabase.from("enterprises").select("id,name,description,created_at,updated_at").order("name")` |
| `GET /v1/enterprises-with-projects` | `heroneSupabase.from("enterprises").select("*, projects(*)").order("name")` |
| `GET /v1/enterprises/{id}/projects` | `heroneSupabase.from("projects").select("id,name,description,keywords,created_at,updated_at").eq("enterprise_id", id).order("name")` |
| `GET /v1/chat/sessions` | `heroneSupabase.from("chat_sessions").select("id,title,created_at,updated_at,tags").eq("owner_id", owner_id).order("updated_at", { ascending: false }).limit(100)` |
| `GET /v1/chat/sessions/{id}/messages` | `heroneSupabase.from("chat_messages").select("role,content,created_at").eq("session_id", id).order("created_at", { ascending: true })` |
| `GET /v1/rag/duration-stats` | `heroneSupabase.from("recordings").select("duration_seconds,client_name")` |

## Vue matérialisée pour les compteurs entreprises

Pour remplacer `GET /v1/enterprises/with-counts` (supprimé), créer une vue matérialisée dans Supabase :

```sql
CREATE MATERIALIZED VIEW enterprise_counts AS
SELECT
  e.id AS enterprise_id,
  COUNT(DISTINCT cr.id) AS cr_count,
  COUNT(DISTINCT r.id) AS recording_count
FROM enterprises e
LEFT JOIN crs cr ON cr.enterprise_id = e.id
LEFT JOIN recordings r ON r.enterprise_id = e.id
GROUP BY e.id;

CREATE UNIQUE INDEX ON enterprise_counts (enterprise_id);
```

Le frontend fait un seul `SELECT * FROM enterprise_counts`.

## CR Edit Flow (détail) — V3 fond/forme séparés (15/07/2026)

### Problème résolu
DeepSeek V4 Flash ne répondait pas de façon fiable au format `<CR>...</CR>` avec le HTML complet (20KB). Le LLM oubliait les balises, modifiait le CSS, ou générait une réponse en français sans HTML.

### Solution : séparation fond/forme + template wrapper

Le backend ne donne plus que le contenu `<article>` à DeepSeek, puis re-wrapper avec le template CSS :

```
Avant : Frontend → envoie 20KB HTML → DeepSeek → régénère 20KB → extraction fragile
Après : Frontend → envoie 20KB HTML → Backend extrait <article> (5KB) → DeepSeek → régénère <article> (5KB) → Backend re-wrapper avec template
```

### Nouvelles fonctions backend (main.py, ajoutées 15/07)

```python
def extract_article(html: str) -> str:
    """Extrait <article>...</article> du HTML complet via regex.
    Si aucun article trouvé, retourne le HTML original."""
    m = re.search(r"(<article[\s\S]*?</article>)", html, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else html

def get_template_shell() -> str:
    """Retourne le shell HTML complet (DOCTYPE + head + style + {{CONTENT}})
    avec {{CONTENT}} comme placeholder. Cache 5 minutes dans _template_cache.
    Lit le CSS depuis templates.html_template (is_default=true)."""

def render_cr(content: str) -> str:
    """Enveloppe le contenu (article) avec le template shell."""
    shell = get_template_shell()
    return shell.replace("{{CONTENT}}", content)
```

## DB Triggers (crs, recordings)

| Trigger | Table | Timing | Effet |
|---|---|---|---|
| `crs_set_updated_at` | crs | BEFORE UPDATE | Met à jour `updated_at` |
| `glossary_retroactive_rewrite` | glossary | BEFORE INSERT/UPDATE | Réécrit tous les CRs avec la correction |
| `recordings_propagate_enterprise` | recordings | AFTER UPDATE | Propage enterprise_id, client_name, project_id vers rag_chunks |
| `trg_propagate_enterprise_to_crs` | recordings | AFTER UPDATE (enterprise_id/project_id) | Propage enterprise_id et project_id de recordings vers le CR lié |
| `recordings_set_updated_at` | recordings | BEFORE UPDATE | Met à jour `updated_at` |
| `recordings_sync_enterprise_name` | recordings | BEFORE INSERT/UPDATE | Sync client_name depuis enterprises.name |
| `trg_recording_display_name` | recordings | BEFORE INSERT/UPDATE | Formate `recordings.title` en `"{Entreprise} — {Type} — {Sujet} — {Date}"` |

## Rate Limiting

- **500 requêtes / 60 secondes** par IP (sliding window)
- IP extraite du header `X-Forwarded-For` (derrière cloudflared)
- **IMPORTANT** : tous les utilisateurs passent par le même tunnel → même IP. Pour plusieurs utilisateurs, retirer ou monter à 5000 req/min.

## Auth

- **Clé partagée** : `PLAUDIA_SHARED_KEY` (env var) — envoyée par le frontend dans `X-Plaudia-Key`
- **Cloudflare Access** : le frontend envoie `CF-Access-Client-Id` et `CF-Access-Client-Secret` (env vars : `VITE_CF_CLIENT_ID`, `VITE_CF_CLIENT_SECRET`) — **⚠️ gap de sécurité : ces variables VITE_* sont exposées dans le bundle JS**. Voir `plaudia-orchestrator` SKILL.md pour l'architecture cible (server function Lovable). SANS CES HEADERS, les appels sont bloqués (403 Forbidden)
- **Token Supabase** : login email/password (martin@herone.fr) → JWT service account
- **Cache token** : 30 secondes avant refresh (in-memory)
- **Cache enterprises** : 5 minutes (in-memory)

## Env vars frontend requises (Lovable)

Sans ces variables dans l'environnement Lovable, l'app ne fonctionne pas :

| Variable | Rôle |
|---|---|
| `VITE_HERONE_SUPABASE_URL` | URL du projet Supabase Hérone |
| `VITE_HERONE_SUPABASE_PUBLISHABLE_KEY` | Clé publishable Supabase |
| `VITE_PLAUDIA_BACKEND_URL` | URL du backend (tunnel Cloudflare) |
| `VITE_PLAUDIA_SHARED_KEY` | Clé partagée du backend |
| `VITE_CF_CLIENT_ID` | Service Token Cloudflare Access (Client ID) |
| `VITE_CF_CLIENT_SECRET` | Service Token Cloudflare Access (Client Secret) |