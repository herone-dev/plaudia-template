#!/usr/bin/env bash
# ============================================================
# setup-plaudia.sh — Installation complète de Plaudia
# sur un nouvel Hermes (Nous Research)
# ============================================================
# Usage: bash setup-plaudia.sh [--domain votre-domaine.app] [--supabase-url https://xxx.supabase.co]
# À exécuter APRÈS avoir configuré /opt/data/.env
# ============================================================
set -euo pipefail

# --- Configuration ---
DOMAIN="${1:-plaudia-api.votre-domaine.app}"
SUPABASE_URL="${2:-}"
ENV_FILE="/opt/data/.env"
TEMPLATE_REPO="https://github.com/herone-dev/plaudia-template.git"
BACKEND_DIR="/opt/data/projects/plaudia/rag_backend"

echo "=== Plaudia — Installation ==="
echo "Domaine tunnel : $DOMAIN"

# --- Vérifications préalables ---
if [ ! -f "$ENV_FILE" ]; then
  echo "ERREUR: $ENV_FILE introuvable. Crée-le d'abord."
  echo "Copie le modèle depuis plaudia-template/env.example"
  exit 1
fi

source "$ENV_FILE"

# Vérifier les variables essentielles
for var in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_EMAIL SUPABASE_SERVICE_PASSWORD OPENAI_API_KEY PLAUDIA_SHARED_KEY; do
  if [ -z "${!var:-}" ]; then
    echo "ERREUR: $var n'est pas défini dans $ENV_FILE"
    exit 1
  fi
done

# --- 1. Cloner le template ---
echo "[1/7] Clonage du template Plaudia..."
cd /opt/data
if [ ! -d "plaudia-template" ]; then
  git clone "$TEMPLATE_REPO"
else
  echo "  → plaudia-template existe déjà"
  cd plaudia-template && git pull && cd /opt/data
fi

# --- 2. Installer les dépendances backend ---
echo "[2/7] Installation des dépendances Python..."
mkdir -p "$BACKEND_DIR"
cp -r plaudia-template/rag_backend/* "$BACKEND_DIR/"
cd "$BACKEND_DIR"
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi
# Dépendances essentielles
pip install fastapi uvicorn pydantic google-auth google-api-python-client svgwrite 2>/dev/null || true

# --- 3. Copier les scripts Hermes ---
echo "[3/7] Copie des scripts cron..."
mkdir -p /opt/data/.hermes/scripts
cp -n plaudia-template/scripts/* /opt/data/.hermes/scripts/ 2>/dev/null || echo "  → scripts déjà présents"

# --- 4. Copier les skills Hermes ---
echo "[4/7] Copie des skills Hermes..."
SKILLS_DIR="/opt/data/skills/productivity"
mkdir -p "$SKILLS_DIR"
for skill in plaudia-orchestrator plaudia-recording-pipeline plaudia-cr-backend; do
  if [ ! -d "$SKILLS_DIR/$skill" ]; then
    cp -r "plaudia-template/skills/$skill" "$SKILLS_DIR/$skill" 2>/dev/null && echo "  → $skill OK" || echo "  → $skill: copie ignorée"
  else
    echo "  → $skill existe déjà"
  fi
done

# --- 5. Créer les crons ---
echo "[5/7] Création des crons Hermes..."
hermes cron create --name plaudia-keepalive --schedule "* * * * *" --script plaudia_keepalive.sh --no-agent 2>/dev/null && echo "  → keepalive OK" || echo "  → keepalive déjà existant"
hermes cron create --name plaudia-watchdog-free --schedule "*/5 * * * *" --script plaudia_watchdog.py --no-agent 2>/dev/null && echo "  → watchdog OK" || echo "  → watchdog déjà existant"
hermes cron create --name plaudia-pipeline-principal --schedule "0 12 * * *" --skill plaudia-recording-pipeline 2>/dev/null && echo "  → pipeline OK" || echo "  → pipeline déjà existant"
hermes cron create --name plaudia-refresh-enterprise-counts --schedule "*/15 * * * *" --script plaudia_refresh_enterprise_counts.py --no-agent 2>/dev/null && echo "  → refresh-counts OK" || echo "  → refresh-counts déjà existant"
hermes cron create --name plaudia-tunnel-watchdog --schedule "0 6 * * *" --script plaudia_tunnel_watchdog.sh --no-agent 2>/dev/null && echo "  → tunnel-watchdog OK" || echo "  → tunnel-watchdog déjà existant"

# --- 6. Démarrer le backend ---
echo "[6/7] Démarrage du backend FastAPI..."
cd "$BACKEND_DIR"
source "$ENV_FILE"

# Tuer l'ancien s'il tourne
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1

nohup /opt/hermes/.venv/bin/python -m uvicorn main:app \
  --workers 4 \
  --host 0.0.0.0 --port 8000 \
  > /opt/data/plaudia_backend.log 2>&1 &

echo "  → Backend démarré (PID: $!)"

# Attendre que le backend soit prêt
echo "     Vérification..."
for i in $(seq 1 10); do
  if curl -sf http://localhost:8000/healthz > /dev/null 2>&1; then
    echo "  → Backend OK"
    break
  fi
  sleep 1
done

# --- 7. Tunnel Cloudflare (optionnel) ---
echo "[7/7] Tunnel Cloudflare..."
if command -v cloudflared &> /dev/null; then
  if [ ! -f /opt/data/.cloudflared/config.yml ]; then
    echo "  → Config tunnel à créer manuellement"
    echo "    Voir docs/cloudflare-tunnel-setup.md"
  else
    nohup nohup cloudflared tunnel --config /opt/data/.cloudflared/config.yml run plaudia-tunnel \
      > /opt/data/plaudia_tunnel.log 2>&1 &
    echo "  → Tunnel démarré"
  fi
else
  echo "  → cloudflared non installé — tunnel à configurer manuellement"
fi

# --- Résumé ---
echo ""
echo "=== Installation terminée ==="
echo ""
echo "Ce qui tourne maintenant :"
echo "  - Backend FastAPI    http://localhost:8000"
echo "  - Keepalive          toutes les minutes"
echo "  - Watchdog           toutes les 5 minutes"
echo "  - Pipeline           tous les jours à 12h"
echo "  - Refresh counts     toutes les 15 min"
echo "  - Tunnel watchdog    tous les jours à 6h"
echo ""
echo "Prochaines étapes :"
echo "  1. Configurer Plaud MCP : /opt/data/mcp-tokens/plaudai.json"
echo "  2. Google OAuth        : /opt/data/google_token.json"
echo "  3. Tunnel Cloudflare   : cloudflared tunnel ..."
echo "  4. Frontend Lovable    : voir docs/frontend-login-prompt.md"
echo ""
echo "Pour vérifier : curl http://localhost:8000/healthz"