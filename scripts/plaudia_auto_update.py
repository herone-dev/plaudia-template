#!/usr/bin/env python3
"""
Plaudia Auto-Update — vérifie les mises à jour du template GitHub.

Fonctionnement :
1. Compare le hash local du template avec le remote
2. Si différent : pull, puis met à jour les fichiers critiques
3. Signale les changements dans le log

Fichiers mis à jour automatiquement :
  - rag_backend/main.py, auth.py, chart_renderer.py, google_integration.py
  - scripts/ (watchdog, keepalive, tunnel watchdog, refresh counts)
  - skills/ (orchestrator, pipeline, cr-backend)

Fichiers NON touchés (configuration locale) :
  - /opt/data/.env (credentials)
  - /opt/data/.cloudflared/ (tunnel config)
  - /opt/data/mcp-tokens/ (Plaud tokens)
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

TEMPLATE_DIR = "/opt/data/plaudia-template"
TEMPLATE_REPO = "https://github.com/herone-dev/plaudia-template.git"
BACKEND_DIR = "/opt/data/projects/plaudia/rag_backend"
HERMES_SCRIPTS = "/opt/data/.hermes/scripts"
SKILLS_DIR = "/opt/data/skills/productivity"
ENV_FILE = "/opt/data/.env"
LOG_FILE = "/opt/data/plaudia_auto_update.log"

# Fichiers à copier (chemins relatifs depuis TEMPLATE_DIR)
FILES_TO_COPY = [
    ("rag_backend/main.py", BACKEND_DIR),
    ("rag_backend/auth.py", BACKEND_DIR),
    ("rag_backend/chart_renderer.py", BACKEND_DIR),
    ("rag_backend/google_integration.py", BACKEND_DIR),
]

SCRIPTS_TO_COPY = [
    "scripts/plaudia_watchdog.py",
    "scripts/plaudia_keepalive.sh",
    "scripts/plaudia_tunnel_watchdog.sh",
]

SKILLS_TO_COPY = [
    "plaudia-orchestrator",
    "plaudia-recording-pipeline",
    "plaudia-cr-backend",
]


def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{__import__('datetime').datetime.now().isoformat()}] {msg}\n")
    print(msg)


def get_local_hash():
    """Get hash of the local template repo."""
    try:
        result = subprocess.run(
            ["git", "-C", TEMPLATE_DIR, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def get_remote_hash():
    """Get hash of the remote template repo."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", TEMPLATE_REPO, "HEAD"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.split()[0]
    except Exception:
        pass
    return None


def pull_template():
    """Pull latest version of the template repo."""
    if not os.path.isdir(TEMPLATE_DIR):
        log("Template non cloné — clonage...")
        subprocess.run(
            ["git", "clone", TEMPLATE_REPO, TEMPLATE_DIR],
            check=True, timeout=60
        )
        return True

    log("Template existe — pull...")
    result = subprocess.run(
        ["git", "-C", TEMPLATE_DIR, "pull", "origin", "master"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        log(f"Pull OK: {result.stdout.strip()[:200]}")
        return True
    else:
        log(f"Pull échoué: {result.stderr[:200]}")
        return False


def copy_files():
    """Copy updated files from template to their destinations."""
    changes = []

    # Backend files
    for rel_path, dest_dir in FILES_TO_COPY:
        src = os.path.join(TEMPLATE_DIR, rel_path)
        dst = os.path.join(dest_dir, os.path.basename(rel_path))
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            changes.append(rel_path)

    # Scripts
    for rel_path in SCRIPTS_TO_COPY:
        src = os.path.join(TEMPLATE_DIR, rel_path)
        dst = os.path.join(HERMES_SCRIPTS, os.path.basename(rel_path))
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            # Make executable
            os.chmod(dst, 0o755)
            changes.append(rel_path)

    # Skills
    for skill_name in SKILLS_TO_COPY:
        src = os.path.join(TEMPLATE_DIR, "skills", skill_name)
        dst = os.path.join(SKILLS_DIR, skill_name)
        if os.path.isdir(src):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            changes.append(f"skills/{skill_name}")

    return changes


def restart_backend():
    """Signal the backend to restart (keepalive will pick it up)."""
    log("Backend mis à jour — keepalive relancera automatiquement")


def main():
    log("=== Vérification de mise à jour ===")

    local_hash = get_local_hash()
    remote_hash = get_remote_hash()

    if not remote_hash:
        log("Impossible de vérifier le remote — réessaie au prochain cycle")
        return

    if local_hash == remote_hash and local_hash is not None:
        log(f"Aucune mise à jour (hash: {local_hash[:12]})")
        return

    log(f"Mise à jour détectée: {local_hash[:12] if local_hash else 'N/A'} → {remote_hash[:12]}")

    if not pull_template():
        log("ÉCHEC: pull impossible")
        return

    changes = copy_files()
    if changes:
        log(f"Fichiers mis à jour: {', '.join(changes)}")
        restart_backend()
    else:
        log("Aucun fichier à mettre à jour")

    log("=== Mise à jour terminée ===")


if __name__ == "__main__":
    main()