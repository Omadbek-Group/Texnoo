"""CRM: o'quvchi hayot sikli — qabul, guruhga biriktirish/ko'chirish, muzlatish, qayta faollashtirish,
bitiruvchilar va ketganlar arxivi, o'quvchi tarixi.

Joriy holat va guruh legacy datasetdagi talaba yozuvida saqlanadi (ilovaning qolgan qismi shuni o'qiydi),
har bir o'zgarish esa crm_events jadvaliga o'chmas tarix sifatida yoziladi.
Talaba hech qachon o'chirilmaydi: o'chirish o'rniga "ketgan" holatiga o'tadi.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from datetime import date, timedelta
from typing import Any, Callable, Optional

from flask import Blueprint, g, jsonify, request

from finance import (
    _all, _audit, _balances, _body, _db, _err, _now_ms, _one, _paging, _text, _this_month, _today, _x,
    _student_name, _norm_phone, init_finance_db, MAX_AMOUNT, _YM_RE, _DAY_RE,
)
from security import require_auth

STATUSES = ("active", "frozen", "graduated", "left")
ARCHIVED = {"graduated", "left"}
STATUS_LABEL = {"active": "Faol", "frozen": "Muzlatilgan", "graduated": "Bitirgan", "left": "Ketgan"}
# Ruxsat etilgan o'tishlar (qaerdan -> qaerga)
TRANSITIONS = {
    "active": {"frozen", "graduated", "left"},
    "frozen": {"active", "graduated", "left"},
    "graduated": {"active"},
    "left": {"active"},
}

bp = Blueprint("crm", __name__, url_prefix="/api/crm")

# app.py o'rnatadi: (read_data, write_data, normalize_data, lock) — aylanma importdan qochish uchun.
_dataset: dict[str, Any] = {}


def configure(read_data: Callable, write_data: Callable, normalize_data: Callable, lock: Any) -> None:
    _dataset.update(read=read_data, write=write_data, normalize=normalize_data, lock=lock)


@bp.before_request
def _ensure_schema() -> None:
    init_finance_db()


def student_status(s: dict[str, Any]) -> str:
    status = str(s.get("status") or "active")
    return status if status in STATUSES else "active"


def record_events(principal: Optional[dict[str, Any]], events: list[dict[str, Any]], center: str = "main") -> None:
    """Hodisalarni yozadi. events: student_id, type va ixtiyoriy maydonlar."""
    if not events:
        return
    init_finance_db()
    with _db() as conn:
        for ev in events:
            _insert_event(conn, principal, ev, center)


def _insert_event(conn: Any, principal: Optional[dict[str, Any]], ev: dict[str, Any], center: str) -> dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "center_id": (principal or {}).get("center") or center,
        "student_id": int(ev["student_id"]),
        "type": ev["type"],
        "from_group": ev.get("from_group"),
        "to_group": ev.get("to_group"),
        "from_status": ev.get("from_status"),
        "to_status": ev.get("to_status"),
        "reason": (ev.get("reason") or "")[:300],
        "effective_date": ev.get("effective_date") or _today().isoformat(),
        "source": ev.get("source") or "crm",
        "actor_role": (principal or {}).get("level") or (principal or {}).get("role"),
        "actor_id": (principal or {}).get("id"),
        "actor_name": (principal or {}).get("name"),
        "created_at": _now_ms(),
    }
    cols = list(row)
    _x(conn, f"INSERT INTO crm_events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
    return row


def _effective_date(value: Any) -> Optional[str]:
    raw = _text(value, 10) or _today().isoformat()
    if not _DAY_RE.match(raw):
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    return raw if abs((day - _today()).days) <= 366 else None


def _students(center: str) -> list[dict[str, Any]]:
    return [s for s in _dataset["read"]().get("students", [])
            if isinstance(s, dict) and str(s.get("centerId") or "main") == center]


def _public(s: dict[str, Any], balance: Optional[dict[str, int]] = None) -> dict[str, Any]:
    return {
        "id": int(s.get("id") or 0),
        "name": _student_name(s),
        "firstName": s.get("firstName") or "",
        "lastName": s.get("lastName") or "",
        "phone": s.get("phone") or "",
        "parentPhone": s.get("parentPhone") or "",
        "group": s.get("group") or "",
        "extraGroups": [str(x) for x in s.get("extraGroups") or []] if isinstance(s.get("extraGroups"), list) else [],
        "birthDate": s.get("birthDate") or "",
        "address": s.get("address") or "",
        "source": s.get("source") or "",
        "status": student_status(s),
        "teacherId": s.get("teacherId"),
        **(balance or {"charged": 0, "paid": 0, "debt": 0, "monthly_fee": 0}),
    }


# --------------------------------------------------------------------------
# O'qish
# --------------------------------------------------------------------------
@bp.get("/summary")
@require_auth("admin", "cashier", "manager")
def summary():
    p = g.principal
    students = _students(p["center"])
    counts = {k: 0 for k in STATUSES}
    for s in students:
        counts[student_status(s)] += 1
    month = _this_month()
    with _db() as conn:
        month_events = _all(conn, """SELECT type, to_status, COUNT(*) AS n FROM crm_events
            WHERE center_id = ? AND effective_date >= ? AND effective_date <= ? GROUP BY type, to_status""",
                            (p["center"], month + "-01", month + "-31"))
    new = sum(int(r["n"]) for r in month_events if r["type"] == "enrolled")
    gone = sum(int(r["n"]) for r in month_events if r["type"] == "status_changed" and r["to_status"] in ARCHIVED)
    return jsonify({"ok": True, "counts": counts, "total": len(students) - counts["graduated"] - counts["left"],
                    "new_this_month": new, "left_this_month": gone, "month": month})


@bp.get("/groups")
@require_auth("admin", "cashier", "manager")
def groups():
    p = g.principal
    data = _dataset["read"]()
    names = {str(x.get("name")) for x in data.get("groups", []) if isinstance(x, dict) and x.get("name")}
    stats: dict[str, dict[str, int]] = {}
    for s in _students(p["center"]):
        name = str(s.get("group") or "")
        if not name:
            continue
        names.add(name)
        stats.setdefault(name, {k: 0 for k in STATUSES})[student_status(s)] += 1
    return jsonify({"ok": True, "items": [{"name": n, **stats.get(n, {k: 0 for k in STATUSES})} for n in sorted(names)]})


@bp.get("/students")
@require_auth("admin", "cashier", "manager")
def list_students():
    p = g.principal
    status = request.args.get("status", "active")
    group = _text(request.args.get("group"), 60)
    q = _text(request.args.get("q"), 80).lower()
    rows = []
    for s in _students(p["center"]):
        st = student_status(s)
        if status in STATUSES and st != status:
            continue
        if status == "current" and st in ARCHIVED:
            continue
        if group and str(s.get("group") or "") != group:
            continue
        if q and q not in f"{_student_name(s)} {s.get('phone') or ''} {s.get('group') or ''}".lower():
            continue
        rows.append(s)
    rows.sort(key=lambda s: (str(s.get("group") or ""), _student_name(s)))
    page, size = _paging()
    with _db() as conn:
        balances = _balances(conn, p["center"], [int(s["id"]) for s in rows])
        if request.args.get("debtors") == "1":
            rows = [s for s in rows if balances[int(s["id"])]["debt"] > 0]
        chunk = rows[(page - 1) * size: page * size]
        enrolled = {int(r["student_id"]): r["d"] for r in _all(conn, """SELECT student_id, MIN(effective_date) AS d FROM crm_events
            WHERE center_id = ? AND type = 'enrolled' GROUP BY student_id""", (p["center"],))}
    return jsonify({"ok": True, "items": [{**_public(s, balances.get(int(s["id"]))), "enrolled_at": enrolled.get(int(s["id"]))}
                                          for s in chunk], "total": len(rows), "page": page, "page_size": size})


@bp.get("/students/<int:student_id>/history")
@require_auth("admin", "cashier", "manager")
def history(student_id: int):
    p = g.principal
    student = next((s for s in _students(p["center"]) if int(s.get("id") or 0) == student_id), None)
    if not student:
        return _err("O'quvchi topilmadi", 404)
    with _db() as conn:
        events = _all(conn, "SELECT * FROM crm_events WHERE center_id = ? AND student_id = ? ORDER BY effective_date DESC, created_at DESC",
                      (p["center"], student_id))
        payments = _all(conn, """SELECT id, receipt_no, amount, method, period, status, void_reason, created_by_name, day, created_at
            FROM fin_payments WHERE center_id = ? AND student_id = ? ORDER BY created_at DESC""", (p["center"], student_id))
        fees = _all(conn, "SELECT monthly_fee, effective_from, created_by_name, created_at FROM fin_fees WHERE center_id = ? AND student_id = ? ORDER BY created_at DESC",
                    (p["center"], student_id))
        balance = _balances(conn, p["center"], [student_id])[student_id]
        att = _all(conn, "SELECT lesson_date, group_name, status FROM att_records WHERE center_id = ? AND student_id = ? ORDER BY lesson_date DESC",
                   (p["center"], student_id))
    data = _dataset["read"]()
    teachers = {int(t.get("id") or 0): str(t.get("name") or "") for t in data.get("teachers", []) if isinstance(t, dict)}
    tids = {int(x) for x in (student.get("teacherIds") or []) if str(x).isdigit()} | ({int(student["teacherId"])} if str(student.get("teacherId") or "").isdigit() else set())
    tests = {str(t.get("id")): t.get("title") or "" for t in data.get("tests", []) if isinstance(t, dict)}
    results = [{"test": tests.get(str(r.get("testId")), "Test"), "correct": r.get("correct"), "total": r.get("total"), "date": r.get("date")}
               for r in data.get("testResults", []) if isinstance(r, dict) and str(r.get("studentId")) == str(student_id)]
    grades = [gr for gr in data.get("homeworkGrades", []) if isinstance(gr, dict) and str(gr.get("studentId")) == str(student_id)]
    att_counts = {k: sum(1 for a in att if a["status"] == k) for k in ("present", "late", "excused", "absent")}
    total = sum(att_counts.values())
    return jsonify({"ok": True, "student": _public(student, balance), "events": events, "payments": payments, "fees": fees,
                    "teachers": [teachers.get(t, f"#{t}") for t in sorted(tids) if t in teachers],
                    "attendance": {**att_counts, "total": total,
                                   "rate": round((att_counts["present"] + att_counts["late"]) * 100 / total) if total else None,
                                   "recent": att[:10]},
                    "tests": sorted(results, key=lambda r: -(r["date"] or 0))[:20],
                    "homework": {"graded": len(grades),
                                 "avg": round(sum(float(x.get("grade") or 0) for x in grades) / len(grades), 1) if grades else None}})


# --------------------------------------------------------------------------
# Yozish (faqat to'liq admin)
# --------------------------------------------------------------------------
def _mutate_student(student_id: int, fn: Callable[[dict[str, Any], dict[str, Any]], Any]):
    """Dataset ichidagi talabani lock ostida o'zgartiradi. fn(student, data) xato matni qaytarsa — bekor."""
    p = g.principal
    with _dataset["lock"]:
        data = _dataset["read"]()
        student = next((s for s in data.get("students", []) if isinstance(s, dict) and int(s.get("id") or 0) == student_id
                        and str(s.get("centerId") or "main") == p["center"]), None)
        if not student:
            return None, _err("O'quvchi topilmadi", 404)
        result = fn(student, data)
        if isinstance(result, tuple):
            return None, result
        data, _ = _dataset["normalize"](data)
        _dataset["write"](data)
    return student, result


@bp.post("/students")
@require_auth("admin", "manager")
def create_student():
    p = g.principal
    body = _body()
    first = _text(body.get("firstName"), 60)
    last = _text(body.get("lastName"), 60)
    phone = re.sub(r"[\s\-()]", "", _text(body.get("phone"), 24))
    parent_phone = re.sub(r"[\s\-()]", "", _text(body.get("parentPhone"), 24))
    group = _text(body.get("group"), 60)
    password = str(body.get("password") or "")
    if not first or not last:
        return _err("Ism va familiyani kiriting")
    if not re.match(r"^\+?\d{9,15}$", phone):
        return _err("Telefon raqam noto'g'ri. Namuna: +998901234567")
    if parent_phone and not re.match(r"^\+?\d{9,15}$", parent_phone):
        return _err("Ota-ona telefoni noto'g'ri")
    if not group:
        return _err("Guruhni tanlang")
    if password and not 4 <= len(password) <= 128:
        return _err("Parol kamida 4 belgi bo'lsin")
    birth, address = _birth_date(body.get("birthDate")), _text(body.get("address"), 200)
    if birth is None:
        return _err("Tug'ilgan sana noto'g'ri (YYYY-MM-DD)")
    start = _effective_date(body.get("start_date"))
    if not start:
        return _err("Boshlanish sanasi noto'g'ri")
    fee = body.get("monthly_fee")
    fee = int(str(fee).replace(" ", "")) if str(fee or "").replace(" ", "").isdigit() else None
    if fee is not None and fee > MAX_AMOUNT:
        return _err("Oylik summa noto'g'ri")
    generated = not password
    password = password or f"{secrets.randbelow(900000) + 100000}"

    with _dataset["lock"]:
        data = _dataset["read"]()
        for key in ("students", "teachers", "admins", "parents", "employers"):
            for acc in data.get(key, []):
                if isinstance(acc, dict) and acc.get("phone") and _norm_phone(acc["phone"]) == _norm_phone(phone):
                    return _err("Bu telefon raqam allaqachon ro'yxatdan o'tgan", 409)
        used = {int(s.get("id") or 0) for s in data.get("students", []) if isinstance(s, dict)}
        new_id = int(time.time() * 1000)
        while new_id in used:
            new_id += 1
        group_rec = next((x for x in data.get("groups", []) if isinstance(x, dict) and str(x.get("name")) == group), None)
        teacher_id = int(group_rec.get("teacherId") or 0) if group_rec else 0
        if not group_rec:
            data.setdefault("groups", []).append({"id": new_id, "name": group, "status": "active", "teacherId": None})
        student = {
            "id": new_id, "firstName": first, "lastName": last, "name": f"{first} {last}",
            "phone": phone, "parentPhone": parent_phone, "password": password, "group": group,
            "birthDate": birth, "address": address, "source": _source(body.get("source")),
            "status": "active", "totalCoins": 0, "level": 1, "streak": 0, "refCode": f"REF{new_id}",
        }
        if p["center"] != "main":
            student["centerId"] = p["center"]
        if teacher_id:
            student.update({"teacherId": teacher_id, "teacherIds": [teacher_id]})
        data.setdefault("students", []).append(student)
        data, _ = _dataset["normalize"](data)
        _dataset["write"](data)

    with _db() as conn:
        _insert_event(conn, p, {"student_id": new_id, "type": "enrolled", "to_group": group, "to_status": "active",
                                "effective_date": start, "reason": _text(body.get("note"), 300)}, p["center"])
        if fee is not None:
            _x(conn, """INSERT INTO fin_fees (id, center_id, student_id, monthly_fee, effective_from, created_by_id, created_by_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (str(uuid.uuid4()), p["center"], new_id, fee, start[:7], p["id"], p["name"], _now_ms()))
        _audit(conn, p, "student.create", "student", new_id, {"group": group, "monthly_fee": fee})
    saved = dict(student)
    saved.pop("password", None)
    return jsonify({"ok": True, "student": _public(saved), "record": saved,
                    "password": password if generated else None}), 201


@bp.post("/students/<int:student_id>/move")
@require_auth("admin", "manager")
def move_student(student_id: int):
    p = g.principal
    body = _body()
    to_group = _text(body.get("group"), 60)
    reason = _text(body.get("reason"), 300)
    when = _effective_date(body.get("date"))
    if not to_group:
        return _err("Yangi guruhni tanlang")
    if not when:
        return _err("Sana noto'g'ri")
    event: dict[str, Any] = {}

    def apply(student: dict[str, Any], data: dict[str, Any]):
        old = str(student.get("group") or "")
        if old == to_group:
            return _err("O'quvchi allaqachon shu guruhda")
        if student_status(student) in ARCHIVED:
            return _err("Arxivdagi o'quvchini avval qayta faollashtiring")
        student["group"] = to_group
        group_rec = next((x for x in data.get("groups", []) if isinstance(x, dict) and str(x.get("name")) == to_group), None)
        if group_rec and group_rec.get("teacherId"):
            student["teacherId"] = int(group_rec["teacherId"])
            student["teacherIds"] = [int(group_rec["teacherId"])]
        event.update(student_id=student_id, type="group_changed", from_group=old, to_group=to_group,
                     reason=reason, effective_date=when)

    student, error = _mutate_student(student_id, apply)
    if student is None:
        return error
    with _db() as conn:
        _insert_event(conn, p, event, p["center"])
        _audit(conn, p, "student.move", "student", student_id, {"from": event["from_group"], "to": to_group})
    return jsonify({"ok": True, "student": _public(student)})


@bp.post("/students/<int:student_id>/status")
@require_auth("admin", "manager")
def change_status(student_id: int):
    p = g.principal
    body = _body()
    to_status = str(body.get("status") or "")
    reason = _text(body.get("reason"), 300)
    when = _effective_date(body.get("date"))
    to_group = _text(body.get("group"), 60)
    if to_status not in STATUSES:
        return _err("Holat noto'g'ri")
    if not when:
        return _err("Sana noto'g'ri")
    if to_status != "active" and len(reason) < 3:
        return _err("Sababni yozing")
    event: dict[str, Any] = {}

    def apply(student: dict[str, Any], data: dict[str, Any]):
        cur = student_status(student)
        if to_status not in TRANSITIONS[cur]:
            return _err(f"'{STATUS_LABEL[cur]}' holatidan '{STATUS_LABEL[to_status]}' holatiga o'tib bo'lmaydi", 409)
        student["status"] = to_status
        old_group = str(student.get("group") or "")
        if to_status == "active" and to_group and to_group != old_group:
            student["group"] = to_group
        event.update(student_id=student_id, type="status_changed", from_status=cur, to_status=to_status,
                     from_group=old_group, to_group=str(student.get("group") or ""), reason=reason, effective_date=when)

    student, error = _mutate_student(student_id, apply)
    if student is None:
        return error
    with _db() as conn:
        _insert_event(conn, p, event, p["center"])
        _audit(conn, p, "student.status", "student", student_id,
               {"from": event["from_status"], "to": to_status, "reason": reason, "date": when})
    return jsonify({"ok": True, "student": _public(student)})


# --------------------------------------------------------------------------
# Qabul: yangi kelganlar, fan bo'yicha yig'iladi va guruh ochilganda o'quvchiga aylantiriladi
# --------------------------------------------------------------------------
LEAD_STATUSES = {"new": "Yangi", "contacted": "Bog'lanildi", "trial": "Sinov darsi", "waiting": "Guruh kutmoqda",
                 "enrolled": "Qabul qilindi", "rejected": "Rad etdi"}
OPEN_LEADS = ("new", "contacted", "trial", "waiting")


@bp.get("/leads")
@require_auth("admin", "manager")
def list_leads():
    p = g.principal
    where, params = ["center_id = ?"], [p["center"]]
    status = request.args.get("status", "open")
    if status == "open":
        where.append("status IN ('new', 'contacted', 'trial', 'waiting')")
    elif status in LEAD_STATUSES:
        where.append("status = ?")
        params.append(status)
    subject = _text(request.args.get("subject"), 80)
    if subject:
        where.append("subject = ?")
        params.append(subject)
    q = _text(request.args.get("q"), 80).lower()
    if q:
        where.append("(lower(name) LIKE ? OR phone LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    with _db() as conn:
        items = _all(conn, f"SELECT * FROM crm_leads WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT 500", params)
        subjects = _all(conn, """SELECT subject, COUNT(*) AS n FROM crm_leads WHERE center_id = ?
            AND status IN ('new', 'contacted', 'trial', 'waiting') GROUP BY subject ORDER BY n DESC""", (p["center"],))
    return jsonify({"ok": True, "items": items, "subjects": [{"subject": r["subject"], "waiting": int(r["n"])} for r in subjects]})


@bp.post("/leads")
@require_auth("admin", "manager")
def create_lead():
    p = g.principal
    body = _body()
    name = _text(body.get("name"), 120)
    phone = re.sub(r"[\s\-()]", "", _text(body.get("phone"), 24))
    subject = _text(body.get("subject"), 80)
    if not name or not subject:
        return _err("Ism va fanni kiriting")
    if not re.match(r"^\+?\d{9,15}$", phone):
        return _err("Telefon raqam noto'g'ri. Namuna: +998901234567")
    row = _insert_lead(p, p["center"], name, phone, subject, _text(body.get("note"), 300), _source(body.get("source")))
    if row is None:
        return _err("Bu telefon shu fanga allaqachon yozilgan", 409)
    return jsonify({"ok": True, "lead": row}), 201


def _insert_lead(p: Optional[dict[str, Any]], center: str, name: str, phone: str, subject: str, note: str,
                 source: str) -> Optional[dict[str, Any]]:
    now = _now_ms()
    with _db() as conn:
        dup = _one(conn, f"""SELECT id FROM crm_leads WHERE center_id = ? AND phone = ? AND lower(subject) = lower(?)
            AND status IN {OPEN_LEADS}""", (center, phone, subject))
        if dup:
            return None
        row = {"id": str(uuid.uuid4()), "center_id": center, "name": name, "phone": phone, "subject": subject,
               "note": note, "status": "new", "student_id": None, "source": source,
               "created_by_name": (p or {}).get("name") or "Onlayn ariza", "created_at": now, "updated_at": now}
        cols = list(row)
        _x(conn, f"INSERT INTO crm_leads ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        _audit(conn, p, "lead.create", "lead", row["id"], {"subject": subject, "source": source}, center)
    return row


@bp.post("/leads/<lead_id>/status")
@require_auth("admin", "manager")
def lead_status(lead_id: str):
    p = g.principal
    body = _body()
    status = str(body.get("status") or "")
    if status not in LEAD_STATUSES:
        return _err("Holat noto'g'ri")
    student_id = body.get("student_id")
    if status == "enrolled":
        try:
            student_id = int(student_id)
        except (TypeError, ValueError):
            return _err("Qabul uchun o'quvchi ID kerak")
        if not any(int(s.get("id") or 0) == student_id for s in _students(p["center"])):
            return _err("O'quvchi topilmadi", 404)
    else:
        student_id = None
    trial_at, trial_group = _text(body.get("trial_at"), 16), _text(body.get("trial_group"), 60)
    if status == "trial" and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", trial_at):
        return _err("Sinov darsi sanasi va vaqtini tanlang")
    with _db() as conn:
        lead = _one(conn, "SELECT * FROM crm_leads WHERE id = ? AND center_id = ?", (lead_id, p["center"]))
        if not lead:
            return _err("Yozuv topilmadi", 404)
        _x(conn, """UPDATE crm_leads SET status = ?, student_id = COALESCE(?, student_id), note = ?, updated_at = ?,
            trial_at = COALESCE(?, trial_at), trial_group = COALESCE(?, trial_group) WHERE id = ?""",
           (status, student_id, _text(body.get("note"), 300) or lead["note"], _now_ms(),
            trial_at if status == "trial" else None, (trial_group or None) if status == "trial" else None, lead_id))
        _audit(conn, p, "lead.status", "lead", lead_id, {"from": lead["status"], "to": status, "student_id": student_id})
    return jsonify({"ok": True})



def _birth_date(value: Any) -> Optional[str]:
    """'' (kiritilmagan) yoki YYYY-MM-DD; noto'g'ri bo'lsa None."""
    raw = _text(value, 10)
    if not raw:
        return ""
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    return raw if date(1930, 1, 1) <= day <= _today() else None


@bp.post("/students/<int:student_id>/profile")
@require_auth("admin", "manager")
def edit_profile(student_id: int):
    """Telefon, ota-ona telefoni, tug'ilgan sana va manzilni tahrirlash."""
    p = g.principal
    body = _body()
    phone = re.sub(r"[\s\-()]", "", _text(body.get("phone"), 24))
    parent_phone = re.sub(r"[\s\-()]", "", _text(body.get("parentPhone"), 24))
    birth, address = _birth_date(body.get("birthDate")), _text(body.get("address"), 200)
    if not re.match(r"^\+?\d{9,15}$", phone):
        return _err("Telefon raqam noto'g'ri. Namuna: +998901234567")
    if parent_phone and not re.match(r"^\+?\d{9,15}$", parent_phone):
        return _err("Ota-ona telefoni noto'g'ri")
    if birth is None:
        return _err("Tug'ilgan sana noto'g'ri (YYYY-MM-DD)")
    changed: dict[str, Any] = {}

    def apply(student: dict[str, Any], data: dict[str, Any]):
        if _norm_phone(phone) != _norm_phone(student.get("phone")):
            for key in ("students", "teachers", "admins", "parents", "employers"):
                for acc in data.get(key, []):
                    if isinstance(acc, dict) and acc is not student and acc.get("phone") and _norm_phone(acc["phone"]) == _norm_phone(phone):
                        return _err("Bu telefon raqam boshqa hisobda bor", 409)
        for field, value in (("phone", phone), ("parentPhone", parent_phone), ("birthDate", birth), ("address", address)):
            if (student.get(field) or "") != value:
                changed[field] = value
                student[field] = value

    student, error = _mutate_student(student_id, apply)
    if student is None:
        return error
    if changed:
        with _db() as conn:
            _audit(conn, p, "student.profile", "student", student_id, {"fields": sorted(changed)})
    return jsonify({"ok": True, "student": _public(student)})


@bp.post("/students/<int:student_id>/courses")
@require_auth("admin", "manager")
def edit_courses(student_id: int):
    """Qo'shimcha kurs (guruh) qo'shish yoki olib tashlash — asosiy guruh o'zgarmaydi."""
    p = g.principal
    body = _body()
    group = _text(body.get("group"), 60)
    action = str(body.get("action") or "add")
    if not group or action not in ("add", "remove"):
        return _err("Guruhni tanlang")
    when = _effective_date(body.get("date"))
    if not when:
        return _err("Sana noto'g'ri")

    def apply(student: dict[str, Any], data: dict[str, Any]):
        extra = [str(x) for x in student.get("extraGroups") or []] if isinstance(student.get("extraGroups"), list) else []
        if action == "add":
            if group == str(student.get("group") or "") or group in extra:
                return _err("O'quvchi bu guruhda allaqachon bor")
            extra.append(group)
        else:
            if group not in extra:
                return _err("Bu qo'shimcha kurs emas")
            extra.remove(group)
        student["extraGroups"] = extra

    student, error = _mutate_student(student_id, apply)
    if student is None:
        return error
    with _db() as conn:
        _insert_event(conn, p, {"student_id": student_id, "type": "course_added" if action == "add" else "course_removed",
                                "to_group": group, "effective_date": when, "reason": _text(body.get("reason"), 300)}, p["center"])
    return jsonify({"ok": True, "student": _public(student)})



SOURCES = {"instagram": "Instagram", "telegram": "Telegram", "youtube": "YouTube", "facebook": "Facebook", "tiktok": "TikTok",
           "website": "Veb-sayt", "friend": "Tanish-bilish", "banner": "Banner / reklama", "walkin": "O'zi kelgan", "other": "Boshqa"}


def _source(value: Any) -> str:
    value = str(value or "").strip().lower()
    return value if value in SOURCES else ""


# --------------------------------------------------------------------------
# Ochiq onlayn ariza: Telegram/Instagram/YouTube va boshqa kanallardagi havola orqali (?src=instagram)
# --------------------------------------------------------------------------
_apply_hits: dict[str, list[float]] = {}


@bp.get("/public/subjects")
def public_subjects():
    with _db() as conn:
        rows = _all(conn, "SELECT DISTINCT subject FROM sched_lessons WHERE status = 'active'")
    subjects = {r["subject"] for r in rows} | {str(x.get("subject")) for x in _dataset["read"]().get("groups", [])
                                               if isinstance(x, dict) and x.get("subject")}
    return jsonify({"ok": True, "items": sorted(subjects), "sources": SOURCES})


@bp.post("/public/apply")
def public_apply():
    from flask import request as req
    ip = (req.headers.get("X-Forwarded-For", "").split(",")[0].strip() or req.remote_addr or "?")
    now = time.time()
    hits = [t for t in _apply_hits.get(ip, []) if now - t < 600]
    if len(hits) >= 5:
        return _err("Juda ko'p ariza yuborildi. Birozdan keyin urinib ko'ring.", 429)
    _apply_hits[ip] = hits + [now]
    body = _body()
    if body.get("website"):  # bot-tuzoq maydoni: odam uni ko'rmaydi
        return jsonify({"ok": True})
    name = _text(body.get("name"), 120)
    phone = re.sub(r"[\s\-()]", "", _text(body.get("phone"), 24))
    subject = _text(body.get("subject"), 80)
    if len(name) < 2 or not subject:
        return _err("Ism va fanni kiriting")
    if not re.match(r"^\+?\d{9,15}$", phone):
        return _err("Telefon raqam noto'g'ri. Namuna: +998901234567")
    row = _insert_lead(None, "main", name, phone, subject, _text(body.get("note"), 300), _source(body.get("source")) or "other")
    if row is None:
        return jsonify({"ok": True, "message": "Arizangiz allaqachon qabul qilingan"})
    return jsonify({"ok": True, "message": "Arizangiz qabul qilindi! Tez orada siz bilan bog'lanamiz."}), 201
