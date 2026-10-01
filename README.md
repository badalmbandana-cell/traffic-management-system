# Optimal Traffic Management System (OTMS)

Real-time, vehicle-density-based adaptive traffic signal control with
automatic emergency-vehicle priority.

Detects vehicles per lane with **YOLOv8 + OpenCV**, decides signal timing
with a rule-based **Finite State Machine**, serves everything over a
**FastAPI** backend, logs every decision to **SQLite**, and shows it live
on a **Streamlit** dashboard.

## Architecture

```
video/image --> [Module 1: YOLOv8 detection] --> per-lane vehicle counts
                                                        |
                                                        v
[Module 3: Emergency tracker] --emergency_lane--> [Module 2: FSM controller]
                                                        |
                                                        v
                                      [Module 4: FastAPI backend]
                                        |                    |
                                        v                    v
                          [Module 6: SQLite logging]  [Module 5: Streamlit dashboard]
```

## Project layout

```
traffic-management-system/
├── detection/
│   ├── vehicle_detector.py      # Module 1 - YOLOv8 vehicle detection
│   ├── emergency_detector.py    # Module 3 - emergency detection + hysteresis tracker
│   ├── lane_mapper.py           # bbox -> lane zone assignment
│   └── live_stream.py           # RTSP/USB/file camera feed with auto-reconnect
├── signal_control/
│   ├── fsm_controller.py        # Module 2 - Enum-based FSM signal control
│   └── failsafe.py              # fixed-duration fallback when detection data is stale/down
├── backend/
│   ├── main.py                  # Module 4 - FastAPI app (6 endpoints)
│   └── schemas.py               # Pydantic request/response models
├── dashboard/
│   └── app.py                   # Module 5 - Streamlit live dashboard
├── database/
│   └── db.py                    # Module 6 - SQLite logging (traffic_logs.db)
├── hardware/
│   └── adapter.py                # vendor-agnostic interface to real signal controllers
├── training/
│   └── train_emergency_model.py # fine-tune YOLOv8 on a real ambulance/fire-truck dataset
├── tests/                       # pytest suite, 38 tests
├── run_pipeline.py              # end-to-end: video/image -> API -> DB
├── simulate_traffic.py          # synthetic traffic generator (no video needed)
└── requirements.txt
```

## Production-readiness modules (what's real vs. what still needs your input)

These close the gap between "college demo" and "runs on an actual junction" -
each one is real, tested code, not a stub, EXCEPT where explicitly marked:

| Module | Status | What it does |
|---|---|---|
| `auth/` (users_db.py, jwt_utils.py, dependencies.py, manage_users.py) | ✅ tested | Role-based login (admin/operator/viewer) protecting every state-changing endpoint. See the dedicated section below. |
| `signal_control/cycle_runner.py` | ✅ tested | **Fixes a real gap**: the FSM alone only computed timing numbers — it never actually held GREEN, then transitioned to YELLOW, then RED, over real time. This module does that for real (verified with live timing: 10s green → 3s yellow → red, watched second-by-second against a running server — see below), and pushes every transition to the hardware adapter. Wired into `/signal/cycle` as a non-blocking background task (confirmed: API responds in 4ms while the light genuinely stays green for the full duration behind the scenes). |
| `signal_control/failsafe.py` | ✅ tested | If no fresh detection data arrives for 30s (camera down, pipeline crashed), signal cycling automatically falls back to fixed-duration round-robin instead of trusting stale data. Verified live: `/health` and `/signal/cycle` both reflect `failsafe` mode correctly. |
| `detection/live_stream.py` | ✅ tested | RTSP/USB-camera/video-file reader with automatic reconnect + exponential backoff. Never hangs (verified: an unreachable source becomes "failsafe-worthy" in bounded time, no infinite loop). |
| `hardware/adapter.py` | ✅ interface tested, ⚠️ needs your controller's manual | Vendor-agnostic interface between the FSM's decision and physical lights. `LoggingAdapter` (default, safe for dev) and `GPIOAdapter` (real Raspberry Pi + relays) are real and tested. `NTCIPAdapterStub` is a documented **stub** — every real traffic-signal controller uses a different protocol, so this needs your specific hardware's manual before it can send real commands. |
| `training/train_emergency_model.py` | ✅ pipeline verified, ⚠️ needs a real dataset | Fine-tunes YOLOv8 to detect `ambulance`/`fire_truck`. The training pipeline was **actually run** end-to-end on a tiny synthetic dataset (proving the code works) but has **not** been trained on real ambulance images — that dataset doesn't exist in this environment. Get one from Roboflow Universe (search "ambulance detection", export in YOLOv8 format) and point `--data` at it. |

`backend/main.py` now wires `failsafe.py` and `hardware/adapter.py` in:
`/signal/cycle` uses the failsafe wrapper automatically, and `/health` reports
`detection_mode: "normal"` or `"failsafe"` so a monitoring dashboard can alert
on it.

## Authentication (login for authority users)

Every state-changing endpoint requires a logged-in account with the right
role. `GET /health` stays public (monitoring tools/load balancers need it
without a token).

| Role | Can do |
|---|---|
| **viewer** | Read-only: `/signal/current`, `/logs` |
| **operator** | Everything viewer can, plus: `/detection/update`, `/emergency/manual`, `/signal/cycle` (drives the actual signal) |
| **admin** | Everything operator can, plus: create/list/delete accounts (`/auth/users`) |

Demo accounts (seeded automatically on first run — **change these
passwords before any real deployment**):

| Username | Password | Role |
|---|---|---|
| `admin` | `admin12345` | admin |
| `operator` | `operator12345` | operator |
| `viewer` | `viewer12345` | viewer |

```bash
# change a password (or create/delete accounts) via CLI - no login needed,
# this talks to the users database directly:
python -m auth.manage_users reset-password --username admin
python -m auth.manage_users create --username field_officer_1 --role operator
python -m auth.manage_users list
```

**Verified live** (curl against a running server): no token → 401 on
protected routes; viewer token → 200 on reads, 403 on `/signal/cycle`;
operator token → 200 on both detection updates and cycling, 403 on
creating users; admin token → can create a new `operator` account, and that
brand-new account can immediately log in and drive the signal.

Tokens are JWTs (`PyJWT`), valid 8 hours, signed with `TMS_JWT_SECRET`
(set this environment variable before deploying — a fixed insecure dev
secret is used otherwise, with a loud warning printed on startup:
`export TMS_JWT_SECRET=$(openssl rand -hex 32)`).

`run_pipeline.py` and `simulate_traffic.py` both log in automatically
(`--username`/`--password`, default `operator`/`operator12345`) before
talking to the API. The dashboard has its own sign-in screen and shows/hides
controls based on the signed-in role (viewers see a read-only dashboard;
only admins see the account-management panel).

**Known limitation**: tokens can't be revoked before they expire (no
blocklist) — if a token leaks, it's valid until its 8-hour expiry runs out.
A real deployment handling this would add a revocation list or move to
shorter-lived tokens with refresh tokens.

## Setup

```bash
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

First run of anything that imports `ultralytics` downloads `yolov8n.pt`
(~6 MB) automatically.

## Run it

**Terminal 1 — backend**
```bash
uvicorn backend.main:app --reload
# docs at http://127.0.0.1:8000/docs
```

**Terminal 2 — dashboard**
```bash
streamlit run dashboard/app.py
```

**Terminal 3 — feed it data** (pick one)
```bash
# no video needed, pure random-walk demo
python simulate_traffic.py

# real detection on a video/image
python run_pipeline.py --source data/sample_videos/bus.jpg --repeat 30
python run_pipeline.py --source traffic.mp4 --simulate-emergency east:20-45
```

## API endpoints

| Method | Path                | Purpose                                      |
|--------|---------------------|-----------------------------------------------|
| GET    | `/health`            | liveness check + `detection_mode` (`normal`/`failsafe`) |
| POST   | `/detection/update`  | latest per-lane vehicle counts (+ optional confirmed emergency lane) |
| POST   | `/emergency/manual`  | demo helper: force-confirm/clear an emergency without a trained model |
| POST   | `/signal/cycle`      | run one FSM cycle (density-based, or failsafe fixed-timing if data is stale/missing), log it, push to hardware adapter |
| GET    | `/signal/current`    | current active lane + all lane states + last cycle |
| GET    | `/logs`              | paginated historical log records (filter by `lane_id`) |

## Verified: video input actually controls the signals end to end

`data/sample_videos/bus_traffic.mp4` is a real, multi-frame video (24 frames,
built from a real photo with per-frame camera jitter so YOLO runs genuine
independent inference on each frame — not a frozen repeat). Running it
through the full pipeline:

```bash
uvicorn backend.main:app --reload            # terminal 1
python run_pipeline.py --source data/sample_videos/bus_traffic.mp4 \
    --cycle-every 6 --simulate-emergency east:10-18   # terminal 2
```

confirmed, against a live server, every link in the chain:
**video frame → YOLOv8 detection → per-lane count → FastAPI → FSM decision →
SQLite log → real-time GREEN→YELLOW→RED transition on the signal.**

Watching `/signal/current` every ~2s during one real cycle showed the exact
expected timeline (10s green, 3s yellow, as computed by the FSM):

```
t= 0.5s   north = GREEN
t= 4.0s   north = GREEN
t= 8.0s   north = GREEN
t=10.5s   north = YELLOW   <- green ended, amber began right on schedule
t=12.0s   north = YELLOW
t=13.5s   north = RED      <- full cycle complete, safely off
```

Use your own dashcam/CCTV footage the same way: point `--source` at any
`.mp4`/`.avi` file, or a live RTSP URL via `detection/live_stream.py`.

## Verified: emergency-vehicle priority actually overrides density

Live scenario, run against the real backend (not a mock):

| Step | South (busiest lane) | West (quietest lane) | Result |
|---|---|---|---|
| 1. Normal traffic: south=15, west=2 | 15 vehicles | 2 vehicles | signal picks **south** (highest density) |
| 2. Ambulance confirmed in west | 15 vehicles | 2 vehicles | signal picks **west** — `was_emergency: true` |

The second cycle's response: `{"lane":"west", "was_emergency":true, "vehicle_count":2, ...}`
— west wins with only 2 vehicles, purely because an emergency vehicle was
confirmed there. Vehicle count is completely ignored once a lane is in
confirmed-emergency state (see `EmergencyTracker`/`FSMController` in
`signal_control/fsm_controller.py`).

**Important nuance**: the *priority logic* (emergency always wins,
regardless of density) is real and fully tested. What is **not** yet
trained is automatic visual recognition of a real ambulance/fire truck from
camera footage — COCO (what the stock YOLOv8 weights know) has no such
class. Until you train `training/train_emergency_model.py` on a real
dataset, "an emergency vehicle is confirmed in lane X" comes from
`POST /emergency/manual` (dashboard button or API call) rather than the
system recognizing the vehicle by itself on video. The override behaviour
itself works exactly the same either way — only the *trigger source*
differs.

## Frontend

`dashboard/app.py` (Streamlit) is the live UI — tested running against a
live backend. It shows:
- A 4-lane junction view with colour-coded lights (green glows), and an
  "EMERGENCY PRIORITY" badge on whichever lane just got an override
- A failsafe warning banner if detection data goes stale/down (pulls
  `detection_mode` from `/health`)
- Controls to set per-lane counts, flag an emergency lane, and run a cycle
- A live per-lane bar chart and a historical trend line + table from `/logs`

Run it with `streamlit run dashboard/app.py` alongside the backend.

## Design decisions

- **Green time formula**: `vehicle_count * 2`, clamped to `[min_green, max_green]`
  (defaults 10s/60s), exactly as specified in the brief.
- **Emergency detection**: COCO (the dataset the stock YOLOv8 weights are
  trained on) has no "ambulance" class. Three options exist — a custom-trained
  model, a colour/siren heuristic (fragile, not used), or a manual/simulated
  trigger for demos. `EmergencyDetector` supports a custom model via
  `model_path=`; without one, use `/emergency/manual` or
  `run_pipeline.py --simulate-emergency LANE:START-END`.
- **Multi-frame confirmation (hysteresis)**: `EmergencyTracker` requires
  `trigger_frames` (default 5) consecutive positive readings before
  overriding the signal, and `release_frames` (default 15) consecutive
  negative readings before releasing it. This avoids single-frame false
  positives and signal flapping.
- **Starvation guard (optional)**: `FSMController(..., starvation_limit=N)`
  forces a lane that's been skipped `N` times in a row to get the next
  green, so a quiet lane can't starve forever behind a busy one. Off by
  default to match the brief's pure "highest density wins" rule.

## Tests

```bash
pytest -v
```
58 tests covering the FSM, emergency tracker, lane mapper, SQLite logging,
failsafe fallback, live-stream reconnect logic, hardware adapters, the timed
GREEN→YELLOW→RED cycle runner, the full authentication system (login, role
checks, user management), and the full FastAPI request/response cycle.

## Deploy it for real (live public URL)

This gives you a real, clickable link (for a portfolio/resume/interview) —
not a real traffic junction. For that, see
`docs/real_junction_roadmap.md`, which needs your college/municipal
authority's involvement and cannot be done remotely.

**What's included and tested here:**
- `Dockerfile.backend` / `Dockerfile.dashboard` — both verified locally to
  correctly bind to a dynamic `$PORT` environment variable (exactly how
  Render/Railway/Fly assign ports) and to talk to each other via
  `TMS_API_BASE`
- `docker-compose.yml` — for running both containers together locally
- `render.yaml` — a Render "Blueprint" that deploys both services in one
  click from this repo
- `.env.example` — required environment variables

**Note on Docker**: this sandbox doesn't have Docker installed, so the
Dockerfiles/compose file could not be `docker build`-tested here — only the
underlying `$PORT`/`TMS_API_BASE` behavior they rely on was verified
directly. Do a local `docker compose up --build` before your first real
deploy to confirm the images build cleanly on your machine.

### Steps (Render, free tier)

1. Push this project to a GitHub repo (you already have one:
   `github.com/badalmbandana-cell`).
2. On [render.com](https://render.com), sign up free, then **New → Blueprint**
   and connect your repo. Render auto-detects `render.yaml` and shows both
   services (`traffic-management-backend`, `traffic-management-dashboard`).
3. Click **Apply**. Render generates a random `TMS_JWT_SECRET` for you and
   automatically wires the dashboard's `TMS_API_BASE` to the backend's real
   URL — no manual config needed.
4. After a few minutes you'll have two public URLs, e.g.
   `https://traffic-management-dashboard.onrender.com` — open it, log in
   with the demo credentials, done.

**Free-tier facts (verified against Render's docs, checked while writing
this), please read before relying on this for a big demo day:**
- 750 free instance-hours/month per account — plenty for a portfolio link.
- Free web services **spin down after ~15 minutes idle** and take **10-30s**
  to wake up on the next request. If you're demoing live to someone,
  open the link a minute early.
- Free tier has **no persistent disk** — `traffic_logs.db` and
  `auth_users.db` reset on every redeploy/restart (accounts you created
  and logged cycles disappear, back to the seeded demo accounts). This is
  fine for a portfolio demo; if you need history to survive restarts,
  attach a persistent disk under each service's "Disks" tab (small paid
  add-on — check Render's current disk pricing) or migrate to Render's
  managed Postgres.
- Other hosts (Railway, Fly.io) work too, using the same Dockerfiles — their
  free-tier terms change often, so check current pricing before choosing.

## Known limitations / next steps

- **Emergency detection accuracy**: `training/train_emergency_model.py` is a
  real, tested training pipeline, but it has only been run on synthetic
  placeholder data here — you need a real ambulance/fire-truck dataset
  (Roboflow Universe) before the detector is accurate. Until then, use
  `/emergency/manual` or `run_pipeline.py --simulate-emergency` for demos.
- **Hardware protocol**: `hardware/adapter.py` gives you `LoggingAdapter`
  (safe default) and a real `GPIOAdapter` (Raspberry Pi + relays). The
  `NTCIPAdapterStub` is deliberately a stub — you need your specific traffic
  controller's manual (every vendor differs) before it can send real commands.
- **In-memory backend state** (`_latest_counts`, FSM, tracker) resets on
  restart and won't work across multiple worker processes — fine for a
  single-process demo; a real deployment would move this into Redis/DB.
- **Lane-zone mapping** (`lane_mapper.py`) assumes vertical strips of one
  camera frame; a real 4-way junction with 4 separate camera feeds would
  skip zoning and call `detect_frame()` once per camera instead.
- **GPU for real-time inference**: CPU inference was ~0.5-1s/frame in
  testing. A real deployment needs an edge GPU (e.g. Jetson Nano/Xavier) for
  usable frame rates.
- Before connecting to a real intersection, get sign-off from your traffic
  engineering authority — this controls physical infrastructure and needs
  real-world safety testing beyond what's in this repo.
