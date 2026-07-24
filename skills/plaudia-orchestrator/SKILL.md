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
- **Maintenir et corriger les bugs de l'app Plaudia en autonomie**

## Diagnostic automatique (maintenance autonome)

Quand un problème est détecté (cron échoué, endpoint 404, watchdog silencieux) :

1. **Lire cette skill** — `skill_view(name='plaudia-orchestrator')` charge toute l'architecture
2. **Charger les skills associées** — `skill_view(name='plaudia-recording-pipeline')` pour le pipeline,
   `skill_view(name='plaudia-cr-backend')` pour le backend
3. **Vérifier les logs** — `hermes cron list` → `cronjob(action='run', job_id='...')`
4. **Tester le backend** — `curl localhost:8000/healthz` puis `openapi.json` (45+ routes attendues)
5. **Vérifier Supabase** — `mcp_supabase_get_advisors()`, `mcp_supabase_execute_sql()`
6. **Appliquer les correctifs** — modifier `main.py`, `auth.py`, directement dans
   `/opt/data/projects/plaudia/rag_backend/`
7. **Attendre le keepalive** — le cron redémarre le backend sous 60s
8. **Commit les correctifs dans le template GitHub** — `git -C /opt/data/projects/plaudia/docs/template add -A && git commit && git push`
9. **Documenter les bugs** dans `docs/debug-guide.md` du template

### Règles de maintenance

- **Ne JAMAIS toucher** aux credentials (`.env`, `mcp-tokens/`, `google_token.json`)
- **Toujours tester d'abord localement** avant de supposer un problème de tunnel
- **Toujours suivre la chaîne upstream** : watchdog → DB → trigger → CR (pas l'inverse)
- **Les skills sont la source de vérité** — si obsolète, patcher avec `skill_manage(action='patch')`
- **Le template GitHub est la source de vérité du déploiement** — tout correctif backend doit y être pushé
- **Le cron `plaudia-auto-update`** (dimanche 3h) propage les mises à jour aux autres VPS automatiquement

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

## État du template de déploiement (24/07/2026)

Le template sur `herone-dev/plaudia-template` est **à jour** et contient :

| Fichier | Statut |
|---------|--------|
| `rag_backend/main.py` | ✅ Plus de hardcode — `owner_id` dynamique via `get_service_owner_id()` |
| `rag_backend/auth.py` | ✅ JWT Supabase Auth |
| `rag_backend/chart_renderer.py` | ✅ SVG charts (svgwrite) |
| `rag_backend/google_integration.py` | ✅ Export Docs + Gmail |
| `scripts/` | ✅ 4 scripts (watchdog, keepalive, tunnel watchdog, refresh counts, auto-update) |
| `skills/` | ✅ 3 skills Hermes |
| `supabase-schema.sql` | ✅ DDL + triggers + RPC + RLS + `is_system` flag |
| `supabase/migrations/002_multi_user_rls.sql` | ✅ RLS policies + shares + triggers |
| `docs/deployment-checklist.md` | ✅ 35 étapes |
| `docs/debug-guide.md` | ✅ 9 bugs documentés |
| `docs/frontend-login-prompt.md` | ✅ Prompts Lovable pour auth JWT |
| `env.example` | ✅ Placeholders uniquement, plus de secrets |
| `setup-plaudia.sh` | ✅ Paramétrable, plus de refs spécifiques à Martin |
| `deployment.md` | ✅ Guide complet avec JWT + proxy + auto-update + maintenance autonome |

### Mise à jour automatique (weekly)

Un cron **plaudia-auto-update** (`d79673e55e0c`) vérifie chaque dimanche à 3h si une
nouvelle version du template est disponible sur GitHub. Si oui, il met à jour :
- Le backend (`rag_backend/main.py`, `auth.py`, etc.)
- Les scripts cron
- Les skills Hermes

**Ce qui NE change PAS :** credentials (`.env`), config tunnel, tokens, données.

### Maintenance autonome

Le backend Hermes sur le VPS est capable de maintenir et corriger les bugs de
l'app Plaudia en autonomie. Voir la section "Maintenance autonome" dans `deployment.md`
du template, ou la section "Diagnostic automatique" ci-dessous.

### Crons actifs

| Nom | Schedule | Script | Rôle |
|-----|----------|--------|------|
| `plaudia-keepalive` | `* * * * *` | `plaudia_keepalive.sh` | Maintient backend + tunnel |
| `plaudia-watchdog-free` | `*/5 * * * *` | `plaudia_watchdog.py` | Poll Plaud → INSERT recordings |
| `plaudia-pipeline-principal` | `0 12 * * *` | LLM (skill) | Génération CR |
| `plaudia-refresh-enterprise-counts` | `*/15 * * * *` | `plaudia_refresh_enterprise_counts.py` | Refresh vue matérialisée |
| `plaudia-tunnel-watchdog` | `0 6 * * *` | `plaudia_tunnel_watchdog.sh` | Reconstruction auto tunnel |
| `plaudia-auto-update` | `0 3 * * 0` | `plaudia_auto_update.py` | Vérification hebdo template GitHub |

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
mcp_supabase_get_advisors(project_id='VOTRE_PROJET_ID', type='security')
mcp_supabase_get_advisors(project_id='VOTRE_PROJET_ID', type='performance')
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
