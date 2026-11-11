"""Dars jadvali, davomat va o'qituvchi oyligi.

Huquqlar:
  - Jadval: admin/boshliq/menejer yozadi; o'qituvchi o'z darslarini, o'quvchi/ota-ona o'z guruhini ko'radi.
  - Davomat: o'qituvchi faqat o'z guruhlarini, admin/boshliq/menejer hammasini belgilaydi;
    o'quvchi o'zini, ota-ona farzandini, o'qituvchi o'z o'quvchilarini ko'radi.
  - Oylik: faqat admin/boshliq belgilaydi va ko'radi; o'qituvchi faqat o'zinikini ko'radi.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable, Optional

from flask import Blueprint, g, jsonify, request

from crm import ARCHIVED, _dataset, student_status
from finance import (
    _DAY_RE, _YM_RE, MAX_AMOUNT, _all, _audit, _balances, _body, _db, _err, _now_ms, _one, _parent_child_ids,
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
    names |= {g for s in _center_students(data, center)
              if student_status(s) not in ARCHIVED and teacher_id in _teacher_ids_of(s) for g in student_groups(s)}
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


def student_groups(s: dict[str, Any]) -> list[str]:
    """Asosiy guruh + qo'shimcha kurslar."""
    extra = s.get("extraGroups") if isinstance(s.get("extraGroups"), list) else []
    return [g for g in [str(s.get("group") or "")] + [str(x) for x in extra] if g]


def _group_students(data: dict[str, Any], center: str, group: str) -> list[dict[str, Any]]:
    rows = [s for s in _center_students(data, center) if group in student_groups(s) and student_status(s) not in ARCHIVED]
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
        groups = {g for s in _center_students(data, p["center"]) if int(s.get("id") or 0) in ids for g in student_groups(s)}
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
        conflict = _conflict(conn, p["center"], weekday, start, end, teacher_id, room, group)
        if conflict:
            return _err(conflict, 409)
        row = _insert_lesson(conn, p, group, subject, teacher_id, room, weekday, start, end)
    return jsonify({"ok": True, "lesson": _lesson_out(row, _teachers(_data()))}), 201


def _conflict(conn: Any, center: str, weekday: int, start: str, end: str, teacher_id: int, room: str, group: str) -> Optional[str]:
    same_day = _all(conn, """SELECT * FROM sched_lessons WHERE center_id = ? AND weekday = ? AND status = 'active'
        AND start_time < ? AND ? < end_time""", (center, weekday, end, start))
    for other in same_day:
        when = f"{WEEKDAYS[weekday]} {other['start_time']}-{other['end_time']}"
        if int(other["teacher_id"]) == teacher_id:
            return f"To'qnashuv: o'qituvchi bu vaqtda {other['group_name']} guruhida dars beradi ({when})"
        if room and other["room"] and other["room"].lower() == room.lower():
            return f"To'qnashuv: {room} xonasi band — {other['group_name']} ({when})"
        if other["group_name"] == group:
            return f"To'qnashuv: {group} guruhining bu vaqtda boshqa darsi bor ({when})"
    return None


def _insert_lesson(conn: Any, p: dict[str, Any], group: str, subject: str, teacher_id: int, room: str,
                   weekday: int, start: str, end: str) -> dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()), "center_id": p["center"], "group_name": group, "subject": subject,
        "teacher_id": teacher_id, "room": room, "weekday": weekday, "start_time": start, "end_time": end,
        "status": "active", "created_by_name": p["name"], "created_at": _now_ms(),
    }
    cols = list(row)
    _x(conn, f"INSERT INTO sched_lessons ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
    _audit(conn, p, "lesson.create", "lesson", row["id"], {"group": group, "weekday": weekday, "time": f"{start}-{end}", "room": room})
    return row


@bp.post("/groups")
@require_auth("admin", "manager")
def create_group():
    """Yangi guruh: nom, fan, o'qituvchi va haftalik dars vaqtlari bir yo'la. To'qnashuv bo'lsa hech narsa yozilmaydi."""
    p = g.principal
    body = _body()
    name = _text(body.get("name"), 60)
    subject = _text(body.get("subject"), 80)
    room = _text(body.get("room"), 40)
    start, end = _text(body.get("start"), 5), _text(body.get("end"), 5)
    try:
        teacher_id = int(body.get("teacher_id"))
        weekdays = sorted({int(d) for d in body.get("weekdays") or []})
    except (TypeError, ValueError):
        return _err("O'qituvchi va kunlarni tanlang")
    if not name or not subject:
        return _err("Guruh nomi va fanni kiriting")
    if not weekdays or any(d not in WEEKDAYS for d in weekdays):
        return _err("Kamida bitta dars kunini tanlang")
    if not _TIME_RE.match(start) or not _TIME_RE.match(end) or start >= end:
        return _err("Vaqt HH:MM formatida va boshlanishi tugashidan oldin bo'lsin")
    teacher = _teachers(_data()).get(teacher_id)
    if not teacher or teacher.get("status") == "pending":
        return _err("O'qituvchi topilmadi", 404)
    with _dataset["lock"]:
        data = _dataset["read"]()
        taken = {str(x.get("name")).lower() for x in data.get("groups", []) if isinstance(x, dict) and x.get("name")}
        taken |= {gr.lower() for s in _center_students(data, p["center"]) for gr in student_groups(s)}
        if name.lower() in taken:
            return _err("Bu nomli guruh allaqachon bor", 409)
        with _db() as conn:
            for day in weekdays:
                conflict = _conflict(conn, p["center"], day, start, end, teacher_id, room, name)
                if conflict:
                    return _err(conflict, 409)
            for day in weekdays:
                _insert_lesson(conn, p, name, subject, teacher_id, room, day, start, end)
        data.setdefault("groups", []).append({"id": _now_ms(), "name": name, "subject": subject, "status": "active",
                                              "teacherId": teacher_id, "room": room,
                                              "schedule": {"days": weekdays, "time": f"{start}-{end}"}})
        _dataset["write"](data)
    return jsonify({"ok": True, "group": name}), 201


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
        students = _group_students(data, p["center"], group)
        balances = _balances(conn, p["center"], [int(s["id"]) for s in students])
    items = [{
        "student_id": int(s["id"]), "name": _student_name(s), "status": student_status(s), "phone": s.get("phone") or "",
        "debt": balances[int(s["id"])]["debt"],
        "mark": (marks.get(int(s["id"])) or {}).get("status"), "note": (marks.get(int(s["id"])) or {}).get("note") or "",
    } for s in students]
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


@bp.get("/students")
@require_auth("admin", "manager", "teacher")
def students_list():
    """O'qituvchi o'z o'quvchilarini, xodimlar hammasini ko'radi: telefon, qarz, shu oy davomati."""
    p = g.principal
    data = _data()
    q = _text(request.args.get("q"), 80).lower()
    with _db() as conn:
        allowed = _allowed_groups(conn, data, p)
        rows = [s for s in _center_students(data, p["center"]) if student_status(s) not in ARCHIVED
                and (allowed is None or str(s.get("group") or "") in allowed or p["id"] in _teacher_ids_of(s))]
        if q:
            rows = [s for s in rows if q in f"{_student_name(s)} {s.get('phone') or ''} {s.get('parentPhone') or ''} {s.get('group') or ''}".lower()]
        ids = [int(s["id"]) for s in rows]
        balances = _balances(conn, p["center"], ids)
        month = _this_month()
        att = _all(conn, """SELECT student_id, status FROM att_records WHERE center_id = ? AND lesson_date >= ? AND lesson_date <= ?""",
                   (p["center"], month + "-01", month + "-31"))
    by_student: dict[int, list[dict[str, Any]]] = {}
    for r in att:
        by_student.setdefault(int(r["student_id"]), []).append(r)
    items = [{
        "id": int(s["id"]), "name": _student_name(s), "phone": s.get("phone") or "", "parentPhone": s.get("parentPhone") or "",
        "group": ", ".join(student_groups(s)), "status": student_status(s), "attendance": _stats(by_student.get(int(s["id"]), []))["rate"],
        "birthDate": s.get("birthDate") or "", "birthday": is_birthday(s),
        **balances[int(s["id"])],
    } for s in rows]
    if request.args.get("debtors") == "1":
        items = [i for i in items if i["debt"] > 0]
    items.sort(key=lambda i: (i["group"], i["name"]))
    return jsonify({"ok": True, "items": items, "debtors": sum(1 for i in items if i["debt"] > 0),
                    "birthdays": [i["name"] for i in items if i["birthday"]]})


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
            lessons = [l for l in _all(conn, """SELECT * FROM sched_lessons WHERE center_id = ? AND status = 'active'
                ORDER BY weekday, start_time""", (p["center"],)) if l["group_name"] in student_groups(s)]
            out.append({"student_id": sid, "name": _student_name(s), "group": s.get("group") or "", "status": student_status(s),
                        "records": rows, "stats": _stats(rows), "lessons": [_lesson_out(l, teachers) for l in lessons]})
    return jsonify({"ok": True, "items": out})


# --------------------------------------------------------------------------
# O'qituvchi oyligi
# --------------------------------------------------------------------------
def _rule_for(rules: list[dict[str, Any]], month: str) -> Optional[dict[str, Any]]:
    active = sorted((r for r in rules if r["effective_from"] <= month), key=lambda r: (r["effective_from"], r["created_at"]))
    return active[-1] if active else None


def compute_salary(rule: Optional[dict[str, Any]], base: int, paid_students: int = 0) -> int:
    """fixed: value so'm. percent: value = foiz*100 (35.5% -> 3550), tushumdan.
    per_student: value so'm har bir shu oy to'lov qilgan o'quvchi uchun."""
    if not rule:
        return 0
    if rule["type"] == "fixed":
        return int(rule["value"])
    if rule["type"] == "per_student":
        return int(rule["value"]) * paid_students
    return int(base) * int(rule["value"]) // 10000


def _salary_rows(conn: Any, data: dict[str, Any], center: str, month: str, only_teacher: Optional[int] = None) -> list[dict[str, Any]]:
    rules: dict[int, list[dict[str, Any]]] = {}
    for r in _all(conn, "SELECT * FROM sal_rules WHERE center_id = ?", (center,)):
        rules.setdefault(int(r["teacher_id"]), []).append(r)
    students = {int(s["id"]): s for s in _center_students(data, center)}
    payouts: dict[int, dict[str, int]] = {}
    for r in _all(conn, "SELECT teacher_id, kind, SUM(amount) AS s FROM sal_payouts WHERE center_id = ? AND month = ? GROUP BY teacher_id, kind",
                  (center, month)):
        payouts.setdefault(int(r["teacher_id"]), {})[r["kind"]] = int(r["s"])
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
        paid_students = len({int(x["student_id"]) for x in pays})
        out.append({
            "teacher_id": tid, "teacher_name": str(t.get("name") or f"#{tid}"),
            "rule": rule, "base": base, "payments_count": len(pays), "paid_students": paid_students,
            "students": sum(1 for s in students.values() if tid in _teacher_ids_of(s) and student_status(s) not in ARCHIVED),
            "amount": compute_salary(rule, base, paid_students),
            "remaining": compute_salary(rule, base, paid_students) - sum(payouts.get(tid, {}).values()),
            "advance": payouts.get(tid, {}).get("advance", 0),
            "paid_out": sum(payouts.get(tid, {}).values()),
            "payments": pays if only_teacher is not None else None,
        })
    out.sort(key=lambda r: r["teacher_name"])
    return out


def _month_arg() -> Optional[str]:
    month = _text(request.args.get("month"), 7) or _this_month()
    return month if _YM_RE.match(month) else None


@bp.get("/salary")
@require_auth("admin", "manager")
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
@require_auth("admin", "manager")
def salary_rule():
    p = g.principal
    body = _body()
    kind = str(body.get("type") or "")
    try:
        teacher_id = int(body.get("teacher_id"))
        raw = float(str(body.get("value")).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return _err("O'qituvchi va qiymatni kiriting")
    if kind in ("fixed", "per_student"):
        value = int(raw)
        if not 0 <= value <= MAX_AMOUNT:
            return _err("Maosh summasi noto'g'ri")
    elif kind == "percent":
        if not 0 <= raw <= 100:
            return _err("Foiz 0 dan 100 gacha bo'lsin")
        value = round(raw * 100)
    else:
        return _err("Turi: qat'iy maosh, foiz yoki har o'quvchi uchun summa")
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


# --------------------------------------------------------------------------
# AI yordamchi
# --------------------------------------------------------------------------
def ask_openai(messages: list[dict[str, str]], max_tokens: int = 700) -> tuple[Optional[str], Optional[str]]:
    """OpenAI chat javobi. (javob, None) yoki (None, xato matni)."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return None, "OPENAI_API_KEY sozlanmagan"
    payload = json.dumps({"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"), "messages": messages,
                          "temperature": 0.3, "max_tokens": max_tokens}).encode("utf-8")
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=payload, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=35) as res:
            out = json.loads(res.read().decode("utf-8"))
        return (out.get("choices", [{}])[0].get("message", {}).get("content", "").strip() or "Javob topilmadi"), None
    except urllib.error.HTTPError as exc:
        return None, exc.read().decode("utf-8", errors="ignore") or str(exc)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def center_snapshot(p: dict[str, Any]) -> dict[str, Any]:
    """AI uchun markaz holati — faqat umumiy raqamlar, ism/telefon yuborilmaydi."""
    data = _data()
    students = _center_students(data, p["center"])
    counts: dict[str, int] = {}
    for s in students:
        counts[student_status(s)] = counts.get(student_status(s), 0) + 1
    month = _this_month()
    today = _today()
    with _db() as conn:
        balances = _balances(conn, p["center"], [int(s["id"]) for s in students])
        att = _stats(_all(conn, "SELECT status FROM att_records WHERE center_id = ? AND lesson_date = ?", (p["center"], today.isoformat())))
        lessons_today = _one(conn, "SELECT COUNT(*) AS n FROM sched_lessons WHERE center_id = ? AND weekday = ? AND status = 'active'",
                             (p["center"], today.isoweekday()))
        leads = _all(conn, """SELECT subject, COUNT(*) AS n FROM crm_leads WHERE center_id = ? AND status IN ('new', 'contacted', 'waiting')
            GROUP BY subject""", (p["center"],))
        snap: dict[str, Any] = {
            "sana": today.isoformat(), "oquvchilar_holati": counts, "guruhlar_soni": len({s.get("group") for s in students if s.get("group")}),
            "bugungi_darslar": int(lessons_today["n"]), "bugungi_davomat": att,
            "qabul_kutayotganlar_fan_boyicha": {r["subject"]: int(r["n"]) for r in leads},
        }
        if is_full_admin(p):
            fin = _one(conn, """SELECT COALESCE(SUM(amount), 0) AS s, COUNT(*) AS n FROM fin_payments
                WHERE center_id = ? AND status = 'active' AND day >= ?""", (p["center"], month + "-01"))
            exp = _one(conn, "SELECT COALESCE(SUM(amount), 0) AS s FROM fin_expenses WHERE center_id = ? AND status = 'active' AND day >= ?",
                       (p["center"], month + "-01"))
            debtors = [b["debt"] for b in balances.values() if b["debt"] > 0]
            snap.update({"shu_oy_tushum": int(fin["s"]), "shu_oy_tolovlar_soni": int(fin["n"]), "shu_oy_xarajat": int(exp["s"]),
                         "qarzdorlar_soni": len(debtors), "qarz_jami": sum(debtors)})
    return snap


_AI_GUIDE = (
    "Siz TEXNOO o'quv markazi boshqaruv tizimining yordamchisisiz. O'zbek tilida qisqa va aniq javob bering. "
    "Faqat berilgan markaz ma'lumotlariga tayaning, raqam o'ylab topmang; ma'lumot bo'lmasa shuni ayting. "
    "Tizim bo'limlari: 'O'quvchilar (CRM)' — qabul (yangi kelganlar fan bo'yicha), o'quvchi qo'shish, guruhga ko'chirish, "
    "muzlatish, bitirish/ketish arxivi, o'quvchi profili (tarix, to'lov, sertifikat); 'Moliya va kassa' — to'lov qabul qilish "
    "(bir oy uchun qayta to'lov mumkin emas), xarajat, oylik tarif va chegirma (sababi bilan), qarzdorlar, CSV eksport; "
    "'Dars jadvali' — haftalik darslar, to'qnashuv tekshiruvi; 'Davomat' — keldi/kechikdi/sababli/kelmadi; "
    "'O'qituvchilar oyligi' — qat'iy, foiz yoki har to'lagan o'quvchi uchun summa. Qanday qilishni so'rashsa, qadamma-qadam tushuntiring."
)


@bp.post("/ai")
@require_auth("admin", "manager")
def ai_assist():
    p = g.principal
    question = _text(_body().get("question"), 1000)
    if not question:
        return _err("Savolni yozing")
    snap = center_snapshot(p)
    answer, error = ask_openai([
        {"role": "system", "content": _AI_GUIDE},
        {"role": "system", "content": "Markaz ma'lumotlari (JSON): " + json.dumps(snap, ensure_ascii=False)},
        {"role": "user", "content": question},
    ])
    if error:
        return _err("AI javob bermadi: " + error[:300], 503 if "sozlanmagan" in error else 502)
    return jsonify({"ok": True, "answer": answer})



@bp.post("/salary/payouts")
@require_auth("admin", "manager")
def salary_payout():
    """O'qituvchiga avans yoki oylik berildi: oylikdan ayiriladi va kassada "Ish haqi" xarajati bo'lib yoziladi."""
    p = g.principal
    body = _body()
    kind = str(body.get("kind") or "advance")
    month = _text(body.get("month"), 7) or _this_month()
    try:
        teacher_id = int(body.get("teacher_id"))
        amount = int(str(body.get("amount")).replace(" ", ""))
    except (TypeError, ValueError):
        return _err("O'qituvchi va summani kiriting")
    if kind not in ("advance", "salary"):
        return _err("Turi: avans yoki oylik")
    if not 0 < amount <= MAX_AMOUNT:
        return _err("Summa noto'g'ri")
    if not _YM_RE.match(month):
        return _err("Oy formati YYYY-MM")
    method = str(body.get("method") or "cash")
    if method not in ("cash", "card", "bank"):
        return _err("To'lov turi noto'g'ri")
    teacher = _teachers(_data()).get(teacher_id)
    if not teacher:
        return _err("O'qituvchi topilmadi", 404)
    label = "Avans" if kind == "advance" else "Oylik"
    note = f"{label}: {teacher.get('name')} ({month}) {_text(body.get('note'), 200)}".strip()
    now = _now_ms()
    with _db() as conn:
        expense_id = str(uuid.uuid4())
        _x(conn, """INSERT INTO fin_expenses (id, center_id, category, amount, method, note, status, created_by_role, created_by_id,
            created_by_name, idempotency_key, day, created_at) VALUES (?, ?, 'salary', ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)""",
           (expense_id, p["center"], amount, method, note, p["level"] or p["role"], p["id"], p["name"], expense_id, _today().isoformat(), now))
        row = {"id": str(uuid.uuid4()), "center_id": p["center"], "teacher_id": teacher_id, "month": month, "kind": kind,
               "amount": amount, "note": note, "expense_id": expense_id, "created_by_name": p["name"], "created_at": now}
        cols = list(row)
        _x(conn, f"INSERT INTO sal_payouts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        _audit(conn, p, "salary.payout", "teacher", teacher_id, {"kind": kind, "amount": amount, "month": month})
        history = _all(conn, "SELECT * FROM sal_payouts WHERE center_id = ? AND teacher_id = ? AND month = ? ORDER BY created_at",
                       (p["center"], teacher_id, month))
    return jsonify({"ok": True, "payout": row, "history": history}), 201


@bp.get("/salary/payouts")
@require_auth("admin", "manager")
def salary_payouts():
    p = g.principal
    month = _month_arg()
    if not month:
        return _err("Oy formati YYYY-MM")
    with _db() as conn:
        rows = _all(conn, "SELECT * FROM sal_payouts WHERE center_id = ? AND month = ? ORDER BY created_at DESC", (p["center"], month))
    return jsonify({"ok": True, "items": rows})


# --------------------------------------------------------------------------
# Tug'ilgan kun
# --------------------------------------------------------------------------
def is_birthday(s: dict[str, Any], today: Optional[date] = None) -> bool:
    bd = str(s.get("birthDate") or "")
    return bool(_DAY_RE.match(bd)) and bd[5:] == (today or _today()).isoformat()[5:]


def birthday_tick(send: Callable[[Any, str], Any], today: Optional[date] = None) -> int:
    """Bugun tug'ilgan o'quvchiga tabrik va uning o'qituvchisiga eslatma (Telegram ulangan bo'lsa). Kuniga bir marta."""
    today = today or _today()
    data = _data()
    teachers = _teachers(data)
    sent = 0
    init_finance_db()
    with _db() as conn:
        for s in data.get("students", []):
            if not isinstance(s, dict) or student_status(s) in ARCHIVED or not is_birthday(s, today):
                continue
            name = _student_name(s)
            targets = [(s.get("telegramId"), f"🎉 Hurmatli {name}! Tug'ilgan kuningiz bilan tabriklaymiz! O'qishlaringizda omad va yangi marralar tilaymiz. — {os.environ.get('SCHOOL_NAME', 'TEXNOO')}")]
            for tid in _teacher_ids_of(s):
                t = teachers.get(tid) or {}
                targets.append((t.get("telegramId"), f"🎂 Bugun o'quvchingiz {name} ({s.get('group') or ''}) tug'ilgan kuni. Tabriklashni unutmang!"))
            for chat_id, text in targets:
                if not chat_id:
                    continue
                key = f"bday:{today.isoformat()}:{chat_id}:{s.get('id')}"
                if _one(conn, "SELECT key FROM notif_log WHERE key = ?", (key,)):
                    continue
                ok = send(chat_id, text)
                if ok is not False and not (isinstance(ok, tuple) and ok and ok[0] is False):
                    _x(conn, "INSERT INTO notif_log (key, created_at) VALUES (?, ?)", (key, _now_ms()))
                    sent += 1
    return sent


def start_birthday_job(send: Callable[[Any, str], Any]) -> None:
    def loop() -> None:
        while True:
            try:
                birthday_tick(send)
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger("school").exception("Tug'ilgan kun tabrigi yuborilmadi")
            time.sleep(3600)
    threading.Thread(target=loop, name="birthday-job", daemon=True).start()


# --------------------------------------------------------------------------
# Ta'lim yangiliklari (RSS)
# --------------------------------------------------------------------------
NEWS_FEEDS = [u.strip() for u in os.environ.get(
    "NEWS_RSS_URLS", "https://kun.uz/news/rss,https://www.gazeta.uz/uz/rss/,https://daryo.uz/feed/,https://uza.uz/uz/rss").split(",") if u.strip()]
EDU_WORDS = ("ta'lim", "ta’lim", "talim", "maktab", "o'quvchi", "o‘quvchi", "talaba", "universitet", "oliy ta", "imtihon", "abituriyent",
             "dtm", "ielts", "sat ", "o'qituvchi", "o‘qituvchi", "ustoz", "bitiruvchi", "grant", "kontrakt", "litsey", "kollej", "akademiya",
             "таълим", "мактаб", "ўқувчи", "талаба", "университет", "имтиҳон", "ўқитувчи", "абитуриент")
_news_cache: dict[str, Any] = {"at": 0.0, "items": []}
_NEWS_TTL = 300


def _fetch_feed(url: str) -> list[dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TexnooNews)"})
    with urllib.request.urlopen(req, timeout=8) as res:
        root = ET.fromstring(res.read(3_000_000))
    source = urllib.parse.urlparse(url).netloc.replace("www.", "")
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith(("http://", "https://")):
            continue
        desc = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        out.append({"title": title[:300], "link": link, "source": source, "date": (item.findtext("pubDate") or "").strip(),
                    "summary": re.sub(r"\s+", " ", desc).strip()[:300]})
    return out


def edu_news(force: bool = False) -> list[dict[str, Any]]:
    if not force and time.time() - _news_cache["at"] < _NEWS_TTL:
        return _news_cache["items"]
    items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda u: _safe_fetch(u), NEWS_FEEDS):
            items += result
    for it in items:
        text = f"{it['title']} {it['summary']}".lower()
        it["edu"] = any(w in text for w in EDU_WORDS)
    _news_cache.update(at=time.time(), items=items)
    return items


def _safe_fetch(url: str) -> list[dict[str, Any]]:
    try:
        return _fetch_feed(url)
    except Exception:  # noqa: BLE001
        return []


@bp.get("/news")
@require_auth()
def news_feed():
    items = edu_news()
    only_edu = request.args.get("all") != "1"
    rows = [i for i in items if i["edu"]] if only_edu else items
    return jsonify({"ok": True, "items": rows[:60], "sources": sorted({i["source"] for i in items}), "updated_at": int(_news_cache["at"])})
