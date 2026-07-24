# Dépannage tunnel Cloudflare + proxy Lovable

## Quand le frontend Lovable ne peut pas joindre le backend

### 1. Diagnostiquer la couche qui bloque

Tester chaque couche séparément :

```bash
# Couche 1 : backend local (doit répondre)
curl -sf http://localhost:8000/healthz

# Couche 2 : tunnel cloudflared (sans headers CF Access)
curl -s -o /dev/null -w "%{http_code}" https://plaudia-api.herone.app/healthz

# Couche 3 : tunnel avec clé API (si X-Plaudia-Key requise)
curl -s -H "X-Plaudia-Key: $KEY" https://plaudia-api.herone.app/v1/enterprises
```

### 2. Interpréter les codes HTTP

| Code | Réponse | Cause probable |
|---|---|---|
| 200 | JSON valide | ✅ Tout fonctionne |
| 403 | Page HTML "Cloudflare Access" | Service Token manquant ou invalide |
| 404 | `{"detail":"Not Found"}` | Endpoint GET manquant dans main.py |
| 405 | Page HTML ou `{"detail":"Method Not Allowed"}` | Méthode HTTP incorrecte ou vieux processus backend |
| 502 | Cloudflare error | Tunnel mort ou backendDown |

### 3. Service Token Cloudflare Access

Si le tunnel renvoie 403 avec une page HTML "Cloudflare Access" :

1. Créer un Service Token dans le dashboard Cloudflare :
   - Zero Trust → Access → Service Auth → Add Service Token
   - Nom : `plaudia-api-service-token`
   - Noter le Client ID et Client Secret

2. Ajouter le token à la policy Access :
   - Zero Trust → Access → Applications → `plaudia-api.herone.app`
   - Policies → Add rule → `Service Token = plaudia-api-service-token` → Allow

3. Stocker les credentials dans Lovable (server-side secrets, PAS dans `.env`) :
   - `CF_CLIENT_ID` = Client ID
   - `CF_CLIENT_SECRET` = Client Secret

4. Le proxy Lovable doit inclure ces headers dans chaque requête :
   ```
   CF-Access-Client-Id: {{CF_CLIENT_ID}}
   CF-Access-Client-Secret: {{CF_CLIENT_SECRET}}
   ```

### 4. Proxy Lovable (server function)

Quand le frontend utilise un proxy `callHermes` (server function) :

1. Le proxy intercepte tous les appels `hermesAPI.*` et les route vers le backend
2. Il injecte `X-Plaudia-Key` + `CF-Access-*` headers côté serveur
3. **Conséquence : tous les GET endpoints doivent être ré-ajoutés dans le backend** (le proxy ne peut pas appeler Supabase directement)

### 5. Erreur "Method Not Allowed" = faux positif fréquent

Si le frontend Lovable signale 405 mais que le backend local répond 200 :

1. Le proxy Lovable reçoit une réponse HTML 403 de Cloudflare
2. La réponse HTML n'est pas du JSON → le proxy peut l'interpréter comme 405
3. **Toujours tester d'abord localement** avant de supposer que l'endpoint n'existe pas

### 6. Piège : keepalive + vieux PID

Le keepalive (`plaudia-keepalive`) redémarre le backend toutes les minutes. Si le backend a été lancé manuellement (nohup ou background), le keepalive peut le tuer + le relancer avec un PID différent. Le fichier `/opt/data/plaudia_backend.pid` peut être obsolète.

Solution : mettre à jour le PID après chaque redémarrage manuel :
```bash
echo "$(pgrep -f 'uvicorn main:app' | head -1)" > /opt/data/plaudia_backend.pid
```