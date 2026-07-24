# Plaudia — Déploiement via GitHub Template

## Repo template

**URL** : `https://github.com/herone-dev/plaudia-template`

**✅ TEMPLATE À JOUR (24/07/2026).** Le repo contient 54 fichiers, pushés depuis l'environnement de production.

### Contenu du template

```
plaudia-template/
├── README.md                    # Instructions complètes
├── setup-plaudia.sh             # Script d'installation auto (paramétrable)
├── .env.example                 # Modèle des variables d'env (placeholders uniquement)
├── deployment.md                # Guide déploiement complet + maintenance autonome
├── rag_backend/                 # Backend FastAPI
│   ├── main.py                  # Toutes les credentials lues depuis l'env (plus de hardcode)
│   ├── auth.py                  # JWT Supabase Auth
│   ├── chart_renderer.py        # SVG charts (svgwrite)
│   └── google_integration.py    # Export Docs + Gmail
├── scripts/                     # Scripts cron Hermes (5 scripts)
│   ├── plaudia_watchdog.py
│   ├── plaudia_keepalive.sh
│   ├── plaudia_tunnel_watchdog.sh
│   ├── plaudia_refresh_enterprise_counts.py
│   └── plaudia_auto_update.py
├── supabase/
│   └── schema.sql               # DDL + triggers + RPC + RLS + is_system
│   └── migrations/
│       └── 002_multi_user_rls.sql  # RLS policies + shares + triggers
├── skills/                      # Skills Hermes (3 skills)
│   ├── plaudia-orchestrator/
│   ├── plaudia-recording-pipeline/
│   └── plaudia-cr-backend/
└── docs/                        # Documentation
    ├── deployment-checklist.md  # 35 étapes de vérification
    ├── debug-guide.md           # 9 bugs documentés
    └── frontend-login-prompt.md # Prompts Lovable pour auth JWT
```

## Utilisation

Sur un nouvel Hermes :

```bash
git clone https://github.com/herone-dev/plaudia-template.git
cd plaudia-template
cp .env.example /opt/data/.env
# Éditer /opt/data/.env avec VOS vraies clés
bash setup-plaudia.sh
```

## Mise à jour automatique

Un cron **plaudia-auto-update** (dimanche 3h) vérifie les mises à jour du template
et les applique automatiquement. Voir `deployment.md` section 9.

## Principe : squelette vierge, pas de données client

Le template ne contient **aucune donnée réelle** :
- `main.py` lit toutes les credentials depuis l'environnement (pas de valeurs hardcodées)
- `schema.sql` = uniquement du DDL (CREATE TABLE, CREATE INDEX, CREATE FUNCTION) — pas de INSERT
- `.env.example` = placeholders uniquement
- Les skills Hermes sont génériques

## Forks par client

```bash
gh repo fork herone-dev/plaudia-template --clone --fork-name plaudia-client-x
```

## Prérequis

1. Projet Supabase créé → `schema.sql` + `002_multi_user_rls.sql` exécutés
2. `/opt/data/.env` configuré avec VOS vraies clés
3. Hermes installé sur le VPS

## Vérification

```bash
curl http://localhost:8000/healthz        # → {"status":"ok"}
hermes cron list                          # → 6 crons plaudia-*
mcp_supabase_execute_sql(...)            # → tables vides, prêtes
```