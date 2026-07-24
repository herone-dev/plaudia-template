#!/usr/bin/env bash
# Watchdog tunnel Plaudia — vérifie la connexion Cloudflare, recrée le tunnel si mort.
# Usage: sans argument (lancé par cron)
# Log: /opt/data/plaudia_tunnel_watchdog.log

set -euo pipefail

LOG="/opt/data/plaudia_tunnel_watchdog.log"
CLOUDFLARED="/opt/data/.local/bin/cloudflared"
CONFIG_DIR="/opt/data/.cloudflared"
CONFIG_FILE="$CONFIG_DIR/config.yml"
TUNNEL_NAME="plaudia-tunnel"
LOG_TUNNEL="/opt/data/plaudia_tunnel.log"
PID_FILE="/opt/data/plaudia_tunnel.pid"
BACKEND_HEALTH="http://127.0.0.1:8000/healthz"
PUBLIC_URL="https://plaudia-api.herone.app"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

log "=== Watchdog tunnel lancé ==="

# 1. Vérifier que le backend local répond
if ! curl -sf --connect-timeout 5 "$BACKEND_HEALTH" > /dev/null 2>&1; then
  log "ERREUR: Backend local injoignable (port 8000) — pas de tunnel à créer"
  exit 1
fi
log "Backend local OK"

# 2. Vérifier l'état du tunnel
TUNNEL_OK=false

# 2a. Vérifier le PID
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    log "Processus tunnel OK (PID $OLD_PID)"
  else
    log "PID $OLD_PID mort — tunnel à redémarrer"
  fi
else
  log "Pas de PID file — tunnel à démarrer"
fi

# 2b. Vérifier les connexions Cloudflare
CONNECTIONS=$($CLOUDFLARED tunnel info "$TUNNEL_NAME" 2>/dev/null | grep -c "cdg" || true)
if [ "$CONNECTIONS" -gt 0 ]; then
  log "Tunnel connecté ($CONNECTIONS lignes Cloudflare)"
  TUNNEL_OK=true
else
  log "Tunnel sans connexion Cloudflare"
fi

# 2c. Vérifier que l'URL publique répond
if [ "$TUNNEL_OK" = true ]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "$PUBLIC_URL/healthz" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" != "000" ]; then
    log "URL publique répond (HTTP $HTTP_CODE)"
  else
    log "URL publique ne répond pas — tunnel à reconstruire"
    TUNNEL_OK=false
  fi
fi

# 3. Si tout va bien, on sort
if [ "$TUNNEL_OK" = true ]; then
  log "=== Tunnel OK, rien à faire ==="
  exit 0
fi

# 4. Tunnel mort — on tue les processus résiduels
log "=== Tunnel mort — reconstruction ==="

# Tuer les vieux processus
pkill -f "cloudflared.*$TUNNEL_NAME" 2>/dev/null || true
sleep 3

# 5. Supprimer l'ancien tunnel côté Cloudflare
if $CLOUDFLARED tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  log "Suppression de l'ancien tunnel..."
  $CLOUDFLARED tunnel delete "$TUNNEL_NAME" >> "$LOG" 2>&1 || true
  sleep 2
fi

# 6. Créer un nouveau tunnel
log "Création d'un nouveau tunnel..."
NEW_TUNNEL_OUTPUT=$($CLOUDFLARED tunnel create "$TUNNEL_NAME" 2>&1)
echo "$NEW_TUNNEL_OUTPUT" >> "$LOG"

# Extraire le nouvel ID
NEW_TUNNEL_ID=$(echo "$NEW_TUNNEL_OUTPUT" | grep -oP 'id \K[0-9a-f-]+' || true)
if [ -z "$NEW_TUNNEL_ID" ]; then
  log "ERREUR: impossible de créer le tunnel"
  exit 1
fi
log "Nouveau tunnel ID: $NEW_TUNNEL_ID"

# 7. Mettre à jour la config
NEW_CRED_FILE="$CONFIG_DIR/$NEW_TUNNEL_ID.json"
sed -i "s|credentials-file:.*|credentials-file: $NEW_CRED_FILE|" "$CONFIG_FILE"
log "Config mise à jour"

# 8. Router le DNS
$CLOUDFLARED tunnel route dns --overwrite-dns "$TUNNEL_NAME" "plaudia-api.herone.app" >> "$LOG" 2>&1
log "DNS mis à jour"

# 9. Démarrer le tunnel
log "Démarrage du tunnel..."
export HOME=/tmp/cloudflared-home
nohup $CLOUDFLARED tunnel --config "$CONFIG_FILE" run "$TUNNEL_NAME" > "$LOG_TUNNEL" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
log "Tunnel démarré (PID $NEW_PID)"

# 10. Attendre et vérifier
sleep 15
CONNECTIONS=$($CLOUDFLARED tunnel info "$TUNNEL_NAME" 2>/dev/null | grep -c "cdg" || true)
if [ "$CONNECTIONS" -gt 0 ]; then
  log "SUCCÈS: tunnel reconnecté ($CONNECTIONS lignes Cloudflare)"
else
  log "ÉCHEC: tunnel sans connexion après démarrage"
fi

log "=== Watchdog terminé ==="