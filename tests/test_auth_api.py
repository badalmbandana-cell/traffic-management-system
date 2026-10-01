"""API-level auth tests using FastAPI's TestClient - real HTTP-shaped requests,
just without a real network socket."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import auth.users_db as users_db_module
    monkeypatch.setattr(users_db_module, "DB_PATH", tmp_path / "test_users.db")

    import database.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_logs.db")

    import backend.main as main_module
    importlib.reload(main_module)

    async def _instant_cycle(fsm, hardware, cycle_result):
        from signal_control.fsm_controller import SignalState
        fsm.set_state(cycle_result["lane"], SignalState.GREEN)
        hardware.apply(cycle_result["lane"], SignalState.GREEN)
    monkeypatch.setattr(main_module, "execute_timed_cycle_async", _instant_cycle)

    with TestClient(main_module.app) as c:
        yield c


def login(client, username, password):
    r = client.post("/auth/login", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_no_token_rejected(client):
    r = client.get("/signal/current")
    assert r.status_code == 401


def test_wrong_password_rejected(client):
    r = client.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


def test_viewer_can_read_but_not_write(client):
    token = login(client, "viewer", "viewer12345")
    r = client.get("/signal/current", headers=auth_header(token))
    assert r.status_code == 200
    r = client.post("/signal/cycle", headers=auth_header(token))
    assert r.status_code == 403
    r = client.post("/detection/update", json={"lane_counts": {"north": 1}}, headers=auth_header(token))
    assert r.status_code == 403


def test_operator_can_control_signals_but_not_manage_users(client):
    token = login(client, "operator", "operator12345")
    r = client.post("/detection/update", json={"lane_counts": {"north": 5, "south": 12}},
                     headers=auth_header(token))
    assert r.status_code == 200
    r = client.post("/signal/cycle", headers=auth_header(token))
    assert r.status_code == 200
    r = client.post("/auth/users", json={"username": "x", "password": "longenough123", "role": "viewer"},
                     headers=auth_header(token))
    assert r.status_code == 403


def test_admin_can_manage_users(client):
    admin_token = login(client, "admin", "admin12345")
    r = client.post("/auth/users", json={"username": "officer1", "password": "longenough123", "role": "operator"},
                     headers=auth_header(admin_token))
    assert r.status_code == 201
    assert r.json()["role"] == "operator"

    r = client.get("/auth/users", headers=auth_header(admin_token))
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert "officer1" in usernames

    # new user can now log in and use their role
    officer_token = login(client, "officer1", "longenough123")
    r = client.post("/signal/cycle", headers=auth_header(officer_token))
    assert r.status_code == 200


def test_admin_cannot_delete_own_account_while_logged_in_as_it(client):
    admin_token = login(client, "admin", "admin12345")
    r = client.delete("/auth/users/admin", headers=auth_header(admin_token))
    assert r.status_code == 400


def test_health_is_public_no_token_needed(client):
    r = client.get("/health")
    assert r.status_code == 200
