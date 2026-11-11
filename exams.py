"""CEFR va SAT amaliy imtihonlari.

Savollar serverda saqlanadi; o'quvchiga to'g'ri javoblar yuborilmaydi, ball serverda hisoblanadi.
Natija taxminiy (amaliy) — rasmiy CEFR/SAT sertifikati emas.
Savollar banki bo'sh bo'lsa exam_bank.json dagi boshlang'ich savollar yuklanadi; xodimlar savol qo'sha oladi.
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any, Optional

from flask import Blueprint, g, jsonify, request

from crm import _dataset
from finance import _all, _audit, _body, _db, _err, _now_ms, _one, _student_name, _text, _x, init_finance_db
from security import require_auth

EXAMS: dict[str, dict[str, Any]] = {
    "cefr": {"name": "CEFR (ingliz tili darajasi)", "minutes": 30, "sections": {"grammar": 18, "vocabulary": 12},
             "levels": ("A1", "A2", "B1", "B2", "C1", "C2")},
    "sat": {"name": "SAT (Math + Reading & Writing)", "minutes": 35, "sections": {"math": 12, "rw": 8},
            "levels": ("easy", "medium", "hard")},
}
SECTION_LABEL = {"grammar": "Grammatika", "vocabulary": "Lug'at", "math": "Math", "rw": "Reading & Writing"}
GRACE_MS = 2 * 60 * 1000
BANK = Path(__file__).resolve().parent / "exam_bank.json"

bp = Blueprint("exams", __name__, url_prefix="/api/exams")

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS exam_questions (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        exam TEXT NOT NULL,
        section TEXT NOT NULL,
        level TEXT,
        text TEXT NOT NULL,
        options_json TEXT NOT NULL,
        answer INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_by_name TEXT,
        created_at BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS exam_attempts (
        id TEXT PRIMARY KEY,
        center_id TEXT NOT NULL,
        student_id BIGINT NOT NULL,
        exam TEXT NOT NULL,
        question_ids TEXT NOT NULL,
        answers_json TEXT,
        started_at BIGINT NOT NULL,
        deadline_at BIGINT NOT NULL,
        submitted_at BIGINT,
        correct INTEGER,
        total INTEGER NOT NULL,
        result_json TEXT,
        late INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_exam_attempts_student ON exam_attempts (center_id, student_id)",
]
_ready = False


@bp.before_request
def _ensure_schema() -> None:
    global _ready
    init_finance_db()
    if not _ready:
        with _db() as conn:
            for stmt in _SCHEMA:
                _x(conn, stmt)
        _ready = True


def _seed(conn: Any, center: str, exam: str) -> None:
    if _one(conn, "SELECT id FROM exam_questions WHERE center_id = ? AND exam = ? LIMIT 1", (center, exam)):
        return
    for q in json.loads(BANK.read_text(encoding="utf-8")).get(exam, []):
        _x(conn, """INSERT INTO exam_questions (id, center_id, exam, section, level, text, options_json, answer, status, created_by_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 'TEXNOO', ?)""",
           (str(uuid.uuid4()), center, exam, q["section"], q.get("level"), q["text"], json.dumps(q["options"], ensure_ascii=False),
            int(q["answer"]), _now_ms()))


def _plan(raw: str) -> list[dict[str, Any]]:
    return [{"id": x, "perm": list(range(10))} if isinstance(x, str) else x for x in json.loads(raw)]


def score(exam: str, questions: list[dict[str, Any]], answers: list[Any]) -> dict[str, Any]:
    """Bo'limlar bo'yicha to'g'ri javoblar va taxminiy daraja/ball."""
    by_section: dict[str, list[int]] = {}
    for i, q in enumerate(questions):
        chosen = answers[i] if i < len(answers) else None
        by_section.setdefault(q["section"], [0, 0])
        by_section[q["section"]][1] += 1
        if isinstance(chosen, int) and chosen == int(q["answer"]):
            by_section[q["section"]][0] += 1
    correct = sum(v[0] for v in by_section.values())
    total = sum(v[1] for v in by_section.values())
    sections = {k: {"correct": v[0], "total": v[1]} for k, v in by_section.items()}
    result: dict[str, Any] = {"correct": correct, "total": total, "sections": sections}
    pct = correct / total if total else 0
    if exam == "cefr":
        result["level"] = next(lvl for lim, lvl in ((0.25, "A1"), (0.45, "A2"), (0.6, "B1"), (0.75, "B2"), (0.9, "C1"), (1.01, "C2")) if pct < lim)
    else:
        scaled = {k: 200 + round(v["correct"] / v["total"] * 60) * 10 if v["total"] else 200 for k, v in sections.items()}
        result["scaled"] = scaled
        result["total_score"] = scaled.get("math", 200) + scaled.get("rw", 200)
    return result


def _staff_or_teacher_students(p: dict[str, Any]) -> Optional[set[int]]:
    """None = hamma (xodimlar); o'qituvchi uchun faqat o'z o'quvchilari."""
    if p["role"] == "admin":
        return None
    ids = set()
    for s in _dataset["read"]().get("students", []):
        tids = {str(x) for x in (s.get("teacherIds") or [])} | {str(s.get("teacherId") or "")}
        if str(p["id"]) in tids:
            ids.add(int(s.get("id") or 0))
    return ids


# --------------------------------------------------------------------------
# O'quvchi
# --------------------------------------------------------------------------
@bp.get("")
@require_auth()
def exams_info():
    p = g.principal
    mine: list[dict[str, Any]] = []
    if p["role"] == "student":
        with _db() as conn:
            mine = _all(conn, """SELECT id, exam, submitted_at, correct, total, result_json, late FROM exam_attempts
                WHERE center_id = ? AND student_id = ? AND submitted_at IS NOT NULL ORDER BY submitted_at DESC LIMIT 20""",
                        (p["center"], p["id"]))
        for r in mine:
            r["result"] = json.loads(r.pop("result_json") or "{}")
    return jsonify({"ok": True, "exams": {k: {"name": v["name"], "minutes": v["minutes"], "questions": sum(v["sections"].values())}
                                          for k, v in EXAMS.items()}, "results": mine})


@bp.post("/<exam>/start")
@require_auth("student")
def start(exam: str):
    p = g.principal
    cfg = EXAMS.get(exam)
    if not cfg:
        return _err("Imtihon topilmadi", 404)
    now = _now_ms()
    with _db() as conn:
        _seed(conn, p["center"], exam)
        open_attempt = _one(conn, """SELECT * FROM exam_attempts WHERE center_id = ? AND student_id = ? AND exam = ?
            AND submitted_at IS NULL AND deadline_at > ? ORDER BY started_at DESC LIMIT 1""", (p["center"], p["id"], exam, now))
        if open_attempt:
            plan = _plan(open_attempt["question_ids"])
        else:
            picked = []
            for section, count in cfg["sections"].items():
                pool = _all(conn, """SELECT id, options_json FROM exam_questions WHERE center_id = ? AND exam = ? AND section = ?
                    AND status = 'active'""", (p["center"], exam, section))
                picked += random.sample(pool, min(count, len(pool)))
            if not picked:
                return _err("Savollar banki bo'sh", 409)
            # Har bir urinishda variantlar tartibi aralashtiriladi (to'g'ri javob o'rnini yodlab bo'lmaydi).
            plan = [{"id": r["id"], "perm": random.sample(range(len(json.loads(r["options_json"]))), len(json.loads(r["options_json"])))}
                    for r in picked]
            open_attempt = {"id": str(uuid.uuid4()), "center_id": p["center"], "student_id": p["id"], "exam": exam,
                            "question_ids": json.dumps(plan), "started_at": now, "deadline_at": now + cfg["minutes"] * 60000, "total": len(plan)}
            cols = list(open_attempt)
            _x(conn, f"INSERT INTO exam_attempts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [open_attempt[c] for c in cols])
        ids = [q["id"] for q in plan]
        rows = {r["id"]: r for r in _all(conn, f"SELECT id, section, text, options_json FROM exam_questions WHERE id IN ({', '.join('?' * len(ids))})", ids)}
    questions = []
    for q in plan:
        if q["id"] in rows:
            opts = json.loads(rows[q["id"]]["options_json"])
            questions.append({"id": q["id"], "section": rows[q["id"]]["section"], "text": rows[q["id"]]["text"],
                              "options": [opts[k] for k in q["perm"] if k < len(opts)]})
    return jsonify({"ok": True, "attempt_id": open_attempt["id"], "exam": exam, "name": cfg["name"],
                    "deadline_at": open_attempt["deadline_at"], "now": now, "questions": questions})


@bp.post("/attempts/<attempt_id>/submit")
@require_auth("student")
def submit(attempt_id: str):
    p = g.principal
    answers = _body().get("answers")
    if not isinstance(answers, list) or len(answers) > 200:
        return _err("Javoblar ro'yxati noto'g'ri")
    answers = [a if isinstance(a, int) and 0 <= a < 10 else None for a in answers]
    now = _now_ms()
    with _db() as conn:
        att = _one(conn, "SELECT * FROM exam_attempts WHERE id = ? AND center_id = ? AND student_id = ?", (attempt_id, p["center"], p["id"]))
        if not att:
            return _err("Urinish topilmadi", 404)
        if att["submitted_at"]:
            return _err("Bu imtihon allaqachon topshirilgan", 409)
        plan = _plan(att["question_ids"])
        ids = [q["id"] for q in plan]
        rows = {r["id"]: r for r in _all(conn, f"SELECT id, section, answer FROM exam_questions WHERE id IN ({', '.join('?' * len(ids))})", ids)}
        kept = [(q, rows[q["id"]]) for q in plan if q["id"] in rows]
        # Ko'rsatilgan tartibdagi tanlovni bankdagi asl variant raqamiga qaytaramiz.
        original = [q["perm"][a] if isinstance(a, int) and a < len(q["perm"]) else None
                    for (q, _), a in zip(kept, answers + [None] * len(kept))]
        late = now > int(att["deadline_at"]) + GRACE_MS
        # Vaqt tugagandan keyin yuborilgan javoblar hisobga olinmaydi.
        result = score(att["exam"], [r for _, r in kept], [] if late else original)
        _x(conn, """UPDATE exam_attempts SET answers_json = ?, submitted_at = ?, correct = ?, result_json = ?, late = ? WHERE id = ?""",
           (json.dumps(answers), now, result["correct"], json.dumps(result, ensure_ascii=False), int(late), attempt_id))
        _audit(conn, p, "exam.submit", "exam", attempt_id, {"exam": att["exam"], "correct": result["correct"], "total": result["total"]})
    return jsonify({"ok": True, "result": result, "late": late})


# --------------------------------------------------------------------------
# Xodimlar va o'qituvchi: natijalar va savollar banki
# --------------------------------------------------------------------------
@bp.get("/results")
@require_auth("admin", "manager", "teacher")
def results():
    p = g.principal
    allowed = _staff_or_teacher_students(p)
    where, params = ["center_id = ?", "submitted_at IS NOT NULL"], [p["center"]]
    if request.args.get("student_id", "").isdigit():
        where.append("student_id = ?")
        params.append(int(request.args["student_id"]))
    if request.args.get("exam") in EXAMS:
        where.append("exam = ?")
        params.append(request.args["exam"])
    with _db() as conn:
        rows = _all(conn, f"""SELECT id, student_id, exam, submitted_at, correct, total, result_json, late FROM exam_attempts
            WHERE {' AND '.join(where)} ORDER BY submitted_at DESC LIMIT 300""", params)
    names = {int(s.get("id") or 0): (_student_name(s), s.get("group") or "") for s in _dataset["read"]().get("students", []) if isinstance(s, dict)}
    out = []
    for r in rows:
        if allowed is not None and int(r["student_id"]) not in allowed:
            continue
        r["result"] = json.loads(r.pop("result_json") or "{}")
        r["student_name"], r["group"] = names.get(int(r["student_id"]), (f"#{r['student_id']}", ""))
        out.append(r)
    return jsonify({"ok": True, "items": out})


@bp.get("/questions")
@require_auth("admin", "manager", "teacher")
def list_questions():
    p = g.principal
    exam = request.args.get("exam", "cefr")
    if exam not in EXAMS:
        return _err("Imtihon noto'g'ri")
    with _db() as conn:
        _seed(conn, p["center"], exam)
        rows = _all(conn, """SELECT id, section, level, text, options_json, answer, created_by_name FROM exam_questions
            WHERE center_id = ? AND exam = ? AND status = 'active' ORDER BY section, created_at""", (p["center"], exam))
    for r in rows:
        r["options"] = json.loads(r.pop("options_json"))
    return jsonify({"ok": True, "items": rows, "sections": list(EXAMS[exam]["sections"]), "levels": EXAMS[exam]["levels"]})


@bp.post("/questions")
@require_auth("admin", "manager", "teacher")
def add_question():
    p = g.principal
    body = _body()
    exam, section = str(body.get("exam") or ""), str(body.get("section") or "")
    if exam not in EXAMS or section not in EXAMS[exam]["sections"]:
        return _err("Imtihon yoki bo'lim noto'g'ri")
    text = _text(body.get("text"), 1000)
    options = [_text(o, 300) for o in (body.get("options") or [])]
    try:
        answer = int(body.get("answer"))
    except (TypeError, ValueError):
        return _err("To'g'ri javobni belgilang")
    if not text or not 2 <= len(options) <= 6 or not all(options) or not 0 <= answer < len(options):
        return _err("Savol matni, 2–6 ta variant va to'g'ri javob kerak")
    level = _text(body.get("level"), 10)
    row = {"id": str(uuid.uuid4()), "center_id": p["center"], "exam": exam, "section": section,
           "level": level if level in EXAMS[exam]["levels"] else None, "text": text,
           "options_json": json.dumps(options, ensure_ascii=False), "answer": answer, "status": "active",
           "created_by_name": p["name"], "created_at": _now_ms()}
    cols = list(row)
    with _db() as conn:
        _seed(conn, p["center"], exam)
        _x(conn, f"INSERT INTO exam_questions ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", [row[c] for c in cols])
        _audit(conn, p, "exam.question_add", "exam", row["id"], {"exam": exam, "section": section})
    return jsonify({"ok": True, "id": row["id"]}), 201


@bp.post("/questions/<question_id>/remove")
@require_auth("admin", "manager", "teacher")
def remove_question(question_id: str):
    p = g.principal
    with _db() as conn:
        q = _one(conn, "SELECT id FROM exam_questions WHERE id = ? AND center_id = ? AND status = 'active'", (question_id, p["center"]))
        if not q:
            return _err("Savol topilmadi", 404)
        _x(conn, "UPDATE exam_questions SET status = 'removed' WHERE id = ?", (question_id,))
        _audit(conn, p, "exam.question_remove", "exam", question_id, {})
    return jsonify({"ok": True})
