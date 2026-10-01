"""
Module 4 - FastAPI backend.

Ties Modules 1/2/3/6 together behind a REST API:
  GET  /health            -> liveness check
  POST /detection/update   -> latest per-lane vehicle counts (+ optional emergency)
  POST /signal/cycle       -> run one FSM cycle on the latest counts, log it
  GET  /signal/current     -> current active lane + all lane states
  GET  /logs               -> paginated historical log records
  POST /emergency/manual   -> demo-mode manual emergency trigger

Run it with:  uvicorn backend.main:app --reload
Docs:         http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Dict, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

from auth.dependencies import CurrentUser, get_current_user, require_role
from auth.jwt_utils import create_access_token
from auth.users_db import (
    authenticate,
    create_user,
    delete_user,
    init_users_db,
    list_users,
    seed_default_users,
)
from backend.schemas import (
    CycleResult,
    DetectionUpdate,
    DetectionUpdateResponse,
    HealthResponse,
    LogRecord,
    LogsResponse,
    ManualEmergencyRequest,
    SignalStateResponse,
    TokenResponse,
    UserCreateRequest,
    UserOut,
)
from database.db import count_logs, get_logs, init_db, log_cycle_result
from detection.emergency_detector import EmergencyTracker
from hardware.adapter import LoggingAdapter, SignalHardwareAdapter
from signal_control.cycle_runner import execute_timed_cycle_async
from signal_control.failsafe import FailsafeFSMWrapper
from signal_control.fsm_controller import FSMController

LANE_IDS = ["north", "south", "east", "west"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # ensure traffic_logs.db + table exist before the first request
    init_users_db()
    seed_default_users()  # creates admin/operator/viewer demo accounts if none exist yet
    yield


app = FastAPI(
    title="Optimal Traffic Management System API",
    description="Vehicle-density-based adaptive traffic signal control with emergency priority.",
    version="1.0.0",
    lifespan=lifespan,
)

# Dashboard runs on a different port (Streamlit), so it needs CORS enabled.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory state -------------------------------------------------------
# A real deployment would swap this for Redis/shared storage across workers;
# for a single-process demo, plain module-level state is enough.
fsm = FSMController(LANE_IDS)
# Failsafe wrapper: if no fresh /detection/update arrives within 30s (camera
# down, detection process crashed, network partition...), signal cycling
# automatically falls back to a fixed-duration round-robin instead of
# trusting stale/missing density data. See signal_control/failsafe.py.
safe_fsm = FailsafeFSMWrapper(fsm, stale_after_seconds=30.0, fixed_green_seconds=20)
emergency_tracker = EmergencyTracker(LANE_IDS)

# Hardware adapter: turns "lane X is now GREEN" into a physical action.
# LoggingAdapter is the safe default (dev/demo/CI). Swap in a real adapter
# (see hardware/adapter.py) once you know your controller's protocol -
# nothing else in this file needs to change.
hardware: SignalHardwareAdapter = LoggingAdapter()

_latest_counts: Dict[str, int] = {lane: 0 for lane in LANE_IDS}
_last_cycle: Optional[CycleResult] = None


# --- Auth endpoints -----------------------------------------------------------
@app.post("/auth/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    role = authenticate(form.username, form.password)
    if role is None:
        raise HTTPException(status_code=401, detail="Incorrect username or password",
                             headers={"WWW-Authenticate": "Bearer"})
    token = create_access_token(form.username, role)
    return TokenResponse(access_token=token, role=role, username=form.username)


@app.get("/auth/me", response_model=UserOut)
def whoami(current: CurrentUser = Depends(get_current_user)) -> UserOut:
    for u in list_users():
        if u["username"] == current["username"]:
            return UserOut(**dict(u))
    raise HTTPException(404, "User not found (may have been deleted)")


@app.post("/auth/users", response_model=UserOut, status_code=201)
def admin_create_user(
    req: UserCreateRequest, _admin: CurrentUser = Depends(require_role("admin"))
) -> UserOut:
    """Admin-only: create a new authority account (admin/operator/viewer)."""
    try:
        create_user(req.username, req.password, req.role)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    for u in list_users():
        if u["username"] == req.username:
            return UserOut(**dict(u))
    raise HTTPException(500, "User created but could not be re-read")  # should never happen


@app.get("/auth/users", response_model=list[UserOut])
def admin_list_users(_admin: CurrentUser = Depends(require_role("admin"))) -> list[UserOut]:
    """Admin-only: list all authority accounts."""
    return [UserOut(**dict(u)) for u in list_users()]


@app.delete("/auth/users/{username}", status_code=204)
def admin_delete_user(username: str, admin: CurrentUser = Depends(require_role("admin"))) -> None:
    """Admin-only: remove an authority account."""
    if username == admin["username"]:
        raise HTTPException(400, "You cannot delete your own account while logged in as it")
    if not delete_user(username):
        raise HTTPException(404, f"User '{username}' not found")


# --- Traffic-control endpoints -------------------------------------------------
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    # Deliberately public / no auth: monitoring tools and load balancers need
    # to reach this without a token.
    st = safe_fsm.status()
    return HealthResponse(
        status="ok",
        detection_mode=st.mode,
        detection_status_reason=st.reason,
    )


@app.post("/detection/update", response_model=DetectionUpdateResponse)
def update_detection(
    update: DetectionUpdate, _user: CurrentUser = Depends(require_role("admin", "operator"))
) -> DetectionUpdateResponse:
    global _latest_counts
    unknown = set(update.lane_counts) - set(LANE_IDS)
    if unknown:
        raise HTTPException(422, f"Unknown lane id(s): {sorted(unknown)}. Known lanes: {LANE_IDS}")
    if update.emergency_lane is not None and update.emergency_lane not in LANE_IDS:
        raise HTTPException(422, f"Unknown emergency_lane '{update.emergency_lane}'")

    _latest_counts.update(update.lane_counts)
    safe_fsm.mark_data_received()  # fresh data -> keeps us out of failsafe mode

    # Feed the tracker: emergency_lane says "seen this reading", everyone else "not seen".
    emergency_tracker.update_all({lane: (lane == update.emergency_lane) for lane in LANE_IDS})

    return DetectionUpdateResponse(
        accepted=True,
        lane_counts=dict(_latest_counts),
        emergency_lane=emergency_tracker.get_emergency_lane(),
    )


@app.post("/emergency/manual", response_model=DetectionUpdateResponse)
def manual_emergency(
    req: ManualEmergencyRequest, _user: CurrentUser = Depends(require_role("admin", "operator"))
) -> DetectionUpdateResponse:
    """Demo helper: force-confirm (or clear) an emergency without needing a trained model."""
    if req.lane_id not in LANE_IDS:
        raise HTTPException(422, f"Unknown lane '{req.lane_id}'. Known lanes: {LANE_IDS}")
    reps = emergency_tracker.trigger_frames if req.active else emergency_tracker.release_frames
    for _ in range(reps):
        emergency_tracker.update(req.lane_id, req.active)
    return DetectionUpdateResponse(
        accepted=True,
        lane_counts=dict(_latest_counts),
        emergency_lane=emergency_tracker.get_emergency_lane(),
    )


@app.post("/signal/cycle", response_model=CycleResult)
def run_signal_cycle(
    background_tasks: BackgroundTasks, _user: CurrentUser = Depends(require_role("admin", "operator"))
) -> CycleResult:
    global _last_cycle
    emergency_lane = emergency_tracker.get_emergency_lane()
    # safe_fsm decides internally: normal density-based cycle, or - if
    # detection data is missing/stale/unhealthy - a fixed round-robin.
    # (This call also immediately sets the FSM's in-memory state to GREEN,
    # so /signal/current reflects the decision right away.)
    result = safe_fsm.run_cycle(_latest_counts, emergency_lane=emergency_lane)
    logged_id = log_cycle_result(result)

    # Actually WALK the light through GREEN -> (hold) -> YELLOW -> (hold) -> RED
    # in real time, pushing each transition to the hardware adapter. Runs in
    # the background so this endpoint responds immediately instead of
    # blocking for green_duration + yellow_duration seconds.
    background_tasks.add_task(execute_timed_cycle_async, fsm, hardware, dict(result))

    cycle = CycleResult(**result, logged_id=logged_id)
    _last_cycle = cycle
    return cycle


@app.get("/signal/current", response_model=SignalStateResponse)
def current_signal(_user: CurrentUser = Depends(get_current_user)) -> SignalStateResponse:
    states = {lane: state.value for lane, state in fsm.get_states().items()}
    return SignalStateResponse(active_lane=fsm.active_lane, states=states, last_cycle=_last_cycle)


@app.get("/logs", response_model=LogsResponse)
def logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    lane_id: Optional[str] = Query(None),
    _user: CurrentUser = Depends(get_current_user),
) -> LogsResponse:
    items = get_logs(limit=limit, offset=offset, lane_id=lane_id)
    return LogsResponse(
        total=count_logs(lane_id=lane_id),
        limit=limit,
        offset=offset,
        items=[LogRecord(**{**item, "is_emergency": bool(item["is_emergency"])}) for item in items],
    )
