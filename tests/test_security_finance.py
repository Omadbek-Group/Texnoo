"""Xavfsizlik (token, RBAC, /api/data himoyasi) va moliya moduli testlari.

Ishga tushirish:  python -m pytest tests -q
"""

import importlib
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    monkeypatch.setenv("SQLITE_PATH", str(Path(tmp) / "test.sqlite3"))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RUN_TELEGRAM_BOT", "0")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("RATE_LIMIT_API", "100000")
    monkeypatch.setenv("RATE_LIMIT_WRITE", "100000")
    monkeypatch.setenv("RATE_LIMIT_AUTH", "100000")
    sys.path.insert(0, str(ROOT))
    for name in ("app", "school", "crm", "finance", "security", "data_database"):
        sys.modules.pop(name, None)
    app_module = importlib.import_module("app")
    data = {
        "students": [
            {"id": 1001, "name": "Ali Valiyev", "phone": "+998901112233", "email": "ali@x.uz", "password": "pass1", "group": "D1", "teacherId": 2001, "teacherIds": [2001]},
            {"id": 1002, "name": "Vali Aliyev", "phone": "+998901112244", "email": "vali@x.uz", "password": "pass2", "group": "D2"},
        ],
        "teachers": [{"id": 2001, "name": "Ustoz", "phone": "+998900000001", "password": "teach", "status": "active"},
                     {"id": 2002, "name": "Ustoz2", "phone": "+998900000009", "password": "teach2", "status": "active"}],
        "admins": [
            {"id": 3001, "name": "Admin", "phone": "+998900000002", "password": "admin", "level": "platform_admin"},
            {"id": 3002, "name": "Kassir", "phone": "+998900000003", "password": "cash", "level": "cashier"},
            {"id": 3003, "name": "Menejer", "phone": "+998900000005", "password": "mgr", "level": "manager"},
            {"id": 3004, "name": "Boshliq", "phone": "+998900000006", "password": "boss", "level": "director"},
        ],
        "parents": [{"id": 3501, "name": "Ota", "phone": "+998900000004", "password": "par", "childPhones": ["+998901112233"]}],
        "employers": [],
        "transactions": [],
        "nextStudentId": 1003,
    }
    app_module.write_data(app_module.normalize_data(data)[0])
    app_module.app.config["TESTING"] = True
    yield app_module.app.test_client()
    sys.path.remove(str(ROOT))


def login(client, identifier, password):
    res = client.post("/api/auth/login", json={"identifier": identifier, "password": password})
    assert res.status_code == 200, res.get_json()
    return {"Authorization": "Bearer " + res.get_json()["token"]}


def key():
    return uuid.uuid4().hex


# ---------------------------------------------------------------- security
def test_data_requires_login(client):
    assert client.get("/api/data").status_code == 401
    assert client.post("/api/data", json={"students": [], "transactions": [], "nextStudentId": 1}).status_code == 401
    assert client.get("/api/data", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_sensitive_files_not_served(client):
    index = client.get("/").data
    for path in ("/app.py", "/data_database.py", "/requirements.txt", "/.env", "/security.py"):
        # 404 handler SPA uchun index.html qaytaradi; muhimi — fayl mazmuni berilmaydi.
        assert client.get(path).data == index, path
    assert b"<html" in client.get("/privacy.html").data.lower()


def test_student_sees_no_foreign_contacts(client):
    h = login(client, "+998901112233", "pass1")
    data = client.get("/api/data", headers=h).get_json()
    other = next(s for s in data["students"] if s["id"] == 1002)
    me = next(s for s in data["students"] if s["id"] == 1001)
    assert other["phone"] == "" and other["email"] == ""
    assert me["phone"] == "+998901112233"
    assert all(not s.get("password") for s in data["students"])


def test_student_cannot_escalate_or_wipe(client):
    h = login(client, "+998901112233", "pass1")
    data = client.get("/api/data", headers=h).get_json()
    data["admins"] = [{"id": 9999, "name": "Hacker", "password": "x", "level": "platform_admin"}]
    data["students"] = [s for s in data["students"] if s["id"] == 1001]  # boshqa talabani o'chirishga urinish
    data["students"][0]["password"] = "hacked"
    data["teachers"][0]["status"] = "blocked"
    assert client.post("/api/data", json=data, headers=h).status_code == 200

    admin_h = login(client, "+998900000002", "admin")
    saved = client.get("/api/data", headers=admin_h).get_json()
    assert {a["id"] for a in saved["admins"]} == {3001, 3002, 3003, 3004}
    assert {s["id"] for s in saved["students"]} == {1001, 1002}
    assert saved["teachers"][0]["status"] == "active"
    assert next(s for s in saved["students"] if s["id"] == 1002)["phone"] == "+998901112244"
    # parol /api/data orqali o'zgarmadi
    assert client.post("/api/auth/login", json={"identifier": "+998901112233", "password": "hacked"}).status_code == 401
    login(client, "+998901112233", "pass1")


def test_register_then_login(client):
    res = client.post("/api/auth/register", json={
        "role": "student", "firstName": "Yangi", "lastName": "Talaba", "phone": "+998907777777", "password": "secret1",
    })
    assert res.status_code == 201
    assert client.post("/api/auth/register", json={
        "role": "student", "firstName": "A", "lastName": "B", "phone": "+998 90 777 77 77", "password": "secret1",
    }).status_code == 409
    login(client, "+998907777777", "secret1")


def test_password_change_revokes_old_token(client):
    h = login(client, "+998901112233", "pass1")
    res = client.post("/api/auth/change-password", headers=h, json={"oldPassword": "pass1", "newPassword": "pass9"})
    assert res.status_code == 200
    assert client.get("/api/data", headers=h).status_code == 401
    assert client.get("/api/data", headers={"Authorization": "Bearer " + res.get_json()["token"]}).status_code == 200


def test_admin_endpoints_need_admin_token(client):
    h = login(client, "+998901112233", "pass1")
    assert client.post("/api/admin/exchange-rate", headers=h, json={"adminId": 3001, "rate": 1}).status_code == 403
    assert client.post("/api/currency/exchange", headers=h, json={"studentId": 1002, "direction": "c2d", "amount": 1}).status_code == 403


# ---------------------------------------------------------------- finance
def test_payment_flow_debt_and_void(client):
    admin = login(client, "+998900000002", "admin")
    month = __import__("finance")._this_month()
    assert client.post("/api/finance/fees", headers=admin, json={"student_id": 1001, "monthly_fee": 500000, "effective_from": month}).status_code == 201

    k = key()
    res = client.post("/api/finance/payments", headers=admin, json={"student_id": 1001, "amount": 300000, "method": "cash", "idempotency_key": k})
    assert res.status_code == 201
    pay = res.get_json()["payment"]
    assert pay["receipt_no"].endswith("000001")
    # takroriy yuborish yangi yozuv yaratmaydi
    dup = client.post("/api/finance/payments", headers=admin, json={"student_id": 1001, "amount": 300000, "method": "cash", "idempotency_key": k})
    assert dup.get_json()["duplicate"] is True

    debtors = client.get("/api/finance/debtors", headers=admin).get_json()
    assert debtors["total"] == 200000 and debtors["items"][0]["student_id"] == 1001

    s = client.get("/api/finance/summary", headers=admin).get_json()
    assert s["income"] == 300000 and s["income_by_method"]["cash"] == 300000 and s["debt_total"] == 200000

    assert client.post(f"/api/finance/payments/{pay['id']}/void", headers=admin, json={"reason": ""}).status_code == 400
    assert client.post(f"/api/finance/payments/{pay['id']}/void", headers=admin, json={"reason": "Xato kiritildi"}).status_code == 200
    assert client.post(f"/api/finance/payments/{pay['id']}/void", headers=admin, json={"reason": "Yana"}).status_code == 409
    s = client.get("/api/finance/summary", headers=admin).get_json()
    assert s["income"] == 0 and s["debt_total"] == 500000
    # bekor qilingan yozuv o'chmaydi, ro'yxatda qoladi
    items = client.get("/api/finance/payments", headers=admin).get_json()["items"]
    assert items[0]["status"] == "void" and items[0]["void_reason"] == "Xato kiritildi"

    actions = [a["action"] for a in client.get("/api/finance/audit", headers=admin).get_json()["items"]]
    assert {"fee.set", "payment.create", "payment.void"} <= set(actions)


def test_expenses_and_net(client):
    admin = login(client, "+998900000002", "admin")
    client.post("/api/finance/payments", headers=admin, json={"student_id": 1002, "amount": 1000000, "method": "card", "idempotency_key": key()})
    assert client.post("/api/finance/expenses", headers=admin, json={"amount": 250000, "method": "cash", "category": "rent", "idempotency_key": key()}).status_code == 201
    assert client.post("/api/finance/expenses", headers=admin, json={"amount": 1, "method": "cash", "category": "bogus", "idempotency_key": key()}).status_code == 400
    s = client.get("/api/finance/summary", headers=admin).get_json()
    assert s["net"] == 750000 and s["balance_by_method"] == {"cash": -250000, "card": 1000000, "bank": 0}
    csv = client.get("/api/finance/export?kind=payments", headers=admin)
    assert csv.status_code == 200 and b"Vali Aliyev" in csv.data


def test_finance_rbac(client):
    student = login(client, "+998901112233", "pass1")
    teacher = login(client, "+998900000001", "teach")
    cashier = login(client, "+998900000003", "cash")
    admin = login(client, "+998900000002", "admin")
    for h in (student, teacher):
        assert client.get("/api/finance/payments", headers=h).status_code == 403
        assert client.post("/api/finance/payments", headers=h, json={"student_id": 1001, "amount": 1, "method": "cash", "idempotency_key": key()}).status_code == 403
    res = client.post("/api/finance/payments", headers=cashier, json={"student_id": 1002, "amount": 100000, "method": "bank", "idempotency_key": key()})
    assert res.status_code == 201
    pid = res.get_json()["payment"]["id"]
    # kassir bekor qila olmaydi va tarif o'rnata olmaydi, admin esa qila oladi
    assert client.post(f"/api/finance/payments/{pid}/void", headers=cashier, json={"reason": "test"}).status_code == 403
    assert client.post("/api/finance/fees", headers=cashier, json={"student_id": 1002, "monthly_fee": 1}).status_code == 403
    assert client.get("/api/finance/audit", headers=cashier).status_code == 403
    # kassir legacy datasetda admin huquqiga ega emas
    data = client.get("/api/data", headers=cashier).get_json()
    data["settings"]["schoolName"] = "Hack"
    client.post("/api/data", json=data, headers=cashier)
    assert client.get("/api/data", headers=admin).get_json()["settings"].get("schoolName") != "Hack"
    # talaba boshqa talabaning kvitansiyasini ko'rmaydi, ota-ona o'z farzandinikini ko'radi
    other = client.post("/api/finance/payments", headers=admin, json={"student_id": 1001, "amount": 5000, "method": "cash", "idempotency_key": key()}).get_json()["payment"]["id"]
    assert client.get(f"/api/finance/payments/{pid}", headers=student).status_code == 404
    assert client.get(f"/api/finance/payments/{other}", headers=student).status_code == 200
    parent = login(client, "+998900000004", "par")
    assert client.get(f"/api/finance/payments/{other}", headers=parent).status_code == 200
    assert client.get(f"/api/finance/payments/{pid}", headers=parent).status_code == 404
    my = client.get("/api/finance/my", headers=parent).get_json()
    assert [i["student_id"] for i in my["items"]] == [1001]


def test_validation(client):
    admin = login(client, "+998900000002", "admin")
    bad = [
        {"student_id": 1001, "amount": 0, "method": "cash", "idempotency_key": key()},
        {"student_id": 1001, "amount": -5, "method": "cash", "idempotency_key": key()},
        {"student_id": 1001, "amount": 100, "method": "crypto", "idempotency_key": key()},
        {"student_id": 1001, "amount": 100, "method": "cash"},
        {"student_id": 1001, "amount": 100, "method": "cash", "period": "2026-13", "idempotency_key": key()},
    ]
    for body in bad:
        assert client.post("/api/finance/payments", headers=admin, json=body).status_code == 400, body
    assert client.post("/api/finance/payments", headers=admin, json={"student_id": 4242, "amount": 100, "method": "cash", "idempotency_key": key()}).status_code == 404


def test_compute_charges_fee_history():
    sys.path.insert(0, str(ROOT))
    from finance import compute_charges
    fees = [
        {"effective_from": "2026-01", "monthly_fee": 100, "created_at": 1},
        {"effective_from": "2026-03", "monthly_fee": 200, "created_at": 2},
        {"effective_from": "2026-03", "monthly_fee": 150, "created_at": 3},  # o'sha oy uchun keyingi tuzatish
        {"effective_from": "2026-05", "monthly_fee": 0, "created_at": 4},   # to'xtatildi
    ]
    assert compute_charges(fees, "2026-02") == 200
    assert compute_charges(fees, "2026-04") == 100 + 100 + 150 + 150
    assert compute_charges(fees, "2026-08") == 500
    assert compute_charges([], "2026-08") == 0


# ---------------------------------------------------------------- CRM
def _month_shift(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def test_crm_freeze_skips_billing(client):
    admin = login(client, "+998900000002", "admin")
    month = __import__("finance")._this_month()
    m2, m1 = _month_shift(month, -2), _month_shift(month, -1)
    res = client.post("/api/crm/students", headers=admin, json={
        "firstName": "Muz", "lastName": "Talaba", "phone": "+998905550000", "group": "D3",
        "monthly_fee": 500000, "start_date": m2 + "-05"})
    assert res.status_code == 201
    sid = res.get_json()["student"]["id"]
    assert res.get_json()["password"]  # avtomatik parol bir marta qaytariladi
    assert client.post(f"/api/crm/students/{sid}/status", headers=admin, json={"status": "frozen", "reason": "Kasal", "date": m1 + "-01"}).status_code == 200
    assert client.post(f"/api/crm/students/{sid}/status", headers=admin, json={"status": "frozen", "reason": "x" * 5}).status_code == 409
    # muzlatilgan oy (m1) hisoblanmaydi, joriy oy qayta faollashtirilgach hisoblanadi
    assert client.post(f"/api/crm/students/{sid}/status", headers=admin, json={"status": "active"}).status_code == 200
    hist = client.get(f"/api/crm/students/{sid}/history", headers=admin).get_json()
    assert hist["student"]["charged"] == 1000000
    assert [e["type"] for e in hist["events"]].count("status_changed") == 2


def test_crm_move_and_legacy_delete_archives(client):
    admin = login(client, "+998900000002", "admin")
    assert client.post("/api/crm/students/1002/move", headers=admin, json={"group": "D9", "reason": "Daraja"}).status_code == 200
    client.post("/api/finance/payments", headers=admin, json={"student_id": 1002, "amount": 1000, "method": "cash", "idempotency_key": key()})
    # eski "o'chirish" tugmasi: admin datasetdan talabani olib tashlaydi
    data = client.get("/api/data", headers=admin).get_json()
    assert next(s for s in data["students"] if s["id"] == 1002)["group"] == "D9"
    data["students"] = [s for s in data["students"] if s["id"] != 1002]
    assert client.post("/api/data", json=data, headers=admin).status_code == 200
    assert 1002 not in [s["id"] for s in client.get("/api/data", headers=admin).get_json()["students"]]
    left = client.get("/api/crm/students?status=left", headers=admin).get_json()["items"]
    assert [s["id"] for s in left] == [1002] and left[0]["paid"] == 1000
    # arxivdagi talaba keyingi saqlashlarda yo'qolmaydi va qayta faollashtiriladi
    client.post("/api/data", json=client.get("/api/data", headers=admin).get_json(), headers=admin)
    assert client.post("/api/crm/students/1002/status", headers=admin, json={"status": "active", "group": "D1"}).status_code == 200
    events = [e["type"] for e in client.get("/api/crm/students/1002/history", headers=admin).get_json()["events"]]
    assert events.count("group_changed") == 1 and events.count("status_changed") == 2


def test_crm_rbac_and_status_authority(client):
    teacher = login(client, "+998900000001", "teach")
    cashier = login(client, "+998900000003", "cash")
    assert client.post("/api/crm/students/1001/status", headers=teacher, json={"status": "left", "reason": "test"}).status_code == 403
    assert client.post("/api/crm/students/1001/status", headers=cashier, json={"status": "left", "reason": "test"}).status_code == 403
    assert client.get("/api/crm/students", headers=cashier).status_code == 200
    # holatni /api/data orqali o'zgartirib bo'lmaydi (admin ham)
    admin = login(client, "+998900000002", "admin")
    data = client.get("/api/data", headers=admin).get_json()
    data["students"][0]["status"] = "graduated"
    client.post("/api/data", json=data, headers=admin)
    assert client.get("/api/crm/summary", headers=admin).get_json()["counts"]["graduated"] == 0


def test_billable_month():
    sys.path.insert(0, str(ROOT))
    from finance import billable_month
    ev = [{"to_status": "active", "effective_date": "2026-01-10", "created_at": 1},
          {"to_status": "frozen", "effective_date": "2026-02-15", "created_at": 2},
          {"to_status": "active", "effective_date": "2026-04-03", "created_at": 3}]
    assert [billable_month(ev, m) for m in ("2026-01", "2026-02", "2026-03", "2026-04")] == [True, True, False, True]
    assert billable_month([], "2026-03")


# ---------------------------------------------------------------- jadval, davomat, oylik, rollar
def lesson(client, h, **kw):
    body = {"group": "D1", "subject": "Python", "teacher_id": 2001, "room": "101", "weekday": 1, "start": "14:00", "end": "15:30"}
    body.update(kw)
    return client.post("/api/school/lessons", headers=h, json=body)


def test_schedule_conflicts(client):
    admin = login(client, "+998900000002", "admin")
    assert lesson(client, admin).status_code == 201
    assert lesson(client, admin, group="D2", start="15:00", end="16:00", room="102").status_code == 409   # o'qituvchi band
    assert lesson(client, admin, group="D2", teacher_id=2002, start="15:00", end="16:00").status_code == 409  # xona band
    assert lesson(client, admin, teacher_id=2002, start="14:30", end="15:00", room="103").status_code == 409  # guruh band
    assert lesson(client, admin, group="D2", start="15:30", end="17:00").status_code == 201  # ketma-ket, to'qnashmaydi
    assert lesson(client, admin, group="D2", teacher_id=2002, room="102", weekday=2).status_code == 201
    assert lesson(client, admin, start="16:00", end="15:00").status_code == 400
    teacher2 = login(client, "+998900000009", "teach2")
    assert [l["group_name"] for l in client.get("/api/school/lessons", headers=teacher2).get_json()["items"]] == ["D2"]
    student = login(client, "+998901112233", "pass1")
    assert {l["group_name"] for l in client.get("/api/school/lessons", headers=student).get_json()["items"]} == {"D1"}
    assert lesson(client, teacher2, weekday=3).status_code == 403


def test_attendance_access_and_stats(client):
    teacher = login(client, "+998900000001", "teach")
    today = __import__("finance")._today().isoformat()
    body = {"group": "D1", "date": today, "marks": [{"student_id": 1001, "status": "late"}]}
    assert client.post("/api/school/attendance", headers=teacher, json=body).status_code == 200
    body["marks"][0]["status"] = "present"   # qayta belgilash yangilaydi, takror yozmaydi
    assert client.post("/api/school/attendance", headers=teacher, json=body).status_code == 200
    assert client.post("/api/school/attendance", headers=teacher, json={**body, "group": "D2", "marks": [{"student_id": 1002, "status": "present"}]}).status_code == 403
    assert client.post("/api/school/attendance", headers=teacher, json={**body, "marks": [{"student_id": 1002, "status": "present"}]}).status_code == 400
    assert client.post("/api/school/attendance", headers=teacher, json={**body, "date": "2099-01-01"}).status_code == 400
    stats = client.get("/api/school/attendance/stats?group=D1", headers=teacher).get_json()
    assert stats["summary"]["total"] == 1 and stats["summary"]["present"] == 1 and stats["summary"]["rate"] == 100
    my = client.get("/api/school/attendance/my", headers=login(client, "+998901112233", "pass1")).get_json()
    assert my["items"][0]["records"][0]["status"] == "present"
    parent = client.get("/api/school/attendance/my", headers=login(client, "+998900000004", "par")).get_json()
    assert [i["student_id"] for i in parent["items"]] == [1001]
    manager = login(client, "+998900000005", "mgr")
    assert client.post("/api/school/attendance", headers=manager, json={**body, "group": "D2", "marks": [{"student_id": 1002, "status": "absent"}]}).status_code == 200
    assert client.get("/api/school/attendance/sheet?group=D1", headers=login(client, "+998900000003", "cash")).status_code == 403


def test_teacher_salary_percent_and_fixed(client):
    admin = login(client, "+998900000002", "admin")
    month = __import__("finance")._this_month()
    assert client.post("/api/school/salary/rules", headers=admin, json={"teacher_id": 2001, "type": "percent", "value": "30", "effective_from": month}).status_code == 201
    assert client.post("/api/school/salary/rules", headers=admin, json={"teacher_id": 2002, "type": "fixed", "value": 2000000, "effective_from": month}).status_code == 201
    assert client.post("/api/school/salary/rules", headers=admin, json={"teacher_id": 2002, "type": "percent", "value": 150}).status_code == 400
    client.post("/api/finance/payments", headers=admin, json={"student_id": 1001, "amount": 1000000, "method": "cash", "idempotency_key": key()})
    void_id = client.post("/api/finance/payments", headers=admin, json={"student_id": 1001, "amount": 500000, "method": "cash", "idempotency_key": key()}).get_json()["payment"]["id"]
    client.post(f"/api/finance/payments/{void_id}/void", headers=admin, json={"reason": "xato"})
    rows = {r["teacher_id"]: r for r in client.get("/api/school/salary", headers=admin).get_json()["items"]}
    assert rows[2001]["base"] == 1000000 and rows[2001]["amount"] == 300000
    assert rows[2002]["amount"] == 2000000
    teacher = login(client, "+998900000001", "teach")
    my = client.get("/api/school/salary/my", headers=teacher).get_json()["item"]
    assert my["amount"] == 300000 and len(my["payments"]) == 1
    assert client.get("/api/school/salary", headers=teacher).status_code == 403
    assert client.get("/api/school/salary", headers=login(client, "+998900000005", "mgr")).status_code == 200  # menejer ham boshqaradi
    assert client.get("/api/school/salary", headers=login(client, "+998900000006", "boss")).status_code == 200


def test_manager_and_director_roles(client):
    manager = login(client, "+998900000005", "mgr")
    director = login(client, "+998900000006", "boss")
    assert client.post("/api/crm/students", headers=manager, json={"firstName": "M", "lastName": "N", "phone": "+998907771111", "group": "D1"}).status_code == 201
    assert client.get("/api/finance/summary", headers=manager).status_code == 403
    assert client.post("/api/finance/payments", headers=manager, json={"student_id": 1001, "amount": 1, "method": "cash", "idempotency_key": key()}).status_code == 403
    assert client.get("/api/finance/summary", headers=director).status_code == 200
    assert client.get("/api/finance/audit", headers=director).status_code == 200


# ---------------------------------------------------------------- chegirma, qayta to'lov, qabul, AI
def test_discount_and_period_payment_block(client):
    admin = login(client, "+998900000002", "admin")
    month = __import__("finance")._this_month()
    fee = {"student_id": 1001, "monthly_fee": 500000, "effective_from": month, "discount_pct": 20}
    assert client.post("/api/finance/fees", headers=admin, json=fee).status_code == 400   # sababsiz chegirma
    assert client.post("/api/finance/fees", headers=admin, json={**fee, "discount_reason": "Aka-uka"}).status_code == 201
    pay = lambda amount, sid=1001: client.post("/api/finance/payments", headers=admin, json={
        "student_id": sid, "amount": amount, "method": "cash", "period": month, "idempotency_key": key()})
    assert pay(500000).status_code == 409          # chegirmadan keyin oylik 400 000 — ortiqcha
    assert pay(300000).status_code == 201
    assert pay(150000).status_code == 409          # qolgani 100 000
    assert pay(100000).status_code == 201
    assert pay(1000).status_code == 409            # oy to'liq to'langan — qayta to'lov yo'q
    debt = client.get("/api/finance/fees", headers=admin).get_json()["items"]
    row = next(r for r in debt if r["student_id"] == 1001)
    assert row["monthly_fee"] == 400000 and row["discount_pct"] == 20 and row["discount_reason"] == "Aka-uka" and row["debt"] == 0
    # tarifsiz o'quvchi: shu oy uchun aynan shu summani ikki marta to'lab bo'lmaydi
    assert pay(70000, 1002).status_code == 201 and pay(70000, 1002).status_code == 409


def test_salary_per_paying_student(client):
    admin = login(client, "+998900000002", "admin")
    assert client.post("/api/school/salary/rules", headers=admin, json={"teacher_id": 2001, "type": "per_student", "value": 150000}).status_code == 201
    for amount in (200000, 300000):  # bitta o'quvchi ikki marta — bitta o'quvchi hisoblanadi
        client.post("/api/finance/payments", headers=admin, json={"student_id": 1001, "amount": amount, "method": "cash", "idempotency_key": key()})
    row = next(r for r in client.get("/api/school/salary", headers=admin).get_json()["items"] if r["teacher_id"] == 2001)
    assert row["paid_students"] == 1 and row["amount"] == 150000


def test_teacher_sees_own_students_with_phone_and_debt(client):
    admin = login(client, "+998900000002", "admin")
    client.post("/api/finance/fees", headers=admin, json={"student_id": 1001, "monthly_fee": 300000})
    teacher = login(client, "+998900000001", "teach")
    out = client.get("/api/school/students", headers=teacher).get_json()
    assert [i["id"] for i in out["items"]] == [1001]
    assert out["items"][0]["phone"] == "+998901112233" and out["items"][0]["debt"] == 300000 and out["debtors"] == 1
    assert client.get("/api/school/students?q=yo'q", headers=teacher).get_json()["items"] == []
    assert len(client.get("/api/school/students", headers=admin).get_json()["items"]) == 2
    assert [s["id"] for s in client.get("/api/crm/students?debtors=1", headers=admin).get_json()["items"]] == [1001]
    sheet = client.get("/api/school/attendance/sheet?group=D1", headers=teacher).get_json()["items"][0]
    assert sheet["phone"] == "+998901112233" and sheet["debt"] == 300000


def test_leads_by_subject(client):
    manager = login(client, "+998900000005", "mgr")
    lead = {"name": "Yangi Bola", "phone": "+998 90 123 45 67", "subject": "Python"}
    res = client.post("/api/crm/leads", headers=manager, json=lead)
    assert res.status_code == 201
    assert client.post("/api/crm/leads", headers=manager, json=lead).status_code == 409
    client.post("/api/crm/leads", headers=manager, json={**lead, "phone": "+998901234500"})
    client.post("/api/crm/leads", headers=manager, json={**lead, "phone": "+998901234501", "subject": "Ingliz tili"})
    out = client.get("/api/crm/leads", headers=manager).get_json()
    assert {x["subject"]: x["waiting"] for x in out["subjects"]} == {"Python": 2, "Ingliz tili": 1}
    lid = res.get_json()["lead"]["id"]
    assert client.post(f"/api/crm/leads/{lid}/status", headers=manager, json={"status": "enrolled"}).status_code == 400
    assert client.post(f"/api/crm/leads/{lid}/status", headers=manager, json={"status": "enrolled", "student_id": 1001}).status_code == 200
    assert len(client.get("/api/crm/leads?subject=Python", headers=manager).get_json()["items"]) == 1
    assert client.get("/api/crm/leads", headers=login(client, "+998900000001", "teach")).status_code == 403


def test_ai_assistant_uses_aggregates_only(client, monkeypatch):
    admin = login(client, "+998900000002", "admin")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.post("/api/school/ai", headers=admin, json={"question": "Nechta qarzdor bor?"}).status_code == 503
    sent = {}

    class Fake:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"choices":[{"message":{"content":"2 ta qarzdor"}}]}'

    def fake_urlopen(req, timeout=0):
        sent["body"] = req.data.decode("utf-8")
        return Fake(req.data)

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(sys.modules["school"].urllib.request, "urlopen", fake_urlopen)
    out = client.post("/api/school/ai", headers=admin, json={"question": "Nechta qarzdor bor?"})
    assert out.status_code == 200 and out.get_json()["answer"] == "2 ta qarzdor"
    assert "qarzdorlar_soni" in sent["body"] and "Ali Valiyev" not in sent["body"] and "+998901112233" not in sent["body"]
    assert client.post("/api/school/ai", headers=login(client, "+998900000001", "teach"), json={"question": "x"}).status_code == 403


# ---------------------------------------------------------------- profil, kurslar, guruh, sinov, avans, tug'ilgan kun, vazifa bahosi, yangiliklar
def test_student_profile_birth_address_and_courses(client):
    admin = login(client, "+998900000002", "admin")
    base = {"firstName": "Sevara", "lastName": "Qodirova", "phone": "+998907000001", "group": "D1"}
    assert client.post("/api/crm/students", headers=admin, json={**base, "birthDate": "2099-01-01"}).status_code == 400
    res = client.post("/api/crm/students", headers=admin, json={**base, "birthDate": "2010-05-17", "address": "Toshkent, Chilonzor"})
    assert res.status_code == 201
    sid = res.get_json()["student"]["id"]
    assert client.post("/api/crm/students", headers=admin, json={**base, "phone": "+998907000002"}).status_code == 201  # sana/manzil ixtiyoriy
    assert client.post(f"/api/crm/students/{sid}/profile", headers=admin, json={"phone": "+998907000001", "address": "Samarqand", "birthDate": ""}).status_code == 200
    assert client.post(f"/api/crm/students/{sid}/profile", headers=admin, json={"phone": "+998901112233"}).status_code == 409
    assert client.post(f"/api/crm/students/{sid}/courses", headers=admin, json={"group": "D2"}).status_code == 200
    assert client.post(f"/api/crm/students/{sid}/courses", headers=admin, json={"group": "D2"}).status_code == 400
    sheet = client.get("/api/school/attendance/sheet?group=D2", headers=admin).get_json()["items"]
    assert sid in [x["student_id"] for x in sheet]   # qo'shimcha kurs guruhida ham ko'rinadi
    prof = client.get(f"/api/crm/students/{sid}/history", headers=admin).get_json()
    assert prof["student"]["address"] == "Samarqand" and prof["student"]["extraGroups"] == ["D2"] and "attendance" in prof
    student = login(client, "+998901112233", "pass1")
    other = next(x for x in client.get("/api/data", headers=student).get_json()["students"] if x["id"] == sid)
    assert other["address"] == "" and other["birthDate"] == ""


def test_create_group_with_schedule(client):
    admin = login(client, "+998900000002", "admin")
    body = {"name": "PY-1", "subject": "Python", "teacher_id": 2001, "room": "201", "weekdays": [1, 3, 5], "start": "16:00", "end": "17:30"}
    assert client.post("/api/school/groups", headers=admin, json=body).status_code == 201
    assert client.post("/api/school/groups", headers=admin, json=body).status_code == 409                       # nom band
    assert client.post("/api/school/groups", headers=admin, json={**body, "name": "PY-2", "weekdays": [3], "room": "202"}).status_code == 409  # o'qituvchi band
    lessons = [l for l in client.get("/api/school/lessons", headers=admin).get_json()["items"] if l["group_name"] == "PY-1"]
    assert sorted(l["weekday"] for l in lessons) == [1, 3, 5]
    assert "PY-1" in [g["name"] for g in client.get("/api/crm/groups", headers=admin).get_json()["items"]]
    assert "PY-1" in client.get("/api/school/groups", headers=login(client, "+998900000001", "teach")).get_json()["items"]


def test_lead_trial_lesson(client):
    admin = login(client, "+998900000002", "admin")
    lid = client.post("/api/crm/leads", headers=admin, json={"name": "Aziz", "phone": "+998909990000", "subject": "SAT"}).get_json()["lead"]["id"]
    assert client.post(f"/api/crm/leads/{lid}/status", headers=admin, json={"status": "trial"}).status_code == 400
    assert client.post(f"/api/crm/leads/{lid}/status", headers=admin, json={"status": "trial", "trial_at": "2026-12-01T15:00", "trial_group": "D1"}).status_code == 200
    lead = client.get("/api/crm/leads", headers=admin).get_json()["items"][0]
    assert lead["status"] == "trial" and lead["trial_at"] == "2026-12-01T15:00" and lead["trial_group"] == "D1"


def test_salary_advance_and_expense(client):
    manager = login(client, "+998900000005", "mgr")
    admin = login(client, "+998900000002", "admin")
    client.post("/api/school/salary/rules", headers=manager, json={"teacher_id": 2002, "type": "fixed", "value": 3000000})
    assert client.post("/api/school/salary/payouts", headers=manager, json={"teacher_id": 2002, "amount": 1000000, "kind": "advance"}).status_code == 201
    assert client.post("/api/school/salary/payouts", headers=manager, json={"teacher_id": 2002, "amount": 0}).status_code == 400
    row = next(r for r in client.get("/api/school/salary", headers=admin).get_json()["items"] if r["teacher_id"] == 2002)
    assert row["amount"] == 3000000 and row["advance"] == 1000000 and row["remaining"] == 2000000
    s = client.get("/api/finance/summary", headers=admin).get_json()
    assert s["expense_by_category"].get("salary") == 1000000


def test_birthday_greetings_sent_once(client):
    admin = login(client, "+998900000002", "admin")
    school = sys.modules["school"]
    today = __import__("finance")._today()
    data = client.get("/api/data", headers=admin).get_json()
    for st in data["students"]:
        if st["id"] == 1001:
            st["birthDate"] = f"2011-{today.isoformat()[5:]}"
            st["telegramId"] = 555
    for t in data["teachers"]:
        if t["id"] == 2001:
            t["telegramId"] = 777
    client.post("/api/data", json=data, headers=admin)
    sent = []
    assert school.birthday_tick(lambda chat, text: sent.append((chat, text)) or (True, "")) == 2
    assert school.birthday_tick(lambda chat, text: sent.append((chat, text)) or (True, "")) == 0   # qayta yuborilmaydi
    assert {c for c, _ in sent} == {555, 777} and "tabriklaymiz" in sent[0][1]
    teacher = login(client, "+998900000001", "teach")
    assert client.get("/api/school/students", headers=teacher).get_json()["birthdays"] == ["Ali Valiyev"]


def test_homework_grades_only_by_staff(client):
    teacher = login(client, "+998900000001", "teach")
    data = client.get("/api/data", headers=teacher).get_json()
    data["homeworkGrades"] = [{"homeworkId": "hw1", "studentId": 1001, "grade": 5, "teacherId": 2001}]
    client.post("/api/data", json=data, headers=teacher)
    student = login(client, "+998901112233", "pass1")
    sdata = client.get("/api/data", headers=student).get_json()
    assert sdata["homeworkGrades"][0]["grade"] == 5
    sdata["homeworkGrades"] = [{"homeworkId": "hw1", "studentId": 1001, "grade": 2}]
    client.post("/api/data", json=sdata, headers=student)
    assert client.get("/api/data", headers=teacher).get_json()["homeworkGrades"][0]["grade"] == 5


def test_edu_news_filter(client, monkeypatch):
    school = sys.modules["school"]
    rss = ("<rss><channel>"
           "<item><title>Maktab o'quvchilari uchun yangi imtihon tartibi</title><link>https://kun.uz/1</link></item>"
           "<item><title>Futbol: terma jamoa g'alabasi</title><link>https://kun.uz/2</link></item>"
           "<item><title>Bad link</title><link>javascript:alert(1)</link></item>"
           "</channel></rss>").encode("utf-8")

    class Fake:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return rss

    monkeypatch.setattr(school, "NEWS_FEEDS", ["https://kun.uz/news/rss"])
    monkeypatch.setattr(school.urllib.request, "urlopen", lambda req, timeout=0: Fake())
    school._news_cache.update(at=0, items=[])
    h = login(client, "+998901112233", "pass1")
    out = client.get("/api/school/news", headers=h).get_json()
    assert [i["link"] for i in out["items"]] == ["https://kun.uz/1"]
    assert len(client.get("/api/school/news?all=1", headers=h).get_json()["items"]) == 2
