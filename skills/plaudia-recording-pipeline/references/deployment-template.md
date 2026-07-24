# Plaudia — Template de déploiement

Un dossier `docs/template/` dans le projet Plaudia (`/opt/data/projects/plaudia/docs/template/`) contient tout le nécessaire pour déployer le système sur un nouvel environnement.

## Fichiers

| Fichier | Contenu |
|---------|---------|
| `README.md` | Architecture, composants, schéma |
| `env.example` | Toutes les variables d'environnement frontend et backend |
| `deployment.md` | Guide pas-à-pas : Supabase, backend, frontend, crons, OAuth, Cloudflare |
| `architecture.md` | Diagramme d'architecture, flux de données, tables, endpoints |
| `supabase-schema.sql` | Migration SQL complète : tables, contraintes, triggers, RPC, vue matérialisée |

## Utilisation

Pour déployer sur un nouvel environnement :

1. Créer un projet Supabase → exécuter `supabase-schema.sql`
2. Copier `env.example` → `.env` et remplir les valeurs
3. Déployer le backend FastAPI (`rag_backend/`)
4. Déployer le frontend Lovable
5. Configurer les crons Hermes (keepalive, watchdog, pipeline)
6. Configurer Google OAuth
7. Configurer le tunnel Cloudflare

## Hardcodés à externaliser

Le fichier `main.py` contient encore des valeurs en dur qui doivent être passées en variables d'environnement avant déploiement :

| Variable | Ligne | Valeur actuelle |
|----------|-------|-----------------|
| `SUPABASE_URL` | 57 | `https://ezqbxfmafvdjtgrrxcxy.supabase.co` |
| `ANON_KEY` | 58 | `eyJhbG...PBj4` (tronqué) |
| `SERVICE_EMAIL` | 59 | `martin@herone.fr` |
| `OPUS_MODEL` | 66 | `deepseek/deepseek-v4-flash` |
| `OPENROUTER_URL` | 67 | `https://openrouter.ai/api/v1/chat/completions` |

Voir `docs/template/deployment.md` pour les instructions complètes.