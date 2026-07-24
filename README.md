# Plaudia — Template de déploiement

Squelette vierge pour déployer Plaudia (système de comptes-rendus de réunion) sur un nouvel environnement.

## Architecture

```
                     ┌──────────────────────────────────┐
                     │       Frontend Lovable           │
                     │    (React + TypeScript)          │
                     │                                  │
                     │  ┌─ Lectures (GET) ──────────┐   │
                     │  │  → Supabase PostgREST     │   │
                     │  └───────────────────────────┘   │
                     │  ┌─ Écritures (POST/PATCH) ──┐   │
                     │  │  → Backend FastAPI        │   │
                     │  │    (via proxy callHermes) │   │
                     │  └───────────────────────────┘   │
                     └──────────┬───────────────────────┘
                                │
                     ┌──────────┴──────────┐
                     │  Cloudflare Tunnel   │
                     │  (cloudflared)       │
                     └──────────┬──────────┘
                                │
                     ┌──────────┴──────────┐
                     │  Backend FastAPI     │
                     │  (port 8000)         │
                     │                     │
                     │  • Auth JWT         │
                     │  • Chat RAG         │
                     │  • CR édition       │
                     │  • Export/Email     │
                     │  • Glossaire        │
                     └──────┬──────┬───────┘
                            │      │
                     ┌──────┘      └──────┐
                     ▼                    ▼
              ┌────────────┐      ┌────────────┐
              │  Supabase   │      │  Plaud API │
              │ (PostgreSQL)│      │ (watchdog) │
              └────────────┘      └────────────┘
```

## Structure du template

```
plaudia-template/
├── README.md                          # Ce fichier
├── setup-plaudia.sh                   # Script d'installation auto
├── .env.example                       # Modèle des variables d'env (placeholders)
├── deployment.md                      # Guide de déploiement complet
│
├── rag_backend/                       # Backend FastAPI
│   ├── main.py                        # 2689 lignes — tous les endpoints
│   ├── auth.py                        # JWT Supabase Auth
│   ├── chart_renderer.py              # SVG charts (svgwrite)
│   └── google_integration.py          # Export Docs + Gmail
│
├── scripts/                           # Scripts cron Hermes
│   ├── plaudia_watchdog.py            # Poll Plaud → INSERT recordings
│   ├── plaudia_keepalive.sh           # Maintient backend + tunnel
│   └── plaudia_tunnel_watchdog.sh     # Reconstruction auto tunnel
│
├── supabase/
│   ├── schema.sql                     # DDL + triggers + RPC + RLS
│   └── migrations/
│       └── 002_multi_user_rls.sql     # RLS policies + shares + triggers
│
├── skills/                            # Skills Hermes
│   ├── plaudia-orchestrator/
│   ├── plaudia-recording-pipeline/
│   └── plaudia-cr-backend/
│
└── docs/                              # Documentation
    ├── deployment-checklist.md        # 35 étapes de vérification
    ├── frontend-login-prompt.md       # Prompts Lovable pour l'auth JWT
    └── debug-guide.md                 # 9 bugs documentés
```

## Déploiement rapide

```bash
# 1. Cloner
git clone https://github.com/herone-dev/plaudia-template.git
cd plaudia-template

# 2. Configurer les variables
cp .env.example /opt/data/.env
nano /opt/data/.env  # Remplacer TOUS les placeholders

# 3. Exécuter le schéma Supabase
# Coller supabase/schema.sql dans l'éditeur SQL Supabase
# Puis migrations/002_multi_user_rls.sql

# 4. Installer
bash setup-plaudia.sh

# 5. Vérifier
curl http://localhost:8000/healthz
```

## Prérequis

- VPS Ubuntu 22.04+ avec Hermes installé
- Projet Supabase (gratuit)
- Compte Cloudflare (pour le tunnel)
- Compte Plaud.ai (abonnement avec API)
- Compte OpenAI (pour les embeddings + LLM)

## Principe : squelette vierge, pas de données client

Ce template ne contient **aucune donnée réelle** :
- `main.py` lit toutes les credentials depuis l'environnement
- `schema.sql` = pur DDL (CREATE TABLE, CREATE INDEX, CREATE FUNCTION)
- `.env.example` = placeholders uniquement
- Les skills Hermes sont génériques

## Maintenance

Un cron hebdomadaire (`plaudia-auto-update`) vérifie si une nouvelle version du template
est disponible sur GitHub. Si oui, il met à jour les scripts, les skills, et le backend
automatiquement. Voir la section "Mise à jour automatique" dans `deployment.md`.