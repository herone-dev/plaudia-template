#!/usr/bin/env bash
# Plaudia keepalive — vérifie backend + tunnel, relance si mort.
set -e

URL_FILE="/opt/data/plaudia_tunnel_url.txt"
ENV_FILE="/opt/data/.env"

# Backend sur port 8000
if ! curl -sf http://127.0.0.1:8000/healthz > /dev/null 2>&1; then
    echo "[$(date)] Backend mort — relance..."
    cd /opt/data/projects/plaudia/rag_backend
    source "$ENV_FILE"
    export SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_EMAIL SUPABASE_SERVICE_PASSWORD OPENAI_API_KEY ANTHROPIC_API_KEY PLAUDIA_SHARED_KEY
    nohup /opt/hermes/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 > /opt/data/plaudia_backend.log 2>&1 &
    echo $! > /opt/data/plaudia_backend.pid
    echo "[$(date)] Backend relancé"
fi

# Tunnel cloudflared
if [ -f /opt/data/plaudia_tunnel.pid ] && kill -0 "$(cat /opt/data/plaudia_tunnel.pid)" 2>/dev/null; then
    TUNNEL_URL=$(cat "$URL_FILE" 2>/dev/null || echo "")
    if [ -n "$TUNNEL_URL" ] && ! curl -sf --connect-timeout 5 "$TUNNEL_URL/healthz" > /dev/null 2>&1; then
        echo "[$(date)] Tunnel ne répond plus — relance..."
        kill "$(cat /opt/data/plaudia_tunnel.pid)" 2>/dev/null || true
        sleep 2
    else
        exit 0  # Tout va bien
    fi
fi

# Relancer le tunnel
echo "[$(date)] Lancement du tunnel..."
nohup /opt/data/.local/bin/cloudflared tunnel --config /opt/data/.cloudflared/config.yml run plaudia-tunnel > /opt/data/plaudia_tunnel.log 2>&1 &
echo $! > /opt/data/plaudia_tunnel.pid
sleep 8
echo "https://plaudia-api.herone.app" > "$URL_FILE" 2>/dev/null || true
echo "[$(date)] Tunnel relancé — URL: https://plaudia-api.herone.app"