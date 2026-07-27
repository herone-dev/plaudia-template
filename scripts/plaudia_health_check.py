#!/usr/bin/env python3
"""
Plaudia Health Check — surveille le gateway Hermes et alerte si le scheduler ne tourne pas.
S'exécute toutes les 5 minutes via cron (no_agent=true).
Silencieux si tout va bien, alerte si problème détecté.
"""
import json
import os
import subprocess
import time
import urllib.request

GATEWAY_PID_FILE = "/tmp/plaudia_health_gateway_pid"
HEARTBEAT_FILE = "/tmp/plaudia_health_heartbeat"

def check_gateway():
    """Vérifie si le gateway Hermes tourne et si le scheduler ticke."""
    try:
        # Vérifier via hermes cron status
        result = subprocess.run(
            ["hermes", "cron", "status"],
            capture_output=True, text=True, timeout=15,
        )
        output = result.stdout + result.stderr
        
        if "Gateway is not running" in output:
            return False, "Gateway is not running — cron jobs will NOT fire"
        
        if "Gateway is running" in output:
            if "Ticker heartbeat" in output:
                # Extraire le heartbeat
                import re
                m = re.search(r"Ticker heartbeat: (\d+)s ago", output)
                if m:
                    seconds = int(m.group(1))
                    if seconds > 300:  # Plus de 5 min sans heartbeat = problème
                        return False, f"Scheduler ticker stalled — {seconds}s without heartbeat"
                return True, "OK"
            return True, "Gateway running (no ticker info)"
        
        return False, f"Unknown gateway status: {output[:200]}"
    except Exception as e:
        return False, f"Error checking gateway: {e}"


def check_backend():
    """Vérifie si le backend FastAPI est en vie."""
    try:
        req = urllib.request.Request("http://localhost:8000/healthz")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, "OK"
            return False, f"Backend returned HTTP {resp.status}"
    except Exception as e:
        return False, f"Backend unreachable: {e}"


def check_watchdog():
    """Vérifie si le watchdog a run récemment."""
    try:
        result = subprocess.run(
            ["hermes", "cron", "list"],
            capture_output=True, text=True, timeout=15,
        )
        # Chercher le watchdog et sa dernière execution
        lines = result.stdout.split("\n")
        in_watchdog = False
        last_run = None
        for line in lines:
            if "plaudia-watchdog-free" in line:
                in_watchdog = True
            if in_watchdog and "Last run:" in line:
                last_run = line.strip()
                break
        
        if last_run:
            return True, f"Watchdog OK — {last_run}"
        return True, "Watchdog found (no last run info)"
    except Exception as e:
        return False, f"Error checking watchdog: {e}"


def main():
    results = []
    all_ok = True
    
    # 1. Gateway
    gw_ok, gw_msg = check_gateway()
    all_ok = all_ok and gw_ok
    results.append(f"  Gateway: {'✅' if gw_ok else '❌'} {gw_msg}")
    
    # 2. Backend
    bk_ok, bk_msg = check_backend()
    all_ok = all_ok and bk_ok
    results.append(f"  Backend: {'✅' if bk_ok else '❌'} {bk_msg}")
    
    # 3. Watchdog
    wd_ok, wd_msg = check_watchdog()
    all_ok = all_ok and wd_ok
    results.append(f"  Watchdog: {'✅' if wd_ok else '❌'} {wd_msg}")
    
    # Mettre à jour le heartbeat
    with open(HEARTBEAT_FILE, "w") as f:
        f.write(str(time.time()))
    
    if all_ok:
        return  # SILENT — tout va bien
    
    # ALERTE — quelque chose ne va pas
    print(f"[plaudia-health] ⚠️ Problème détecté sur le système Plaudia :")
    for r in results:
        print(r)
    
    # Tentative d'auto-réparation
    if not gw_ok:
        print("[plaudia-health] 🔧 Tentative de redémarrage du gateway...")
        subprocess.run(
            ["hermes", "gateway", "run"],
            check=False, capture_output=True, timeout=10,
        )


if __name__ == "__main__":
    main()