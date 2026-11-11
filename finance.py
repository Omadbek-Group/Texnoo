"""Moliya moduli: to'lovlar, xarajatlar, oylik tarif, qarzdorlik, kassa va audit log.

Qoidalar:
  - Har bir yozuv UUID bilan, markaz (center_id) bo'yicha ajratilgan.
  - Moliyaviy yozuv hech qachon o'chirilmaydi: faqat sabab bilan "bekor qilinadi" (void),
    va bu audit logga yoziladi.
  - Takroriy yozuvdan himoya: har bir yaratish so'rovi idempotency_key bilan keladi.
  - Hisobotlar faqat shu jadvallardagi real yozuvlardan hisoblanadi.
  - DATABASE_URL bo'lsa PostgreSQL, aks holda SQLite (bitta manba, nusxa ko'chirilmaydi).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator, Optional

import psycopg
from flask import Blueprint, Response, g, jsonify, request
from psycopg.rows import dict_row

from data_database import DATABASE_URL, SQLITE_PATH, get_all_data
from security import require_auth

TZ = timezone(timedelta(hours=5))  # O'zbekiston, yozgi vaqt yo'q
METHODS = ("cash", "card", "bank")
EXPENSE_CATEGORIES = ("rent", "salary", "utilities", "marketing", "supplies", "tax", "other")
MAX_AMOUNT = 1_000_000_000
_YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

bp = Blueprint("finance", __name__, url_prefix="/api/finance")

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS fin_payments (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        receipt_no TEXT NOT NULL,
        student_id BIGINT NOT NULL,
        student_name TEXT NOT NULL,
        group_name TEXT,
        amount BIGINT NOT NULL CHECK (amount > 0),
        method TEXT NOT NULL,
        period TEXT,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        void_reason TEXT,
        voided_by TEXT,
        voided_at BIGINT,
        created_by_role TEXT NOT NULL,
        created_by_id BIGINT NOT NULL,
        created_by_name TEXT,
        idempotency_key TEXT NOT NULL,
        day TEXT NOT NULL,
        created_at BIGINT NOT NULL,
        UNIQUE (center_id, receipt_no),
        UNIQUE (center_id, idempotency_key)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_fin_payments_day ON fin_payments (center_id, day)",
    "CREATE INDEX IF NOT EXISTS ix_fin_payments_student ON fin_payments (center_id, student_id)",
    """CREATE TABLE IF NOT EXISTS fin_expenses (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        category TEXT NOT NULL,
        amount BIGINT NOT NULL CHECK (amount > 0),
        method TEXT NOT NULL,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        void_reason TEXT,
        voided_by TEXT,
        voided_at BIGINT,
        created_by_role TEXT NOT NULL,
        created_by_id BIGINT NOT NULL,
        created_by_name TEXT,
        idempotency_key TEXT NOT NULL,
        day TEXT NOT NULL,
        created_at BIGINT NOT NULL,
        UNIQUE (center_id, idempotency_key)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_fin_expenses_day ON fin_expenses (center_id, day)",
    """CREATE TABLE IF NOT EXISTS fin_fees (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        student_id BIGINT NOT NULL,
        monthly_fee BIGINT NOT NULL CHECK (monthly_fee >= 0),
        effective_from TEXT NOT NULL,
        created_by_id BIGINT NOT NULL,
        created_by_name TEXT,
        created_at BIGINT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_fin_fees_student ON fin_fees (center_id, student_id)",
    """CREATE TABLE IF NOT EXISTS fin_counters (
        center_id TEXT NOT NULL,
        name TEXT NOT NULL,
        value BIGINT NOT NULL,
        PRIMARY KEY (center_id, name)
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        actor_role TEXT,
        actor_id BIGINT,
        actor_name TEXT,
        action TEXT NOT NULL,
        entity TEXT,
        entity_id TEXT,
        details TEXT,
        ip TEXT,
        created_at BIGINT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_time ON audit_log (center_id, created_at)",
    # O'quvchi hayot sikli: qabul, guruh almashishi, holat (faol/muzlatilgan/bitirgan/ketgan). Faqat qo'shiladi.
    """CREATE TABLE IF NOT EXISTS crm_events (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        student_id BIGINT NOT NULL,
        type TEXT NOT NULL,
        from_group TEXT,
        to_group TEXT,
        from_status TEXT,
        to_status TEXT,
        reason TEXT,
        effective_date TEXT NOT NULL,
        source TEXT NOT NULL,
        actor_role TEXT,
        actor_id BIGINT,
        actor_name TEXT,
        created_at BIGINT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_crm_events_student ON crm_events (center_id, student_id)",
    # Dars jadvali: haftalik takrorlanuvchi darslar. O'chirilmaydi, status='removed' bo'ladi.
    """CREATE TABLE IF NOT EXISTS sched_lessons (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        group_name TEXT NOT NULL,
        subject TEXT NOT NULL,
        teacher_id BIGINT NOT NULL,
        room TEXT,
        weekday INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_by_name TEXT,
        created_at BIGINT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_sched_lessons_day ON sched_lessons (center_id, weekday)",
    # Davomat: guruh + sana + o'quvchi bo'yicha bitta yozuv (qayta belgilansa yangilanadi).
    """CREATE TABLE IF NOT EXISTS att_records (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        lesson_date TEXT NOT NULL,
        group_name TEXT NOT NULL,
        student_id BIGINT NOT NULL,
        status TEXT NOT NULL,
        note TEXT,
        marked_by_id BIGINT,
        marked_by_name TEXT,
        updated_at BIGINT NOT NULL,
        UNIQUE (center_id, lesson_date, group_name, student_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_att_records_student ON att_records (center_id, student_id, lesson_date)",
    # Qabul: kursga yozilmoqchi bo'lgan yangi kelganlar (fan bo'yicha), guruh ochilguncha kutadi.
    """CREATE TABLE IF NOT EXISTS crm_leads (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        subject TEXT NOT NULL,
        note TEXT,
        status TEXT NOT NULL DEFAULT 'new',
        student_id BIGINT,
        created_by_name TEXT,
        created_at BIGINT NOT NULL,
        updated_at BIGINT NOT NULL
    )""",
    # O'qituvchiga berilgan avans/oylik (har biri kassada xarajat sifatida ham yoziladi).
    """CREATE TABLE IF NOT EXISTS sal_payouts (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        teacher_id BIGINT NOT NULL,
        month TEXT NOT NULL,
        kind TEXT NOT NULL,
        amount BIGINT NOT NULL CHECK (amount > 0),
        note TEXT,
        expense_id TEXT,
        created_by_name TEXT,
        created_at BIGINT NOT NULL
    )""",
    # Bir marta yuboriladigan xabarlar (tug'ilgan kun tabrigi) jurnali.
    "CREATE TABLE IF NOT EXISTS notif_log (key TEXT PRIMARY KEY, created_at BIGINT NOT NULL)",
    # O'qituvchi oylik sharti: qat'iy (so'm) yoki foiz (value = foiz * 100). Tarix saqlanadi.
    """CREATE TABLE IF NOT EXISTS sal_rules (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        teacher_id BIGINT NOT NULL,
        type TEXT NOT NULL,
        value BIGINT NOT NULL CHECK (value >= 0),
        effective_from TEXT NOT NULL,
        created_by_name TEXT,
        created_at BIGINT NOT NULL
    )""",
]

_initialized = False


# --------------------------------------------------------------------------
# DB yordamchilari (SQLite va PostgreSQL uchun bitta kod)
# --------------------------------------------------------------------------
def _pg() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def _db() -> Iterator[Any]:
    if _pg():
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=15)
    else:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(SQLITE_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _x(conn: Any, sql: str, params: tuple | list = ()) -> Any:
    return conn.execute(sql.replace("?", "%s") if _pg() else sql, tuple(params))


def _all(conn: Any, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in _x(conn, sql, params).fetchall()]


def _one(conn: Any, sql: str, params: tuple | list = ()) -> Optional[dict[str, Any]]:
    row = _x(conn, sql, params).fetchone()
    return dict(row) if row else None


def _is_unique_violation(exc: Exception) -> bool:
    return isinstance(exc, (sqlite3.IntegrityError, psycopg.errors.UniqueViolation))


def init_finance_db() -> None:
    global _initialized
    if _initialized:
        return
    with _db() as conn:
        for stmt in _SCHEMA:
            _x(conn, stmt)
        # Mavjud bazalar uchun migratsiya (yangi ustunlar).
        for table, column, ddl in (("fin_payments", "teacher_id", "BIGINT"),
                                   ("fin_fees", "discount_pct", "INTEGER NOT NULL DEFAULT 0"),
                                   ("fin_fees", "discount_reason", "TEXT"),
                                   ("crm_leads", "trial_at", "TEXT"),
                                   ("crm_leads", "trial_group", "TEXT"),
                                   ("crm_leads", "source", "TEXT"),
                                   ("sal_rules", "start_date", "TEXT")):
            if _pg():
                _x(conn, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
            elif column not in {r["name"] for r in _all(conn, f"PRAGMA table_info({table})")}:
                _x(conn, f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    _initialized = True


@bp.before_request
def _ensure_schema() -> None:
    init_finance_db()


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------
def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.remote_addr) or ""


def _audit(conn: Any, principal: Optional[dict[str, Any]], action: str, entity: str = "",
           entity_id: str = "", details: Optional[dict[str, Any]] = None, center: str = "") -> None:
    _x(conn, """INSERT INTO audit_log
        (id, center_id, actor_role, actor_id, actor_name, action, entity, entity_id, details, ip, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        str(uuid.uuid4()),
        center or (principal or {}).get("center") or "main",
        (principal or {}).get("role"),
        (principal or {}).get("id"),
        (principal or {}).get("name"),
        action, entity, str(entity_id or ""),
        json.dumps(details or {}, ensure_ascii=False)[:4000],
        _client_ip(),
        _now_ms(),
    ))


def audit(principal: Optional[dict[str, Any]], action: str, entity: str = "", entity_id: Any = "",
          details: Optional[dict[str, Any]] = None, center: str = "") -> None:
    """Moliya modulidan tashqaridagi hodisalar uchun (login, import, ...). Xato ilovani to'xtatmaydi."""
    try:
        init_finance_db()
        with _db() as conn:
            _audit(conn, principal, action, entity, str(entity_id or ""), details, center)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("finance").exception("Audit log yozilmadi: %s", action)


# --------------------------------------------------------------------------
# Umumiy yordamchilar
# --------------------------------------------------------------------------
def _now_ms() -> int:
    return int(time.time() * 1000)


def _today() -> date:
    return datetime.now(TZ).date()


def _this_month() -> str:
    return _today().strftime("%Y-%m")


def _err(message: str, code: int = 400):
    return jsonify({"ok": False, "status": "error", "message": message}), code


def _body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _amount(value: Any) -> Optional[int]:
    try:
        number = int(str(value).replace(" ", ""))
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= MAX_AMOUNT else None


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _norm_phone(value: Any) -> str:
    return re.sub(r"[\s\-()]", "", str(value or "")).lower()


def _student_name(s: dict[str, Any]) -> str:
    full = f"{s.get('firstName') or ''} {s.get('lastName') or ''}".strip()
    return str(s.get("name") or full or f"#{s.get('id')}")


def _center_students(center: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for s in get_all_data().get("students", []):
        if not isinstance(s, dict):
            continue
        if str(s.get("centerId") or "main") != center:
            continue
        try:
            out[int(s.get("id"))] = s
        except (TypeError, ValueError):
            continue
    return out


def _date_range() -> tuple[str, str]:
    today = _today()
    start = request.args.get("from", "") or today.replace(day=1).isoformat()
    end = request.args.get("to", "") or today.isoformat()
    if not _DAY_RE.match(start) or not _DAY_RE.match(end):
        raise ValueError("Sana formati YYYY-MM-DD bo'lishi kerak")
    if start > end:
        start, end = end, start
    return start, end


def _paging() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(100, max(1, int(request.args.get("page_size", 25))))
    except ValueError:
        page, size = 1, 25
    return page, size


def _months(start_ym: str, end_ym: str) -> list[str]:
    out: list[str] = []
    y, m = int(start_ym[:4]), int(start_ym[5:7])
    while f"{y:04d}-{m:02d}" <= end_ym:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def billable_month(status_events: list[dict[str, Any]], ym: str) -> bool:
    """Oy uchun to'lov hisoblanadimi: o'quvchi shu oyning kamida bir kunida faol bo'lgan bo'lsa — ha.

    status_events: to_status va effective_date (YYYY-MM-DD) maydonli holat hodisalari.
    Hodisa bo'lmasa o'quvchi faol hisoblanadi.
    shortcut: oy qismlarga bo'linmaydi (prorata yo'q); kerak bo'lsa kunlik hisobga o'tkazing.
    """
    ordered = sorted(status_events, key=lambda e: (e["effective_date"], e["created_at"]))
    start = ym + "-01"
    # 1-sanadagi holat: shu kungacha (shu kun ham) kuchga kirgan oxirgi hodisa.
    at_start = [e for e in ordered if e["effective_date"] <= start]
    if not at_start or at_start[-1]["to_status"] == "active":
        return True
    return any(e["to_status"] == "active" for e in ordered if start < e["effective_date"] and e["effective_date"][:7] == ym)


def net_fee(fee: dict[str, Any]) -> int:
    """Chegirmadan keyingi oylik summa."""
    return int(fee["monthly_fee"]) * (100 - int(fee.get("discount_pct") or 0)) // 100


def fee_for_month(fees: list[dict[str, Any]], month: str) -> Optional[dict[str, Any]]:
    current = sorted((f for f in fees if f["effective_from"] <= month), key=lambda f: (f["effective_from"], f["created_at"]))
    return current[-1] if current else None


def compute_charges(fees: list[dict[str, Any]], as_of_ym: str,
                    status_events: Optional[list[dict[str, Any]]] = None) -> int:
    """Oylik tarif tarixidan as_of_ym oyigacha (shu oy ham) hisoblangan jami summa.

    Bir oy uchun shu oydan oldin/shu oyda kuchga kirgan eng oxirgi tarif olinadi;
    bir oyga bir nechta tarif kiritilgan bo'lsa, eng keyin kiritilgani amal qiladi.
    Tarif 0 bo'lsa, o'sha oydan boshlab hisoblash to'xtaydi.
    Muzlatilgan/bitirgan/ketgan o'quvchi uchun butun oy nofaol bo'lsa, o'sha oy hisoblanmaydi.
    """
    if not fees:
        return 0
    ordered = sorted(fees, key=lambda f: (f["effective_from"], f["created_at"]))
    total = 0
    for month in _months(ordered[0]["effective_from"], as_of_ym):
        if status_events and not billable_month(status_events, month):
            continue
        current = fee_for_month(ordered, month)
        total += net_fee(current) if current else 0
    return total


def _balances(conn: Any, center: str, student_ids: Optional[list[int]] = None) -> dict[int, dict[str, int]]:
    """Har bir talaba uchun: hisoblangan, to'langan, qarz (manfiy = avans), joriy tarif."""
    fee_rows = _all(conn, """SELECT student_id, monthly_fee, discount_pct, discount_reason, effective_from, created_at
        FROM fin_fees WHERE center_id = ?""", (center,))
    paid_rows = _all(conn, """SELECT student_id, SUM(amount) AS paid FROM fin_payments
        WHERE center_id = ? AND status = 'active' GROUP BY student_id""", (center,))
    status_rows = _all(conn, """SELECT student_id, to_status, effective_date, created_at FROM crm_events
        WHERE center_id = ? AND type IN ('status_changed', 'enrolled')""", (center,))
    fees: dict[int, list[dict[str, Any]]] = {}
    for row in fee_rows:
        fees.setdefault(int(row["student_id"]), []).append(row)
    statuses: dict[int, list[dict[str, Any]]] = {}
    for row in status_rows:
        statuses.setdefault(int(row["student_id"]), []).append(row)
    paid = {int(r["student_id"]): int(r["paid"] or 0) for r in paid_rows}
    month = _this_month()
    ids = set(student_ids) if student_ids is not None else set(fees) | set(paid)
    out: dict[int, dict[str, int]] = {}
    for sid in ids:
        student_fees = fees.get(sid, [])
        charged = compute_charges(student_fees, month, statuses.get(sid))
        current = fee_for_month(student_fees, month)
        out[sid] = {
            "charged": charged,
            "paid": paid.get(sid, 0),
            "debt": charged - paid.get(sid, 0),
            "monthly_fee": net_fee(current) if current else 0,
            "base_fee": int(current["monthly_fee"]) if current else 0,
            "discount_pct": int(current.get("discount_pct") or 0) if current else 0,
            "discount_reason": (current.get("discount_reason") or "") if current else "",
        }
    return out


def _public_payment(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.pop("idempotency_key", None)
    return out


# --------------------------------------------------------------------------
# To'lovlar
# --------------------------------------------------------------------------
def _list_query(extra_where: list[str], extra_params: list[Any]):
    p = g.principal
    try:
        start, end = _date_range()
    except ValueError as exc:
        return None, _err(str(exc))
    where = ["center_id = ?", "day >= ?", "day <= ?"] + extra_where
    params: list[Any] = [p["center"], start, end] + extra_params
    status = request.args.get("status", "")
    if status in ("active", "void"):
        where.append("status = ?")
        params.append(status)
    method = request.args.get("method", "")
    if method in METHODS:
        where.append("method = ?")
        params.append(method)
    return (" AND ".join(where), params), None


@bp.get("/payments")
@require_auth("admin", "cashier")
def list_payments():
    extra_where: list[str] = []
    extra_params: list[Any] = []
    if request.args.get("student_id", "").isdigit():
        extra_where.append("student_id = ?")
        extra_params.append(int(request.args["student_id"]))
    q = _text(request.args.get("q"), 80).lower()
    if q:
        extra_where.append("(lower(student_name) LIKE ? OR lower(receipt_no) LIKE ? OR lower(coalesce(group_name, '')) LIKE ?)")
        extra_params += [f"%{q}%"] * 3
    built, error = _list_query(extra_where, extra_params)
    if error:
        return error
    where, params = built
    page, size = _paging()
    sort = {"amount": "amount DESC", "oldest": "created_at ASC"}.get(request.args.get("sort", ""), "created_at DESC")
    with _db() as conn:
        total = _one(conn, f"SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status = 'active' THEN amount ELSE 0 END), 0) AS s FROM fin_payments WHERE {where}", params)
        rows = _all(conn, f"SELECT * FROM fin_payments WHERE {where} ORDER BY {sort} LIMIT ? OFFSET ?", params + [size, (page - 1) * size])
    return jsonify({"ok": True, "items": [_public_payment(r) for r in rows], "total": int(total["n"]),
                    "sum": int(total["s"]), "page": page, "page_size": size})


@bp.post("/payments")
@require_auth("admin", "cashier")
def create_payment():
    p = g.principal
    body = _body()
    key = _text(body.get("idempotency_key"), 64)
    if not _KEY_RE.match(key):
        return _err("idempotency_key kerak")
    amount = _amount(body.get("amount"))
    if amount is None:
        return _err(f"Summa 1 dan {MAX_AMOUNT:,} so'mgacha butun son bo'lishi kerak")
    method = str(body.get("method") or "")
    if method not in METHODS:
        return _err("To'lov turi: naqd, plastik yoki bank")
    period = _text(body.get("period"), 7) or _this_month()
    if not _YM_RE.match(period):
        return _err("Davr formati YYYY-MM bo'lishi kerak")
    try:
        student_id = int(body.get("student_id"))
    except (TypeError, ValueError):
        return _err("O'quvchini tanlang")
    student = _center_students(p["center"]).get(student_id)
    if not student:
        return _err("O'quvchi topilmadi", 404)
    note = _text(body.get("note"), 500)

    with _db() as conn:
        existing = _one(conn, "SELECT * FROM fin_payments WHERE center_id = ? AND idempotency_key = ?", (p["center"], key))
        if existing:
            return jsonify({"ok": True, "duplicate": True, "payment": _public_payment(existing)})
        block = _period_block(conn, p["center"], student_id, period, amount)
        if block:
            return _err(block, 409)
        seq = _one(conn, """INSERT INTO fin_counters (center_id, name, value) VALUES (?, 'receipt', 1)
            ON CONFLICT (center_id, name) DO UPDATE SET value = fin_counters.value + 1 RETURNING value""", (p["center"],))
        now = _now_ms()
        today = _today()
        payment = {
            "id": str(uuid.uuid4()),
            "center_id": p["center"],
            "receipt_no": f"TX-{today.year}-{int(seq['value']):06d}",
            "student_id": student_id,
            "student_name": _student_name(student),
            "group_name": str(student.get("group") or ""),
            "teacher_id": int(student.get("teacherId") or 0) or None,
            "amount": amount,
            "method": method,
            "period": period,
            "note": note,
            "status": "active",
            "created_by_role": p["role"] if not p["level"] else p["level"],
            "created_by_id": p["id"],
            "created_by_name": p["name"],
            "idempotency_key": key,
            "day": today.isoformat(),
            "created_at": now,
        }
        cols = list(payment)
        try:
            _x(conn, f"INSERT INTO fin_payments ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
               [payment[c] for c in cols])
        except Exception as exc:  # noqa: BLE001
            if not _is_unique_violation(exc):
                raise
            conn.rollback()
            existing = _one(conn, "SELECT * FROM fin_payments WHERE center_id = ? AND idempotency_key = ?", (p["center"], key))
            if existing:
                return jsonify({"ok": True, "duplicate": True, "payment": _public_payment(existing)})
            raise
        _audit(conn, p, "payment.create", "payment", payment["id"], {
            "receipt_no": payment["receipt_no"], "student_id": student_id, "amount": amount, "method": method, "period": period,
        })
    return jsonify({"ok": True, "payment": _public_payment(payment)}), 201


def _period_block(conn: Any, center: str, student_id: int, period: str, amount: int) -> Optional[str]:
    """Bir oy uchun qayta yoki ortiqcha to'lovni to'xtatadi. Xato matni yoki None."""
    paid_rows = _all(conn, """SELECT amount FROM fin_payments WHERE center_id = ? AND student_id = ? AND period = ?
        AND status = 'active'""", (center, student_id, period))
    paid = sum(int(r["amount"]) for r in paid_rows)
    fees = _all(conn, "SELECT monthly_fee, discount_pct, effective_from, created_at FROM fin_fees WHERE center_id = ? AND student_id = ?",
                (center, student_id))
    fee = fee_for_month(fees, period)
    due = net_fee(fee) if fee else 0
    if due:
        if paid >= due:
            return f"{period} oyi uchun to'lov to'liq qilingan ({paid:,} so'm). Qayta to'lab bo'lmaydi.".replace(",", " ")
        if paid + amount > due:
            return f"{period} oyi uchun qolgan summa: {due - paid:,} so'm.".replace(",", " ")
    elif any(int(r["amount"]) == amount for r in paid_rows):
        return f"{period} oyi uchun xuddi shu summa allaqachon to'langan. Qayta to'lab bo'lmaydi."
    return None


def _can_view_student(principal: dict[str, Any], student_id: int) -> bool:
    if principal["role"] == "admin":
        return True
    if principal["role"] == "student":
        return principal["id"] == student_id
    if principal["role"] == "parent":
        return student_id in _parent_child_ids(principal)
    return False


def _parent_child_ids(principal: dict[str, Any]) -> list[int]:
    data = get_all_data()
    parent = next((x for x in data.get("parents", []) if int(x.get("id") or 0) == principal["id"]), None)
    if not parent:
        return []
    phones = list(parent.get("childPhones") or []) or ([parent["childPhone"]] if parent.get("childPhone") else [])
    wanted = {_norm_phone(ph) for ph in phones if ph}
    return [int(s["id"]) for s in data.get("students", []) if s.get("phone") and _norm_phone(s["phone"]) in wanted]


@bp.get("/payments/<payment_id>")
@require_auth()
def get_payment(payment_id: str):
    p = g.principal
    with _db() as conn:
        row = _one(conn, "SELECT * FROM fin_payments WHERE id = ? AND center_id = ?", (payment_id, p["center"]))
    if not row or not _can_view_student(p, int(row["student_id"])):
        return _err("To'lov topilmadi", 404)
    school = (get_all_data().get("settings") or {}).get("schoolName") or "TEXNOO"
    return jsonify({"ok": True, "payment": _public_payment(row), "school_name": school})


@bp.post("/payments/<payment_id>/void")
@require_auth("admin")
def void_payment(payment_id: str):
    return _void("fin_payments", "payment", payment_id)


def _void(table: str, entity: str, entity_id: str):
    p = g.principal
    reason = _text(_body().get("reason"), 300)
    if len(reason) < 3:
        return _err("Bekor qilish sababini yozing")
    with _db() as conn:
        row = _one(conn, f"SELECT * FROM {table} WHERE id = ? AND center_id = ?", (entity_id, p["center"]))
        if not row:
            return _err("Yozuv topilmadi", 404)
        if row["status"] != "active":
            return _err("Yozuv allaqachon bekor qilingan", 409)
        _x(conn, f"UPDATE {table} SET status = 'void', void_reason = ?, voided_by = ?, voided_at = ? WHERE id = ? AND status = 'active'",
           (reason, f"{p['name']} (#{p['id']})", _now_ms(), entity_id))
        _audit(conn, p, f"{entity}.void", entity, entity_id, {"reason": reason, "amount": int(row["amount"])})
        row = _one(conn, f"SELECT * FROM {table} WHERE id = ?", (entity_id,))
    return jsonify({"ok": True, entity: _public_payment(row)})


# --------------------------------------------------------------------------
# Xarajatlar
# --------------------------------------------------------------------------
@bp.get("/expenses")
@require_auth("admin", "cashier")
def list_expenses():
    extra_where: list[str] = []
    extra_params: list[Any] = []
    category = request.args.get("category", "")
    if category in EXPENSE_CATEGORIES:
        extra_where.append("category = ?")
        extra_params.append(category)
    built, error = _list_query(extra_where, extra_params)
    if error:
        return error
    where, params = built
    page, size = _paging()
    with _db() as conn:
        total = _one(conn, f"SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status = 'active' THEN amount ELSE 0 END), 0) AS s FROM fin_expenses WHERE {where}", params)
        rows = _all(conn, f"SELECT * FROM fin_expenses WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [size, (page - 1) * size])
    return jsonify({"ok": True, "items": [_public_payment(r) for r in rows], "total": int(total["n"]),
                    "sum": int(total["s"]), "page": page, "page_size": size})


@bp.post("/expenses")
@require_auth("admin", "cashier")
def create_expense():
    p = g.principal
    body = _body()
    key = _text(body.get("idempotency_key"), 64)
    if not _KEY_RE.match(key):
        return _err("idempotency_key kerak")
    amount = _amount(body.get("amount"))
    if amount is None:
        return _err(f"Summa 1 dan {MAX_AMOUNT:,} so'mgacha butun son bo'lishi kerak")
    method = str(body.get("method") or "")
    if method not in METHODS:
        return _err("To'lov turi: naqd, plastik yoki bank")
    category = str(body.get("category") or "")
    if category not in EXPENSE_CATEGORIES:
        return _err("Xarajat kategoriyasini tanlang")
    note = _text(body.get("note"), 500)
    with _db() as conn:
        existing = _one(conn, "SELECT * FROM fin_expenses WHERE center_id = ? AND idempotency_key = ?", (p["center"], key))
        if existing:
            return jsonify({"ok": True, "duplicate": True, "expense": _public_payment(existing)})
        expense = {
            "id": str(uuid.uuid4()),
            "center_id": p["center"],
            "category": category,
            "amount": amount,
            "method": method,
            "note": note,
            "status": "active",
            "created_by_role": p["role"] if not p["level"] else p["level"],
            "created_by_id": p["id"],
            "created_by_name": p["name"],
            "idempotency_key": key,
            "day": _today().isoformat(),
            "created_at": _now_ms(),
        }
        cols = list(expense)
        try:
            _x(conn, f"INSERT INTO fin_expenses ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
               [expense[c] for c in cols])
        except Exception as exc:  # noqa: BLE001
            if not _is_unique_violation(exc):
                raise
            conn.rollback()
            existing = _one(conn, "SELECT * FROM fin_expenses WHERE center_id = ? AND idempotency_key = ?", (p["center"], key))
            if existing:
                return jsonify({"ok": True, "duplicate": True, "expense": _public_payment(existing)})
            raise
        _audit(conn, p, "expense.create", "expense", expense["id"], {"amount": amount, "category": category, "method": method})
    return jsonify({"ok": True, "expense": _public_payment(expense)}), 201


@bp.post("/expenses/<expense_id>/void")
@require_auth("admin")
def void_expense(expense_id: str):
    return _void("fin_expenses", "expense", expense_id)


# --------------------------------------------------------------------------
# Oylik tarif va qarzdorlik
# --------------------------------------------------------------------------
@bp.get("/fees")
@require_auth("admin", "cashier")
def list_fees():
    p = g.principal
    students = _center_students(p["center"])
    with _db() as conn:
        balances = _balances(conn, p["center"], list(students))
        history: list[dict[str, Any]] = []
        if request.args.get("student_id", "").isdigit():
            history = _all(conn, """SELECT * FROM fin_fees WHERE center_id = ? AND student_id = ?
                ORDER BY effective_from DESC, created_at DESC""", (p["center"], int(request.args["student_id"])))
    items = [{
        "student_id": sid,
        "student_name": _student_name(s),
        "group_name": str(s.get("group") or ""),
        **balances.get(sid, {"charged": 0, "paid": 0, "debt": 0, "monthly_fee": 0}),
    } for sid, s in students.items()]
    items.sort(key=lambda r: (r["group_name"], r["student_name"]))
    return jsonify({"ok": True, "items": items, "history": history, "month": _this_month()})


@bp.post("/fees")
@require_auth("admin")
def set_fee():
    p = g.principal
    body = _body()
    try:
        student_id = int(body.get("student_id"))
        fee = int(str(body.get("monthly_fee")).replace(" ", ""))
    except (TypeError, ValueError):
        return _err("O'quvchi va oylik summani kiriting")
    if not 0 <= fee <= MAX_AMOUNT:
        return _err("Oylik summa noto'g'ri")
    effective_from = _text(body.get("effective_from"), 7) or _this_month()
    if not _YM_RE.match(effective_from):
        return _err("Boshlanish oyi YYYY-MM formatida bo'lishi kerak")
    if student_id not in _center_students(p["center"]):
        return _err("O'quvchi topilmadi", 404)
    try:
        discount = int(str(body.get("discount_pct") or 0).replace(" ", ""))
    except ValueError:
        return _err("Chegirma foizi butun son bo'lsin")
    reason = _text(body.get("discount_reason"), 300)
    if not 0 <= discount <= 100:
        return _err("Chegirma 0 dan 100 foizgacha bo'lsin")
    if discount and len(reason) < 3:
        return _err("Chegirma sababini yozing")
    row = {
        "id": str(uuid.uuid4()),
        "center_id": p["center"],
        "student_id": student_id,
        "monthly_fee": fee,
        "discount_pct": discount,
        "discount_reason": reason if discount else "",
        "effective_from": effective_from,
        "created_by_id": p["id"],
        "created_by_name": p["name"],
        "created_at": _now_ms(),
    }
    cols = list(row)
    with _db() as conn:
        _x(conn, f"INSERT INTO fin_fees ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        _audit(conn, p, "fee.set", "student", student_id, {"monthly_fee": fee, "effective_from": effective_from,
                                                             "discount_pct": discount, "reason": row["discount_reason"]})
        balance = _balances(conn, p["center"], [student_id])[student_id]
    return jsonify({"ok": True, "fee": row, "balance": balance}), 201


@bp.get("/debtors")
@require_auth("admin", "cashier")
def debtors():
    p = g.principal
    students = _center_students(p["center"])
    with _db() as conn:
        balances = _balances(conn, p["center"], list(students))
    items = []
    for sid, bal in balances.items():
        if bal["debt"] <= 0:
            continue
        s = students[sid]
        items.append({
            "student_id": sid,
            "student_name": _student_name(s),
            "group_name": str(s.get("group") or ""),
            "phone": str(s.get("phone") or ""),
            **bal,
            "months_owed": round(bal["debt"] / bal["monthly_fee"], 1) if bal["monthly_fee"] else None,
        })
    items.sort(key=lambda r: -r["debt"])
    return jsonify({"ok": True, "items": items, "count": len(items), "total": sum(r["debt"] for r in items)})


# --------------------------------------------------------------------------
# Dashboard / kassa
# --------------------------------------------------------------------------
@bp.get("/summary")
@require_auth("admin", "cashier")
def summary():
    p = g.principal
    try:
        start, end = _date_range()
    except ValueError as exc:
        return _err(str(exc))
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 366:
        return _err("Oraliq 1 yildan oshmasin")
    center = p["center"]
    students = _center_students(center)
    with _db() as conn:
        income_rows = _all(conn, """SELECT day, method, SUM(amount) AS s, COUNT(*) AS n FROM fin_payments
            WHERE center_id = ? AND status = 'active' AND day >= ? AND day <= ? GROUP BY day, method""", (center, start, end))
        expense_rows = _all(conn, """SELECT day, method, category, SUM(amount) AS s FROM fin_expenses
            WHERE center_id = ? AND status = 'active' AND day >= ? AND day <= ? GROUP BY day, method, category""", (center, start, end))
        all_income = _all(conn, """SELECT method, SUM(amount) AS s FROM fin_payments
            WHERE center_id = ? AND status = 'active' GROUP BY method""", (center,))
        all_expense = _all(conn, """SELECT method, SUM(amount) AS s FROM fin_expenses
            WHERE center_id = ? AND status = 'active' GROUP BY method""", (center,))
        balances = _balances(conn, center, list(students))

    income_by_method = {m: 0 for m in METHODS}
    expense_by_method = {m: 0 for m in METHODS}
    expense_by_category: dict[str, int] = {}
    series: dict[str, dict[str, int]] = {}
    payments_count = 0
    for r in income_rows:
        income_by_method[r["method"]] = income_by_method.get(r["method"], 0) + int(r["s"])
        series.setdefault(r["day"], {"income": 0, "expense": 0})["income"] += int(r["s"])
        payments_count += int(r["n"])
    for r in expense_rows:
        expense_by_method[r["method"]] = expense_by_method.get(r["method"], 0) + int(r["s"])
        expense_by_category[r["category"]] = expense_by_category.get(r["category"], 0) + int(r["s"])
        series.setdefault(r["day"], {"income": 0, "expense": 0})["expense"] += int(r["s"])

    day = date.fromisoformat(start)
    daily = []
    while day.isoformat() <= end:
        key = day.isoformat()
        daily.append({"day": key, **series.get(key, {"income": 0, "expense": 0})})
        day += timedelta(days=1)

    inc_all = {r["method"]: int(r["s"]) for r in all_income}
    exp_all = {r["method"]: int(r["s"]) for r in all_expense}
    income = sum(income_by_method.values())
    expense = sum(expense_by_method.values())
    debt_rows = [b for b in balances.values() if b["debt"] > 0]
    return jsonify({
        "ok": True,
        "from": start,
        "to": end,
        "income": income,
        "income_by_method": income_by_method,
        "payments_count": payments_count,
        "expense": expense,
        "expense_by_method": expense_by_method,
        "expense_by_category": expense_by_category,
        "net": income - expense,
        "daily": daily,
        "balance_by_method": {m: inc_all.get(m, 0) - exp_all.get(m, 0) for m in METHODS},
        "debtors_count": len(debt_rows),
        "debt_total": sum(b["debt"] for b in debt_rows),
        "students_total": len(students),
        "students_billed": sum(1 for b in balances.values() if b["monthly_fee"] > 0),
    })


@bp.get("/export")
@require_auth("admin", "cashier")
def export_csv():
    p = g.principal
    kind = request.args.get("kind", "payments")
    try:
        start, end = _date_range()
    except ValueError as exc:
        return _err(str(exc))
    if kind == "payments":
        cols = ["receipt_no", "day", "student_id", "student_name", "group_name", "amount", "method", "period",
                "status", "void_reason", "created_by_name", "note"]
        table = "fin_payments"
    elif kind == "expenses":
        cols = ["day", "category", "amount", "method", "status", "void_reason", "created_by_name", "note"]
        table = "fin_expenses"
    else:
        return _err("kind: payments yoki expenses")
    with _db() as conn:
        rows = _all(conn, f"SELECT {', '.join(cols)} FROM {table} WHERE center_id = ? AND day >= ? AND day <= ? ORDER BY created_at",
                    (p["center"], start, end))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for r in rows:
        # Excel formula injection oldini olish
        writer.writerow(["'" + str(v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in (r[c] for c in cols)])
    with _db() as conn:
        _audit(conn, p, "finance.export", kind, "", {"from": start, "to": end, "rows": len(rows)})
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kind}_{start}_{end}.csv"'})


@bp.get("/audit")
@require_auth("admin")
def audit_list():
    p = g.principal
    page, size = _paging()
    with _db() as conn:
        total = _one(conn, "SELECT COUNT(*) AS n FROM audit_log WHERE center_id = ?", (p["center"],))
        rows = _all(conn, "SELECT * FROM audit_log WHERE center_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (p["center"], size, (page - 1) * size))
    for r in rows:
        try:
            r["details"] = json.loads(r.get("details") or "{}")
        except ValueError:
            pass
    return jsonify({"ok": True, "items": rows, "total": int(total["n"]), "page": page, "page_size": size})


# --------------------------------------------------------------------------
# O'quvchi / ota-ona: o'z to'lov holati
# --------------------------------------------------------------------------
@bp.get("/my")
@require_auth("student", "parent")
def my_finance():
    p = g.principal
    ids = [p["id"]] if p["role"] == "student" else _parent_child_ids(p)
    students = _center_students(p["center"])
    ids = [i for i in ids if i in students]
    out = []
    with _db() as conn:
        balances = _balances(conn, p["center"], ids)
        for sid in ids:
            payments = _all(conn, """SELECT * FROM fin_payments WHERE center_id = ? AND student_id = ?
                ORDER BY created_at DESC LIMIT 50""", (p["center"], sid))
            out.append({
                "student_id": sid,
                "student_name": _student_name(students[sid]),
                "group_name": str(students[sid].get("group") or ""),
                **balances[sid],
                "payments": [_public_payment(r) for r in payments],
            })
    return jsonify({"ok": True, "items": out, "month": _this_month()})
