# Plaudia Frontend — Architecture & UX Design

## Source du code

- **Repo GitHub** : `herone-dev/plaudia-v1-martin`
- **Stack** : React + TypeScript + TanStack Router + shadcn/ui + Tailwind CSS
- **Auth** : Supabase Auth (email/password) avec `AuthContext`
- **Backend API** : `hermesAPI` service dans `src/services/hermes.ts`
- **Backend URL** : via `VITE_PLAUDIA_BACKEND_URL` (tunnel Cloudflare Access privé)
- **Cloudflare Access** : les appels backend nécessitent `VITE_CF_CLIENT_ID` et `VITE_CF_CLIENT_SECRET` via `apiHeaders()` (dans `hermes.ts`) — sans ces headers, Cloudflare renvoie 403. **Ces variables doivent être configurées dans Lovable Dashboard.**
- **Supabase client** : `heroneSupabase` utilise `VITE_HERONE_SUPABASE_URL` + `VITE_HERONE_SUPABASE_PUBLISHABLE_KEY` (format `sb_publishable_*`) pour les lectures directes

## Structure du code (v3)

```
src/
├── components/
│   ├── v3/
│   │   ├── Sidebar.tsx          # Navigation latérale (5 entrées)
│   │   ├── DiscussionView.tsx   # Chat RAG contextuel avec tags
│   │   ├── CRDetailView.tsx     # Édition CR (contenteditable + instruction)
│   │   ├── CRListView.tsx       # Liste CRs avec versions
│   │   ├── EnterprisesView.tsx  # Gestion entreprises/projets
│   │   ├── ProjectsView.tsx     # Projets groupés par entreprise
│   │   ├── ConversationsView.tsx # Historique des sessions chat
│   │   ├── NewEnterpriseDialog.tsx
│   │   ├── NewProjectDialog.tsx
│   │   ├── SettingsView.tsx
│   │   ├── MobileHeader.tsx
│   │   └── MobileDrawer.tsx
│   └── PlaudApp.tsx             # Point d'entrée, routage des vues
├── context/
│   ├── EnterprisesContext.tsx    # State enterprises/projects + scope sélectionné
│   ├── ChatSessionsContext.tsx   # State sessions chat
│   └── AuthContext.tsx           # Auth Supabase
├── services/
│   └── hermes.ts                # API client (enterprises, CRs, chat, sessions)
├── hooks/
│   ├── useMeetings.ts           # CRUD meetings (legacy)
│   ├── useCRHistory.ts
│   └── ...
└── routes/
    └── index.tsx                # Route unique → PlaudApp
```

## Navigation (vues)

| Vue | Composant | Rôle |
|---|---|---|
| `discussions` | `DiscussionView` | Chat RAG avec tags, export, dictée |
| `conversations` | `ConversationsView` | Liste des sessions passées |
| `crs` | `CRListView` | CRs avec versions, validation, export |
| `enterprises` | `EnterprisesView` | Entreprises avec projets dépliables |
| `projects` | `ProjectsView` | Projets groupés par entreprise |
| `settings` | `SettingsView` | Glossaire, annuaire, préférences |

## Problèmes UX identifiés

### 1. Navigation trop complexe (ancien design)
- 5 clics pour discuter d'un projet : Sidebar → Entreprises → Déplier → Trouver projet → Discussion
- Résolu par le design "tags" : le scope est directement accessible depuis le chat via le panneau "+".

### 2. Hiérarchie cachée
- Entreprise → Projet est une vraie relation dans Supabase, mais l'UI la traite comme 2 vues séparées
- **Correction** (13/07/2026) : `EnterprisesView` affiche maintenant les projets sous chaque entreprise (accordéon). Cliquer sur un projet → navigation vers `ProjectsView` avec le projet en surbrillance.

## Décision UX finale — Design Claude-like

### Principe
- **Sidebar** avec 5 items de navigation + section **Récents** (liens vers les dernières sessions)
- **Tags système** : les discussions sont associées à des entreprises/projets/CRs via des tags, persistés en base
- **Panneau "+"** dans la barre de chat : checkboxes pour ajouter des entreprises, projets, CRs comme tags actifs
- **CRs versionnés** : chaque édition crée une nouvelle version, les anciennes dans un accordéon, possibilité de restaurer

## Bugs identifiés et corrigés (13/07/2026)

### Bug 1 — Titre de discussion non réinitialisé
**Problème** : Quand l'utilisateur crée une nouvelle discussion (via le bouton "+" ou en cliquant "Discussion" depuis Entreprises/Projets), le titre de la discussion reste celui de l'ancienne session.

**Cause** : Dans `DiscussionView.tsx`, quand `activeSessionId` passe à `null`, le `useEffect` (lignes 108-109) reset `messages` mais pas `title` ni `tags` :

```typescript
// AVANT (BUG)
if (!activeSessionId) {
  setMessages([]);
  // don't wipe tags if just came from pending; but for fresh new keep them as-is
  return;
}

// APRÈS (CORRECTION)
if (!activeSessionId) {
  setMessages([]);
  setTitle('Nouvelle discussion');
  setTags([]);
  return;
}
```

**Solution** : Ajouter `setTitle('Nouvelle discussion')` et `setTags([])` quand `activeSessionId` est null.

### Bug 2 — Entreprises → Projets : navigation non intuitive
**Problème** : Les entreprises et projets étaient dans deux vues séparées sans lien de navigation. Impossible de naviguer d'une entreprise vers ses projets.

**Solution** : 
1. `EnterprisesView` rend chaque entreprise cliquable (accordéon) pour déplier ses projets
2. Cliquer sur un projet dans l'accordéon → navigation vers `ProjectsView` avec le projet en surbrillance
3. `ProjectsView` groupe les projets par entreprise en accordéon
4. Le groupe du projet sélectionné est automatiquement ouvert

**Changements** :
- `PlaudApp.tsx` : ajout d'un état `selectedProjectId` pour passer le projet sélectionné entre les vues
- `EnterprisesView.tsx` : `onViewChange` accepte maintenant un `projectId` optionnel ; ajout d'accordéon avec `expanded` state
- `ProjectsView.tsx` : nouveau `selectedProjectId` prop ; groupement par entreprise ; auto-expand du groupe sélectionné

## Tags persistés en base

`chat_sessions.tags` (JSONB) stocke le tableau de tags. Chargé quand l'utilisateur ouvre une session, mis à jour via `PATCH /v1/chat/sessions/{id}`.

Structure d'un tag :
```typescript
interface DiscussionTag {
  kind: 'enterprise' | 'project' | 'cr';
  id: string;
  name: string;
  enterpriseId?: string;  // pour les tags project et cr
  enterpriseName?: string;
}
```

## Env vars requises dans Lovable

| Variable | Rôle |
|---|---|
|| `VITE_HERONE_SUPABASE_URL` | `https://VOTRE_PROJET.supabase.co` |
|| `VITE_HERONE_SUPABASE_PUBLISHABLE_KEY` | `VOTRE_CLE_ANON` |
| `VITE_PLAUDIA_BACKEND_URL` | `https://plaudia-api.herone.app` |
| `VITE_PLAUDIA_SHARED_KEY` | Clé partagée du backend |
| `VITE_CF_CLIENT_ID` | Service Token Cloudflare Access |
| `VITE_CF_CLIENT_SECRET` | Service Token Cloudflare Access |

Sans ces variables :
- Erreur de chargement dans l'historique (Supabase pas joignable)
- Erreur de connexion dans le chat RAG (Cloudflare bloque)
- Édition CR impossible
