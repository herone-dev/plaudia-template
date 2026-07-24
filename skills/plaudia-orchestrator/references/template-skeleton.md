# Template Plaudia — squelette vierge, pas de données client

## Principe

Le template sur `herone-dev/plaudia-template` est un **squelette** réutilisable. Un nouveau client le clone et exécute `setup-plaudia.sh` qui configure TOUT avec ses propres credentials.

## Ce que le template NE doit PAS contenir

| Interdit | Exemple | Risque |
|---|---|---|
| URLs Supabase réelles | `https://ezqbxfmafvdjtgrrxcxy.supabase.co` | Données client exposées |
| Clés API | `OPENAI_API_KEY=sk-pro-...`, `sbp_...` | Vol de crédits API |
| Tokens | `PLAUDIA_SHARED_KEY=Vs4fc...`, `CF_CLIENT_ID=...` | Accès non autorisé |
| Emails réels | `martin@herone.fr` | Identité exposée |
| Mots de passe | `Herone2026test` | Intrusion |
| IDs de cron | `d4777fc4327a` | Lié à un environnement spécifique |
| Références à des repos clients | `herone-dev/plaudia-v1-martin` | Ne concerne pas le nouveau client |
| **UUIDs d'utilisateurs** | `79d6876b-bc72-424b-8c23-8c485eaa1b57` | **N'existe pas sur un autre environnement** — le backend crashe ou échoue silencieusement |

## Règles pour maintenir le template propre

1. `main.py` — toutes les credentials via `os.environ.get("VAR", "")` — **jamais** de valeurs en dur
2. `main.py` — **aucun UUID en dur** — `owner_id`, `user_id`, etc. doivent passer par `get_service_owner_id()` ou une variable d'env
3. `schema.sql` — pur DDL (CREATE TABLE, CREATE INDEX, CREATE FUNCTION) — **aucun INSERT**
4. `.env.example` — placeholders uniquement (`votre-projet.supabase.co`, `à_générer_avec_openssl`) — **aucune valeur réelle**
5. `scripts/` — tokens et IDs via env vars, pas en dur
6. `setup-plaudia.sh` — générique : pas de référence à un client spécifique, pas de repo privé, pas de credentials

## Vérification

Avant de push le template, lancer une vérification automatique :

```bash
# Leak detection
grep -rn "supabase\.co\|eyJh\|sbp_\|martin@\|Herone2026\|ezqbxf" rag_backend/ scripts/ .env.example

# Hardcoded UUID check (UUID de production qui n'est pas un placeholder)
grep -rnE "\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b" rag_backend/main.py
```

Si une ligne est trouvée et n'est pas un placeholder, c'est un leak. **NOTE : le fichier `rag_backend/main.py` contient actuellement un UUID en dur (`79d6876b-bc72-424b-8c23-8c485eaa1b57` aux lignes 689, 708, 719) — le remplacer par `get_service_owner_id()` AVANT de push le template.**

## Workflow de déploiement pour un nouveau client

1. Forker `herone-dev/plaudia-template` → `herone-dev/plaudia-client-X`
2. Le nouveau client crée son projet Supabase et note ses clés
3. Exécute `setup-plaudia.sh` sur son VPS Hermes
4. Le script copie le backend, crée les crons, démarre le serveur
5. Le client configure Plaud MCP + Google OAuth (optionnel)
6. Le client crée un projet Lovable et configure le proxy + secrets