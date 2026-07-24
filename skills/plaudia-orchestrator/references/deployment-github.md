# Plaudia — Déploiement via GitHub Template

## Repo template

**URL** : `https://github.com/herone-dev/plaudia-template`

**⚠️ CE REPO N'EST PAS À JOUR (20/07/2026).** Les fichiers locaux dans `/opt/data/projects/plaudia/docs/template/` n'ont jamais été pushés sur GitHub. Le repo existe (HTTP 200) mais ne contient pas le code à jour.

### Contenu ACTUEL du template local

```\nplaudia-template/docs/template/\n├── README.md\N├── architecture.md\n├── deployment.md       # Obsolète — 202607, pas de JWT\n├── env.example         # ATTENTION : fuite de secrets réels\n├── setup-plaudia.sh    # Spécifique Martin (clone plaudia-v1-martin)\n└── supabase-schema.sql # DDL propre mais sans RLS policies\n```

### Contenu MANQUANT (à copier avant push)

```
├── rag_backend/                # À copier depuis /opt/data/projects/plaudia/rag_backend/
│   ├── main.py                 # 2687 lignes — hardcode owner_id à corriger
│   ├── auth.py                 # JWT Supabase Auth
│   ├── chart_renderer.py       # SVG charts via svgwrite
│   └── google_integration.py   # Export Docs + Gmail
├── scripts/                    # À copier depuis /opt/data/.hermes/scripts/
│   ├── plaudia_watchdog.py
│   ├── plaudia_keepalive.sh
│   ├── plaudia_tunnel_watchdog.sh
│   └── plaudia_refresh_enterprise_counts.py
├── supabase/
│   └── migrations/
│       └── 002_multi_user_rls.sql   # RLS + project_shares + triggers
├── skills/                     # Skills Hermes (3 dossiers)
├── docs/
│   ├── deployment-checklist.md # 15 étapes (à créer)
│   ├── debug-guide.md          # 9 bugs documentés (à créer)
│   └── frontend-login-prompt.md # Prompts Lovable auth JWT (à créer)
```

Voir la section **PITFALLS DÉPLOIEMENT** dans la SKILL.md du plaudia-orchestrator pour la liste des correctifs P0/P1 avant déploiement.

## Forks par client

```bash
gh repo fork herone-dev/plaudia-template --clone --fork-name plaudia-client-x
```

## Prérequis

1. Projet Supabase créé → `schema.sql` exécuté dans l'éditeur SQL
2. `/opt/data/.env` configuré avec VOS vraies clés
3. Hermes installé sur le VPS

## Vérification

```bash
curl http://localhost:8000/healthz        # → {"status":"ok"}
hermes cron list                          # → 3 crons plaudia-*
mcp_supabase_execute_sql(...)            # → tables vides, prêtes
```