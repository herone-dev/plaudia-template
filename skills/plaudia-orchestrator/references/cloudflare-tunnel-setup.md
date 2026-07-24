# Cloudflare Tunnel + Access — Plaudia

## Architecture

```
Lovable (frontend)
  └─ server function (hermes-proxy.functions.ts)
       ├─ injecte CF-Access-Client-Id + Secret (headers)
       └─ injecte X-Plaudia-Key (header)
            │
            ▼ HTTPS
     plaudia-api.herone.app  ← tunnel cloudflared
            │
            ▼ HTTP
     localhost:8000  ← uvicorn (FastAPI)
```

## Tunnel config

Le tunnel utilise un **token Argo** (`--token` flag), pas un tunnel nommé statique avec `cert.pem`.

**Config** (`/opt/data/.cloudflared/config.yml`) :
```yaml
tunnel: plaudia-tunnel
credentials-file: /opt/data/.cloudflared/<uuid>.json
ingress:
  - hostname: plaudia-api.herone.app
    service: http://localhost:8000
  - service: http_status:404
```

**Lancement** :
```bash
cloudflared tunnel run --token <eyJ...token>
```

**PID** : `/opt/data/plaudia_tunnel.pid`
**Log** : `/opt/data/plaudia_tunnel.log`
**URL** : `/opt/data/plaudia_tunnel_url.txt`

## Cloudflare Access (Zero Trust)

### Si le frontend reçoit 403 « Error · Cloudflare Access »

La cause est que la requête arrive bien au tunnel, mais Cloudflare Access (couche Zero Trust) la bloque avant qu'elle atteigne le backend.

**Diagnostic** :
```bash
# Backend local (doit être ✅)
curl -s -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" http://localhost:8000/v1/enterprises/with-counts

# Tunnel (sera ❌ 403 si Access bloque)
curl -s -o /dev/null -w "HTTP %{http_code}" \
  -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" \
  https://plaudia-api.herone.app/v1/enterprises/with-counts
```

**Solution** : le proxy Lovable doit envoyer les headers `CF-Access-Client-Id` et `CF-Access-Client-Secret` dans chaque requête. Ces valeurs sont stockées côté serveur (Lovable secrets), jamais dans des variables `VITE_*`.

### Configurer un Service Token

1. Dashboard Cloudflare → Zero Trust → Access → Service Auth
2. Créer un token (ex: `plaudia-api-service-token`)
3. Copier `Client ID` et `Client Secret`
4. Access → Applications → `plaudia-api.herone.app` → Policies → ajouter `Service Token = plaudia-api-service-token`
5. Ajouter les secrets dans Lovable (`add_secret`) :
   - `CF_CLIENT_ID` = le Client ID
   - `CF_CLIENT_SECRET` = le Client Secret

### Pitfall — rotation du Service Token

Si le token est régénéré, le secret change. Il faut mettre à jour le secret dans Lovable ET dans tout endroit qui l'utilise. Sans ça, le frontend ne peut plus joindre le backend jusqu'à la prochaine mise à jour.

## Keepalive

Le script `plaudia_keepalive.sh` (cron toutes les 1 min) vérifie :
- Si le backend (port 8000) répond → sinon le relance
- Si le tunnel répond → sinon le relance

**PID du keepalive** : le cron Hermes, pas un fichier PID — le processus peut être mort sans que le keepalive le sache immédiatement (intervalle de 1 min).