"""Server-side authentication and RBAC.

Login issues a signed, expiring token. Every protected endpoint resolves the
caller from that token (never from ids sent in the request body) and checks
the role against the database on each request, so a deleted account or a
changed password invalidates old tokens immediately.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from flask import g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from data_database import DATA_DIR, get_auth_record

TOKEN_MAX_AGE_SEC = int(os.environ.get("AUTH_TOKEN_MAX_AGE_SEC", 7 * 24 * 3600))

# Admin "level" values. Boshliq (director) has full rights; cashier = cash desk only;
# manager = students (CRM), schedule and attendance only.
FULL_ADMIN_LEVELS = {"platform_admin", "school_admin", "director"}
CASHIER_LEVEL = "cashier"
MANAGER_LEVEL = "manager"


def _load_secret() -> str:
    env_secret = os.environ.get("SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    # No env secret: persist a random one next to the data so tokens survive restarts.
    path = Path(DATA_DIR) / ".secret_key"
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        path.write_text(value, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return value
    except OSError:
        # shortcut: read-only disk gets a per-process secret, tokens die on restart; set SECRET_KEY in prod.
        return secrets.token_urlsafe(48)


_serializer = URLSafeTimedSerializer(_load_secret(), salt="texnoo-auth-v1")


def _password_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(str(password_hash or "").encode("utf-8")).hexdigest()[:16]


def issue_token(role: str, account_id: int) -> Optional[str]:
    record = get_auth_record(role, account_id)
    if not record:
        return None
    return _serializer.dumps({
        "r": role,
        "i": int(account_id),
        "p": _password_fingerprint(record["password_hash"]),
    })


def principal_from_record(role: str, account_id: int, record: dict[str, Any]) -> dict[str, Any]:
    meta = record.get("meta") or {}
    level = str(meta.get("level") or meta.get("role") or "") if role == "admin" else ""
    if role == "admin" and level not in FULL_ADMIN_LEVELS | {CASHIER_LEVEL, MANAGER_LEVEL}:
        level = "school_admin"
    return {
        "role": role,
        "id": int(account_id),
        "level": level,
        "name": record.get("name") or "",
        "status": record.get("status") or "active",
        "phone": record.get("phone") or "",
        "center": str(meta.get("centerId") or "main"),
        "meta": meta,
    }


def resolve_principal() -> Optional[dict[str, Any]]:
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        return None
    try:
        payload = _serializer.loads(token, max_age=TOKEN_MAX_AGE_SEC)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    role = str(payload.get("r") or "")
    try:
        account_id = int(payload.get("i") or 0)
    except (TypeError, ValueError):
        return None
    record = get_auth_record(role, account_id)
    if not record or _password_fingerprint(record["password_hash"]) != payload.get("p"):
        return None
    principal = principal_from_record(role, account_id, record)
    if role == "teacher" and principal["status"] == "pending":
        return None
    return principal


def is_full_admin(principal: Optional[dict[str, Any]]) -> bool:
    return bool(principal) and principal["role"] == "admin" and principal["level"] in FULL_ADMIN_LEVELS


def is_cashier(principal: Optional[dict[str, Any]]) -> bool:
    return bool(principal) and principal["role"] == "admin" and principal["level"] == CASHIER_LEVEL


def require_auth(*allowed: str) -> Callable:
    """Decorator. `allowed` items: a role ("student"), "admin" (full admins only), "cashier" or "manager".

    With no arguments any authenticated user passes. The caller is put on `g.principal`.
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            principal = resolve_principal()
            if not principal:
                return jsonify({"status": "error", "ok": False, "message": "Avval tizimga kiring", "error": "unauthorized"}), 401
            if allowed and not _matches(principal, allowed):
                return jsonify({"status": "error", "ok": False, "message": "Bu amal uchun ruxsat yo'q", "error": "forbidden"}), 403
            g.principal = principal
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def _matches(principal: dict[str, Any], allowed: tuple[str, ...]) -> bool:
    for item in allowed:
        if item == "admin" and is_full_admin(principal):
            return True
        if item in {CASHIER_LEVEL, MANAGER_LEVEL} and principal["role"] == "admin" and principal["level"] == item:
            return True
        if item not in {"admin", CASHIER_LEVEL, MANAGER_LEVEL} and principal["role"] == item:
            return True
    return False
