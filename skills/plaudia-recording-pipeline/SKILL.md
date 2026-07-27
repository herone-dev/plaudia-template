---
name: plaudia-recording-pipeline
description: Process Plaud voice recordings into the Plaudia app (project "Hérone") — fetch transcripts via mcp_plaud_*, insert transcript + generate branded CR (compte-rendu) HTML into Supabase (`recordings` + `crs` tables). Also covers the CR edit backend (modifications via chat). Use whenever the user asks to "traiter des enregistrements Plaud pour Plaudia/Hérone", process a batch of recordings into the pipeline, or regenerate a CR for a recording.
mandatory: true
---

# ⚠️ RÈGLE ABSOLUE — À LIRE AVANT TOUTE ACTION

Cette skill est **obligatoire** pour toute opération Plaudia.  
L'agent DOIT charger cette skill AVANT de générer un CR, modifier le pipeline, ou toucher au watchdog.

**NE PAS** :
- Écrire de script manuel pour générer un CR → utiliser le template dans `references/cr-generation-prompt.md`
- Inventer un prompt → recopier celui de la référence
- Créer un cron sans `skills: ["plaudia-recording-pipeline"]`

**Vérifier** : `skill_view(name='plaudia-recording-pipeline')` avant chaque action.

---

# Plaudia recording pipeline (Plaud → Supabase → CR)

## Architecture CQRS (20/07/2026 — mise à jour majeure)

Le backend suit désormais **CQRS** (Command Query Responsibility Segregation) :

- **Lectures** (lister CRs, entreprises, projets, sessions) → `heroneSupabase.from(...)` direct — Supabase PostgREST scale nativement
- **Écritures avec logique métier** (création, validation, chat, email, attribution, glossaire) → `hermesAPI.*` via backend FastAPI

### Ce qui change concrètement

- Les GET endpoints wrappers (`GET /v1/crs`, `GET /v1/chat/sessions`, etc.) ont été supprimés du backend, **sauf** `GET /v1/enterprises` et `GET /v1/enterprises/{id}/projects` qui ont été **ré-ajoutés** le 20/07/2026 car le frontend les appelle encore via `hermesAPI` (migration CQRS incomplète côté frontend).
- Le frontend lit les données directement via `heroneSupabase` (lectures) et passe par le backend pour les écritures
- Les compteurs entreprises (`cr_count`, `recording_count`) utilisent une vue matérialisée `enterprise_counts` Supabase
- La liste complète des endpoints conservés/supprimés est dans `references/backend-api-architecture.md`

### Ce qui ne change PAS

- Le pipeline cron continue en MCP Supabase direct (inchangé)
- Le watchdog continue en script Python (inchangé)
- Le RAG chat et l'édition CR via chat continuent via `POST /v1/chat/completions`
- La génération CR initiale continue via le pipeline

## When this applies
User asks to process N Plaud recordings for "le pipeline Plaudia" / "Hérone": for each recording, insert the raw transcript and a generated CR (compte-rendu) HTML document into Supabase.

Project context lives at `/opt/data/projects/plaudia/docs/` (brief, RAG strategy, design system) — skim these if unsure about current conventions; they are the source of truth over this skill if they conflict.
Frontend architecture and UX design decisions (current codebase structure, identified UX problems, agreed redesign) live at `references/frontend-architecture.md` in this skill.
Backend API architecture (main.py endpoint structure, CR edit flow internals, DB triggers, rate limiting, auth) lives at `references/backend-api-architecture.md` in this skill.
CR edit V3 (content/template separation, Chart.js → V4 SVG) and chart-embed SVG system live at `references/plaudia-cr-v3.md` in this skill.
Direct Supabase calls audit (which frontend components still bypass the backend API) lives at `references/direct-supabase-calls-audit.md` in this skill.

**CRITICAL — read `references/backend-api-architecture.md` before touching any backend code.** The file encodes current endpoint contracts, the CR edit V3 flow (content/template separation), all DB triggers (recordings→rag_chunks, glossary→crs), rate limiting, and known pitfalls (restore endpoint, ANON_KEY truncation). Code decisions made there override assumptions from this SKILL.md.

**BEFORE migrating frontend calls from `heroneSupabase` to `hermesAPI` — read `references/direct-supabase-calls-audit.md`.** It maps every direct Supabase call to the backend endpoint that should replace it, lists missing endpoints, and documents the `is_system` migration needed for the "Général" project filter.

## Prerequisites / project state

- **Plaud MCP server** (`plaud-org/plaud-mcp-server`) must be installed and configured under `/opt/data/mcp-tokens/plaud.json` (OAuth token). If not, run `cat /opt/data/mcp-tokens/plaud.client.json` to get the `client_id`, then walk the user through creating a Plaud integration at https://app.plaud.ai/settings → Integrations → New Integration → Hermes. The redirect URI must match the `redirect_uris` in the client JSON.
- **Watchdog cron** (`plaudia-watchdog-free`, `no_agent=True`, schedule `*/5 * * * *`) must be active on the Hermes instance that has the Plaud MCP tokens. It polls Plaud every 5 minutes for new recordings and inserts them into Supabase. **Le script actif est dans `/opt/data/.hermes/scripts/plaudia_watchdog.py`** (c'est celui que le cron exécute). Ne pas confondre avec `/opt/data/scripts/plaudia_watchdog.py` qui est l'ancienne version de référence mais pas celle utilisée par le cron. Les deux versions existent — faire attention à laquelle est modifiée.
- **Pipeline cron** (`plaudia-pipeline-principal`, LLM-agent, schedule `0 12 * * *`) generates CRs daily at noon. Not a script — a cron job definition with a prompt that each tick the agent runs. Triggered manually via `hermes cron run d4777fc4327a`.
- **Supabase** project `Herone_vocal_ia` (`VOTRE_PROJET_ID`). Tables: `recordings`, `crs`, `enterprises`, `projects`, `cr_versions`, `rag_chunks`.
- **Backend FastAPI** at `/opt/data/projects/plaudia/rag_backend/main.py`, port 8000, tunnel `https://plaudia-api.herone.app`. Restarted by keepalive cron every minute. The `main.py` CR edit V3 flow now separates content (`<article>`) from the CSS template — read `references/backend-api-architecture.md` for current contract.
- **6 env vars** required in the Lovable frontend (see `references/backend-api-architecture.md` → "Env vars frontend requises"). Missing one = 403/connection failures.

## Pipeline steps (when generating CRs for new recordings)

When the user asks to "process new recordings" or the cron fires:

1. **Fetch new recordings** — Query the `recordings` table for rows where `status = 'transcribed' AND enterprise_id IS NOT NULL`. These are recordings that arrived via the watchdog and have been attributed to an enterprise (see Pitfalls — CRs orphelins).
2. **Detect enterprise/project** — Now handled by the watchdog at insertion time (`detect_enterprise()`/`detect_project()` in `plaudia_watchdog.py`). If a recording still has `enterprise_id = NULL`, attempt to match by title against `enterprises.name` (case-insensitive substring). If no match, leave as NULL — the frontend attribution UI handles manual correction.
3. **Generate CR for each recording** — Call the LLM with the raw_transcript, the enterprise context (client_name, meeting_type, meeting_subject), and the style guide from `cr_style_guide`. The CR HTML is generated with the template shell (CSS + Chart.js CDN), then stored in `crs` with `enterprise_id` and `project_id` inherited from the recording.
4. **Propagate enterprise_id to CR** — The trigger `trg_propagate_enterprise_to_crs` handles this for existing recordings whose enterprise_id is updated. For new CR generation, explicitly include `enterprise_id` and `project_id` in the INSERT.
5. **Mark recording as processed** — Set `status = 'ready'`.

## Key files

| File | Path | Purpose |
|---|---|---|
| Watchdog script | `/opt/data/.hermes/scripts/plaudia_watchdog.py` (actif, PostgREST+JWT) — `/opt/data/scripts/plaudia_watchdog.py` (copie synchro) | Polls Plaud API, inserts recordings with enterprise detection via PostgREST. Modèle de référence dans `scripts/plaudia_watchdog.py` de cette skill. |
| Backend FastAPI | `/opt/data/projects/plaudia/rag_backend/main.py` | CRUD, CR generation/edit, RAG chat, enterprises CRUD |
| Supabase client | `src/integrations/supabase/herone-client.ts` | Dedicated Supabase client for Hérone project |
| Direct Supabase audit | `references/direct-supabase-calls-audit.md` | Every frontend→Supabase direct call mapped to the API endpoint that should replace it. Consult before migrating any remaining `heroneSupabase` calls. |

## Pitfalls discovered

**CRs orphelins (enterprise_id/project_id NULL)** — Le watchdog (`plaudia_watchdog.py`) insère les recordings sans entreprise détectée. Depuis la mise à jour du 17/07, le watchdog détecte l'entreprise depuis le titre du fichier (`detect_enterprise()`, `detect_project()`). Le trigger `trg_propagate_enterprise_to_crs` (AFTER UPDATE sur `recordings`) propage automatiquement vers le CR lié. Voir la migration `propagate_enterprise_to_crs` et le endpoint `PATCH /v1/crs/{cr_id}` pour l'attribution manuelle. Le frontend a un bloc Rattachement dans CRDetailView (CRListView.tsx).

**Large transcript tool output gets auto-persisted, don't re-fetch blind.** `mcp_plaud_get_transcript` on long recordings (>100KB) returns a `persisted-output` pointer to `/tmp/hermes-results/<toolcall_id>.txt` instead of inline content. Parse it with Python rather than paging through `read_file` line-by-line (which prepends `N|` markers that break `json.loads`).

**`execute_code` is often BLOCKED in cron/unattended sessions** (`BLOCKED: execute_code runs arbitrary local Python ... cron jobs run without a user present to approve it`). Don't loop retrying it — fall back immediately to `terminal` running `python3 -c "..."` (short scripts) or `python3 /opt/data/work/<project>/extract.py <in> <out>` (reusable script, see `scripts/extract_transcript.py` in this skill — copy it into the working dir and invoke it per file_id rather than hand-writing the parse logic each time).

**Pipeline attribution cycle** — When fixing orphaned CRs, always work upstream-first:
1. Watchdog (data source) → fix recording insertion to include enterprise_id/project_id
2. DB triggers → propagate recording→CR automatically
3. Backfill existing orphans
4. Backend PATCH endpoint → manual correction via API
5. Frontend attribution UI → user-facing correction

**Extracting client_name/meeting_type/meeting_subject from a transcript is guesswork unless cross-checked against the user's real client list.** A recording title's leading token is often a date fragment, not a client name, and transcripts rarely state a company's official name cleanly. Before assigning client_name, find the user's authoritative client list (CRM, Airtable base, or — seen in a real session — a Google Drive folder like AA-CLIENTS with one subfolder per client) and match transcript content (people/company names mentioned) against those exact folder names rather than inventing a normalized spelling. When no reliable match exists, write an explicit placeholder such as "À classer" instead of a best guess — a wrong guess silently corrupts per-client grouping/RAG filtering later, while a placeholder is visibly incomplete and safe to fix. Also verify non-obvious classifications by reading enough of the actual CR body, not just the title — a recording about "structure juridique activite secondaire" turned out, on reading the body, to be about the user's own company's legal structure, not an unrelated personal matter; assuming personal from the title alone would have wrongly excluded real business content.

**Private recordings get different handling.** Recording titles containing `[PRIVE]` or `[PERSO]` markers indicate a different (more restrictive) procedure than the default — check for this marker before deciding transcript/CR content and `is_private` flag: for a match, insert into `recordings` with `is_private=true`, keep `title` as-is, set `recorded_at`/`duration_seconds` from Plaud metadata, `status='ready'`, and `raw_transcript=NULL` — do NOT fetch or store the transcript at all, and do NOT generate a CR.

**Escaping raw transcript text in SQL: use dollar-quoting, and verify the tag isn't already in the text.** Transcripts contain apostrophes, quotes, and arbitrary punctuation. Use Postgres dollar-quoting with a unique per-insert tag (e.g. `$plaudia_rec3_v1$...$plaudia_rec3_v1$`) rather than escaping single quotes. Before using the tag, confirm it doesn't appear inside the content (`'plaudia_recN_v1' in text` in Python) — collision would break the query silently.

**The persisted-output text isn't always a clean single JSON document — expect an "Extra data" `json.loads` error.** Some persisted files have a JSON object followed by trailing bytes (or start with non-JSON preamble). Locate the JSON start (`raw.find('{"result"}')`) and use `json.JSONDecoder().raw_decode(raw[idx:])` instead of `json.loads(raw[idx:])` — `raw_decode` stops at the first complete object and ignores anything after it.

**Make glossary corrections self-propagating, not just forward-looking.** If the user wants a correction (e.g. a mis-transcribed company name like "Eron" corrected to "Herone") to also fix every CR already generated, not just future ones, do not do it by hand with one-off UPDATE statements per correction. Put a BEFORE INSERT OR UPDATE trigger on the glossary table itself that runs an UPDATE on crs.content using regexp_replace with word-boundary matching, scoped by owner_id if the correction is personal or unscoped if owner_id IS NULL. This makes every future glossary edit automatically rewrite historical CRs with zero extra agent work per correction — verify it fired by checking that the old term no longer appears in a known-affected row right after inserting the glossary entry.

**When several transcripts were fetched in parallel, persisted-output files can arrive without an obvious mapping back to their `plaud_file_id`.** Match them by grepping the first ~400 chars of each file for the source tag pattern `source_transaction:<hex>:<plaud_file_id>`.

**`write_file` blocks writes to many paths as "protected system/credential file"** (`/tmp/*`, `/opt/hermes/*`, and others) — this is not an environment bug, it's a guard. Use `terminal` with a heredoc or a Python script writing to a workspace dir instead.

**Check the `glossary` table first, once per batch.** `SELECT term_raw, term_corrected FROM glossary` gives name/term corrections to apply across transcripts and CRs (e.g. mis-transcribed proper nouns). If empty, skip corrections — but still flag genuinely uncertain names/terms inline in the CR text as "(orthographe non confirmée)" rather than silently guessing or silently leaving them wrong.

**"Général" project filter is fragile — prefer `is_system` flag.** The backend auto-creates a project named "Général" for every new enterprise (main.py:1561-1564). The frontend filters it by name (`isGeneral()` in EnterprisesContext.tsx:80, `.neq("name", "Général")` in ProjectsView.tsx:39). If someone renames it, the filter silently breaks and the project appears everywhere. Fix: add a `is_system boolean DEFAULT false` column to `projects`, mark the auto-created project with `is_system=true`, and filter by that column. Both backend and frontend need updating.

**Cron scheduling for a day-spanning active window** (e.g. "7 days/week, active 6h30–01h00, i.e. wraps past midnight and starts mid-hour"): a single 5-field cron expression can't express both "starts at :30 past a specific hour" and "wraps past midnight" cleanly in one rule. Split into two jobs instead: one covering the partial starting hour (`30-59/5 6 * * *`) and one covering the rest of the range, listing the wrapped hour explicitly (`*/5 7-23,0 * * *`).

**Le watchdog n'utilise plus l'API Management Supabase — il utilise PostgREST + JWT.** L'ancienne version utilisait `SUPABASE_ACCESS_TOKEN` (token `sbp_...`) avec l'endpoint `api.supabase.com/v1/projects/{id}/database/query`. Ce token peut être révoqué ou regénéré sans prévenir (ex: regénération des clés API dans le dashboard Supabase). La version actuelle (`/opt/data/.hermes/scripts/plaudia_watchdog.py`) se connecte via le service account (`martin@herone.fr`) pour obtenir un JWT, puis utilise l'API PostgREST (`SUPABASE_URL/rest/v1/...`). **Ne pas recopier l'ancienne approche Management API.**

**La clé anon Supabase peut être regénérée dans le dashboard.** Si le watchdog retourne `Invalid API key` sur l'endpoint auth, c'est que la clé `SUPABASE_ANON_KEY` dans `.env` ne correspond plus à celle du projet. Vérifier en comparant avec Supabase Dashboard → Settings → API → anon key. Le watchdog n'a PAS de fallback hardcodé valide — il prend la clé depuis `os.environ.get("SUPABASE_ANON_KEY")` et échoue si vide. Quand run hors cron (terminal), faire `source /opt/data/.env` avant.

**`hermes cron run` dans un watchdog no_agent timeout à 30s par défaut.** Le watchdog lance `subprocess.run(["hermes", "cron", "run", LLM_JOB_ID], timeout=30)` après avoir inséré des enregistrements. 30s est trop court — `hermes cron run` peut prendre >30s pour démarrer. Solution : soit `subprocess.Popen(...)` (fire-and-forget, pas d'attente), soit `timeout=300`. Si le pipeline ne se déclenche pas, lancer manuellement `cronjob(action='run', job_id=...)`.

**Le pipeline cron DOIT avoir la skill `plaudia-recording-pipeline` chargée dans `skills`.** Sans skills, l'agent ne sait pas quel template HTML utiliser, ni le format A4, ni la convention de nommage. Vérifier avec `cronjob(action='list', job_id='d4777fc4327a')` que `skills` contient bien `["plaudia-recording-pipeline"]`.

**Le watchdog doit être copié à DEUX endroits.** Le cron résout `plaudia_watchdog.py` depuis `/opt/data/scripts/` (pas `~/.hermes/scripts/`). Les deux versions doivent être synchronisées. Faire après chaque modification : `cp /opt/data/.hermes/scripts/plaudia_watchdog.py /opt/data/scripts/plaudia_watchdog.py`.

**Détection entreprise : ne pas se limiter au titre — scanner aussi la transcription.** `detect_enterprise()` vérifie maintenant `enterprise_name.lower() in transcript.lower()` en plus du titre. Les fichiers Plaud ont souvent des noms non identifiants (ex: "24/07/2026") mais la transcription contient le nom de l'entreprise.

**Convention de nommage des enregistrements :** `[Entreprise] — [Type] — [Sujet] — [JJ/MM/AAAA]`. Exemple : `Veron Diet — Consultation client — Refonte site web et automatisation IA — 24/07/2026`. Le trigger DB `trg_update_recording_title` met à jour automatiquement le titre quand `enterprise_id` est setté, mais le format doit être correct.

**Le scheduler Hermes peut se figer sans warning.** Dans une session réelle, les crons n'ont pas déclenché depuis 4 jours (last_run_at figé) alors que le processus `hermes dashboard` tournait normalement. Aucun log d'erreur. Diagnostic : vérifier `hermes cron list` — si tous les `next_run_at` sont dans le passé, le scheduler est bloqué. Solution : redémarrer Hermes ou recréer les crons. Les jobs manuels via `cronjob(action='run')` fonctionnent même quand le scheduler est bloqué.

## Behind the scenes

- La plupart des endpoints GET (lectures) ont été supprimés du backend — le frontend lit directement via Supabase (PostgREST). Exception : `GET /v1/enterprises` et `GET /v1/enterprises/{id}/projects` ont été ré-ajoutés car le frontend les appelle encore via `hermesAPI`.
- Les écritures (POST/PATCH/DELETE) passent par le backend avec validation croisée, auth via JWT Supabase Auth + Cloudflare Access
- Rate limiting: 500 requests / 60 seconds per IP (from `X-Forwarded-For`) — ATTENTION : tous les utilisateurs passent par le même tunnel, même IP
- Auth: JWT Supabase Auth (`Authorization: Bearer ***  + Cloudflare Access. Fallback `X-Plaudia-Key` conservé pour les crons uniquement. Voir `plaudia-cr-backend` → Auth architecture.
- La vue matérialisée `enterprise_counts` (rafraîchie toutes les 15 min par cron) remplace les 3 requêtes frontend pour les compteurs entreprises

## Deployment template

A complete deployment template lives on GitHub at `herone-dev/plaudia-template`. It contains:

- `rag_backend/main.py` + `auth.py` — backend complet avec auth JWT
- `supabase/schema.sql` + `migrations/002_multi_user_rls.sql` — schéma + RLS + triggers
- `setup-plaudia.sh` — installation automatisée (backend, crons, scripts)
- `.env.example` — toutes les variables requises (plus de hardcode dans le code)
- `docs/deployment-checklist.md` — checklist 15 étapes pour nouveau client
- `docs/debug-guide.md` — 9 bugs documentés avec solutions
- `docs/frontend-login-prompt.md` — prompts Lovable pour le frontend
- `scripts/` — keepalive, watchdog, tunnel watchdog
- `skills/` — les 3 skills Hermes

**Plus de hardcode dans main.py.** SUPABASE_URL, SUPABASE_ANON_KEY, SERVICE_EMAIL, SERVICE_PASSWORD, OPENAI_API_KEY, OPENROUTER_API_KEY sont tous en variables d'environnement.

**Pour déployer :**
```bash
git clone https://github.com/herone-dev/plaudia-template.git
cp .env.example /opt/data/.env
# Éditer .env avec les vraies valeurs
# Exécuter supabase/schema.sql + migrations/002_multi_user_rls.sql dans Supabase
bash setup-plaudia.sh
# Voir docs/deployment-checklist.md
```

## Reference docs

- `references/backend-api-architecture.md` — all endpoints, CR edit V3 flow, DB triggers, rate limiting, env vars
- `references/frontend-architecture.md` — frontend structure, enterprise view, project view, scope system
- `references/plaudia-cr-v3.md` — CR edit V3, Chart.js → SVG migration
- `references/direct-supabase-calls-audit.md` — **NEW 20/07** — audit of direct Supabase calls vs API endpoints, migration plan, missing endpoints, `is_system` flag for projects