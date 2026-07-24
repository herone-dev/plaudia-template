# Frontend Supabase → Hermes API — Migration Guide

## Contexte

Le frontend Plaudia (Lovable) appelle directement Supabase (`heroneSupabase.from(...)`) pour **27 opérations** réparties sur **7 tables**. L'objectif est de migrer toutes les écritures + les lectures critiques vers le backend Hermes (FastAPI), et de n'autoriser que l'auth Supabase directe côté client.

## Inventaire complet (21/07/2026)

### Table `recordings` — 9 appels

| Fichier | Ligne | Opération | Priorité |
|---------|-------|-----------|----------|
| `hooks/useCRHistory.ts` | 15 | SELECT id, title, recorded_at, crs!inner(...) | P2 |
| `hooks/useCRHistory.ts` | 58 | UPDATE status, updated_at WHERE id | **P0** |
| `hooks/useTranscriptionHistory.ts` | 78 | SELECT id, title, is_private, updated_at, crs(...) | P2 |
| `hooks/useTranscriptionHistory.ts` | 123 | UPDATE title, is_private, updated_at WHERE id | **P0** |
| `hooks/useMeetings.ts` | 44 | SELECT ... ORDER BY recorded_at | P2 |
| `hooks/useMeetings.ts` | 92 | UPDATE client_name, meeting_type, meeting_subject WHERE id | **P0** |
| `hooks/useMeetings.ts` | 134 | DELETE WHERE id | **P0** |
| `context/EnterprisesContext.tsx` | 62 | SELECT enterprise_id (counts) | P2 |
| `components/v3/RAGChatFull.tsx` | 97 | SELECT client_name, recorded_at LIMIT 20 | P2 |
| `components/v3/CRDetailView.tsx` | 109-118 | SELECT DISTINCT client_name / meeting_type | P2 |

### Table `crs` — 8 appels

| Fichier | Ligne | Opération | Priorité |
|---------|-------|-----------|----------|
| `hooks/useCRHistory.ts` | 58 | UPDATE status, updated_at WHERE id | **P0** |
| `hooks/useTranscriptionHistory.ts` | 143 | UPDATE content, doc_url, email_sent_to, ... WHERE id | **P0** |
| `hooks/useMeetings.ts` | 110 | SELECT content, version WHERE id .maybeSingle() | P2 |
| `context/EnterprisesContext.tsx` | 52 | SELECT enterprise_id (counts) | P2 |
| `components/v3/CRListView.tsx` | 46 | SELECT avec JOIN recordings + enterprises | P2 |
| `components/v3/CRDetailView.tsx` | 242 | UPDATE content, version, updated_at WHERE id | **P0** |

### Table `enterprises` — 2 appels (P2)

| Fichier | Ligne | Opération |
|---------|-------|-----------|
| `context/EnterprisesContext.tsx` | 44 | SELECT *, projects(*) ORDER BY name |
| `components/v3/TagPickerPanel.tsx` | 57 | SELECT id, name, description, created_at ORDER BY name |

### Table `projects` — 2 appels (P2)

| Fichier | Ligne | Opération |
|---------|-------|-----------|
| `components/v3/ProjectsView.tsx` | 36 | SELECT *, enterprise:enterprises(name) ORDER BY name |
| `components/v3/TagPickerPanel.tsx` | 61 | SELECT avec JOIN enterprise ORDER BY name |

### Table `chat_sessions` — 1 appel (P2)

| Fichier | Ligne | Opération |
|---------|-------|-----------|
| `context/ChatSessionsContext.tsx` | 27 | SELECT id, title, created_at, updated_at, tags LIMIT 100 |

### Table `participants` — 4 appels (P1)

| Fichier | Ligne | Opération |
|---------|-------|-----------|
| `hooks/useEmailHistory.ts` | 24 | SELECT email, created_at LIMIT 200 |
| `components/v3/DirectoryView.tsx` | 32 | SELECT recording_id, name, email, created_at |
| `components/v3/DirectoryView.tsx` | 81 | UPDATE name WHERE email |
| `components/v3/DirectoryView.tsx` | 99 | UPDATE email=null WHERE email (soft-delete) |

### Table `glossary` — 6 appels (P1)

| Fichier | Ligne | Opération |
|---------|-------|-----------|
| `components/v3/GlossaryView.tsx` | 33 | SELECT id, owner_id, term_raw, ... ORDER BY created_at |
| `components/v3/GlossaryView.tsx` | 63 | INSERT {term_raw, term_corrected, owner_id} |
| `components/v3/GlossaryView.tsx` | 95 | UPDATE term_corrected WHERE id |
| `components/v3/GlossaryView.tsx` | 108 | DELETE WHERE id |
| `components/v3/CRDetailView.tsx` | 204 | INSERT (depuis sélection de texte) |
| `components/v3/RAGChatFull.tsx` | 93 | SELECT term_corrected, uses_count LIMIT 10 |

### Auth (exclu de la migration) — 9 appels

Tous les appels `supabase.auth.*` (getSession, onAuthStateChange, signInWithPassword, signOut) restent côté client. C'est le design normal de Supabase Auth.

## Matrice de priorité

| Priorité | Zone | Risque | Endpoint backend |
|----------|------|--------|-----------------|
| **P0** | `crs` UPDATE content/status/version | Écriture métier critique, bypass RLS possible | `PATCH /v1/crs/:id`, `POST /v1/crs/:id/validate` |
| **P0** | `recordings` UPDATE/DELETE | Suppression irréversible | `PATCH /v1/recordings/:id`, `DELETE /v1/recordings/:id` |
| **P1** | `glossary` CRUD | Aucun endpoint backend sauf POST | `GET/PATCH/DELETE /v1/glossary/:id` |
| **P1** | `participants` CRUD | Aucun endpoint backend | `GET/PATCH/DELETE /v1/participants` |
| **P2** | SELECT lecture seule (enterprises, projects, chat_sessions, counts) | Risque moindre (RLS) | Endpoints GET existent déjà |

## Pattern de migration côté frontend

### 1. Stub `NotProxied` (dans `src/services/hermes.ts`)

```typescript
class NotProxied extends Error {
  constructor(feature: string) {
    super(`[Hermes] ${feature} — cet appel n'est pas encore migré.`);
    this.name = "NotProxied";
  }
}

export const hermesAPI = {
  glossary: {
    async list(): Promise<unknown[]> {
      throw new NotProxied("glossary.list() — endpoint GET /v1/glossary manquant");
    },
    // ... create, update, delete
  },
  participants: { /* ... */ },
  recordings: { /* ... */ },
};
```

### 2. Lint check (scripts/check-supabase-imports.sh)

Script bash qui interdit `import { heroneSupabase } from "@/integrations/supabase/herone-client"` dans les fichiers `components/`, `hooks/`, et `context/` (sauf `AuthContext.tsx`). Exit 1 si violation.

```bash
find src \( -name '*.ts' -o -name '*.tsx' \) -print0 | while read -d '' FILE; do
  # vérifie si le fichier importe heroneSupabase
  # skip si dans la liste AUTHORIZED
done
```

### 3. Méthodes manquantes ajoutées (21/07/2026)

Ces méthodes étaient appelées par les composants mais absentes de `hermesAPI` :

| Méthode | Endpoint | Raison |
|---------|----------|--------|
| `listCRs(opts?)` | `GET /v1/crs?enterprise_id=&project_id=` | HistoryView, TagPickerPanel |
| `getCR(crId)` | `GET /v1/crs/:id` | HistoryView, CRListView detail |
| `listCRVersions(crId)` | `GET /v1/crs/:id/versions` | CRListView version history |
| `getSessionMessages(id)` | `GET /v1/chat/sessions/:id/messages` | RAGChatFull, DiscussionView |

### 4. Types manquants ajoutés (21/07/2026)

```typescript
export interface CRSummary {
  id: string; recording_id: string; version: number; status: string;
  title?: string | null; display_name?: string | null;
  meeting_subject?: string | null; enterprise_name?: string | null;
  recorded_at?: string | null; updated_at?: string | null;
}
export interface ChatMessage {
  role: "user" | "assistant"; content: string; created_at?: string;
}
export interface ChatSession {
  id: string; title: string; created_at: string; updated_at: string;
  tags?: DiscussionTag[];
}
```

## Séquence de migration recommandée

```
Phase 1 — P0 (écritures critiques)
  ├─ Migrer les UPDATE crs (content, status, version, meta)
  ├─ Migrer les UPDATE/DELETE recordings
  └─ Vérifier que les endpoints PATCH/DELETE existent dans main.py

Phase 2 — P1 (tables sans backend)
  ├─ Créer endpoints GET/PATCH/DELETE /v1/glossary
  ├─ Créer endpoints GET/PATCH/DELETE /v1/participants
  └─ Remplacer les appels heroneSupabase par hermesAPI.glossary.* / participants.*

Phase 3 — P2 (lectures)
  ├─ Migrer enterprises SELECT avec JOIN projects
  ├─ Migrer projects SELECT
  ├─ Migrer chat_sessions SELECT
  └─ Migrer les SELECT recordings (distinct client_name, meeting_type)

Phase 4 — Lock
  ├─ Activer le lint check dans la CI
  └─ Supprimer le client heroneSupabase de l'API publique
```