# Backend Management — VPS Hostinger

## Env vars (.env)

Fichier : `/opt/data/projects/plaudia/rag_backend/.env`

```env
OPENAI_API_KEY="sk-..."        # REQUIS — embeddings + chat (gpt-4o-mini)
PLAUDIA_SHARED_KEY="..."       # REQUIS — auth du proxy Lovable
ANTHROPIC_API_KEY=""           # Optionnel
OPENROUTER_API_KEY=""          # Plus nécessaire depuis migration OpenAI
PLAUDIA_SERVICE_PASSWORD="..." # Optionnel
```

**PITFALL — La clé OpenAI peut être corrompue lors de l'écriture.** Vérifier avec `grep -oP 'sk-proj-\K\w+' .env` et comparer la fin avec la clé originale. Si la clé est corrompue (segments répétés), l'API OpenAI renvoie 401 "Incorrect API key provided".

## Démarrer le serveur

```bash
cd /opt/data/projects/plaudia/rag_backend
bash start.sh
```

Le script source `.env`, puis lance `uvicorn main:app --host 0.0.0.0 --port 8000`.

## Arrêter le serveur

```bash
kill $(pgrep -f "uvicorn main:app")
```

## Vérifier que le serveur tourne

```bash
curl -sS http://localhost:8000/healthz
# → {"status":"ok"}

# Avec auth (X-Plaudia-Key) :
curl -sS -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" http://localhost:8000/v1/crs?limit=1
# → [{...}] HTTP 200
```

## Diagnostiquer un 502 Cloudflare

1. Vérifier le process local : `curl http://localhost:8000/healthz` — si 200, le backend est up
2. Vérifier le tunnel : `ps aux | grep cloudflared` — doit montrer 1-2 processus
3. Vérifier le config tunnel : `cat ~/.cloudflared/config.yml` — doit router `plaudia-api.herone.app` → `http://localhost:8000`
4. Si le process est mort : `bash start.sh &`
5. Si le tunnel est mort : `cloudflared tunnel run --token <token> &` (le token est dans les processus ps)

**Erreur fréquente :** Le process FastAPI a crashé à cause d'une exception non catchée (ex: filtre `or=` mal formé, colonne Supabase inexistante). Voir les logs en relançant le process en foreground.

## Logs

Le serveur tourne en background → pas de logs persistants. Pour debug : relancer en foreground avec `bash start.sh` (sans `&`).

## Systemd (pas disponible)

Le VPS tourne en conteneur (PID 1 = `entrypoint.sh`). Pas de `systemd`. Pour auto-démarrage : ajouter `/opt/data/projects/plaudia/rag_backend/start.sh &` dans `/entrypoint.sh`.

## API key corruption detection

Les clés OpenAI `sk-proj-...` (130-160 chars) peuvent être corrompues lors de l'écriture. Symptôme : le dernier segment se répète (`...BL62iNXI0EA` → `...BL62iNBL62iN`). Détection :

```bash
grep -oP '([A-Za-z0-9_-]{6,})\1' /opt/data/projects/plaudia/rag_backend/.env
```

Si match, réécrire la clé avec `patch`, pas `write_file`. Toujours tester après écriture :

```bash
curl -sS -X POST -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hi"}]}' \
  -H "X-Plaudia-Key: $PLAUDIA_SHARED_KEY" \
  http://localhost:8000/v1/chat/completions | grep -c "Incorrect API key"
# 0 = OK, 1 = corrompue
```

## Participants table — colonnes réelles

La table Supabase `participants` n'a PAS les colonnes `cr_id` ni `role` (erreur 42703). Colonnes disponibles : `id, recording_id, name, email, created_at, owner_id`.

## GET /v1/recordings — existe déjà

L'endpoint est à ~ligne 1350 de `main.py`. Le user pensait qu'il manquait à cause du 502 général.

## Vérification complète après redémarrage (tous les endpoints)

```bash
H="X-Plaudia-Key: $(grep PLAUDIA_SHARED_KEY /opt/data/projects/plaudia/rag_backend/.env | cut -d= -f2 | tr -d '\"')"

echo "Health:   $(curl -sS http://localhost:8000/healthz)"
echo "CRs:      $(curl -sS -o /dev/null -w '%{http_code}' -H "$H" 'http://localhost:8000/v1/crs?limit=1')"
echo "Part.:    $(curl -sS -o /dev/null -w '%{http_code}' -H "$H" 'http://localhost:8000/v1/participants?limit=3')"
echo "Rec.:     $(curl -sS -o /dev/null -w '%{http_code}' -H "$H" 'http://localhost:8000/v1/recordings?limit=2')"
echo "RAG:      $(curl -sS -o /dev/null -w '%{http_code}' -H "$H" -H 'Content-Type: application/json' -X POST -d '{"messages":[{"role":"user","content":"hi"}],"cr_id":null}' 'http://localhost:8000/v1/chat/completions')"
echo "Ent.:     $(curl -sS -o /dev/null -w '%{http_code}' -H "$H" 'http://localhost:8000/v1/enterprises/with-counts')"
echo "Gloss.:   $(curl -sS -o /dev/null -w '%{http_code}' -H "$H" 'http://localhost:8000/v1/glossary')"
```

Tous doivent retourner 200. Si RAG retourne 200 mais contient "Incorrect API key" dans le body, la clé OpenAI est corrompue.