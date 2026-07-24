# Multi-user migration — Plaudia (23/07/2026)

## Contexte

Plaudia passait d'un modèle "shared key unique + service account" à un modèle "JWT Supabase Auth + RLS" pour supporter plusieurs utilisateurs par environnement client.

**1 client = 1 environnement complet** (VPS + Supabase + tunnel + frontend), mais chaque environnement peut avoir plusieurs utilisateurs (admin + users) avec cloisonnement RLS et partage de projets par email.

## Changements clés

### 1. Schéma Supabase

Migration `002_multi_user_rls.sql` (dans `supabase/migrations/`) :

- Table `project_shares(project_id, shared_with_email, permission, shared_by)`
- RLS policies sur toutes les 12+ tables (admin = tout, user = ses données + partages)
- Trigger `on_auth_user_created` → INSERT auto dans `user_profiles`
- Trigger `refresh_enterprise_counts()` sur INSERT/UPDATE/DELETE de crs/recordings/enterprises
- Index : `idx_user_profiles_role`, `idx_crs_owner_id`, `idx_recordings_owner_id`, etc.

### 2. Backend — auth.py (nouveau fichier)

Module dédié, séparé de main.py pour clarté :

```python
def decode_jwt(token) -> dict | None
def extract_user_context(token) -> dict | None  # {user_id, email, role, is_service}
def get_service_token() -> str
def get_service_owner_id() -> str
def sb_headers(user_token=None) -> dict
```

- `decode_jwt()` : vérifie la signature HMAC avec `SUPABASE_ANON_KEY` comme secret
- `extract_user_context()` : extrait `sub` (user_id), `email`, `role` du payload JWT
- `get_service_token()` : login password grant du service account (pour crons)
- `sb_headers(user_token=None)` : si token fourni, l'utilise (RLS respecté) ; sinon token service account

### 3. Backend — main.py

- `check_shared_key()` remplacé par `get_current_user(request)` sur tous les ~40 endpoints
- `get_service_owner_id()` remplacé par `user["user_id"]` sur les endpoints utilisateur
- `get_service_owner_id()` conservé dans les fonctions internes (update_cr_content, learn_from_cr_edit, get_known_enterprises)
- Fallback `X-Plaudia-Key` conservé pour les crons (via `os.environ.get("PLAUDIA_SHARED_KEY")`)
- 5 nouveaux endpoints multi-user

### 4. Migration regex

Script batch en Python pour remplacer `check_shared_key()` → `get_current_user()` :

```python
import re

# Pattern 1: check_shared_key + rate_limit + owner_id
content = re.sub(
    r'    check_shared_key\(request, query_key=plaudia_key\)\n    check_rate_limit\(get_client_ip\(request\)\)\n    owner_id = get_service_owner_id\(\)',
    '    user = get_current_user(request)\n    check_rate_limit(get_client_ip(request))\n    owner_id = user["user_id"]',
    content
)

# Pattern 2: check_shared_key + owner_id (sans rate_limit)
content = re.sub(
    r'    check_shared_key\(request, query_key=plaudia_key\)\n    owner_id = get_service_owner_id\(\)',
    '    user = get_current_user(request)\n    owner_id = user["user_id"]',
    content
)

# Pattern 3: check_shared_key seul (sans owner_id)
content = re.sub(
    r'    check_shared_key\(request, query_key=plaudia_key\)',
    '    user = get_current_user(request)',
    content
)

# Pattern 4: check_shared_key(request) sans query_key
content = re.sub(
    r'    check_shared_key\(request\)',
    '    user = get_current_user(request)',
    content
)
```

**PITFALL** : toujours vérifier les `get_service_owner_id()` restants après le script. 7-10 doivent subsister (fonctions internes) ; si plus de 15, le script a raté des patterns.

### 5. Template (plaudia-template/)

- `rag_backend/auth.py` ajouté
- `rag_backend/main.py` mis à jour avec JWT auth
- `rag_backend/migrations/002_multi_user_rls.sql` ajouté
- `supabase/schema.sql` complété avec la migration
- `docs/frontend-auth-prompts.md` — 5 prompts Lovable pour le frontend
- `.env.example` mis à jour (SUPABASE_URL, SUPABASE_ANON_KEY ajoutés)
- `.gitignore` créé

### 6. Frontend (prompts Lovable)

Les 5 changements frontend nécessaires dans `docs/frontend-auth-prompts.md` :

| Prompt | Fichier | Ce qui change |
|--------|---------|---------------|
| 1 | AuthContext.tsx + LoginPage.tsx + App.tsx | Connexion Supabase Auth, état global |
| 2 | hermes.ts | Remplacer `X-Plaudia-Key` par `Authorization: Bearer <JWT>` |
| 3 | ProfilePanel.tsx | Infos utilisateur, déconnexion |
| 4 | ProjectsView.tsx | Partage de projets par email (UI + API) |
| 5 | — | Vérification RLS (optionnel) |

## Vérification

```bash
# Tester le backend
cd /opt/data/projects/plaudia/rag_backend
python3 -c "from main import app; print(f'{len([r for r in app.routes if hasattr(r,\"path\")])} routes')"
# → 50 routes (dont 5 nouvelles multi-user)

# Vérifier que check_shared_key n'existe plus
grep -c "check_shared_key" main.py
# → 0

# Vérifier get_service_owner_id restants (≤10)
grep -c "get_service_owner_id()" main.py
# → 7 (fonctions internes uniquement)
```

### 7. Admin-only user creation (23/07/2026, session 2)

Ajouté après demande de Martin : les utilisateurs ne doivent PAS pouvoir creer leur compte depuis le frontend. Martin crée lui-même les utilisateurs dans le dashboard Supabase.

**Solution finale :** Pas d'endpoint backend. Pas de formulaire frontend.
- Martin va dans Supabase → Authentication → Users → Add User (email + mot de passe)
- Le trigger `on_auth_user_created` crée automatiquement le `user_profiles` avec le rôle `"user"`
- Pour passer un user en admin : `UPDATE user_profiles SET role = 'admin' WHERE email = '...'`

**Frontend :** LoginPage = CONNEXION UNIQUEMENT (pas d'inscription, pas de toggle, message "Compte créé par votre administrateur")
- Lien "Mot de passe oublié ?" qui appelle `supabase.auth.resetPasswordForEmail()`
- Page `UpdatePasswordPage.tsx` (route `/update-password`) pour le changement de mot de passe après réception de l'email

**PITFALL — Variables VITE_CF_* à supprimer :** `VITE_CF_CLIENT_ID`, `VITE_CF_CLIENT_SECRET` et `VITE_PLAUDIA_SHARED_KEY` doivent être supprimées de l'environnement Lovable. Les variables VITE_* sont bundlées dans le JS client — n'importe qui peut les lire. L'auth passe uniquement par le JWT Supabase Auth. Le tunnel Cloudflare n'a pas besoin de secrets côté frontend.

## Problèmes connus

- Le MCP Supabase peut perdre son token d'accès (401 Unauthorized). Solution : exécuter la migration SQL directement dans l'éditeur SQL du dashboard Supabase.
- La signature JWT HMAC avec `SUPABASE_ANON_KEY` fonctionne mais n'est pas la méthode officielle Supabase (ils recommandent endpoint `auth/v1/user` pour validation). Si problèmes de signature, remplacer par un appel HTTP à `auth/v1/user` avec le token.
- **VITE_CF_CLIENT_SECRET expose dans le JS bundle** : toute variable VITE_* est bundlee dans le JavaScript client. Ne JAMAIS mettre de secrets dans les VITE_* (sauf URLs publiques). Solution : supprimer VITE_CF_CLIENT_ID et VITE_CF_CLIENT_SECRET du frontend, laisser Cloudflare gerer l'auth a l'edge.
