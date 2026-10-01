"""
API tests using FastAPI's TestClient (starlette) - no real network socket needed,
so these run fast and don't depend on a port being free.

Auth mechanics themselves (login, 401/403, role checks, user management) are
covered in tests/test_auth_api.py. These tests authenticate as an operator
(who can drive the signal) and focus on the actual traffic-control business
logic: density-based selection, emergency override, input validation.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the DB modules at throwaway files before importing backend.main,
    # then re-import so every module-level object (fsm, tracker, DB paths) is fresh.
    import auth.users_db as users_db_module
    monkeypatch.setattr(users_db_module, "DB_PATH", tmp_path / "test_users.db")

    import database.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_logs.db")

    import backend.main as main_module
    importlib.reload(main_module)

    # /signal/cycle schedules a REAL-TIME GREEN->YELLOW->RED background task
    # (verified separately, with real timing, in tests/test_cycle_runner.py
    # and by hand against a live uvicorn server - see README). Starlette's
    # TestClient runs background tasks synchronously before returning from
    # client.post(), so leaving the real one in place would make every API
    # test here actually wait out the full green+yellow duration (seconds to
    # tens of seconds). We replace it with an instant stand-in so these API
    # tests stay fast, while still exercising the real scheduling wiring.
    async def _instant_cycle(fsm, hardware, cycle_result):
        from signal_control.fsm_controller import SignalState
        lane = cycle_result["lane"]
        fsm.set_state(lane, SignalState.GREEN)
        hardware.apply(lane, SignalState.GREEN)

    monkeypatch.setattr(main_module, "execute_timed_cycle_async", _instant_cycle)

    with TestClient(main_module.app) as c:
        yield c


@pytest.fixture()
def auth_headers(client):
    """Logged in as the seeded 'operator' account - can drive signals/detection."""
    r = client.post("/auth/login", data={"username": "operator", "password": "operator12345"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_full_cycle_flow(client, auth_headers):
    r = client.post("/detection/update", json={"lane_counts": {"north": 4, "south": 15, "east": 8, "west": 3}},
                     headers=auth_headers)
    assert r.status_code == 200

    r = client.post("/signal/cycle", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["lane"] == "south"

    r = client.get("/signal/current", headers=auth_headers)
    assert r.json()["active_lane"] == "south"

    r = client.get("/logs", headers=auth_headers)
    assert r.json()["total"] == 1


def test_emergency_overrides_via_api(client, auth_headers):
    client.post("/detection/update", json={"lane_counts": {"north": 4, "south": 15, "east": 8, "west": 3}},
                headers=auth_headers)
    client.post("/emergency/manual", json={"lane_id": "west", "active": True}, headers=auth_headers)
    r = client.post("/signal/cycle", headers=auth_headers)
    assert r.json()["lane"] == "west"
    assert r.json()["was_emergency"] is True


def test_rejects_unknown_lane(client, auth_headers):
    r = client.post("/detection/update", json={"lane_counts": {"nowhere": 5}}, headers=auth_headers)
    assert r.status_code == 422


def test_rejects_negative_count(client, auth_headers):
    r = client.post("/detection/update", json={"lane_counts": {"north": -1}}, headers=auth_headers)
    assert r.status_code == 422
