# Direct Supabase Calls Audit — Frontend vs Backend API

Date: 20/07/2026 — **Mise à jour CQRS**
Source: Audit complet du code frontend (v3 components) + backend (main.py)

## Principe CQRS (20/07/2026)

**Les lectures restent en direct Supabase, seules les écritures avec logique métier passent par le backend.**

- **Lectures** → `heroneSupabase.from(...)` (PostgREST, scale nativement)
- **Écritures simples** (PATCH/DELETE sans validation) → `heroneSupabase.from(...)`
- **Écritures avec logique métier** (LLM, email, validation croisée, glossaire) → `hermesAPI.*`

## ⚠️ Endpoints GET : statut réel (vérifié le 22/07/2026)

**La migration CQRS n'a PAS été finalisée sur le backend.** Tous les endpoints GET sont encore présents dans `main.py` et le frontend les appelle encore via `hermesAPI`. Le tableau ci-dessous montre le statut réel.

| Endpoint | Statut réel (main.py) | Plan CQRS (non exécuté) |
|---|---|---|
| `GET /v1/crs` | ✅ Conservé (l.1252) | Direct Supabase |
| `GET /v1/crs/{cr_id}` | ✅ Conservé (l.1385) | Direct Supabase |
| `GET /v1/crs/{cr_id}/versions` | ✅ Conservé (l.1471) | Direct Supabase |
| `GET /v1/crs/{cr_id}/current-version` | ❌ Jamais créé | Direct Supabase |
| `GET /v1/enterprises` | ✅ Conservé | Direct Supabase |
| `GET /v1/enterprises-with-projects` | ✅ Conservé | Direct Supabase |
| `GET /v1/enterprises/with-counts` | ❌ Jamais créé | Vue mat. `enterprise_counts` |
| `GET /v1/enterprises/{id}/projects` | ✅ Conservé | Direct Supabase |
| `GET /v1/chat/sessions` | ✅ Conservé (l.1483) | Direct Supabase |
| `GET /v1/chat/sessions/{id}/messages` | ✅ Conservé (l.1496) | Direct Supabase |
| `GET /v1/rag/duration-stats` | ❌ Jamais créé | Direct Supabase |

## Vue matérialisée pour les compteurs entreprises

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

Le frontend remplace ses 3 requêtes par un seul :
```sql
SELECT * FROM enterprise_counts WHERE enterprise_id = ANY($ids)
```

## Cartographie complète des appels frontend

### Fichier : src/services/hermes.ts

| Méthode | Endpoint | Statut | Action |
|---|---|---|---|
| `listCRs` | `GET /v1/crs` | ✅ Conservé (migration en attente) | Appeler `heroneSupabase.from("crs").select(...)` |\n| `getCR` | `GET /v1/crs/{id}` | ✅ Conservé (migration en attente) | Idem |\n| `listCRVersions` | `GET /v1/crs/{id}/versions` | ✅ Conservé (migration en attente) | Idem |\n| `listEnterprises` | `GET /v1/enterprises` | ✅ Conservé (migration en attente) | Idem |\n| `listEnterprisesWithProjects` | `GET /v1/enterprises-with-projects` | ✅ Conservé (migration en attente) | Idem |\n| `listSessions` | `GET /v1/chat/sessions` | ✅ Conservé (migration en attente) | Idem |\n| `getSessionMessages` | `GET /v1/chat/sessions/{id}/messages` | ✅ Conservé (migration en attente) | Idem |
| `updateRecording` | `PATCH /v1/recordings/{id}` | ✅ Conservé | — |
| `deleteRecording` | `DELETE /v1/recordings/{id}` | ✅ Conservé | — |
| `updateProject` | `PATCH /v1/projects/{id}` | ✅ Conservé | — |
| `attachCRsToProject` | `POST /v1/projects/{id}/crs` | ✅ Conservé | — |
| `bulkAssign` | `POST /v1/enterprises/{id}/assignments` | ✅ Conservé | — |
| `createGlossaryEntry` | `POST /v1/glossary` | ✅ Conservé | — |
| `createProject` | `POST /v1/projects` (avec cr_ids) | ✅ Conservé | — |
| `chat` | `POST /v1/chat/completions` | ✅ Conservé | — |
| `updateCR` | `PATCH /v1/crs/{id}` | ✅ Conservé | — |
| `validateCR` | `POST /v1/crs/{id}/validate` | ✅ Conservé | — |
| `restoreCRVersion` | `POST /v1/crs/{id}/restore` | ✅ Conservé | — |
| `deleteCR` | `DELETE /v1/crs/{id}` | ✅ Conservé | — |
| `exportDoc` | `POST /v1/cr/export-doc` | ✅ Conservé | — |
| `sendEmail` | `POST /v1/cr/send-email` | ✅ Conservé | — |
| `getEmailDefaults` | `GET /v1/cr/{id}/email-defaults` | ✅ Conservé | — |
| `updateSession` | `PATCH /v1/chat/sessions/{id}` | ✅ Conservé | — |
| `deleteSession` | `DELETE /v1/chat/sessions/{id}` | ✅ Conservé | — |
| `checkNewRecordings` | `POST /v1/recordings/check-new` | ✅ Conservé | — |
| `streamProcess` | `GET /v1/process-stream` | ✅ Conservé | — |

### Fichier : src/context/EnterprisesContext.tsx

| Ligne | Appel | Statut |
|---|---|---|
| 44-69 | `heroneSupabase.from("enterprises").select("*, projects(*)")` + 2 compteurs | ✅ Lecture directe — à remplacer par vue matérialisée |
| 105-111 | `hermesAPI.createEnterprise()` | ✅ Déjà via backend |
| 113-116 | `hermesAPI.deleteEnterprise()` | ✅ Déjà via backend |
| 118-126 | `hermesAPI.createProject()` | ✅ Déjà via backend |

### Fichier : src/hooks/useMeetings.ts

| Ligne | Appel | Statut |
|---|---|---|
| 42-81 | `db.from("recordings").select(...)` avec `crs()` join | ✅ Lecture directe OK |
| 83-107 | `updateMeetingMeta()` → `db.from("recordings").update()` | ✅ Direct Supabase OK (écriture simple) |
| 109-127 | `refreshMeetingCr()` → `db.from("crs").select("content, version")` | ✅ Lecture directe OK |
| 129-137 | `deleteMeeting()` → `db.from("recordings").delete()` | ✅ Direct Supabase OK (écriture simple) |

### Fichier : src/components/v3/CRListView.tsx

| Ligne | Appel | Statut |
|---|---|---|
| 46-84 | `heroneSupabase.from("crs").select(...)` | ✅ Lecture directe OK |
| 317-328 | `hermesAPI.updateCR()` | ✅ Déjà via backend |

### Fichier : src/components/v3/CRDetailView.tsx

| Ligne | Appel | Statut |
|---|---|---|
| 109-131 | `heroneSupabase.from("recordings").select("client_name")` | ✅ Lecture directe OK |
| 204-206 | `heroneSupabase.from("glossary").insert(...)` | ✅ Direct Supabase OK (écriture simple, trigger retroactive) |
| 242-246 | `heroneSupabase.from("crs").update({ content, version })` | ✅ Direct Supabase OK (écriture simple) |

### Fichier : src/components/v3/ProjectsView.tsx

| Ligne | Appel | Statut |
|---|---|---|
| 36-49 | `heroneSupabase.from("projects").select(...)` | ✅ Lecture directe OK |

## Projet "Général" — remplacer le filtre par nom

**Problème** : backend crée auto un projet "Général" (main.py:1561-1564). Frontend filtre par `isGeneral()` (EnterprisesContext.tsx:80) et `.neq("name", "Général")` (ProjectsView.tsx:39). Si renommé, il réapparaît.

**Solution** : Ajouter `is_system boolean DEFAULT false` dans `projects` :
- Le projet "Général" auto-créé a `is_system = true`
- Frontend filtre par `is_system` au lieu du nom
- Backend exclut auto `is_system = true` des réponses

## Nommage automatique du CR

Le backend calcule déjà `display_name` dans `GET /v1/crs` (format `{Entreprise} — {Sujet} — {JJ/MM/AAAA}`). Mais :\n- `GET /v1/crs/{cr_id}` ne retourne pas le `display_name` (endpoint toujours présent mais sans ce champ)\n- Le frontend doit calculer le display_name côté client ou enrichir le endpoint

## RLS Policies

Le service account (JWT de martin@herone.fr) a le rôle `service_role` — les RLS sont contournées. La sécurité repose sur la clé partagée (`X-Plaudia-Key`). OK pour petite équipe.

## Plan de migration CQRS

1. ❌ **Backend** : Supprimer les GET wrappers, garder les écritures avec logique — **PAS FAIT** (tous les GET endpoints sont encore dans main.py)
2. ⏳ **Supprimer les méthodes mortes de `hermes.ts`** : `listCRs`, `getCR`, `listCRVersions`, `listEnterprises`, `listEnterprisesWithProjects`, `listSessions`, `getSessionMessages`
3. ⏳ **Vue matérialisée** : Créer `enterprise_counts` (voir SQL ci-dessus)
4. ⏳ **Colonne `is_system`** : Ajouter à `projects` pour remplacer le filtre par nom "Général"
5. ❌ **Aucune migration frontend nécessaire** — les lectures sont déjà en direct Supabase, ce qui est le comportement désiré en CQRS