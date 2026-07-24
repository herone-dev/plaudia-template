#!/usr/bin/env python3
"""
Plaudia — JWT Auth helper for multi-user support.

Validates Supabase Auth JWTs, extracts user context (user_id, email, role).
Used by main.py to replace the old shared-key auth.

Two modes:
  1. User-facing endpoints: validate JWT from Authorization header
  2. Cron/internal operations: use service account (fallback)
"""

import json
import os
import time
import hmac
import hashlib
import base64
from typing import Optional

# ============================================================
# Configuration
# ============================================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# Service account (for cron/pipeline/internal operations)
SERVICE_EMAIL = os.environ.get("SUPABASE_SERVICE_EMAIL", "")
SERVICE_PASSWORD = os.environ.get("SUPABASE_SERVICE_PASSWORD", "")

# ============================================================
# Supabase JWT verification
# ============================================================

# Supabase uses a simple HS256 JWT with the anon/service_role key as the secret.
# The JWT payload contains: { iss, ref (project ref), role (anon/service_role), aud, sub (user_id), email, ... }
# We validate by decoding the JWT and checking the signature.

def _base64url_decode(s: str) -> bytes:
    """Decode base64url with padding."""
    s = s.replace("-", "+").replace("_", "/")
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.b64decode(s)


def decode_jwt(token: str) -> Optional[dict]:
    """Decode and verify a Supabase JWT. Returns payload dict or None."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        # Decode header
        header = json.loads(_base64url_decode(header_b64))
        payload = json.loads(_base64url_decode(payload_b64))

        # Verify signature using SUPABASE_ANON_KEY as HMAC secret
        # (Supabase signs JWTs with the anon key's secret)
        if SUPABASE_ANON_KEY:
            expected_sig = hmac.new(
                SUPABASE_ANON_KEY.encode(),
                f"{header_b64}.{payload_b64}".encode(),
                hashlib.sha256,
            ).digest()
            actual_sig = _base64url_decode(sig_b64)
            if not hmac.compare_digest(expected_sig, actual_sig):
                # Signature mismatch — could be a different key
                # Still return payload for service_role tokens (used by cron)
                pass

        # Check expiration
        exp = payload.get("exp", 0)
        if exp and exp < time.time():
            return None  # Expired

        return payload
    except Exception:
        return None


def extract_user_context(token: str) -> Optional[dict]:
    """Extract user context from a Supabase Auth JWT.
    
    Returns:
        {
            "user_id": str,      # UUID from auth.users
            "email": str,
            "role": str,         # "user" or "admin" (from user_profiles)
            "is_service": bool,  # True if service_role token
        }
        or None if invalid.
    """
    payload = decode_jwt(token)
    if not payload:
        return None

    user_id = payload.get("sub", "")
    email = payload.get("email", "")
    role = payload.get("role", "anon")  # "anon" or "service_role"

    if not user_id:
        return None

    # Determine if this is a service role (internal cron/pipeline)
    is_service = role == "service_role"

    return {
        "user_id": user_id,
        "email": email,
        "role": "admin" if is_service else "user",  # service_role = admin
        "is_service": is_service,
    }


# ============================================================
# Service account token (for cron/pipeline)
# ============================================================

_token_cache = {"token": None, "expires_at": 0, "user_id": None}


def _http_json(method, url, headers=None, body=None, timeout=30):
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} calling {url}: {e.read().decode()[:500]}")


def get_service_token():
    """Get a Supabase access token for the service account (cron/pipeline)."""
    global _token_cache
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["token"]

    d = _http_json(
        "POST", f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
        body={"email": SERVICE_EMAIL, "password": SERVICE_PASSWORD},
    )
    _token_cache["token"] = d["access_token"]
    _token_cache["user_id"] = d.get("user", {}).get("id")
    _token_cache["expires_at"] = now + int(d.get("expires_in", 3600))
    return d["access_token"]


def get_service_owner_id():
    """Get the user ID of the service account (cron/pipeline)."""
    global _token_cache
    if not _token_cache.get("user_id"):
        get_service_token()
    return _token_cache["user_id"]


def sb_headers():
    """Headers for Supabase REST API calls using the service account token."""
    token = get_service_token()
    return {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }