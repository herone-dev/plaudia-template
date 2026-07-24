---
name: plaudia-orchestrator
description: Skill chef d'orchestre pour un nouvel Hermes Plaudia — installation, crons, dépendances, architecture globale.
---

# Plaudia Orchestrator — Installation et maintenance

## Quand cette skill s'applique

Tu viens d'arriver sur un VPS avec Hermes tout neuf. Tu dois :
- Installer et configurer Plaudia
- Recréer les crons (keepalive, watchdog, pipeline)
- Vérifier que tout tourne
- Diagnostiquer un problème

## Dépendances

- **Backend Python** : `/opt/data/projects/plaudia/rag_backend/main.py` + `auth.py`
- **Frontend** : Projet Lovable connecté à `herone-dev/plaudia-v1-martin`
- **Scripts Hermes** : `plaudia_watchdog.py`, `plaudia_keepalive.sh` dans `/opt/data/.hermes/scripts/`
- **Google OAuth** : `/opt/data/google_token.json`
- **Plaud MCP** : Token OAuth dans `/opt/data/mcp-tokens/plaudai.json` (watchdog uniquement)
- **Supabase** : Projet avec Auth activé (email + mot de passe)

## Auth multi-utilisateur (23/07/2026)

Le backend utilise désormais Supabase Auth JWT au lieu d'une clé partagée.

### Installation

```bash
# 1. Cloner le template
cd /opt/data
git clone https://github.com/herone-dev/plaudia-template.git
cp -r plaudia-template/rag_backend/* /opt/data/projects/plaudia/rag_backend/

# 2. Variables d'environnement (dans /opt/data/.env)
# VOIR .env.example dans le template
# REQUISES :
#   SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_EMAIL,
#   SUPABASE_SERVICE_PASSWORD, OPENAI_API_KEY, OPENROUTER_API_KEY
# OPTIONNELLES :
#   PLAUDIA_SHARED_KEY (fallback pour les crons)

# 3. Migration SQL
# Exécuter supabase/schema.sql dans l'éditeur SQL Supabase
# Exécuter supabase/migrations/002_multi_user_rls.sql

# 4. Créer le premier admin
# Aller dans Supabase Dashboard → Authentication → Users → Add User
# Puis dans SQL Editor : UPDATE user_profiles SET role = 'admin' WHERE email = '...';

# 5. Keepalive (doit exporter les bonnes variables)
# Vérifier que le script exporte SUPABASE_URL SUPABASE_ANON_KEY etc.
```

### Variables d'env REQUISES dans /opt/data/.env

```env
SUPABASE_URL=https://votre-projet.supabase.co
SUPABASE_ANON_KEY=eyJhbG...votre_cle_anon
SUPABASE_SERVICE_EMAIL=admin@votre-boite.fr
SUPABASE_SERVICE_PASSWORD=...
OPENAI_API_KEY=sk-pro-...
OPENROUTER_API_KEY=sk-or-...
PLAUDIA_SHARED_KEY=Vs4fc... (fallback crons)
```

### Vérification

```bash
# Backend
curl http://localhost:8000/healthz  # → {"status":"ok"}

# Auth (sans JWT → 401 normal)
curl -w "%{http_code}" http://localhost:8000/v1/auth/me  # → 401

# Auth (avec shared key → 200)
curl -w "%{http_code}" http://localhost:8000/v1/auth/me \
  -H "x-plaudia-key: VOTRE_CLE"

# CRs
curl -w "%{http_code}" http://localhost:8000/v1/crs \
  -H "x-plaudia-key: VOTRE_CLE"  # → 200
```

## Installation

### 1. Cloner les dépôts

```bash
cd /opt/data
git clone https://github.com/herone-dev/plaudia-v1-martin.git
git clone https://github.com/herone-dev/plaudia.git /opt/data/projects/plaudia
```

### 2. Copier les scripts cron

```bash
cp /opt/data/projects/plaudia/scripts/plaudia_watchdog.py /opt/data/.hermes/scripts/
cp /opt/data/projects/plaudia/scripts/plaudia_keepalive.sh /opt/data/.hermes/scripts/
```

### 3. Créer les crons

```bash
# Keepalive (toutes les minutes)
hermes cron create --name plaudia-keepalive --schedule "* * * * *" \
  --script plaudia_keepalive.sh --no-agent

# Watchdog Plaud (toutes les 5 min)
hermes cron create --name plaudia-watchdog-free --schedule "*/5 * * * *" \
  --script plaudia_watchdog.py --no-agent

# Pipeline CR (tous les jours à midi)
hermes cron create --name plaudia-pipeline-principal --schedule "0 12 * * *" \
  --skill plaudia-recording-pipeline \
  --model deepseek/deepseek-v4-flash --provider openrouter

# Refresh vue matérialisée enterprise_counts (toutes les 15 min)
hermes cron create --name plaudia-refresh-enterprise-counts --schedule "*/15 * * * *" \
  --script plaudia_refresh_enterprise_counts.py --no-agent
```

### 4. Démarrer le backend

```bash
cd /opt/data/projects/plaudia/rag_backend
source /opt/data/.env 2>/dev/null
nohup /opt/hermes/.venv/bin/python -m uvicorn main:app --workers 4 \
  --host 0.0.0.0 --port 8000 > /opt/data/plaudia_backend.log 2>&1 &
```

### 5. Configurer les variables d'environnement (dans /opt/data/.env puis rag_backend/.env)

**Variables REQUISES (depuis la migration multi-user du 23/07/2026) :**

```env
# === Supabase (REQUIS — plus de hardcode dans main.py) ===
SUPABASE_URL=https://votre-projet.supabase.co
SUPABASE_ANON_KEY=eyJhbG...  # Settings > API > anon/public key
SUPABASE_SERVICE_EMAIL=admin@votre-boite.fr  # User auth Supabase
SUPABASE_SERVICE_PASSWORD=...  # Mot de passe du service account

# === LLM ===
OPENAI_API_KEY=sk-pro-...       # Embeddings RAG (+ LLM fallback)
OPENROUTER_API_KEY=sk-or-...    # LLM DeepSeek (optionnel)

# === Backend ===
PLAUDIA_SHARED_KEY=...          # Fallback pour crons uniquement (openssl rand -hex 32)
```

**Où les mettre :**
1. `/opt/data/.env` — source par le keepalive script
2. `/opt/data/projects/plaudia/rag_backend/.env` — utilisé par le service systemd `plaudia-backend.service`

**PITFALL — Variables manquantes = 500 sur les endpoints.** `auth.py` lit `SUPABASE_URL`, `SUPABASE_ANON_KEY`, etc. depuis l'environnement. Si l'une manque, `get_service_token()` construit une URL relative `/auth/v1/token?...` → `ValueError: unknown url type`. Vérifier avec :

```bash
# Tester que le backend charge les bonnes routes (45+ attendues)
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['paths']), 'routes')"
```

### 6. Mettre à jour le keepalive script

Le script `/opt/data/.hermes/scripts/plaudia_keepalive.sh` doit exporter les nouvelles variables Supabase :

```bash
export SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_EMAIL SUPABASE_SERVICE_PASSWORD OPENAI_API_KEY ANTHROPIC_API_KEY PLAUDIA_SHARED_KEY
```

### 7. Configurer Plaud MCP (pour le watchdog)

Créer `/opt/data/mcp-tokens/plaudai.json` avec le refresh token OAuth Plaud.

### 8. Vérifier

```bash
# Backend
curl http://localhost:8000/healthz  # → {"status":"ok"}

# Routes (45+ attendues depuis migration multi-user)
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['paths']), 'routes')"

# Auth endpoint
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/v1/auth/me  # → 401 (normal, nécessite JWT)

# Cron jobs
hermes cron list

# Supabase
mcp_supabase_execute_sql(project_id="...", query="SELECT count(*) FROM recordings")
```

## Architecture résumée

```
Watchdog (5min) ──► Plaud API ──► INSERT recordings
Pipeline (midi) ──► DeepSeek ──► INSERT crs
Backend ──► Écritures API ──► Supabase
Frontend (Lovable) ──► proxy serveur ──► Cloudflare tunnel ──► Backend
```

## Auth architecture (mise à jour 23/07/2026 — JWT Supabase Auth)

**Changement principal :** Le `PLAUDIA_SHARED_KEY` et les variables `VITE_CF_*` ont été **supprimés du frontend**. L'authentification passe uniquement par **JWT Supabase Auth** :

```
Frontend                         Backend                    Supabase
   |                               |                          |
   |-- Login (email + mdp) ------> |                          |
   |                               |-- POST /auth/v1/token -->|
   |<--- JWT (access_token) -------|<-------------------------|
   |                               |                          |
   |-- API call (JWT Bearer) ----> |                          |
   |                               |-- REST (même JWT) ------>|
   |                               |    (RLS filtre par user) |
   |<--- données filtrées ---------|<-------------------------|
```

**Détail :**
1. L'utilisateur se connecte avec email + mot de passe (login uniquement — pas d'inscription)
2. Supabase Auth renvoie un JWT
3. Le frontend envoie le JWT dans `Authorization: Bearer <token>` (plus de `X-Plaudia-Key`)
4. Le backend valide le JWT avec `get_current_user(request)` (fonction dans `auth.py`)
5. Le backend utilise le JWT de l'utilisateur pour appeler Supabase → RLS filtre par `auth.uid()`
6. Les crons (pipeline, watchdog) utilisent toujours le service account (`PLAUDIA_SHARED_KEY` en fallback)

**Fichiers clés :**
- `rag_backend/auth.py` — validation JWT HMAC, extraction user context, service account
- `rag_backend/main.py` — `get_current_user()` remplace `check_shared_key()` partout
- `supabase/migrations/002_multi_user_rls.sql` — RLS policies sur toutes les tables

**Ce qui a été supprimé :**
- `VITE_CF_CLIENT_ID` (n'était plus dans le bundle JS)
- `VITE_CF_CLIENT_SECRET` (n'était plus dans le bundle JS)
- `VITE_PLAUDIA_SHARED_KEY` (remplacé par le JWT)
- Le frontend n'envoie plus de secrets — juste le JWT

**Nouveaux endpoints :**
| Endpoint | Description |
|----------|-------------|
| `GET /v1/auth/me` | Profil de l'utilisateur connecté (rôle, email, nom) |
| `POST /v1/projects/{id}/share` | Partager un projet par email |
| `DELETE /v1/projects/{id}/share/{share_id}` | Supprimer un partage |
| `GET /v1/projects/{id}/shares` | Lister les partages d'un projet |
| `GET /v1/shares/me` | Lister les projets partagés avec moi |

**Création d'utilisateurs :** Martin crée les comptes manuellement dans le dashboard Supabase (Authentication → Users → Add User). Pas d'inscription depuis le frontend, pas d'endpoint backend. Le trigger `on_auth_user_created` crée automatiquement l'entrée dans `user_profiles`.

**PITFALL — .venv local vs hermes venv.** Le service systemd `plaudia-backend.service` pointe vers `.venv/bin/uvicorn`. Si ce .venv local contient une copie périmée de `main.py` et `auth.py`, le backend retourne 404 sur les nouveaux endpoints. Voir Troubleshooting → Backend retourne 404 sur les nouveaux endpoints.

Voir `references/cloudflare-tunnel-setup.md` pour la configuration complète du tunnel et de Cloudflare Access.

## Architecture multi-client

**Décision d'architecture (Martin, 22/07/2026) :** Pas de multi-tenant dans un seul Lovable. Pas de `clients.ts`, pas de routing dynamique, pas de `localStorage`.

À chaque nouveau client :
1. Dupliquer le projet Lovable (même code, env vars différentes)
2. Créer un VPS dédié
3. Créer un projet Supabase dédié
4. Le kit Hermes fournit les prompts Lovable prêts à coller pour configurer les secrets/env vars

Chaque projet Lovable a son URL fixe, son Supabase fixe, son backend fixe. Zéro complexité d'auth croisée. Le template de déploiement (`references/deployment-github.md`) guide le setup.

## PITFALLS DÉPLOIEMENT — Bloqueurs pour un nouvel environnement

### P0 — `main.py` hardcode un `owner_id` spécifique à Martin

**Où :** `rag_backend/main.py` lignes 689, 708, 719 — l'UUID `79d6876b-bc72-424b-8c23-8c485eaa1b57` (Martin) est écrit en dur dans `load_style_guide()` et `learn_from_edit()`.

**Symptôme sur un nouvel environnement :** Le style guide et l'apprentissage automatique échouent silencieusement (les requêtes Supabase ciblent un owner_id qui n'existe pas).

**Fix AVANT déploiement :**
```python
# Remplacer les 3 occurrences par get_service_owner_id()
# ligne 689 : owner_id=eq.{get_service_owner_id()}
# ligne 708 : "owner_id": get_service_owner_id(),
# ligne 719 : def load_style_guide(owner_id: str = None):
#     if owner_id is None: owner_id = get_service_owner_id()
```

### P0 — `env.example` contient des secrets de production

**Où :** `docs/template/env.example` — contient les vraies valeurs de l'environnement Martin :
- `VITE_PLAUDIA_SHARED_KEY=Vs4fcBFp_...` (clé partagée réelle)
- `VITE_HERONE_SUPABASE_URL=https://ezqbxfmafvdjtgrrxcxy.supabase.co` (URL Supabase réelle)
- `PLAUDIA_SERVICE_PASSWORD=Herone2026test` (mot de passe réel)

**Risque :** Fuite de credentials si le template est partagé ou forké.

**Fix :** Remplacer TOUTES les valeurs réelles par des placeholders du type `à_remplacer`, `votre-projet.supabase.co`, `sk-pro-...`, `openssl_rand_-hex_32`.

### P1 — Le template GitHub n'est pas à jour

**Problème :** Le repo `herone-dev/plaudia-template` existe sur GitHub (HTTP 200) mais les fichiers locaux dans `/opt/data/projects/plaudia/docs/template/` n'ont **jamais été pushés**. Le repo est vide ou contient une version antérieure.

**En conséquence, la commande `git clone https://github.com/herone-dev/plaudia-template.git` ne récupère pas les bons fichiers.** Avant de déployer sur un nouveau client :
1. Copier les fichiers manquants dans le template :
   - `rag_backend/` (main.py, auth.py, chart_renderer.py, google_integration.py)
   - `scripts/` (plaudia_watchdog.py, plaudia_keepalive.sh, plaudia_tunnel_watchdog.sh, plaudia_refresh_enterprise_counts.py)
   - `skills/` (les 3 dossiers)
   - `supabase/migrations/002_multi_user_rls.sql`
2. Créer les docs manquants :
   - `docs/deployment-checklist.md` (15 étapes)
   - `docs/debug-guide.md` (9 bugs documentés)
   - `docs/frontend-login-prompt.md` (prompts Lovable pour auth JWT)
3. Push sur `herone-dev/plaudia-template`

### P1 — `setup-plaudia.sh` est spécifique à Martin

**Problème :** Le script clone `https://github.com/herone-dev/plaudia-v1-martin.git` — un repo privé qui n'existe pas pour un nouveau client.

**Fix :** Remplacer par `git clone https://github.com/herone-dev/plaudia-template.git` (après avoir pushé le template à jour). Si le client a son propre fork, paramétrer l'URL en variable.

### P1 — RLS policies absentes du schema.sql

**Problème :** `supabase-schema.sql` contient le DDL complet (CREATE TABLE, CREATE INDEX, CREATE FUNCTION) mais **zéro RLS policy**. Un nouveau déploiement a une base ouverte.

**Fix :** Ajouter dans le schema.sql :
```sql
ALTER TABLE enterprises ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE recordings ENABLE ROW LEVEL SECURITY;
ALTER TABLE crs ENABLE ROW LEVEL SECURITY;
-- ... (toutes les tables)
CREATE POLICY "owner_all" ON enterprises FOR ALL USING (owner_id = auth.uid());
-- ... (policy par table, voir 002_multi_user_rls.sql)
```

## Troubleshooting

### Backend retourne 404 sur les nouveaux endpoints (mais 200 sur healthz)

**Cause :** Le service systemd `plaudia-backend.service` utilise `.venv/bin/uvicorn` (un venv local au projet) qui a une version périmée de `main.py` et `auth.py`. Le fichier `.venv/lib/python*/site-packages/` peut contenir des caches compilés obsolètes.

**Symptômes :**
- `curl localhost:8000/healthz` → 200 OK
- `curl localhost:8000/v1/auth/me` → 404
- `curl localhost:8000/openapi.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['paths']), 'paths')"` → 31 (au lieu de 45+)

**Diagnostic :**
```bash
python3 -c "
import os
with open('/proc/net/tcp') as f:
    for line in f:
        if ':1F40' in line:
            inode = line.split()[9]
            for pid in os.listdir('/proc'):
                if pid.isdigit():
                    for fd in os.listdir(f'/proc/{pid}/fd'):
                        try:
                            link = os.readlink(f'/proc/{pid}/fd/{fd}')
                            if f'socket:[{inode}]' in link:
                                cmd = open(f'/proc/{pid}/cmdline').read().replace(chr(0), ' ').strip()
                                print(f'PID {pid}: {cmd[:200]}')
                        except: pass
"
```

Si le chemin contient `.venv`, tuer ce PID et redémarrer avec le bon Python :
```bash
kill <PID>
cd /opt/data/projects/plaudia/rag_backend
/opt/hermes/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

**Correction définitive :** Modifier `plaudia-backend.service` pour pointer vers `/opt/hermes/.venv/bin/uvicorn` au lieu de `.venv/bin/uvicorn`.
Le keepalive (`plaudia-keepalive`, toutes les minutes) le relance automatiquement. Vérifier :
```bash
curl http://localhost:8000/healthz   # → {"status":"ok"}
```

### Tunnel Cloudflare — diagnostiquer 403 (Access) vs vrai problème backend
Quand le frontend (Lovable) signale une erreur, le coupable est souvent Cloudflare Access, pas le backend. Protocole de diagnostic :

```bash
# 1. Backend local (toujours tester en premier)
source /opt/data/.env
curl -s -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" http://localhost:8000/<endpoint>

# 2. Tunnel public
curl -s -o /dev/null -w "HTTP %{http_code}" \
  -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" \
  https://plaudia-api.herone.app/<endpoint>
```

**Résultats possibles :**
| Local | Tunnel | Cause |
|-------|--------|-------|
| ✅ 200 | ✅ 200 | Tout va bien |
| ✅ 200 | ❌ 403 HTML (`Error · Cloudflare Access`) | **Cloudflare Access bloque** — le proxy Lovable doit envoyer `CF-Access-Client-Id` + `CF-Access-Client-Secret` |
| ✅ 200 | ❌ 502/503 | Tunnel mort ou mal configuré (vérifier `ps aux \| grep cloudflared`) |
| ❌ Erreur | ❌ Erreur | Backend mort (keepalive le relance sous 1 min) |

**Le tunnel utilise `--token` (Argo Tunnel token)** : pas de fichier `cert.pem`, pas de tunnel statique nommé. La config est dans `/opt/data/.cloudflared/config.yml` :
```yaml
tunnel: plaudia-tunnel
credentials-file: /opt/data/.cloudflared/<uuid>.json
ingress:
  - hostname: plaudia-api.herone.app
    service: http://localhost:8000
  - service: http_status:404
```

### Cloudflare Access — 403 « Error · Cloudflare Access »

**Depuis la migration multi-user (23/07) :** Les secrets Cloudflare ne sont plus envoyés depuis le frontend (`VITE_CF_CLIENT_ID` et `VITE_CF_CLIENT_SECRET` ont été supprimés). L'auth passe par le JWT Supabase Auth.

**Si le tunnel bloque encore :**
- Vérifier que le tunnel utilise Zero Trust avec une application protégée
- SOIT le tunnel est ouvert (pas de Zero Trust) → l'app gère seule l'auth via JWT
- SOIT le tunnel est protégé → le backend doit être accessible via un token de service Cloudflare (voir `references/cloudflare-tunnel-setup.md`)

**Pour laisser le tunnel sans auth Cloudflare (option recommandée pour les déploiements clients) :**
1. Aller sur `https://one.dash.cloudflare.com` → Zero Trust → Access → Applications
2. Supprimer la règle d'accès pour l'application `plaudia-api.herone.app` (ou désactiver)
3. Le tunnel laisse passer tout le trafic → l'app gère l'auth via JWT Supabase

### 405 Method Not Allowed — vrai ou faux ?
Si le frontend signale un 405, toujours vérifier d'abord localement. Le 405 peut être :
- **Vrai** : l'endpoint n'existe pas dans `main.py` (vérifier avec `grep '@app\.\(get\|post\|patch\|delete\)' rag_backend/main.py`)
- **Faux** : le proxy Lovable interprète mal la réponse d'erreur (403 Cloudflare Access → HTML → le proxy peut le lire comme 405)

### Watchdog ne trouve rien
Vérifier le token Plaud dans `/opt/data/mcp-tokens/plaud.json` (refresh token OAuth). Si expiré, le watchdog log une erreur.

### Pipeline silencieux
Le cron répond `[SILENT]` si aucun `recording.status='transcribed'` avec `enterprise_id IS NOT NULL`. Vérifier :
```sql
SELECT id, status, enterprise_id, title FROM recordings WHERE status = 'transcribed' ORDER BY created_at DESC;
```
Si `enterprise_id IS NULL`, le pipeline ignore l'enregistrement — l'attribuer d'abord via le frontend.

### Compteurs entreprises bloqués
Vérifier que le cron `plaudia-refresh-enterprise-counts` est actif :
```bash
hermes cron list | grep enterprise-counts
```
Forcer un refresh manuel dans Supabase :
```sql
REFRESH MATERIALIZED VIEW enterprise_counts;
```

### Erreur Supabase
```bash
mcp_supabase_get_advisors(project_id='ezqbxfmafvdjtgrrxcxy', type='security')
mcp_supabase_get_advisors(project_id='ezqbxfmafvdjtgrrxcxy', type='performance')
```
- **Erreur Supabase** : `mcp_supabase_get_advisors(project_id, 'security')` pour voir les policies

### Lovable server function bloquée par requireSupabaseAuth (401)

**Symptôme :** `Error: Unauthorized: No authorization header provided` dans `auth-middleware.ts` (auto-généré par Lovable). Blank screen côté front.

**Cause :** Le middleware `requireSupabaseAuth` (TanStack Start) valide le JWT Supabase depuis le header `Authorization` de la requête HTTP. S'applique à **toutes** les server functions — y compris le proxy Hermes qui n'en a pas besoin.

**Principe :** Le backend Hermes valide lui-même l'auth via `X-Plaudia-Key` + Cloudflare Access. Le proxy n'a pas besoin de vérifier le JWT Supabase.

**Solution :** Créer la server function `callHermes` SANS le middleware `requireSupabaseAuth`. Prompt Lovable :

```
Créer src/lib/hermes-proxy.functions.ts :
import { createServerFn } from "@tanstack/react-start";
import { getRequest } from "@tanstack/react-start/server";

export const callHermes = createServerFn({ method: "POST" })
  .handler(async ({ data }) => {
    const request = getRequest();
    const backendUrl = process.env.PLAUDIA_BACKEND_URL;
    const headers = new Headers();
    headers.set("Content-Type", "application/json");
    headers.set("X-Plaudia-Key", process.env.PLAUDIA_SHARED_KEY);
    headers.set("CF-Access-Client-Id", process.env.CF_CLIENT_ID);
    headers.set("CF-Access-Client-Secret", process.env.CF_CLIENT_SECRET);
    const authHeader = request.headers.get("authorization");
    if (authHeader) headers.set("Authorization", authHeader);
    const response = await fetch(`${backendUrl}${data.path}`, {
      method: data.method || "POST",
      headers,
      body: data.body ? JSON.stringify(data.body) : undefined,
    });
    return { status: response.status, body: await response.text() };
  });
```

Puis déclarer les secrets dans Lovable (pas en VITE_*, côté serveur) :
- `PLAUDIA_BACKEND_URL` (serveur)
- `PLAUDIA_SHARED_KEY` (serveur)
- `CF_CLIENT_ID` (serveur)
- `CF_CLIENT_SECRET` (serveur)

**PITFALL** : Ne JAMAIS mettre les secrets CF/backend en `VITE_*` — ils fuient dans le bundle JS public.
