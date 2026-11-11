"""Relational hybrid storage for the application.

Primary account data is normalized into SQL tables and mirrored to SQLite and
PostgreSQL. The legacy full-dataset shape is reconstructed on reads so the
current frontend can keep working while security is improved.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import bcrypt
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger("data_database")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = Path("/app/data") if Path("/app").is_dir() else BASE_DIR / "data"
DATA_DIR = Path(os.environ.get("DATA_DIR", str(DEFAULT_DATA_DIR)))
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH", str(DATA_DIR / "app_data.sqlite3")))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

_USER_ROLES = ("student", "teacher", "admin", "parent", "employer")
_META_KEYS = (
    "transactions",
    "groups",
    "adminRequests",
    "pendingReqs",
    "pendingTelegramLinks",
    "telegramProfiles",
    "tests",
    "testResults",
    "plans",
    "submissions",
    "settings",
    "currencyExchanges",
    "gamePlays",
    "practicePlays",
    "battleLog",
    "attendanceLog",
    "pairHistory",
    "materials",
    "news",
    "homeworks",
    "homeworkSubmissions",
    "homeworkGrades",
    "lessonPlans",
    "courses",
    "jobs",
    "applications",
    "certificates",
)

_SQLITE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    user_pk INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    name TEXT,
    first_name TEXT,
    last_name TEXT,
    phone TEXT,
    email TEXT,
    code TEXT,
    status TEXT,
    avatar TEXT,
    password_hash TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(role, legacy_id)
);

CREATE TABLE IF NOT EXISTS students (
    user_pk INTEGER PRIMARY KEY,
    group_name TEXT,
    teacher_id INTEGER,
    teacher_ids_json TEXT NOT NULL DEFAULT '[]',
    total_coins INTEGER NOT NULL DEFAULT 0,
    olmos INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    badge TEXT,
    ref_code TEXT,
    school TEXT,
    grade TEXT,
    streak INTEGER NOT NULL DEFAULT 0,
    meta_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(user_pk) REFERENCES users(user_pk) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS teachers (
    user_pk INTEGER PRIMARY KEY,
    subject TEXT,
    level_label TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(user_pk) REFERENCES users(user_pk) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS parents (
    user_pk INTEGER PRIMARY KEY,
    child_phone TEXT,
    child_phones_json TEXT NOT NULL DEFAULT '[]',
    meta_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(user_pk) REFERENCES users(user_pk) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS employers (
    user_pk INTEGER PRIMARY KEY,
    company TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(user_pk) REFERENCES users(user_pk) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    bucket TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata_store (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""

_POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_pk BIGSERIAL PRIMARY KEY,
    legacy_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    name TEXT,
    first_name TEXT,
    last_name TEXT,
    phone TEXT,
    email TEXT,
    code TEXT,
    status TEXT,
    avatar TEXT,
    password_hash TEXT NOT NULL,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL,
    UNIQUE(role, legacy_id)
);

CREATE TABLE IF NOT EXISTS students (
    user_pk BIGINT PRIMARY KEY REFERENCES users(user_pk) ON DELETE CASCADE,
    group_name TEXT,
    teacher_id BIGINT,
    teacher_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_coins BIGINT NOT NULL DEFAULT 0,
    olmos BIGINT NOT NULL DEFAULT 0,
    level BIGINT NOT NULL DEFAULT 1,
    badge TEXT,
    ref_code TEXT,
    school TEXT,
    grade TEXT,
    streak BIGINT NOT NULL DEFAULT 0,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS teachers (
    user_pk BIGINT PRIMARY KEY REFERENCES users(user_pk) ON DELETE CASCADE,
    subject TEXT,
    level_label TEXT,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS parents (
    user_pk BIGINT PRIMARY KEY REFERENCES users(user_pk) ON DELETE CASCADE,
    child_phone TEXT,
    child_phones_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS employers (
    user_pk BIGINT PRIMARY KEY REFERENCES users(user_pk) ON DELETE CASCADE,
    company TEXT,
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    bucket TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata_store (
    key TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at BIGINT NOT NULL
);
"""


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _json_loads(data: Any, default: Any) -> Any:
    if isinstance(data, (dict, list)):
        return data
    if data in (None, ""):
        return default
    try:
        return json.loads(data)
    except Exception:  # noqa: BLE001
        return default


def _postgres_enabled() -> bool:
    return bool(DATABASE_URL)


def _get_postgres_connection():
    if not _postgres_enabled():
        raise RuntimeError("DATABASE_URL sozlanmagan")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)


def _get_sqlite_connection() -> sqlite3.Connection:
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _is_password_hash(value: str) -> bool:
    return value.startswith("$2a$") or value.startswith("$2b$") or value.startswith("$2y$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def _resolve_password_hash(raw_password: str, existing_hash: str | None = None) -> str:
    candidate = str(raw_password or "").strip()
    if candidate and _is_password_hash(candidate):
        return candidate
    if candidate:
        return hash_password(candidate)
    if existing_hash:
        return existing_hash
    return hash_password(secrets.token_urlsafe(24))


def init_sqlite_db() -> None:
    with _get_sqlite_connection() as conn:
        conn.executescript(_SQLITE_SCHEMA)
        conn.commit()


def init_postgres_db() -> None:
    if not _postgres_enabled():
        logger.warning("PostgreSQL init o'tkazib yuborildi: DATABASE_URL sozlanmagan.")
        return
    with _get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_POSTGRES_SCHEMA)
        conn.commit()


def init_data_db() -> None:
    init_sqlite_db()
    try:
        init_postgres_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PostgreSQL init xatosi, SQLite ishlashda davom etadi: %s", exc)


def _now() -> int:
    return int(time.time())


def _sanitize_meta(item: dict[str, Any], remove: Iterable[str]) -> dict[str, Any]:
    out = dict(item)
    for key in remove:
        out.pop(key, None)
    out.pop("password", None)
    out.pop("pass", None)
    return out


def _next_id(items: list[dict[str, Any]]) -> int:
    numeric = [int(x.get("id", 0)) for x in items if isinstance(x, dict) and str(x.get("id", "")).isdigit()]
    return (max(numeric) + 1) if numeric else 1


def _default_dataset() -> dict[str, Any]:
    return {
        "seedVersion": 1,
        "students": [],
        "teachers": [],
        "admins": [],
        "parents": [],
        "employers": [],
        "transactions": [],
        "nextStudentId": 1,
        "nextTeacherId": 1,
        "nextAdminId": 1,
        "nextParentId": 1,
        "nextEmployerId": 1,
        "adminRequests": [],
        "nextRequestId": 1,
        "messages": [],
        "groups": [],
        "chatFriends": [],
        "chatGroups": [],
        "pendingReqs": [],
        "pendingTelegramLinks": [],
        "telegramProfiles": {},
        "tests": [],
        "testResults": [],
        "plans": [],
        "submissions": [],
        "settings": {},
        "currencyExchanges": [],
        "nextExchangeId": 1,
        "gamePlays": {},
        "practicePlays": {},
        "battleLog": [],
        "attendanceLog": [],
        "pairHistory": [],
        "materials": [],
        "news": [],
        "homeworks": [],
        "homeworkSubmissions": [],
        "lessonPlans": [],
        "courses": [],
        "jobs": [],
        "applications": [],
        "certificates": [],
    }


def _read_existing_hashes_sqlite() -> dict[tuple[str, int], str]:
    init_sqlite_db()
    with _get_sqlite_connection() as conn:
        rows = conn.execute("SELECT role, legacy_id, password_hash FROM users").fetchall()
    return {(str(r["role"]), int(r["legacy_id"])): str(r["password_hash"]) for r in rows}


def _read_existing_hashes_postgres() -> dict[tuple[str, int], str]:
    if not _postgres_enabled():
        return {}
    try:
        with _get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT role, legacy_id, password_hash FROM users")
                rows = cur.fetchall()
        return {(str(r["role"]), int(r["legacy_id"])): str(r["password_hash"]) for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def _persist_sqlite(data: dict[str, Any]) -> None:
    existing_hashes = _read_existing_hashes_sqlite()
    now = _now()
    with _get_sqlite_connection() as conn:
        conn.executescript(_SQLITE_SCHEMA)
        conn.execute("DELETE FROM students")
        conn.execute("DELETE FROM teachers")
        conn.execute("DELETE FROM parents")
        conn.execute("DELETE FROM employers")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM metadata_store")
        conn.execute("DELETE FROM users")

        for role in _USER_ROLES:
            collection = data.get(f"{role}s", []) if role != "admin" else data.get("admins", [])
            if role == "parent":
                collection = data.get("parents", [])
            elif role == "employer":
                collection = data.get("employers", [])
            for item in collection:
                if not isinstance(item, dict):
                    continue
                legacy_id = int(item.get("id") or 0)
                if not legacy_id:
                    continue
                user_meta = _sanitize_meta(item, {
                    "id", "name", "firstName", "lastName", "phone", "email", "code", "teacherCode",
                    "adminCode", "parentCode", "employerCode", "status", "avatar", "subj", "subject",
                    "role", "level", "company", "childPhone", "childPhones", "group", "teacherId",
                    "teacherIds", "coins", "totalCoins", "olmos", "badge", "ref", "refCode",
                    "school", "grade", "streak",
                })
                password_hash = _resolve_password_hash(
                    str(item.get("password") or item.get("pass") or ""),
                    existing_hashes.get((role, legacy_id)),
                )
                code = item.get("code") or item.get("teacherCode") or item.get("adminCode") or item.get("parentCode") or item.get("employerCode")
                status = item.get("status") or ("active" if role != "teacher" else item.get("status", "active"))
                level_value = item.get("level") if role == "admin" else None
                if role == "teacher":
                    level_value = item.get("level")
                if level_value is not None:
                    user_meta["level"] = level_value
                cur = conn.execute(
                    """
                    INSERT INTO users
                    (legacy_id, role, name, first_name, last_name, phone, email, code, status, avatar,
                     password_hash, meta_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        legacy_id,
                        role,
                        item.get("name"),
                        item.get("firstName"),
                        item.get("lastName"),
                        item.get("phone"),
                        item.get("email"),
                        code,
                        status,
                        item.get("avatar"),
                        password_hash,
                        _json_dumps(user_meta),
                        now,
                        now,
                    ),
                )
                user_pk = int(cur.lastrowid)

                if role == "student":
                    student_meta = _sanitize_meta(item, {
                        "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                        "code", "group", "teacherId", "teacherIds", "coins", "totalCoins", "olmos",
                        "level", "badge", "ref", "refCode", "school", "grade", "streak",
                    })
                    conn.execute(
                        """
                        INSERT INTO students
                        (user_pk, group_name, teacher_id, teacher_ids_json, total_coins, olmos, level,
                         badge, ref_code, school, grade, streak, meta_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_pk,
                            item.get("group"),
                            int(item.get("teacherId") or 0),
                            _json_dumps(item.get("teacherIds") or []),
                            int(item.get("totalCoins") or 0),
                            int(item.get("olmos") or 0),
                            int(item.get("level") or 1),
                            item.get("badge"),
                            item.get("refCode") or item.get("ref"),
                            item.get("school"),
                            item.get("grade"),
                            int(item.get("streak") or 0),
                            _json_dumps(student_meta),
                        ),
                    )
                elif role == "teacher":
                    teacher_meta = _sanitize_meta(item, {
                        "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                        "code", "teacherCode", "subject", "subj", "level",
                    })
                    conn.execute(
                        "INSERT INTO teachers (user_pk, subject, level_label, meta_json) VALUES (?, ?, ?, ?)",
                        (user_pk, item.get("subject") or item.get("subj"), item.get("level"), _json_dumps(teacher_meta)),
                    )
                elif role == "parent":
                    parent_meta = _sanitize_meta(item, {
                        "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                        "code", "parentCode", "childPhone", "childPhones",
                    })
                    conn.execute(
                        "INSERT INTO parents (user_pk, child_phone, child_phones_json, meta_json) VALUES (?, ?, ?, ?)",
                        (user_pk, item.get("childPhone"), _json_dumps(item.get("childPhones") or []), _json_dumps(parent_meta)),
                    )
                elif role == "employer":
                    employer_meta = _sanitize_meta(item, {
                        "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                        "code", "employerCode", "company",
                    })
                    conn.execute(
                        "INSERT INTO employers (user_pk, company, meta_json) VALUES (?, ?, ?)",
                        (user_pk, item.get("company") or item.get("name"), _json_dumps(employer_meta)),
                    )

        for item in data.get("messages", []):
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or secrets.token_hex(8))
            conn.execute(
                """
                INSERT INTO messages (message_id, bucket, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, "messages", _json_dumps(item), int(item.get("timestamp") or now), now),
            )

        for key in _META_KEYS:
            conn.execute(
                "INSERT INTO metadata_store (key, data, updated_at) VALUES (?, ?, ?)",
                (key, _json_dumps(data.get(key, [] if key.endswith("s") or key.endswith("Log") else {})), now),
            )

        next_values = {
            "nextStudentId": data.get("nextStudentId") or _next_id(data.get("students", [])),
            "nextTeacherId": data.get("nextTeacherId") or _next_id(data.get("teachers", [])),
            "nextAdminId": data.get("nextAdminId") or _next_id(data.get("admins", [])),
            "nextParentId": data.get("nextParentId") or _next_id(data.get("parents", [])),
            "nextEmployerId": data.get("nextEmployerId") or _next_id(data.get("employers", [])),
            "nextRequestId": data.get("nextRequestId") or 1,
            "nextExchangeId": data.get("nextExchangeId") or 1,
            "seedVersion": data.get("seedVersion") or 1,
        }
        for key, value in next_values.items():
            conn.execute(
                "INSERT INTO metadata_store (key, data, updated_at) VALUES (?, ?, ?)",
                (key, _json_dumps(value), now),
            )
        conn.commit()


def _persist_postgres(data: dict[str, Any]) -> None:
    if not _postgres_enabled():
        return
    existing_hashes = _read_existing_hashes_postgres()
    now = _now()
    with _get_postgres_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(_POSTGRES_SCHEMA)
            cur.execute("DELETE FROM students")
            cur.execute("DELETE FROM teachers")
            cur.execute("DELETE FROM parents")
            cur.execute("DELETE FROM employers")
            cur.execute("DELETE FROM messages")
            cur.execute("DELETE FROM metadata_store")
            cur.execute("DELETE FROM users")

            for role in _USER_ROLES:
                collection = data.get(f"{role}s", []) if role != "admin" else data.get("admins", [])
                if role == "parent":
                    collection = data.get("parents", [])
                elif role == "employer":
                    collection = data.get("employers", [])
                for item in collection:
                    if not isinstance(item, dict):
                        continue
                    legacy_id = int(item.get("id") or 0)
                    if not legacy_id:
                        continue
                    user_meta = _sanitize_meta(item, {
                        "id", "name", "firstName", "lastName", "phone", "email", "code", "teacherCode",
                        "adminCode", "parentCode", "employerCode", "status", "avatar", "subj", "subject",
                        "role", "level", "company", "childPhone", "childPhones", "group", "teacherId",
                        "teacherIds", "coins", "totalCoins", "olmos", "badge", "ref", "refCode",
                        "school", "grade", "streak",
                    })
                    password_hash = _resolve_password_hash(
                        str(item.get("password") or item.get("pass") or ""),
                        existing_hashes.get((role, legacy_id)),
                    )
                    code = item.get("code") or item.get("teacherCode") or item.get("adminCode") or item.get("parentCode") or item.get("employerCode")
                    status = item.get("status") or ("active" if role != "teacher" else item.get("status", "active"))
                    level_value = item.get("level") if role == "admin" else None
                    if role == "teacher":
                        level_value = item.get("level")
                    if level_value is not None:
                        user_meta["level"] = level_value
                    cur.execute(
                        """
                        INSERT INTO users
                        (legacy_id, role, name, first_name, last_name, phone, email, code, status, avatar,
                         password_hash, meta_json, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                        RETURNING user_pk
                        """,
                        (
                            legacy_id, role, item.get("name"), item.get("firstName"), item.get("lastName"),
                            item.get("phone"), item.get("email"), code, status, item.get("avatar"),
                            password_hash, _json_dumps(user_meta), now, now,
                        ),
                    )
                    user_pk = int(cur.fetchone()["user_pk"])

                    if role == "student":
                        student_meta = _sanitize_meta(item, {
                            "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                            "code", "group", "teacherId", "teacherIds", "coins", "totalCoins", "olmos",
                            "level", "badge", "ref", "refCode", "school", "grade", "streak",
                        })
                        cur.execute(
                            """
                            INSERT INTO students
                            (user_pk, group_name, teacher_id, teacher_ids_json, total_coins, olmos, level,
                             badge, ref_code, school, grade, streak, meta_json)
                            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                            """,
                            (
                                user_pk, item.get("group"), int(item.get("teacherId") or 0),
                                _json_dumps(item.get("teacherIds") or []), int(item.get("totalCoins") or 0),
                                int(item.get("olmos") or 0), int(item.get("level") or 1), item.get("badge"),
                                item.get("refCode") or item.get("ref"), item.get("school"), item.get("grade"),
                                int(item.get("streak") or 0), _json_dumps(student_meta),
                            ),
                        )
                    elif role == "teacher":
                        teacher_meta = _sanitize_meta(item, {
                            "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                            "code", "teacherCode", "subject", "subj", "level",
                        })
                        cur.execute(
                            "INSERT INTO teachers (user_pk, subject, level_label, meta_json) VALUES (%s, %s, %s, %s::jsonb)",
                            (user_pk, item.get("subject") or item.get("subj"), item.get("level"), _json_dumps(teacher_meta)),
                        )
                    elif role == "parent":
                        parent_meta = _sanitize_meta(item, {
                            "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                            "code", "parentCode", "childPhone", "childPhones",
                        })
                        cur.execute(
                            "INSERT INTO parents (user_pk, child_phone, child_phones_json, meta_json) VALUES (%s, %s, %s::jsonb, %s::jsonb)",
                            (user_pk, item.get("childPhone"), _json_dumps(item.get("childPhones") or []), _json_dumps(parent_meta)),
                        )
                    elif role == "employer":
                        employer_meta = _sanitize_meta(item, {
                            "id", "name", "firstName", "lastName", "phone", "email", "avatar", "status",
                            "code", "employerCode", "company",
                        })
                        cur.execute(
                            "INSERT INTO employers (user_pk, company, meta_json) VALUES (%s, %s, %s::jsonb)",
                            (user_pk, item.get("company") or item.get("name"), _json_dumps(employer_meta)),
                        )

            for item in data.get("messages", []):
                if not isinstance(item, dict):
                    continue
                message_id = str(item.get("id") or secrets.token_hex(8))
                cur.execute(
                    "INSERT INTO messages (message_id, bucket, payload_json, created_at, updated_at) VALUES (%s, %s, %s::jsonb, %s, %s)",
                    (message_id, "messages", _json_dumps(item), int(item.get("timestamp") or now), now),
                )

            for key in _META_KEYS:
                cur.execute(
                    "INSERT INTO metadata_store (key, data, updated_at) VALUES (%s, %s::jsonb, %s)",
                    (key, _json_dumps(data.get(key, [] if key.endswith("s") or key.endswith("Log") else {})), now),
                )

            next_values = {
                "nextStudentId": data.get("nextStudentId") or _next_id(data.get("students", [])),
                "nextTeacherId": data.get("nextTeacherId") or _next_id(data.get("teachers", [])),
                "nextAdminId": data.get("nextAdminId") or _next_id(data.get("admins", [])),
                "nextParentId": data.get("nextParentId") or _next_id(data.get("parents", [])),
                "nextEmployerId": data.get("nextEmployerId") or _next_id(data.get("employers", [])),
                "nextRequestId": data.get("nextRequestId") or 1,
                "nextExchangeId": data.get("nextExchangeId") or 1,
                "seedVersion": data.get("seedVersion") or 1,
            }
            for key, value in next_values.items():
                cur.execute(
                    "INSERT INTO metadata_store (key, data, updated_at) VALUES (%s, %s::jsonb, %s)",
                    (key, _json_dumps(value), now),
                )
        conn.commit()


def save_data_dict(key: str, data: Dict[str, Any]) -> Dict[str, bool]:
    if key != "app_data":
        raise ValueError("Faqat app_data qo'llab-quvvatlanadi")
    init_data_db()
    _persist_sqlite(data)
    postgres_ok = False
    if _postgres_enabled():
        try:
            _persist_postgres(data)
            postgres_ok = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("PostgreSQL yozish xatosi, SQLite saqlandi: %s", exc)
    return {"sqlite": True, "postgres": postgres_ok}


def _read_sqlite_dataset() -> Optional[dict[str, Any]]:
    init_sqlite_db()
    data = _default_dataset()
    with _get_sqlite_connection() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY role, legacy_id").fetchall()
        students = {
            int(r["user_pk"]): r for r in conn.execute("SELECT * FROM students").fetchall()
        }
        teachers = {
            int(r["user_pk"]): r for r in conn.execute("SELECT * FROM teachers").fetchall()
        }
        parents = {
            int(r["user_pk"]): r for r in conn.execute("SELECT * FROM parents").fetchall()
        }
        employers = {
            int(r["user_pk"]): r for r in conn.execute("SELECT * FROM employers").fetchall()
        }
        meta_rows = conn.execute("SELECT key, data FROM metadata_store").fetchall()
        message_rows = conn.execute("SELECT payload_json FROM messages ORDER BY created_at ASC").fetchall()

    if not users and not meta_rows and not message_rows:
        return None

    for row in users:
        role = str(row["role"])
        common = _json_loads(row["meta_json"], {})
        common.update({
            "id": int(row["legacy_id"]),
            "name": row["name"] or "",
            "firstName": row["first_name"] or common.get("firstName", ""),
            "lastName": row["last_name"] or common.get("lastName", ""),
            "phone": row["phone"] or "",
            "email": row["email"] or "",
            "avatar": row["avatar"] or "",
            "status": row["status"] or common.get("status", "active"),
            "code": row["code"] or common.get("code", ""),
        })
        common["pass"] = ""
        common["password"] = ""

        if role == "student":
            extra = students.get(int(row["user_pk"]))
            if not extra:
                continue
            rec = _json_loads(extra["meta_json"], {})
            rec.update(common)
            rec.update({
                "group": extra["group_name"] or rec.get("group", "D1"),
                "teacherId": int(extra["teacher_id"] or 0),
                "teacherIds": _json_loads(extra["teacher_ids_json"], []),
                "totalCoins": int(extra["total_coins"] or 0),
                "olmos": int(extra["olmos"] or 0),
                "level": int(extra["level"] or 1),
                "badge": extra["badge"] or rec.get("badge", "Starter"),
                "refCode": extra["ref_code"] or rec.get("refCode", ""),
                "school": extra["school"] or rec.get("school", ""),
                "grade": extra["grade"] or rec.get("grade", ""),
                "streak": int(extra["streak"] or 0),
            })
            data["students"].append(rec)
        elif role == "teacher":
            extra = teachers.get(int(row["user_pk"]))
            rec = _json_loads(extra["meta_json"] if extra else "{}", {})
            rec.update(common)
            if extra:
                rec["subj"] = extra["subject"] or rec.get("subj", "")
                if extra["level_label"]:
                    rec["level"] = extra["level_label"]
            data["teachers"].append(rec)
        elif role == "admin":
            rec = dict(common)
            if "level" not in rec:
                rec["level"] = common.get("level", "school_admin")
            data["admins"].append(rec)
        elif role == "parent":
            extra = parents.get(int(row["user_pk"]))
            rec = _json_loads(extra["meta_json"] if extra else "{}", {})
            rec.update(common)
            if extra:
                rec["childPhone"] = extra["child_phone"] or rec.get("childPhone", "")
                rec["childPhones"] = _json_loads(extra["child_phones_json"], [])
            data["parents"].append(rec)
        elif role == "employer":
            extra = employers.get(int(row["user_pk"]))
            rec = _json_loads(extra["meta_json"] if extra else "{}", {})
            rec.update(common)
            if extra:
                rec["company"] = extra["company"] or rec.get("company", rec.get("name", ""))
            data["employers"].append(rec)

    for row in meta_rows:
        data[str(row["key"])] = _json_loads(row["data"], data.get(str(row["key"]), []))

    data["messages"] = [_json_loads(r["payload_json"], {}) for r in message_rows]
    data["nextStudentId"] = int(data.get("nextStudentId") or _next_id(data["students"]))
    data["nextTeacherId"] = int(data.get("nextTeacherId") or _next_id(data["teachers"]))
    data["nextAdminId"] = int(data.get("nextAdminId") or _next_id(data["admins"]))
    data["nextParentId"] = int(data.get("nextParentId") or _next_id(data["parents"]))
    data["nextEmployerId"] = int(data.get("nextEmployerId") or _next_id(data["employers"]))
    return data


def _read_postgres_dataset() -> Optional[dict[str, Any]]:
    if not _postgres_enabled():
        return None
    try:
        with _get_postgres_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users ORDER BY role, legacy_id")
                users = cur.fetchall()
                cur.execute("SELECT * FROM students")
                students = {int(r["user_pk"]): r for r in cur.fetchall()}
                cur.execute("SELECT * FROM teachers")
                teachers = {int(r["user_pk"]): r for r in cur.fetchall()}
                cur.execute("SELECT * FROM parents")
                parents = {int(r["user_pk"]): r for r in cur.fetchall()}
                cur.execute("SELECT * FROM employers")
                employers = {int(r["user_pk"]): r for r in cur.fetchall()}
                cur.execute("SELECT key, data FROM metadata_store")
                meta_rows = cur.fetchall()
                cur.execute("SELECT payload_json FROM messages ORDER BY created_at ASC")
                message_rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PostgreSQL o'qish xatosi: %s", exc)
        return None

    if not users and not meta_rows and not message_rows:
        return None

    data = _default_dataset()
    for row in users:
        role = str(row["role"])
        common = _json_loads(row["meta_json"], {})
        common.update({
            "id": int(row["legacy_id"]),
            "name": row["name"] or "",
            "firstName": row["first_name"] or common.get("firstName", ""),
            "lastName": row["last_name"] or common.get("lastName", ""),
            "phone": row["phone"] or "",
            "email": row["email"] or "",
            "avatar": row["avatar"] or "",
            "status": row["status"] or common.get("status", "active"),
            "code": row["code"] or common.get("code", ""),
            "pass": "",
            "password": "",
        })
        if role == "student":
            extra = students.get(int(row["user_pk"]))
            if not extra:
                continue
            rec = _json_loads(extra["meta_json"], {})
            rec.update(common)
            rec.update({
                "group": extra["group_name"] or rec.get("group", "D1"),
                "teacherId": int(extra["teacher_id"] or 0),
                "teacherIds": _json_loads(extra["teacher_ids_json"], []),
                "totalCoins": int(extra["total_coins"] or 0),
                "olmos": int(extra["olmos"] or 0),
                "level": int(extra["level"] or 1),
                "badge": extra["badge"] or rec.get("badge", "Starter"),
                "refCode": extra["ref_code"] or rec.get("refCode", ""),
                "school": extra["school"] or rec.get("school", ""),
                "grade": extra["grade"] or rec.get("grade", ""),
                "streak": int(extra["streak"] or 0),
            })
            data["students"].append(rec)
        elif role == "teacher":
            extra = teachers.get(int(row["user_pk"]))
            rec = _json_loads(extra["meta_json"] if extra else {}, {})
            rec.update(common)
            if extra:
                rec["subj"] = extra["subject"] or rec.get("subj", "")
                if extra["level_label"]:
                    rec["level"] = extra["level_label"]
            data["teachers"].append(rec)
        elif role == "admin":
            rec = dict(common)
            if "level" not in rec:
                rec["level"] = common.get("level", "school_admin")
            data["admins"].append(rec)
        elif role == "parent":
            extra = parents.get(int(row["user_pk"]))
            rec = _json_loads(extra["meta_json"] if extra else {}, {})
            rec.update(common)
            if extra:
                rec["childPhone"] = extra["child_phone"] or rec.get("childPhone", "")
                rec["childPhones"] = _json_loads(extra["child_phones_json"], [])
            data["parents"].append(rec)
        elif role == "employer":
            extra = employers.get(int(row["user_pk"]))
            rec = _json_loads(extra["meta_json"] if extra else {}, {})
            rec.update(common)
            if extra:
                rec["company"] = extra["company"] or rec.get("company", rec.get("name", ""))
            data["employers"].append(rec)

    for row in meta_rows:
        data[str(row["key"])] = _json_loads(row["data"], data.get(str(row["key"]), []))
    data["messages"] = [_json_loads(r["payload_json"], {}) for r in message_rows]
    data["nextStudentId"] = int(data.get("nextStudentId") or _next_id(data["students"]))
    data["nextTeacherId"] = int(data.get("nextTeacherId") or _next_id(data["teachers"]))
    data["nextAdminId"] = int(data.get("nextAdminId") or _next_id(data["admins"]))
    data["nextParentId"] = int(data.get("nextParentId") or _next_id(data["parents"]))
    data["nextEmployerId"] = int(data.get("nextEmployerId") or _next_id(data["employers"]))
    return data


def get_all_data() -> Dict[str, Any]:
    return _read_sqlite_dataset() or _read_postgres_dataset() or _default_dataset()


def get_storage_health() -> Dict[str, bool]:
    sqlite_ok = True
    postgres_ok = False
    try:
        init_sqlite_db()
    except Exception:  # noqa: BLE001
        sqlite_ok = False
    if _postgres_enabled():
        try:
            with _get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            postgres_ok = True
        except Exception:  # noqa: BLE001
            postgres_ok = False
    return {"sqlite": sqlite_ok, "postgres": postgres_ok}


def authenticate_user(identifier: str, password: str) -> Optional[dict[str, Any]]:
    ident = str(identifier or "").strip()
    password = str(password or "")
    if not ident or not password:
        return None
    init_sqlite_db()
    with _get_sqlite_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, legacy_id, name, phone, email, status, password_hash, meta_json
            FROM users
            WHERE lower(coalesce(email, '')) = lower(?)
               OR replace(coalesce(phone, ''), ' ', '') = replace(?, ' ', '')
               OR lower(coalesce(code, '')) = lower(?)
               OR CAST(legacy_id AS TEXT) = ?
            ORDER BY CASE role WHEN 'admin' THEN 1 WHEN 'teacher' THEN 2 WHEN 'student' THEN 3 ELSE 4 END
            """,
            (ident, ident, ident, ident),
        ).fetchall()
    for row in rows:
        if verify_password(password, str(row["password_hash"])):
            role = str(row["role"])
            data = get_all_data()
            collection = {
                "student": data.get("students", []),
                "teacher": data.get("teachers", []),
                "admin": data.get("admins", []),
                "parent": data.get("parents", []),
                "employer": data.get("employers", []),
            }.get(role, [])
            found = next((item for item in collection if int(item.get("id") or 0) == int(row["legacy_id"])), None)
            if found:
                return {"role": role, "user": found}
    return None


def get_auth_record(role: str, legacy_id: Any) -> Optional[dict[str, Any]]:
    """Account fields needed to authorize a request (SQLite is the primary store)."""
    role = str(role or "").strip().lower()
    try:
        legacy_id = int(legacy_id or 0)
    except (TypeError, ValueError):
        return None
    if role not in _USER_ROLES or not legacy_id:
        return None
    init_sqlite_db()
    with _get_sqlite_connection() as conn:
        row = conn.execute(
            "SELECT name, phone, status, password_hash, meta_json FROM users WHERE role = ? AND legacy_id = ?",
            (role, legacy_id),
        ).fetchone()
    if not row:
        return None
    return {
        "name": row["name"] or "",
        "phone": row["phone"] or "",
        "status": row["status"] or "active",
        "password_hash": str(row["password_hash"] or ""),
        "meta": _json_loads(row["meta_json"], {}),
    }


def update_user_password(role: str, legacy_id: int, old_password: str, new_password: str) -> bool:
    role = str(role or "").strip().lower()
    if role not in _USER_ROLES:
        return False
    legacy_id = int(legacy_id or 0)
    if not legacy_id or not new_password:
        return False
    init_sqlite_db()
    with _get_sqlite_connection() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE role = ? AND legacy_id = ?",
            (role, legacy_id),
        ).fetchone()
        if not row or not verify_password(old_password, str(row["password_hash"])):
            return False
        new_hash = hash_password(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE role = ? AND legacy_id = ?",
            (new_hash, _now(), role, legacy_id),
        )
        conn.commit()
    if _postgres_enabled():
        try:
            with _get_postgres_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET password_hash = %s, updated_at = %s WHERE role = %s AND legacy_id = %s",
                        (new_hash, _now(), role, legacy_id),
                    )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PostgreSQL password update xatosi: %s", exc)
    return True


def migrate_json_to_db(json_path: Path) -> None:
    if not json_path or not json_path.is_file():
        return
    existing = get_all_data()
    if existing and (
        existing.get("students")
        or existing.get("teachers")
        or existing.get("admins")
        or existing.get("parents")
        or existing.get("employers")
    ):
        return
    try:
        with json_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data:
            save_data_dict("app_data", data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("JSON migratsiyasi xatosi: %s", exc)
