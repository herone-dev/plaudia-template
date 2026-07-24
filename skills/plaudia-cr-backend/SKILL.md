---
name: plaudia-cr-backend
description: Architecture du backend Plaudia (FastAPI) — CR editing, chart generation SVG inline, template separation, glossary detection, and the edit/extraction flow. Use when working on the Plaudia CR generation pipeline, the chat-based CR edit flow, or the SVG chart rendering system.
---

# Plaudia CR Backend — Architecture & Patterns

## When this applies

You're working on the Plaudia FastAPI backend (`rag_backend/main.py`) — CR generation, CR editing via chat, chart rendering, glossary/auto-correction, or the RAG chat system. This is the **backend** skill; the pipeline and frontend have their own skills.

## Key files

| File | Purpose |
|------|---------|
| `rag_backend/main.py` | FastAPI backend (~2600 lignes) — tous les endpoints |
| `rag_backend/auth.py` | JWT Supabase Auth — validation, extraction user context, service account |
| `rag_backend/chart_renderer.py` | SVG chart generation via svgwrite |
| `rag_backend/google_integration.py` | Google Docs export + Gmail send/draft |
| `supabase/migrations/002_multi_user_rls.sql` | Migration multi-user : project_shares, RLS policies, triggers |

## LLM Model (21/07/2026 — migré depuis OpenRouter)

**Actuel :** `gpt-4o-mini` via OpenAI API direct (`https://api.openai.com/v1/chat/completions`)
**Ancien :** `deepseek/deepseek-v4-flash` via OpenRouter (`https://openrouter.ai/api/v1/chat/completions`)

**Raison :** Le user n'avait pas de clé OpenRouter (`OPENROUTER_API_KEY` vide) mais avait une clé OpenAI.

**Migration :**
1. Remplacer `OPUS_MODEL = "deepseek/deepseek-v4-flash"` par `"gpt-4o-mini"`
2. Remplacer `OPENROUTER_URL` par `OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"`
3. Remplacer les 2 appels à `OPENROUTER_URL` + `Bearer {OPENROUTER_KEY}` par `OPENAI_CHAT_URL` + `Bearer {OPENAI_KEY}`
4. Supprimer `OPENROUTER_KEY` si désiré (variable `.env` peut rester vide)

**PITFALL — La clé OpenAI peut être corrompue lors de l'écriture.** Voir `references/backend-management.md`.

## Template separation (V3, 15/07/2026)

The backend no longer sends the full HTML (DOCTYPE + style + content) to DeepSeek. Instead it extracts only the `<article>` and re-wraps after.

**Functions in main.py:**
- `get_template_shell()` — fetches `templates.html_template` (CSS) from Supabase, wraps in DOCTYPE+head shell with `{{CONTENT}}` placeholder. Cached 5 min.
- `extract_article(html)` — regex `<article>...</article>`. Returns original if no match.
- `render_cr(content)` — `shell.replace("{{CONTENT}}", content)`.
- `render_charts_in_cr(html)` — replaces `chart-embed` markers with SVG via subprocess to `chart_renderer.py`.

**CR edit flow:**
1. Frontend sends `<CR>{full_html}</CR>\n\nInstruction : {msg}` + `cr_id`
2. Backend extracts `<article>` from the message
3. DeepSeek receives ONLY the article (5-7K instead of 20K)
4. DeepSeek must return content wrapped in `<CR>...</CR>` tags
5. Backend re-wraps with `render_cr()` → converts chart markers → saves

**PITFALL — DeepSeek omits `<CR>` tags:** Fallback extraction in order: `<CR>...</CR>` → `<article>...</article>`. No more DOCTYPE/html/codeblock fallbacks (removed in V3 because DeepSeek only gets the article now).

**PITFALL — CR size limit:** If a CR exceeds ~25K chars, DeepSeek can't edit it (context overflow). Original CRs are 6-20K. If a CR has been bloated (e.g. by large SVGs), restore it from `cr_versions` before attempting edits:
```sql
UPDATE crs SET content = (SELECT content FROM cr_versions WHERE cr_id='...' AND version=N), version=new_v, updated_at=NOW() WHERE id='...';
```
Use `mcp_supabase_execute_sql` to check CR sizes: `SELECT id, version, length(content) as len FROM public.crs ORDER BY len DESC`.

**PITFALL — Frontend has stale CR HTML cache:** This is the #1 cause of "aucune modification appliquée" even when edits succeed. The frontend loads the CR once and sends the cached HTML to the backend. If the CR was restored or edited in a previous session, the frontend still has the old version.

**Root cause:** The frontend's `hermesAPI.chat()` returns a text message ("Compte-rendu mis à jour.") but the frontend doesn't always call `refreshMeetingCr` to reload the CR. The backend saves correctly (version increments, content changes), but the user sees the old content.

**Debug technique:** Add file-based logging at the top of `chat_completions()`:
```python
with open("/tmp/plaudia_debug.log", "a") as f:
    f.write(f"[{datetime}] cr_id={req.cr_id} session_id={req.session_id} has_cr={'<CR>' in question} has_inst={'Instruction :' in question} qlen={len(question)} preview={question[:200]}\n")
```
Then check the log: `cat /tmp/plaudia_debug.log`. If `has_cr=True` and `has_inst=True` and `cr_id` is set, the edit request is correct. The issue is frontend cache.

**Fix:** The user must provide a prompt to Lovable to fix `refreshMeetingCr` in `CRDetailView.tsx`:
- After `handleChatSubmit` receives a success response, call `refreshMeetingCr(cr_id)` to reload the CR
- The error message "Aucune modification appliquée" appears when the frontend checks for `<CR>...</CR>` in the response (which is a text message, not HTML)

**PITFALL — Keepalive kills manual uvicorn:** The cron `plaudia-keepalive` kills and restarts uvicorn every minute. Manual background processes get replaced. Let keepalive restart after code changes — no need to restart manually.

**PITFALL — Deux uvicorn peuvent cohabiter : `.venv/bin/uvicorn` vs `/opt/hermes/.venv/bin/python -m uvicorn`.** Le service file `plaudia-backend.service` pointe vers `ExecStart=/opt/data/projects/plaudia/rag_backend/.venv/bin/uvicorn main:app`. Ce `.venv` local peut contenir une version PERIMEE du code, même si `/opt/data/projects/plaudia/rag_backend/main.py` est à jour. Symptôme : `curl localhost:8000/healthz` répond 200 mais les nouveaux endpoints (ex: `/v1/auth/me`) retournent 404. Diagnostic :

```bash
# 1. Trouver le PID qui écoute sur le port
python3 -c "
import os
with open('/proc/net/tcp') as f:
    for line in f:
        if ':1F40' in line:  # 8000 en hex
            inode = line.split()[9]
            for pid in os.listdir('/proc'):
                if pid.isdigit():
                    try:
                        for fd in os.listdir(f'/proc/{pid}/fd'):
                            link = os.readlink(f'/proc/{pid}/fd/{fd}')
                            if f'socket:[{inode}]' in link:
                                cmd = open(f'/proc/{pid}/cmdline').read().replace(chr(0), ' ').strip()
                                print(f'PID {pid}: {cmd[:200]}')
                    except: pass
"
# 2. Si le chemin contient .venv, tuer ce PID
kill <PID>
# 3. Redémarrer avec le bon Python
cd /opt/data/projects/plaudia/rag_backend
/opt/hermes/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Pour corriger définitivement, modifier `plaudia-backend.service` pour pointer vers `/opt/hermes/.venv/bin/uvicorn` ou supprimer le `.venv` local.

**PITFALL — Frontend signale 405 mais le vrai problème est Cloudflare Access 403 :** Si le frontend (Lovable) signale une erreur 405 Method Not Allowed, le coupable peut être Cloudflare Access qui bloque la requête avant qu'elle atteigne le backend. Le proxy Lovable (`callHermes`) reçoit une page HTML 403 de Cloudflare et peut interpréter l'erreur comme 405. **Toujours tester d'abord localement** :
```bash
curl -s -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" http://localhost:8000/<endpoint>
```
Si l'appel local fonctionne, le problème est le tunnel Cloudflare, pas le backend. Voir `plaudia-orchestrator` → Troubleshooting → Tunnel pour le diagnostic complet.

**PITFALL — ANON_KEY may be placeholder:** `main.py` may contain `"eyJhbG...PBj4"` (truncated). Get real key via `mcp_supabase_get_publishable_keys`. Verify with `wc -c` on the line (the actual content might be the full key — the `read_file` tool truncates long lines visually).

**TESTING — verify content quality, not just HTTP status:** The user was frustrated by tests claiming "100% success" when chart data was invented. A test that only checks HTTP 200 or version increment is NOT sufficient. Always verify: (1) is the content actually changed? (2) does it have tables? (3) does it have real SVG or just leftover chart-embed markers? (4) is the data accurate or invented? (5) is the CR size under 25K? Never report "100% success" without these checks.

## SVG chart rendering

**History:** Chart.js was tried first (browser-side JS, blocked by `dangerouslySetInnerHTML`). Replaced with matplotlib SVG (25K per chart, too bloated for DeepSeek context). Final solution: **svgwrite** (1.5-2K per chart, ultra-compact).

**Renderer:** `chart_renderer.py` — uses `svgwrite` (NOT matplotlib, NOT pygal, NOT plotly)
**Runtime:** `/opt/data/dwg-env/bin/python3` (has svgwrite 1.4.3 installed via `uv pip install --python <path> svgwrite`)
**Chart engine:** `render_charts_in_cr()` in main.py calls `chart_renderer.py` via subprocess.
**Call order:** DeepSeek returns article → `render_cr()` wraps with template → `render_charts_in_cr()` converts chart-embed markers to SVG. This happens AFTER re-wrapping, so the full HTML (with CDN removed) is processed.
**CDN removed:** `get_template_shell()` no longer includes `<script src="cdn.jsdelivr.net/npm/chart.js">` — SVG is self-contained, no JS needed.

### Chart quality — critical checklist

Every chart MUST have ALL of these. Missing any one is a bug:

1. **Y-axis with gridlines** — scales values from 0 to max_val*1.15, with 4-5 gridlines. Without a scale, the chart is meaningless.
2. **Minimum bar height of 4px** — when one value is much smaller than another (e.g. 1 vs 27), the small bar becomes invisible without a minimum. Use `max(frac * plot_h, min_bar_h)`.
3. **Value labels on top of each bar** — the numeric value (e.g. "27", "1") must be visible above each bar.
4. **X-axis labels below each bar** — the category name (e.g. "Pilote actuel", "Déploiement prévu") must be below the bar.
5. **Chart title** — bold, Hérone blue (#1e3a5f), 11pt, left-aligned.
6. **Unit label** — at top of y-axis, gray (#6b7280), 7.5pt.
7. **Doughnut: percentage labels + legend** — each slice must have a percentage label, and there must be a legend below the chart with labels + percentages.
8. **Line chart: circle markers** — each data point must have a visible circle marker (3.5px, white fill, color stroke).

### Common bugs to check visually

- **2 bars only** → chart looks sparse. Still correct but ensure bars are centered, not squished to one side.
- **Missing grid** → the `n_lines` calculation must produce visible gridlines. Check `n_lines = min(5, max(2, int(y_max / 5)))`.
- **Invisible small bar** → always apply `max(frac * plot_h, 4)` where `4` is the minimum pixel height.
- **Double-printed SVG** → `__main__` section should print the SVG only once (after cleanup, not before).
- **svgwrite vs matplotlib**: matplotlib SVGs are 9-25K (too large, breaks subsequent edits). svgwrite produces 1.5-2K.
- **Empty `<defs />` tag** → clean up with `re.sub(r'<defs\\s*/>', '', svg)`.
- **Extra xmlns attributes** → clean up with `re.sub(r'\\s+xmlns:ev="[^"]*"', '', svg)`.

### Auto-extraction flow ("crée-moi un graphique")

When the user says "crée-moi un graphique" without providing data, DeepSeek must:

1. Look at the transcription (appended to the enriched question)
2. Find numerical data (budget, counts, percentages, durations, comparisons)
3. If found: create a chart-embed marker with the extracted data
4. If NOT found: respond "Je n'ai pas trouvé de données chiffrées dans la transcription pour créer un graphique."
5. NEVER invent data

The edit prompt's `RÈGLE GRAPHIQUES` section instructs DeepSeek on this. The transcription is always available in the enriched question (up to 80K chars).

### Testing SVG quality

After generating a chart, verify with SQL:
```sql
SELECT id, version, length(content) as len, 
  (content LIKE '%<svg%') as has_svg,
  (content LIKE '%chart-embed%') as has_embed,
  (content LIKE '%cr-table%') as has_table
FROM public.crs WHERE id = '...';
```

Expected: `has_svg=true`, `has_embed=false` (no leftover markers), `has_table=true` (tables preserved), `len < 25000`.

## Glossary detection

Located in `detect_glossary_correction(question)` — checks if user message is a spelling/name correction.

**Patterns (added 15/07/2026):**
```python
r"\b(écrit|corrige|correction|orthographe|renomme|appelle|s'appelle)\b"
r"\b(on écrit|il faut écrire|doit s'écrire)\b"
r"\b(c'est\s+\S+\s+pas\s+|c'est\s+\S+\s+et\s+non\s+|c'était\s+\S+\s+pas\s+)\b"
r"\b(pas\s+\S+\s+mais\s+|appelle-moi\s+|nomme\s+)\b"
```

If detected, calls DeepSeek with `GLOSSARY_DETECT_PROMPT` to extract `{term_raw, term_corrected}`. Inserts into `glossary` table. The DB trigger `glossary_retroactive_rewrite` automatically rewrites all existing CRs with the correction.

## Validation endpoint

POST /v1/crs/{cr_id}/validate — validates a CR and auto-generates a Gmail draft.

**Flow:**
1. Frontend calls the endpoint with the CR id
2. Backend updates `crs.status` from `'ready'` to `'validated'`
3. Auto-generates a Gmail **draft** with the CR content via `send_or_draft_email(as_draft=True)`
4. Returns `{ "status": "validated", "version": N, "display_name": "...", "email": "..." }`

**Idempotence :** si `cr.status == "validated"` déjà, retourner 200 OK sans refaire les effets de bord.

## Discussion export & archive (21/07/2026)

### Export session → PDF

**Backend :** `POST /v1/chat/export-session` (existe déjà dans main.py)
- Body : `{ session_id, title? }`
- Appelle gpt-4o-mini pour structurer la conversation en HTML professionnel
- Retourne : `{ html, title, session_id, message_count }`

**Frontend :** `hermesAPI.exportSession(id)` → iframe caché → `print()` → PDF
- Pattern: `<iframe srcdoc={html} style="position:fixed;top:-9999px">` → `iframe.contentWindow.print()`
- Fallback: nouvelle fenêtre si print() échoue
- Cleanup: retirer l'iframe après 30s
- Voir `DiscussionView.tsx` → `handleExport()`

### Archive session → RAG memory

**Backend (endpoint à créer) :** `POST /v1/chat/sessions/{id}/archive`
1. Vérifier owner_id (403 si pas propriétaire)
2. Récupérer les messages de la session
3. Option préférée: utiliser l'export IA (HTML structuré) plutôt que les messages bruts
4. Chunker (500-800 tokens, overlap 50)
5. Générer embeddings via `text-embedding-3-small`
6. Upsert dans `rag_chunks` avec `source_type = 'discussion'`
7. ON CONFLICT (session_id) → purge + ré-insertion
8. Cascade delete: quand DELETE session, purger les chunks associés
9. Retourne : `{ status: "archived", chunks: N, updated: bool }`

**Option de table :** utiliser `rag_chunks` (existante) + colonne `source_type TEXT DEFAULT 'cr'` (option a, préférée).

**RPC à corriger :** `match_rag_chunks_hybrid` filtre `client_name` écrase les discussions (client_name=NULL). Ajouter: `WHERE (filter_client_name IS NULL OR client_name = filter_client_name OR source_type = 'discussion')`.

**Frontend :** `hermesAPI.archiveSession(id)` → `POST /v1/chat/sessions/{id}/archive`
- Bouton "Archiver dans la mémoire" dans le menu de DiscussionView
- Toast avec nombre d'extraits indexés
- Fallback 404: "disponible prochainement"

## Debug logging technique

When the user reports "aucune modification appliquée" from the frontend, add file-based logging to the top of `chat_completions()`:

```python
import datetime
with open("/tmp/plaudia_debug.log", "a") as f:
    _debug = f"[{datetime.datetime.now().isoformat()}] cr_id={req.cr_id} session_id={req.session_id} has_cr={'<CR>' in question} has_inst={'Instruction :' in question} qlen={len(question)} preview={question[:200]}"
    f.write(_debug + "\n")
```

Then check: `cat /tmp/plaudia_debug.log`. If `has_cr=True`, `has_inst=True`, and `cr_id` is set, the edit request format is correct. The issue is the frontend not reloading the CR after success.

## CQRS Architecture (20/07/2026)

The backend follows **CQRS** (Command Query Responsibility Segregation):

- **Lectures (Queries)** → direct Supabase via `heroneSupabase` (PostgREST). Supabase scale natively avec Postgres + PgBouncer pour des centaines de connexions concurrentes.
- **Écritures avec logique métier (Commands)** → via l'API Hermes FastAPI. Validation, LLM, email, cross-entity checks.

### Endpoints conservés sur le backend (écritures + logique métier)

| Endpoint | Raison |
|---|---|
| `POST /v1/chat/completions` | RAG chat + édition CR via LLM |
| `POST /v1/crs/{cr_id}/validate` | Validation + génération brouillon Gmail |
| `POST /v1/cr/export-doc` | Export Google Doc (API OAuth) |
| `POST /v1/cr/send-email` | Envoi Gmail (API OAuth) |
| `GET /v1/cr/{recording_id}/email-defaults` | Pré-remplissage email (partie du workflow) |
| `POST /v1/recordings/check-new` | Vérification Plaud + trigger pipeline |
| `POST /v1/glossary` | Correction ortho → trigger retroactive rewrite |
| `GET /v1/glossary` | Liste des entrées du glossaire (ajouté 21/07) |
| `PATCH /v1/glossary/{id}` | Modifier une entrée (ajouté 21/07) |
| `DELETE /v1/glossary/{id}` | Supprimer une entrée (ajouté 21/07) |
| `GET /v1/participants` | Liste des participants (ajouté 21/07) |
| `POST /v1/participants` | Créer un participant (ajouté 21/07) |
| `PATCH /v1/participants/{id}` | Modifier un participant (ajouté 21/07) |
| `DELETE /v1/participants/{id}` | Supprimer un participant (ajouté 21/07) |
| `POST /v1/enterprises/{id}/assignments` | Attribution bulk avec validation croisée |
| `POST /v1/projects/{id}/crs` | Rattacher CRs à un projet (validation ∃) |
| `POST /v1/projects` (avec `cr_ids[]`) | Création projet + CRs pré-attribués |
| `POST /v1/enterprises` | Création entreprise + projet "Général" auto |
| `DELETE /v1/enterprises/{id}` | Suppression entreprise |
| `DELETE /v1/projects/{id}` | Suppression projet |
- `PATCH /v1/recordings/{id}` | Renommer CR/meta
- `DELETE /v1/recordings/{id}` | Supprimer enregistrement
- `PATCH /v1/projects/{id}` | Éditer projet
- `PATCH /v1/crs/{cr_id}` | Attribution entreprise/projet (validation croisée)
- `POST /v1/crs/{cr_id}/restore` | Restauration de version
- `PATCH /v1/chat/sessions/{session_id}` | Mise à jour titre/tags session
- `DELETE /v1/chat/sessions/{session_id}` | Suppression session
| `GET /v1/enterprises/with-counts` | **Proxy temporaire** (en attendant migration frontend vers vue matérialisée) |
| `GET /v1/enterprises` | Liste des entreprises (lecture directe CQRS — ajouté 20/07) |
| `GET /v1/enterprises/{enterprise_id}/projects` | Liste des projets d'une entreprise (lecture directe CQRS — ajouté 20/07) |
- `GET /v1/healthz` | Healthcheck keepalive
- `GET /v1/process-stream` | SSE streaming

### Endpoints de lecture (GET) — proxy Lovable (20/07/2026)

**Contexte :** Le frontend Lovable utilise un **proxy serveur** (`callHermes` server function) qui route TOUS les appels API via le backend FastAPI — les secrets (`PLAUDIA_SHARED_KEY`, `CF-Access-*`) ne peuvent pas vivre dans le bundle client. Conséquence : les GET endpoints qui avaient été retirés lors de la migration CQRS ont dû être **ré-ajoutés** comme proxy vers Supabase.

**Tous les GET endpoints suivants sont disponibles dans main.py :**

| Endpoint | Description |
|---|---|
| `GET /v1/enterprises-with-projects` | Entreprises avec projets imbriqués (format `e.projects[]` attendu par le frontend) |\n| `GET /v1/enterprises` | Liste des entreprises |\n| `GET /v1/enterprises/{enterprise_id}/projects` | Liste des projets d'une entreprise |\n| `GET /v1/enterprises/with-counts` | Compteurs CRs + recordings (via vue matérialisée `enterprise_counts`) |\n| `GET /v1/crs` | Liste des CRs (filtres : `enterprise_id`, `project_id`, `status`, `limit`, `offset`) |\n| `GET /v1/crs/{cr_id}` | CR complet (content, version, status, metadata) |\n| `GET /v1/crs/{cr_id}/versions` | Historique des versions d'un CR |\n| `GET /v1/chat/sessions` | Sessions de chat RAG |\n| `GET /v1/chat/sessions/{session_id}/messages` | Messages d'une session |\n| `GET /v1/healthz` | Healthcheck keepalive |\n| `GET /v1/process-stream` | SSE streaming |

**PITFALL — Proxy Lovable = tous les appels passent par le backend, même les lectures.** Si le frontend signale un 404, vérifier que l'endpoint GET existe dans `main.py` avec `grep '@app.get' rag_backend/main.py`. Les GET proxy sont des wrappers simples vers Supabase (via `http_json`), pas de logique métier.

**PITFALL — CQRS incomplet avec proxy.** Le CQRS pur (lectures Supabase direct, écritures via backend) est cassé par le proxy Lovable. Les GET endpoints sont des proxy triviaux qui ajoutent de la latence (aller-retour supplémentaire). Solution idéale : déployer le backend et le frontend sur le même domaine (pas de proxy), ou utiliser un BFF qui ne proxy que les lectures vers Supabase directement.

**PITFALL — Supabase resource embedding (`recording:recording_id(...)`) est instable avec la clé anon + RLS.** L'embed est silencieusement ignoré pour les tables avec RLS. La solution fiable est le **batch enrichment** avec `id=in.(...)` filters — 2 requêtes batch, pas N+1.

**PITFALL — `or=(id.eq.1,id.eq.2,…)` 502 BUG (cause #1 des 502 Cloudflare) :** Le filtre `or=` peut produire des URLs mal formées si :
- Un `recording_id` est une chaîne vide (`""`) → génère `id.eq.` → PostgREST 500 → Cloudflare 502
- Trop d'UUIDs → la chaîne `or=(...)` dépasse les limites de l'URL

**Solution :** utiliser `id=in.(uuid1,uuid2)` (opérateur natif PostgREST, plus robuste) + un guard `_valid_uuid()` :

```python
def _valid_uuid(v):
    return v and isinstance(v, str) and len(v) > 20

rec_ids = sorted(set(r["recording_id"] for r in rows if _valid_uuid(r.get("recording_id"))))
if rec_ids:
    recs = http_json("GET",
        f"{SUPABASE_URL}/rest/v1/recordings?select=id,title,client_name,meeting_subject,meeting_type,recorded_at&id=in.({','.join(rec_ids)})",
        headers=sb_headers()) or []
    rec_map = {r["id"]: r for r in recs}
```

**PITFALL — `GET /v1/enterprises/with-counts` doit inclure `projects[]`.** Le frontend attend `(Enterprise & { projects: Project[]; cr_count: number; recording_count: number })[]`. L'ancienne implémentation ne renvoyait que les compteurs sans les projets. Utiliser 3 requêtes batch (projets, CRs, recordings) avec `or=(enterprise_id.eq.X,...)`.

**PITFALL — `POST /v1/crs/{cr_id}/validate` doit être idempotent.** Si le CR est déjà `status="validated"`, retourner 200 OK avec `{"status": "validated", "version": N}` sans refaire les effets de bord (brouillon Gmail). Vérifier `cr.get("status") == "validated"` en début de handler.

**PITFALL — `display_name` manquant sur les CRs.** Le frontend attend `display_name` sur chaque objet CR pour l'afficher dans la liste. La logique de fallback : `recording.title || recording.meeting_subject || enterprise_name || 'Compte rendu'`. Le `GET /v1/crs` doit enrichir chaque CR avec le champ `display_name` et les objets imbriqués `recording`, `enterprise`, `project`.

**PITFALL — `enterprises-with-projects` format attendu.** Le frontend Lovable attend `e.projects[]` (tableau de projets) directement dans la réponse des entreprises. `GET /v1/enterprises/with-counts` ne renvoie que les compteurs, pas les projets. Un endpoint dédié `GET /v1/enterprises-with-projects` doit exister, qui utilise `select=*,projects(*)` (Supabase PostgREST embed) ou un fallback avec deux requêtes séparées.

### Vue matérialisée pour les compteurs entreprises

Remplacer l'endpoint `GET /v1/enterprises/with-counts` par une vue matérialisée Supabase :

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

Le frontend fait un seul `SELECT * FROM enterprise_counts` — aussi rapide qu'une lecture directe.

### Frontend migration & auth patterns

See `references/frontend-supabase-migration.md` for the full inventory of 27 direct Supabase calls, priority matrix (P0-P3), and migration sequence.

**Key patterns :**

- **Stub pattern** : `hermesAPI.glossary.*`, `hermesAPI.participants.*`, `hermesAPI.recordings.*` jettent `NotProxied` tant que le backend n'a pas les endpoints. Cela évite les appels Supabase directs et crash proprement plutôt que de créer des régressions silencieuses.
- **Lint check** : `scripts/check-supabase-imports.sh` bloque `import { heroneSupabase }` dans `components/`, `hooks/`, `context/` (hors `AuthContext.tsx`). Idéal en CI.
- **4 méthodes manquantes** ajoutées à `hermesAPI` le 21/07/2026 : `listCRs`, `getCR`, `listCRVersions`, `getSessionMessages` — appellent les endpoints GET proxy existants.
- **3 types manquants** ajoutés : `CRSummary`, `ChatMessage`, `ChatSession`.

**PITFALL — Ne pas migrer l'auth.** `supabase.auth.signInWithPassword()`, `getSession()`, `onAuthStateChange()` restent côté client. C'est le design normal de Supabase Auth, pas un trou de sécurité.

**PITFALL — VITE_CF_CLIENT_SECRET expose dans le JS bundle.** Toute variable `VITE_*` est bundlee dans le JS client. **Depuis 23/07 :** VITE_CF_CLIENT_ID, VITE_CF_CLIENT_SECRET et VITE_PLAUDIA_SHARED_KEY supprimees de l'env Lovable. L'auth passe uniquement par le JWT Supabase Auth. Le tunnel Cloudflare n'a pas besoin de secrets cote frontend.

**PITFALL — Admin-only user creation.** Martin veut controler la creation. Pas de self-signup frontend, pas d'endpoint backend. Martin cree les utilisateurs dans le dashboard Supabase (Authentication → Users → Add User). Le trigger `on_auth_user_created` cree auto le `user_profiles`. LoginPage = connexion uniquement + lien "Mot de passe oublie ?" (`supabase.auth.resetPasswordForEmail()`). Pour passer un user en admin : `UPDATE user_profiles SET role = 'admin' WHERE email = '...'`.

### Pitfall — "Général" project filter is fragile

The backend auto-creates a project named "Général" for every new enterprise (main.py:1561-1564). The frontend filters it by name (`isGeneral()` in EnterprisesContext.tsx:80, `.neq("name", "Général")` in ProjectsView.tsx:39). If someone renames it, the filter silently breaks.

**Fix** : Add `is_system boolean DEFAULT false` column to `projects`, mark the auto-created project with `is_system=true`, and filter by that column. Both backend and frontend need updating.

## Bilan du fichier main.py
- Tous les endpoints GET sont dans une section `# --- GET endpoints lecture (proxy Lovable) ---`
- Les nouveaux endpoints métier (PATCH recordings, DELETE recordings, PATCH projects, POST glossary, POST projects/{id}/crs, POST enterprises/{id}/assignments) sont dans une section `# New endpoints — frontend migration` à la fin du fichier
- `GET /v1/recordings` existe déjà (ligne ~1350) — pas besoin de le recréer
- `GET /v1/participants` : colonnes réelles = `id, recording_id, name, email, created_at` (pas de `cr_id` ni `role` — erreur 42703 si SELECT sur ces colonnes)
- `POST /v1/participants` : body = `{ recording_id?, name?, role?, email? }` — mais `role` n'est pas persisté (colonne inexistante)
- `GET /v1/glossary` : colonnes réelles = `id, owner_id, term_raw, term_corrected, uses_count, created_at`
- `POST /v1/glossary` : body = `{ term_raw, term_corrected, owner_id? }`
- Le modèle LLM est `gpt-4o-mini` via OpenAI direct (plus OpenRouter)
- L'API key OpenAI est dans `.env` à la racine du projet

## Deployment template

A complete deployment template lives at `docs/template/` in the project root (`/opt/data/projects/plaudia/docs/template/`). It contains `supabase-schema.sql`, `env.example`, `deployment.md`, `architecture.md`, and `README.md` — everything needed to redeploy Plaudia on a fresh environment. See `references/deployment-template.md` in `plaudia-recording-pipeline` for the pointer.

## PITFALL — Keepalive kills manual uvicorn processes

The cron job `plaudia-keepalive` runs every minute and kills/starts uvicorn. Any manual background uvicorn process gets replaced. After editing `main.py`, just wait for the keepalive to restart the backend (it reads from the current file). Don't restart manually unless you need to test immediately.

## PITFALL — Multiple uvicorn processes on port 8000

If you see 404 on endpoints that exist in the file, the running process is likely a STALE version:

1. Check which Python is running: `cat /proc/$(cat /proc/net/tcp | grep ':1F40' | awk '{print $10}')/fd/...` or use `python3 -c` to find the PID via inode
2. The `.venv/bin/uvicorn` (local venv) may be different from `/opt/hermes/.venv/bin/python` (Hermes venv)
3. Fix: `kill <PID>` then restart with the correct Python
4. **Root cause**: the systemd service file `plaudia-backend.service` uses `.venv/bin/uvicorn` — update it to use `/opt/hermes/.venv/bin/python`

## PITFALL — SUPABASE_URL and SUPABASE_ANON_KEY must be in the env

The new auth system (`auth.py`) reads Supabase credentials from ENV VARS, not hardcoded. If they're missing, the backend crashes with:
```
ValueError: unknown url type: '/auth/v1/token?grant_type=password'
```
Fix: ensure these are in `/opt/data/.env` AND exported by the keepalive script:
```
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbG...
SUPABASE_SERVICE_EMAIL=admin@...
SUPABASE_SERVICE_PASSWORD=...
```
The keepalive script must export them: `export SUPABASE_URL SUPABASE_ANON_KEY ...`

## PITFALL — Frontend sends old shared key after auth migration

After migrating to JWT auth, the frontend (Lovable) still sends `X-Plaudia-Key` header. The backend falls back to the shared key if `PLAUDIA_SHARED_KEY` is set in env. This is a TEMPORARY compatibility layer — remove it once all users have migrated to JWT.

## Multi-user auth architecture (23/07/2026)

### Auth flow

```
Frontend (Lovable)          Backend (FastAPI)           Supabase
      |                          |                          |
      |-- Login (email+mdp) ---->|                          |
      |                          |-- POST /auth/v1/token -->|
      |<--- JWT (access_token) --|<-------------------------|
      |                          |                          |
      |-- GET /v1/crs (JWT) ---->|                          |
      |   Authorization: Bearer  |                          |
      |                          |-- GET /rest/v1/crs (JWT) |
      |                          |   (RLS filtre par user)  |
      |<--- CRs filtrés ---------|<-------------------------|
```

### Key changes from shared key to JWT

1. **`auth.py`** — new module: JWT decode, HMAC verification, user context extraction
2. **`get_current_user(request)`** — replaces `check_shared_key()` everywhere
3. **`sb_headers(user_token=None)`** — uses user's JWT when available, falls back to service account
4. **Fallback**: `X-Plaudia-Key` still accepted if `PLAUDIA_SHARED_KEY` is set in env
5. **Service account**: used only for cron jobs (pipeline, watchdog)

### New endpoints

| Endpoint | Description | Auth |
|----------|-------------|------|
| `GET /v1/auth/me` | User profile | JWT |
| `POST /v1/projects/{id}/share` | Share project by email | JWT (admin) |
| `DELETE /v1/projects/{id}/share/{share_id}` | Remove share | JWT (admin) |
| `GET /v1/projects/{id}/shares` | List shares | JWT |
| `GET /v1/shares/me` | My shared projects | JWT |

### Database changes

- Table `project_shares` (project_id, shared_with_email, permission, shared_by)
- RLS policies on ALL tables (admin sees all, user sees own + shared)
- Trigger `on_auth_user_created` (auto-creates user_profiles on signup)
- Auto-refresh trigger for `enterprise_counts` materialized view
- Indexes on owner_id columns for RLS performance

### Frontend changes needed (Lovable prompts in `docs/frontend-login-prompt.md`)

1. AuthContext + LoginPage (Supabase Auth, pas d'inscription, mot de passe oublié)
2. Replace `apiHeaders()` → `getAuthHeaders()` with JWT in `Authorization: Bearer`
3. ProfilePanel (infos utilisateur + déconnexion)
4. Remove VITE_CF_CLIENT_ID, VITE_CF_CLIENT_SECRET, VITE_PLAUDIA_SHARED_KEY from env
5. Keep VITE_PLAUDIA_BACKEND_URL, VITE_HERONE_SUPABASE_URL, VITE_HERONE_SUPABASE_PUBLISHABLE_KEY

## Edit prompt rules

The prompt in `edit_system_prompt` (main.py) must say:
- "Génère UNIQUEMENT le contenu de l'article" — never <style>, <head>, DOCTYPE
- "PRÉSERVE les tableaux <table class=\"cr-table\">" — never convert tables to text
- "PRÉSERVE les SVG <svg> et <div class=\"chart-container\">" — never remove charts
- Chart data rule: "N'invente JAMAIS de données. Utilise UNIQUEMENT les valeurs extraites de la transcription ou fournies par l'utilisateur."