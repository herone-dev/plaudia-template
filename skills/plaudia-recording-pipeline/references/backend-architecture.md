# Plaudia Backend Architecture

## Lecture/écriture split

Pour une performance optimale :

- **Lectures** (CRs, entreprises, projets, sessions) → Supabase direct via `heroneSupabase` client avec clé publishable + RLS anon SELECT
- **Écritures LLM** (chat RAG, édition CR, glossaire) → FastAPI backend derrière Cloudflare Access (protégé par Service Token)
- **CRUD** (création/suppression entreprises/projets) → FastAPI backend

## RLS Policies

Tables avec `row_security = true` :

```sql
-- Anon peut LIRE (SELECT uniquement)
CREATE POLICY anon_select_crs ON public.crs FOR SELECT USING (true);
CREATE POLICY anon_select_recordings ON public.recordings FOR SELECT USING (true);
CREATE POLICY anon_select_enterprises ON public.enterprises FOR SELECT USING (true);
CREATE POLICY anon_select_projects ON public.projects FOR SELECT USING (true);
CREATE POLICY anon_select_chat_sessions ON public.chat_sessions FOR SELECT USING (true);
CREATE POLICY anon_select_chat_messages ON public.chat_messages FOR SELECT USING (true);
CREATE POLICY anon_select_glossary ON public.glossary FOR SELECT USING (true);
CREATE POLICY anon_select_cr_versions ON public.cr_versions FOR SELECT USING (true);
CREATE POLICY anon_select_rag_chunks ON public.rag_chunks FOR SELECT USING (true);
CREATE POLICY anon_select_participants ON public.participants FOR SELECT USING (true);

-- Authenticated + owner_id = auth.uid() pour écritures
-- (backend utilise un service account martin@herone.fr)
```

## Supabase REST API : éviter les JOINs

Les JOINs avec Supabase REST sont peu fiables :
- `resource:foreign_table!inner(cols)` fonctionne en INNER JOIN
- `resource:foreign_table(cols)` (LEFT JOIN) peut retourner vide sans erreur
- Certains CRs ont `enterprise_id = NULL` → l'INNER JOIN les exclut silencieusement

**Approche fiable : batch queries avec OR filter**

```python
# 1 requête pour les CRs
rows = http_json("GET", f"{SUPABASE_URL}/rest/v1/crs?select=id,enterprise_id,recording_id&owner_id=eq.{owner_id}&order=updated_at.desc&limit=50")

# Collecter tous les IDs
ent_ids = list(set(r["enterprise_id"] for r in rows if r.get("enterprise_id")))
rec_ids = list(set(r["recording_id"] for r in rows if r.get("recording_id")))

# 2 requêtes batch (pas N+1)
ent_filter = "or=(" + ",".join(f"id.eq.{eid}" for eid in ent_ids) + ")"
ents = http_json("GET", f"{SUPABASE_URL}/rest/v1/enterprises?select=id,name&{ent_filter}")

rec_filter = "or=(" + ",".join(f"id.eq.{rid}" for rid in rec_ids) + ")"
recs = http_json("GET", f"{SUPABASE_URL}/rest/v1/recordings?select=id,client_name,recorded_at,title,meeting_subject&{rec_filter}")
```

Total : 3 requêtes au lieu de N+1.

## CR Naming

Le endpoint `GET /v1/crs` doit renvoyer les champs suivants pour que le frontend affiche les vrais noms :

```json
{
  "enterprise_name": "...",
  "project_name": "...",
  "title": "02-12 Réunion : Négociation...",
  "meeting_subject": "Négociation collaboration",
  "meeting_type": "Rdv commercial",
  "recorded_at": "...",
  "version": 5
}
```

`title` provient de `recordings.title` (titre original Plaud). Sans ce champ, le frontend affiche des noms génériques.

## Rate Limiting

Pour usage derrière tunnel Cloudflare (toutes les requêtes arrivent avec la même IP) :

```python
_RATE_LIMIT_MAX = 500      # requêtes
_RATE_LIMIT_WINDOW = 60    # secondes
```

## Process Management

- Ne pas utiliser `--reload` en production (empêche kill propre, le processus survit à `fuser -k`)
- Pour forcer un redémarrage :
  1. `fuser -k 8000/tcp`
  2. `rm -rf __pycache__`
  3. Redémarrer sans `--reload`
- Le keepalive cron (toutes les minutes) relance backend + tunnel si mort