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
    for name in ("app", "crm", "finance", "security", "data_database"):
        sys.modules.pop(name, None)
    app_module = importlib.import_module("app")
    data = {
        "students": [
            {"id": 1001, "name": "Ali Valiyev", "phone": "+998901112233", "email": "ali@x.uz", "password": "pass1", "group": "D1"},
            {"id": 1002, "name": "Vali Aliyev", "phone": "+998901112244", "email": "vali@x.uz", "password": "pass2", "group": "D2"},
        ],
        "teachers": [{"id": 2001, "name": "Ustoz", "phone": "+998900000001", "password": "teach", "status": "active"}],
        "admins": [
            {"id": 3001, "name": "Admin", "phone": "+998900000002", "password": "admin", "level": "platform_admin"},
            {"id": 3002, "name": "Kassir", "phone": "+998900000003", "password": "cash", "level": "cashier"},
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
    assert {a["id"] for a in saved["admins"]} == {3001, 3002}
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
