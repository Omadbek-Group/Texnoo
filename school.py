"""Dars jadvali, davomat va o'qituvchi oyligi.

Huquqlar:
  - Jadval: admin/boshliq/menejer yozadi; o'qituvchi o'z darslarini, o'quvchi/ota-ona o'z guruhini ko'radi.
  - Davomat: o'qituvchi faqat o'z guruhlarini, admin/boshliq/menejer hammasini belgilaydi;
    o'quvchi o'zini, ota-ona farzandini, o'qituvchi o'z o'quvchilarini ko'radi.
  - Oylik: faqat admin/boshliq belgilaydi va ko'radi; o'qituvchi faqat o'zinikini ko'radi.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any, Optional

from flask import Blueprint, g, jsonify, request

from crm import ARCHIVED, _dataset, student_status
from finance import (
    _DAY_RE, _YM_RE, MAX_AMOUNT, _all, _audit, _body, _db, _err, _now_ms, _one, _parent_child_ids,
    _student_name, _text, _this_month, _today, _x, init_finance_db,
)
from security import is_full_admin, require_auth

ATT_STATUSES = ("present", "absent", "late", "excused")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
WEEKDAYS = {1: "Dushanba", 2: "Seshanba", 3: "Chorshanba", 4: "Payshanba", 5: "Juma", 6: "Shanba", 7: "Yakshanba"}

bp = Blueprint("school", __name__, url_prefix="/api/school")


@bp.before_request
def _ensure_schema() -> None:
    init_finance_db()


def _staff(p: dict[str, Any]) -> bool:
    return is_full_admin(p) or (p["role"] == "admin" and p["level"] == "manager")


def _data() -> dict[str, Any]:
    return _dataset["read"]()


def _center_students(data: dict[str, Any], center: str) -> list[dict[str, Any]]:
    return [s for s in data.get("students", []) if isinstance(s, dict) and str(s.get("centerId") or "main") == center]


def _teacher_ids_of(s: dict[str, Any]) -> set[int]:
    ids = s.get("teacherIds") if isinstance(s.get("teacherIds"), list) else []
    out = set()
    for x in list(ids) + [s.get("teacherId")]:
        try:
            if int(x or 0):
                out.add(int(x))
        except (TypeError, ValueError):
            pass
    return out


def _teachers(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out = {}
    for t in data.get("teachers", []):
        try:
            out[int(t.get("id"))] = t
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def _teacher_groups(conn: Any, data: dict[str, Any], center: str, teacher_id: int) -> set[str]:
    """O'qituvchiga tegishli guruhlar: guruh yozuvi, o'quvchilari va jadvaldagi darslari bo'yicha."""
    names = {str(x.get("name")) for x in data.get("groups", [])
             if isinstance(x, dict) and x.get("name") and str(x.get("teacherId") or "") == str(teacher_id)}
    names |= {str(s.get("group")) for s in _center_students(data, center)
              if s.get("group") and student_status(s) not in ARCHIVED and teacher_id in _teacher_ids_of(s)}
    names |= {r["group_name"] for r in _all(conn, "SELECT DISTINCT group_name FROM sched_lessons WHERE center_id = ? AND teacher_id = ? AND status = 'active'",
                                            (center, teacher_id))}
    return names


def _allowed_groups(conn: Any, data: dict[str, Any], p: dict[str, Any]) -> Optional[set[str]]:
    """None = hamma guruh (xodimlar)."""
    if _staff(p):
        return None
    if p["role"] == "teacher":
        return _teacher_groups(conn, data, p["center"], p["id"])
    return set()


def _group_students(data: dict[str, Any], center: str, group: str) -> list[dict[str, Any]]:
    rows = [s for s in _center_students(data, center) if str(s.get("group") or "") == group and student_status(s) not in ARCHIVED]
    return sorted(rows, key=_student_name)


# --------------------------------------------------------------------------
# Dars jadvali
# --------------------------------------------------------------------------
def _lesson_out(row: dict[str, Any], teachers: dict[int, dict[str, Any]]) -> dict[str, Any]:
    out = dict(row)
    out["teacher_name"] = str((teachers.get(int(row["teacher_id"])) or {}).get("name") or f"#{row['teacher_id']}")
    out["weekday_name"] = WEEKDAYS.get(int(row["weekday"]), "")
    return out


@bp.get("/lessons")
@require_auth()
def list_lessons():
    p = g.principal
    data = _data()
    with _db() as conn:
        rows = _all(conn, "SELECT * FROM sched_lessons WHERE center_id = ? AND status = 'active' ORDER BY weekday, start_time", (p["center"],))
    if p["role"] == "teacher":
        rows = [r for r in rows if int(r["teacher_id"]) == p["id"]]
    elif p["role"] in ("student", "parent"):
        ids = [p["id"]] if p["role"] == "student" else _parent_child_ids(p)
        groups = {str(s.get("group")) for s in _center_students(data, p["center"]) if int(s.get("id") or 0) in ids}
        rows = [r for r in rows if r["group_name"] in groups]
    elif not _staff(p):
        return _err("Bu amal uchun ruxsat yo'q", 403)
    group = _text(request.args.get("group"), 60)
    if group:
        rows = [r for r in rows if r["group_name"] == group]
    teachers = _teachers(data)
    return jsonify({"ok": True, "items": [_lesson_out(r, teachers) for r in rows]})


@bp.post("/lessons")
@require_auth("admin", "manager")
def create_lesson():
    p = g.principal
    body = _body()
    group = _text(body.get("group"), 60)
    subject = _text(body.get("subject"), 80)
    room = _text(body.get("room"), 40)
    start, end = _text(body.get("start"), 5), _text(body.get("end"), 5)
    try:
        weekday = int(body.get("weekday"))
        teacher_id = int(body.get("teacher_id"))
    except (TypeError, ValueError):
        return _err("Hafta kuni va o'qituvchini tanlang")
    if not group or not subject:
        return _err("Guruh va fanni kiriting")
    if weekday not in WEEKDAYS:
        return _err("Hafta kuni noto'g'ri")
    if not _TIME_RE.match(start) or not _TIME_RE.match(end) or start >= end:
        return _err("Vaqt HH:MM formatida va boshlanishi tugashidan oldin bo'lsin")
    teacher = _teachers(_data()).get(teacher_id)
    if not teacher or teacher.get("status") == "pending":
        return _err("O'qituvchi topilmadi", 404)

    with _db() as conn:
        same_day = _all(conn, """SELECT * FROM sched_lessons WHERE center_id = ? AND weekday = ? AND status = 'active'
            AND start_time < ? AND ? < end_time""", (p["center"], weekday, end, start))
        for other in same_day:
            when = f"{WEEKDAYS[weekday]} {other['start_time']}-{other['end_time']}"
            if int(other["teacher_id"]) == teacher_id:
                return _err(f"To'qnashuv: o'qituvchi bu vaqtda {other['group_name']} guruhida dars beradi ({when})", 409)
            if room and other["room"] and other["room"].lower() == room.lower():
                return _err(f"To'qnashuv: {room} xonasi band — {other['group_name']} ({when})", 409)
            if other["group_name"] == group:
                return _err(f"To'qnashuv: {group} guruhining bu vaqtda boshqa darsi bor ({when})", 409)
        row = {
            "id": str(uuid.uuid4()), "center_id": p["center"], "group_name": group, "subject": subject,
            "teacher_id": teacher_id, "room": room, "weekday": weekday, "start_time": start, "end_time": end,
            "status": "active", "created_by_name": p["name"], "created_at": _now_ms(),
        }
        cols = list(row)
        _x(conn, f"INSERT INTO sched_lessons ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        _audit(conn, p, "lesson.create", "lesson", row["id"], {"group": group, "weekday": weekday, "time": f"{start}-{end}", "room": room})
    return jsonify({"ok": True, "lesson": _lesson_out(row, _teachers(_data()))}), 201


@bp.post("/lessons/<lesson_id>/remove")
@require_auth("admin", "manager")
def remove_lesson(lesson_id: str):
    p = g.principal
    with _db() as conn:
        row = _one(conn, "SELECT * FROM sched_lessons WHERE id = ? AND center_id = ? AND status = 'active'", (lesson_id, p["center"]))
        if not row:
            return _err("Dars topilmadi", 404)
        _x(conn, "UPDATE sched_lessons SET status = 'removed' WHERE id = ?", (lesson_id,))
        _audit(conn, p, "lesson.remove", "lesson", lesson_id, {"group": row["group_name"], "weekday": row["weekday"], "time": row["start_time"]})
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Davomat
# --------------------------------------------------------------------------
@bp.get("/groups")
@require_auth("admin", "manager", "teacher")
def my_groups():
    p = g.principal
    data = _data()
    with _db() as conn:
        allowed = _allowed_groups(conn, data, p)
    names = {str(s.get("group")) for s in _center_students(data, p["center"]) if s.get("group") and student_status(s) not in ARCHIVED}
    names |= {str(x.get("name")) for x in data.get("groups", []) if isinstance(x, dict) and x.get("name")}
    if allowed is not None:
        names &= allowed
    return jsonify({"ok": True, "items": sorted(names)})


def _check_group_access(group: str):
    p = g.principal
    data = _data()
    with _db() as conn:
        allowed = _allowed_groups(conn, data, p)
    if allowed is not None and group not in allowed:
        return None, _err("Bu guruh sizga biriktirilmagan", 403)
    return data, None


def _valid_day(value: Any) -> Optional[str]:
    raw = _text(value, 10) or _today().isoformat()
    if not _DAY_RE.match(raw):
        return None
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    return raw if 0 <= (_today() - day).days <= 366 else None


@bp.get("/attendance/sheet")
@require_auth("admin", "manager", "teacher")
def attendance_sheet():
    p = g.principal
    group = _text(request.args.get("group"), 60)
    day = _valid_day(request.args.get("date"))
    if not group or not day:
        return _err("Guruh va sanani tanlang (kelajak sana bo'lmaydi)")
    data, error = _check_group_access(group)
    if error:
        return error
    with _db() as conn:
        marks = {int(r["student_id"]): r for r in _all(conn, """SELECT student_id, status, note, marked_by_name FROM att_records
            WHERE center_id = ? AND lesson_date = ? AND group_name = ?""", (p["center"], day, group))}
        lessons = _all(conn, """SELECT subject, start_time, end_time, room FROM sched_lessons
            WHERE center_id = ? AND group_name = ? AND weekday = ? AND status = 'active' ORDER BY start_time""",
                       (p["center"], group, date.fromisoformat(day).isoweekday()))
    items = [{
        "student_id": int(s["id"]), "name": _student_name(s), "status": student_status(s),
        "mark": (marks.get(int(s["id"])) or {}).get("status"), "note": (marks.get(int(s["id"])) or {}).get("note") or "",
    } for s in _group_students(data, p["center"], group)]
    return jsonify({"ok": True, "group": group, "date": day, "items": items, "lessons": lessons,
                    "marked_by": next((m["marked_by_name"] for m in marks.values()), None)})


@bp.post("/attendance")
@require_auth("admin", "manager", "teacher")
def save_attendance():
    p = g.principal
    body = _body()
    group = _text(body.get("group"), 60)
    day = _valid_day(body.get("date"))
    marks = body.get("marks")
    if not group or not day:
        return _err("Guruh va sanani tanlang (kelajak sana bo'lmaydi)")
    if not isinstance(marks, list) or not marks or len(marks) > 300:
        return _err("Belgilar ro'yxati bo'sh")
    data, error = _check_group_access(group)
    if error:
        return error
    members = {int(s["id"]) for s in _group_students(data, p["center"], group)}
    clean = []
    for m in marks:
        try:
            sid = int((m or {}).get("student_id"))
        except (TypeError, ValueError):
            return _err("O'quvchi ID noto'g'ri")
        if sid not in members:
            return _err(f"O'quvchi #{sid} bu guruhda emas")
        if m.get("status") not in ATT_STATUSES:
            return _err("Holat: keldi, kelmadi, kechikdi yoki sababli")
        clean.append((sid, m["status"], _text(m.get("note"), 200)))
    now = _now_ms()
    with _db() as conn:
        for sid, status, note in clean:
            updated = _x(conn, """UPDATE att_records SET status = ?, note = ?, marked_by_id = ?, marked_by_name = ?, updated_at = ?
                WHERE center_id = ? AND lesson_date = ? AND group_name = ? AND student_id = ?""",
                         (status, note, p["id"], p["name"], now, p["center"], day, group, sid)).rowcount
            if not updated:
                _x(conn, """INSERT INTO att_records (id, center_id, lesson_date, group_name, student_id, status, note,
                    marked_by_id, marked_by_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (str(uuid.uuid4()), p["center"], day, group, sid, status, note, p["id"], p["name"], now))
        counts = {s: sum(1 for c in clean if c[1] == s) for s in ATT_STATUSES}
        _audit(conn, p, "attendance.mark", "group", group, {"date": day, **counts})
    return jsonify({"ok": True, "saved": len(clean), "counts": counts})


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {s: 0 for s in ATT_STATUSES}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total = sum(counts.values())
    attended = counts["present"] + counts["late"]
    return {**counts, "total": total, "rate": round(attended * 100 / total) if total else None}


def _month_bounds(raw: Any) -> Optional[tuple[str, str]]:
    month = _text(raw, 7) or _this_month()
    return (month + "-01", month + "-31") if _YM_RE.match(month) else None


@bp.get("/attendance/stats")
@require_auth("admin", "manager", "teacher")
def attendance_stats():
    p = g.principal
    group = _text(request.args.get("group"), 60)
    bounds = _month_bounds(request.args.get("month"))
    if not group or not bounds:
        return _err("Guruh va oyni tanlang")
    data, error = _check_group_access(group)
    if error:
        return error
    with _db() as conn:
        rows = _all(conn, """SELECT student_id, lesson_date, status FROM att_records
            WHERE center_id = ? AND group_name = ? AND lesson_date >= ? AND lesson_date <= ?""", (p["center"], group, *bounds))
    by_student: dict[int, list[dict[str, Any]]] = {}
    by_day: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_student.setdefault(int(r["student_id"]), []).append(r)
        by_day.setdefault(r["lesson_date"], []).append(r)
    students = [{"student_id": int(s["id"]), "name": _student_name(s), **_stats(by_student.get(int(s["id"]), []))}
                for s in _group_students(data, p["center"], group)]
    days = [{"date": d, **_stats(v)} for d, v in sorted(by_day.items())]
    return jsonify({"ok": True, "group": group, "students": students, "days": days, "summary": _stats(rows)})


@bp.get("/attendance/today")
@require_auth("admin", "manager")
def attendance_today():
    p = g.principal
    today = _today()
    data = _data()
    teachers = _teachers(data)
    with _db() as conn:
        lessons = _all(conn, """SELECT * FROM sched_lessons WHERE center_id = ? AND weekday = ? AND status = 'active'
            ORDER BY start_time""", (p["center"], today.isoweekday()))
        marks = _all(conn, "SELECT group_name, status FROM att_records WHERE center_id = ? AND lesson_date = ?", (p["center"], today.isoformat()))
    by_group: dict[str, list[dict[str, Any]]] = {}
    for m in marks:
        by_group.setdefault(m["group_name"], []).append(m)
    items = [{**_lesson_out(l, teachers), "group_size": len(_group_students(data, p["center"], l["group_name"])),
              **_stats(by_group.get(l["group_name"], []))} for l in lessons]
    return jsonify({"ok": True, "date": today.isoformat(), "items": items, "summary": _stats(marks)})


@bp.get("/attendance/my")
@require_auth("student", "parent")
def my_attendance():
    p = g.principal
    bounds = _month_bounds(request.args.get("month"))
    if not bounds:
        return _err("Oy formati YYYY-MM")
    data = _data()
    ids = [p["id"]] if p["role"] == "student" else _parent_child_ids(p)
    students = {int(s["id"]): s for s in _center_students(data, p["center"]) if int(s.get("id") or 0) in ids}
    teachers = _teachers(data)
    out = []
    with _db() as conn:
        for sid, s in students.items():
            rows = _all(conn, """SELECT lesson_date, group_name, status, note FROM att_records WHERE center_id = ? AND student_id = ?
                AND lesson_date >= ? AND lesson_date <= ? ORDER BY lesson_date DESC""", (p["center"], sid, *bounds))
            lessons = _all(conn, """SELECT * FROM sched_lessons WHERE center_id = ? AND group_name = ? AND status = 'active'
                ORDER BY weekday, start_time""", (p["center"], str(s.get("group") or "")))
            out.append({"student_id": sid, "name": _student_name(s), "group": s.get("group") or "", "status": student_status(s),
                        "records": rows, "stats": _stats(rows), "lessons": [_lesson_out(l, teachers) for l in lessons]})
    return jsonify({"ok": True, "items": out})


# --------------------------------------------------------------------------
# O'qituvchi oyligi
# --------------------------------------------------------------------------
def _rule_for(rules: list[dict[str, Any]], month: str) -> Optional[dict[str, Any]]:
    active = sorted((r for r in rules if r["effective_from"] <= month), key=lambda r: (r["effective_from"], r["created_at"]))
    return active[-1] if active else None


def compute_salary(rule: Optional[dict[str, Any]], base: int) -> int:
    """Qat'iy: value so'm. Foiz: value = foiz*100 (35.5% -> 3550), tushumdan hisoblanadi."""
    if not rule:
        return 0
    if rule["type"] == "fixed":
        return int(rule["value"])
    return int(base) * int(rule["value"]) // 10000


def _salary_rows(conn: Any, data: dict[str, Any], center: str, month: str, only_teacher: Optional[int] = None) -> list[dict[str, Any]]:
    rules: dict[int, list[dict[str, Any]]] = {}
    for r in _all(conn, "SELECT * FROM sal_rules WHERE center_id = ?", (center,)):
        rules.setdefault(int(r["teacher_id"]), []).append(r)
    students = {int(s["id"]): s for s in _center_students(data, center)}
    payments = _all(conn, """SELECT id, receipt_no, student_id, student_name, amount, day, teacher_id FROM fin_payments
        WHERE center_id = ? AND status = 'active' AND day >= ? AND day <= ?""", (center, month + "-01", month + "-31"))
    by_teacher: dict[int, list[dict[str, Any]]] = {}
    for pay in payments:
        # Eski to'lovlarda o'qituvchi yozilmagan bo'lsa — o'quvchining hozirgi asosiy o'qituvchisi.
        tid = int(pay["teacher_id"] or 0) or int((students.get(int(pay["student_id"])) or {}).get("teacherId") or 0)
        if tid:
            by_teacher.setdefault(tid, []).append(pay)
    out = []
    for tid, t in _teachers(data).items():
        if only_teacher is not None and tid != only_teacher:
            continue
        if t.get("status") == "pending":
            continue
        rule = _rule_for(rules.get(tid, []), month)
        pays = by_teacher.get(tid, [])
        base = sum(int(x["amount"]) for x in pays)
        out.append({
            "teacher_id": tid, "teacher_name": str(t.get("name") or f"#{tid}"),
            "rule": rule, "base": base, "payments_count": len(pays),
            "students": sum(1 for s in students.values() if tid in _teacher_ids_of(s) and student_status(s) not in ARCHIVED),
            "amount": compute_salary(rule, base),
            "payments": pays if only_teacher is not None else None,
        })
    out.sort(key=lambda r: r["teacher_name"])
    return out


def _month_arg() -> Optional[str]:
    month = _text(request.args.get("month"), 7) or _this_month()
    return month if _YM_RE.match(month) else None


@bp.get("/salary")
@require_auth("admin")
def salary_list():
    p = g.principal
    month = _month_arg()
    if not month:
        return _err("Oy formati YYYY-MM")
    with _db() as conn:
        rows = _salary_rows(conn, _data(), p["center"], month)
    return jsonify({"ok": True, "month": month, "items": rows, "total": sum(r["amount"] for r in rows)})


@bp.get("/salary/my")
@require_auth("teacher")
def salary_my():
    p = g.principal
    month = _month_arg()
    if not month:
        return _err("Oy formati YYYY-MM")
    with _db() as conn:
        rows = _salary_rows(conn, _data(), p["center"], month, only_teacher=p["id"])
    return jsonify({"ok": True, "month": month, "item": rows[0] if rows else None})


@bp.post("/salary/rules")
@require_auth("admin")
def salary_rule():
    p = g.principal
    body = _body()
    kind = str(body.get("type") or "")
    try:
        teacher_id = int(body.get("teacher_id"))
        raw = float(str(body.get("value")).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return _err("O'qituvchi va qiymatni kiriting")
    if kind == "fixed":
        value = int(raw)
        if not 0 <= value <= MAX_AMOUNT:
            return _err("Maosh summasi noto'g'ri")
    elif kind == "percent":
        if not 0 <= raw <= 100:
            return _err("Foiz 0 dan 100 gacha bo'lsin")
        value = round(raw * 100)
    else:
        return _err("Turi: qat'iy maosh yoki foiz")
    effective_from = _text(body.get("effective_from"), 7) or _this_month()
    if not _YM_RE.match(effective_from):
        return _err("Boshlanish oyi YYYY-MM formatida bo'lsin")
    if teacher_id not in _teachers(_data()):
        return _err("O'qituvchi topilmadi", 404)
    row = {"id": str(uuid.uuid4()), "center_id": p["center"], "teacher_id": teacher_id, "type": kind, "value": value,
           "effective_from": effective_from, "created_by_name": p["name"], "created_at": _now_ms()}
    cols = list(row)
    with _db() as conn:
        _x(conn, f"INSERT INTO sal_rules ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        _audit(conn, p, "salary.rule", "teacher", teacher_id, {"type": kind, "value": value, "from": effective_from})
    return jsonify({"ok": True, "rule": row}), 201
