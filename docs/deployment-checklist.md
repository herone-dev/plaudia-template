# Plaudia — Checklist de déploiement (15 étapes)

## Phase 1 : Infrastructure (VPS Hermes)

- [ ] 1. **VPS provisionné** — Ubuntu 22.04+, 2GB RAM min, accès SSH
- [ ] 2. **Hermes installé** — `bash <(curl -sSL https://hermes-agent.nousresearch.com/install.sh)`
- [ ] 3. **Dépendances** — `uv python install 3.13`, `npm install -g cloudflared`
- [ ] 4. **Clés SSH/GitHub configurées** — `gh auth login`, `git config`

## Phase 2 : Supabase

- [ ] 5. **Projet Supabase créé** — https://supabase.com → New project
- [ ] 6. **Extensions activées** — `vector`, `pgcrypto`, `uuid-ossp` (dans SQL Editor)
- [ ] 7. **Schéma exécuté** — `supabase-schema.sql` (DDL + triggers + RPC)
- [ ] 8. **Migration multi-user** — `migrations/002_multi_user_rls.sql` (RLS + shares + triggers)
- [ ] 9. **Comptes utilisateurs créés** — Authentication → Users → Add User (pas d'inscription publique)
- [ ] 10. **Clés notées** — Project URL, anon key (Settings → API)

## Phase 3 : Backend

- [ ] 11. **Backend copié** — `cp -r rag_backend/ /opt/data/projects/plaudia/rag_backend/`
- [ ] 12. **.env configuré** — `/opt/data/.env` avec toutes les clés (voir `env.example`)
- [ ] 13. **Backend démarré** — Vérifier `curl http://localhost:8000/healthz` → `{"status":"ok"}`
- [ ] 14. **Routes vérifiées** — `curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['paths']), 'routes')"` → 45+

## Phase 4 : Tunnel Cloudflare

- [ ] 15. **Tunnel créé** — `cloudflared tunnel create plaudia-tunnel`
- [ ] 16. **DNS configuré** — `cloudflared tunnel route dns plaudia-tunnel plaudia-api.votre-domaine.app`
- [ ] 17. **Config.yml** — `/opt/data/.cloudflared/config.yml` avec ingress → localhost:8000
- [ ] 18. **Tunnel démarré** — Vérifier `curl https://plaudia-api.votre-domaine.app/healthz`

## Phase 5 : Crons Hermes

- [ ] 19. **Keepalive** — `hermes cron create --name plaudia-keepalive --schedule "* * * * *" --script plaudia_keepalive.sh --no-agent`
- [ ] 20. **Watchdog** — `hermes cron create --name plaudia-watchdog-free --schedule "*/5 * * * *" --script plaudia_watchdog.py --no-agent`
- [ ] 21. **Pipeline** — `hermes cron create --name plaudia-pipeline-principal --schedule "0 12 * * *" --skill plaudia-recording-pipeline`
- [ ] 22. **Refresh counts** — `hermes cron create --name plaudia-refresh-enterprise-counts --schedule "*/15 * * * *" --script plaudia_refresh_enterprise_counts.py --no-agent`
- [ ] 23. **Tunnel watchdog** — `hermes cron create --name plaudia-tunnel-watchdog --schedule "0 6 * * *" --script plaudia_tunnel_watchdog.sh --no-agent`

## Phase 6 : Plaud MCP

- [ ] 24. **Intégration Plaud créée** — https://app.plaud.ai/settings → Integrations → New Integration
- [ ] 25. **Token OAuth stocké** — `/opt/data/mcp-tokens/plaudai.json` (refresh token)
- [ ] 26. **Watchdog testé** — Vérifier les logs : `hermes cron run <watchdog-id>`

## Phase 7 : Frontend Lovable

- [ ] 27. **Projet Lovable créé** — Connecté au repo GitHub du frontend
- [ ] 28. **Secrets serveur déclarés** — `PLAUDIA_BACKEND_URL`, `PLAUDIA_SHARED_KEY`, `CF_CLIENT_ID`, `CF_CLIENT_SECRET`
- [ ] 29. **Variables VITE_* déclarées** — `VITE_HERONE_SUPABASE_URL`, `VITE_HERONE_SUPABASE_PUBLISHABLE_KEY`
- [ ] 30. **Proxy callHermes fonctionnel** — Tester un appel API

## Phase 8 : Vérification finale

- [ ] 31. `curl http://localhost:8000/healthz` → `{"status":"ok"}`
- [ ] 32. `hermes cron list` → 5 crons actifs
- [ ] 33. Login frontend → JWT obtenu → CRs listés
- [ ] 34. Watchdog → nouveaux enregistrements détectés
- [ ] 35. Pipeline → CR généré depuis transcription