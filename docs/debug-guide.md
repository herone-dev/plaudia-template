# Plaudia — Guide de debug (9 bugs documentés)

## 1. Backend 404 sur nouveaux endpoints

**Symptôme :** `healthz` → 200 OK, mais `/v1/auth/me` → 404

**Cause :** Deux uvicorn cohabitent : `.venv/bin/uvicorn` (local, périmé) vs `/opt/hermes/.venv/bin/python -m uvicorn`

**Diagnostic :**
```bash
python3 -c "
import os
with open('/proc/net/tcp') as f:
    for line in f:
        if ':1F40' in line:
            inode = line.split()[9]
            for pid in os.listdir('/proc'):
                if pid.isdigit() and os.path.isdir(f'/proc/{pid}/fd'):
                    for fd in os.listdir(f'/proc/{pid}/fd'):
                        try:
                            link = os.readlink(f'/proc/{pid}/fd/{fd}')
                            if f'socket:[{inode}]' in link:
                                cmd = open(f'/proc/{pid}/cmdline').read().replace(chr(0), ' ').strip()
                                print(f'PID {pid}: {cmd[:200]}')
                        except: pass
"
```

**Solution :** `kill <PID_STALE>` puis attendre que le keepalive relance avec le bon Python.

## 2. Frontend 405 — Cloudflare Access 403 masqué

**Symptôme :** Le frontend signale 405 Method Not Allowed

**Cause :** Cloudflare Access bloque la requête avant le backend. Le proxy Lovable reçoit une page HTML 403 et l'interprète comme 405.

**Diagnostic :**
```bash
# 1. Tester localement
curl -s -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" http://localhost:8000/v1/enterprises

# 2. Tester via tunnel
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" \
  https://plaudia-api.votre-domaine.app/v1/enterprises
```

**Solution :** Configurer un Service Token Cloudflare Access (voir docs/cloudflare-tunnel-setup.md) ou désactiver l'Access pour ce tunnel.

## 3. Keepalive kill les processus manuels

**Symptôme :** Un `uvicorn` lancé manuellement est remplacé en 60 secondes

**Cause :** Le cron keepalive vérifie toutes les minutes et tue/relance le backend

**Solution :** Ne pas lancer manuellement. Après une modification de `main.py`, attendre 60s pour que le keepalive relance automatiquement.

## 4. ANON_KEY tronquée

**Symptôme :** Erreurs auth aléatoires, JWT non valides

**Cause :** La clé dans `main.py` peut être tronquée (`eyJhbG...PBj4`)

**Diagnostic :** `wc -c /opt/data/projects/plaudia/rag_backend/main.py | grep -o 'SUPABASE_ANON_KEY.*'`

**Solution :** Vérifier la clé réelle avec `mcp_supabase_get_publishable_keys(project_id='...')` et mettre à jour l'env.

## 5. CRs orphelins (enterprise_id NULL)

**Symptôme :** CRs générés mais invisibles dans la vue entreprises

**Cause :** Le watchdog n'a pas détecté l'entreprise au moment de l'insertion

**Solution :** Attribuer manuellement via le frontend (bloc Rattachement dans CRDetailView) ou via PATCH /v1/crs/{cr_id}.

## 6. Pipeline silencieux

**Symptôme :** Le cron pipeline répond `[SILENT]`

**Cause :** Aucun `recording.status='transcribed'` avec `enterprise_id IS NOT NULL`

**Diagnostic :**
```sql
SELECT id, status, enterprise_id, title FROM recordings WHERE status = 'transcribed' ORDER BY created_at DESC;
```

**Solution :** Attribuer une entreprise aux enregistrements orphelins d'abord.

## 7. Compteurs entreprises bloqués

**Symptôme :** Les compteurs CR/recordings n'évoluent pas

**Cause :** La vue matérialisée `enterprise_counts` n'est pas rafraîchie

**Solution :** `REFRESH MATERIALIZED VIEW enterprise_counts;` ou attendre le cron (15 min).

## 8. Frontend cache CR stale

**Symptôme :** "Aucune modification appliquée" après édition CR

**Cause :** Le frontend ne recharge pas le CR après l'édition

**Solution :** Dans `CRDetailView.tsx`, après `handleChatSubmit` succès, appeler `refreshMeetingCr(cr_id)`.

## 9. Lovable server function bloquée par requireSupabaseAuth

**Symptôme :** Blank screen, erreur "Unauthorized: No authorization header provided"

**Cause :** `requireSupabaseAuth` middleware appliqué à la server function `callHermes`

**Solution :** Créer `callHermes` SANS le middleware. Le backend gère l'auth via JWT.