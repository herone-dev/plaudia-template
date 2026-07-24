# Plaudia — Guide de déploiement (JWT Auth + CQRS + Proxy Lovable)

## 1. Créer le projet Supabase

1. Aller sur https://supabase.com → New project
2. Noter le **Project URL** et la **publishable anon key**
3. Copier `env.example` → `/opt/data/.env` et remplir les valeurs

### Extensions requises

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### Migrations

Exécuter dans l'ordre :

```bash
# 1. Schéma de base (DDL + triggers + RPC)
# Coller le contenu de supabase-schema.sql dans l'éditeur SQL Supabase

# 2. Migration multi-user (RLS + shares + project_shares)
# Coller le contenu de supabase/migrations/002_multi_user_rls.sql
```

### Créer les comptes utilisateurs

- Authentication → Users → Add User (pour chaque utilisateur)
- Pas d'inscription publique — Martin crée les comptes manuellement
- Le trigger `on_auth_user_created` crée automatiquement l'entrée `user_profiles`
- Pour passer un user en admin : `UPDATE user_profiles SET role = 'admin' WHERE email = '...'`

## 2. Déployer le backend FastAPI

### Prérequis

- Python 3.13+
- uv installé

### Installation

```bash
mkdir -p /opt/data/projects/plaudia
cp -r rag_backend/ /opt/data/projects/plaudia/rag_backend/
cd /opt/data/projects/plaudia/rag_backend
```

### Configuration

Le backend lit **toutes** ses credentials depuis l'environnement (plus de hardcode) :

```bash
# /opt/data/.env — source par le keepalive
source /opt/data/.env

# Variables REQUISES :
# SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_EMAIL,
# SUPABASE_SERVICE_PASSWORD, OPENAI_API_KEY, PLAUDIA_SHARED_KEY
```

### Démarrage

```bash
# Dev
/opt/hermes/.venv/bin/python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Prod (4 workers) — le keepalive le gère automatiquement
/opt/hermes/.venv/bin/python -m uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000
```

### Vérification

```bash
curl http://localhost:8000/healthz  # → {"status":"ok"}
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['paths']), 'routes')"  # → 45+
```

## 3. Configurer les crons Hermes

### Copier les scripts

```bash
mkdir -p /opt/data/.hermes/scripts
cp scripts/* /opt/data/.hermes/scripts/
```

### Créer les crons

```bash
# Keepalive (backend + tunnel — toutes les minutes)
hermes cron create --name plaudia-keepalive --schedule "* * * * *" --script plaudia_keepalive.sh --no-agent

# Watchdog (poll Plaud — toutes les 5 min)
hermes cron create --name plaudia-watchdog-free --schedule "*/5 * * * *" --script plaudia_watchdog.py --no-agent

# Pipeline (génération CR — quotidienne midi)
hermes cron create --name plaudia-pipeline-principal --schedule "0 12 * * *" --skill plaudia-recording-pipeline

# Refresh vue matérialisée enterprise_counts (toutes les 15 min)
hermes cron create --name plaudia-refresh-enterprise-counts --schedule "*/15 * * * *" --script plaudia_refresh_enterprise_counts.py --no-agent

# Watchdog tunnel (reconstruction auto — 6h tous les jours)
hermes cron create --name plaudia-tunnel-watchdog --schedule "0 6 * * *" --script plaudia_tunnel_watchdog.sh --no-agent
```

## 4. Configurer le tunnel Cloudflare

```bash
# Config
mkdir -p /opt/data/.cloudflared
```

Créer `/opt/data/.cloudflared/config.yml` :

```yaml
tunnel: plaudia-tunnel
credentials-file: /opt/data/.cloudflared/<uuid>.json
ingress:
  - hostname: plaudia-api.votre-domaine.app
    service: http://localhost:8000
  - service: http_status:404
```

```bash
# Créer le tunnel
cloudflared tunnel create plaudia-tunnel
cloudflared tunnel route dns plaudia-tunnel plaudia-api.votre-domaine.app

# Démarrer
cloudflared tunnel run --token <eyJ...token>
```

### Optionnel : Service Token Cloudflare Access

Si le frontend reçoit 403 "Cloudflare Access" :

1. Dashboard Cloudflare → Zero Trust → Access → Service Auth → Add Service Token
2. Ajouter le token à la policy Access de l'application
3. Stocker dans Lovable (secrets serveur) : `CF_CLIENT_ID`, `CF_CLIENT_SECRET`

## 5. Configurer Plaud MCP (watchdog)

1. Aller sur https://app.plaud.ai/settings → Integrations → New Integration
2. Créer une integration MCP, noter le refresh token
3. Stocker dans `/opt/data/mcp-tokens/plaudai.json`

## 6. Configurer Google OAuth (optionnel — export Docs + Gmail)

1. Créer un projet Google Cloud Console
2. Activer : Google Docs, Google Drive, Gmail API
3. Créer un OAuth 2.0 Client ID avec les bons scopes
4. Enregistrer le token dans `/opt/data/google_token.json`

## 7. Déployer le frontend Lovable

1. Créer un nouveau projet Lovable
2. Connecter le dépôt GitHub du frontend
3. Déclarer les **secrets serveur** (Settings → Secrets) :
   - `PLAUDIA_BACKEND_URL` = URL du tunnel
   - `PLAUDIA_SHARED_KEY` = clé générée avec `openssl rand -hex 32`
   - `CF_CLIENT_ID` = (si Access activé)
   - `CF_CLIENT_SECRET` = (si Access activé)
4. Déclarer les **variables publiques** (Settings → Environment Variables) :
   - `VITE_HERONE_SUPABASE_URL` = Project URL
   - `VITE_HERONE_SUPABASE_PUBLISHABLE_KEY` = anon key
5. Créer `callHermes` server function (SANS `requireSupabaseAuth`)
6. Créer AuthContext + LoginPage (login seul, pas d'inscription)
7. Utiliser `getAuthHeaders()` pour injecter le JWT dans les appels API

## 8. Vérification finale

```bash
# Backend local
curl http://localhost:8000/healthz
# → {"status":"ok"}

# Tunnel
curl https://plaudia-api.votre-domaine.app/healthz
# → {"status":"ok"}

# Crons
hermes cron list
# → 5 crons actifs

# API avec JWT
curl -H "Authorization: Bearer <jwt>" https://plaudia-api.votre-domaine.app/v1/auth/me
# → {"user_id":"...", "email":"...", "role":"..."}
```

## Architecture CQRS

```
Frontend (Lovable)
  ├── Lectures (GET) → Supabase PostgREST direct
  │                    (enterprises, crs, projects, etc.)
  └── Écritures (POST/PATCH/DELETE) → Backend FastAPI via proxy callHermes
                                       (chat, validate, restore, email, glossary, etc.)

Backend FastAPI
  ├── Auth JWT Supabase (Authorization: Bearer ***)
  ├── Service account pour les crons (pipeline, watchdog)
  └── Fallback PLAUDIA_SHARED_KEY pour la transition

Crons Hermes (no_agent)
  ├── Watchdog (5min) → Plaud API → INSERT recordings
  ├── Pipeline (midi) → LLM → INSERT crs
  ├── Keepalive (1min) → maintient backend + tunnel
  └── Refresh counts (15min) → REFRESH MATERIALIZED VIEW enterprise_counts
```