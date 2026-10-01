"""
Module 5 - Streamlit live monitoring dashboard.

Pure "view" layer: everything shown here comes from the FastAPI backend
(Module 4), including authentication. The dashboard itself holds no traffic
logic and no user database - it logs in against the backend's /auth/login
and stores the resulting JWT in the browser session, exactly like any real
web client would.

Run it with:  streamlit run dashboard/app.py
(make sure `uvicorn backend.main:app` is running first, default port 8000)
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

API_BASE = os.environ.get("TMS_API_BASE", "http://127.0.0.1:8000")
LANE_IDS = ["north", "south", "east", "west"]
STATE_COLOR = {"GREEN": "#22c55e", "YELLOW": "#eab308", "RED": "#ef4444"}

st.set_page_config(page_title="Traffic Management Dashboard", layout="wide")


@st.cache_resource(show_spinner=False)
def get_detector():
    """
    Loads YOLOv8 ONCE per running container and reuses it across every
    video a user uploads (model load alone took ~39s in testing - doing
    that on every upload would make the feature unusably slow). The first
    upload after a fresh deploy/restart will still pay this cost.
    """
    from detection.vehicle_detector import VehicleDetector
    return VehicleDetector("yolov8n.pt", confidence_threshold=0.4)


def api_get(path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        r = requests.get(f"{API_BASE}{path}", headers=headers, timeout=3, **kwargs)
        if r.status_code == 401:
            st.session_state.token = None
            st.rerun()
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def api_post(path: str, json=None):
    headers = {"Authorization": f"Bearer {st.session_state.token}"}
    try:
        r = requests.post(f"{API_BASE}{path}", json=json, headers=headers, timeout=3)
        if r.status_code == 401:
            st.session_state.token = None
            st.rerun()
        r.raise_for_status()
        return r.json(), None
    except Exception as exc:  # noqa: BLE001
        detail = None
        try:
            detail = exc.response.json().get("detail")  # type: ignore[attr-defined]
        except Exception:
            pass
        return None, detail or str(exc)


def lane_light(lane: str, state: str, is_emergency_lane: bool) -> str:
    color = STATE_COLOR.get(state, "#999")
    glow = f"box-shadow: 0 0 14px 3px {color};" if state == "GREEN" else ""
    badge = ("<br><span style='color:#ef4444;font-weight:700;'>\U0001F691 EMERGENCY PRIORITY</span>"
              if is_emergency_lane else "")
    return f"""
    <div style="border:1px solid #444; border-radius:10px; padding:14px; text-align:center; background:#111;">
      <div style="font-weight:600; font-size:1.05em; margin-bottom:6px;">{lane.upper()}</div>
      <div style="width:34px; height:34px; border-radius:50%; background:{color}; margin:0 auto; {glow}"></div>
      <div style="margin-top:6px; font-size:0.9em; color:#ccc;">{state}</div>
      {badge}
    </div>
    """


# ----------------------------------------------------------------- auth/session
if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.username = None
    st.session_state.role = None

# ------------------------------------------------------------------- login page
if not st.session_state.token:
    st.title("\U0001F6A6 Traffic Management System — Sign in")
    st.caption(f"API: {API_BASE}")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        try:
            r = requests.post(f"{API_BASE}/auth/login",
                               data={"username": username, "password": password}, timeout=5)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Backend unreachable: {exc}\n\nStart it with: uvicorn backend.main:app --reload")
            st.stop()
        if r.status_code == 200:
            data = r.json()
            st.session_state.token = data["access_token"]
            st.session_state.username = data["username"]
            st.session_state.role = data["role"]
            st.rerun()
        else:
            st.error("Incorrect username or password.")
    with st.expander("Demo accounts (change these before real deployment)"):
        st.markdown(
            "- **admin** / admin12345 — full control, manages accounts\n"
            "- **operator** / operator12345 — can update detection data and run signal cycles\n"
            "- **viewer** / viewer12345 — read-only"
        )
    st.stop()

# ---------------------------------------------------------------- logged-in app
role = st.session_state.role
can_control = role in ("admin", "operator")
can_manage_users = role == "admin"

st.title("\U0001F6A6 Optimal Traffic Management System — Live Dashboard")

with st.sidebar:
    st.markdown(f"Signed in as **{st.session_state.username}** ({role})")
    if st.button("Log out", use_container_width=True):
        st.session_state.token = None
        st.rerun()
    st.divider()

    if can_control:
        st.header("Controls")
        st.subheader("Set per-lane vehicle counts")
        counts = {lane: st.number_input(lane.capitalize(), min_value=0, value=0, step=1, key=f"count_{lane}")
                  for lane in LANE_IDS}

        st.subheader("\U0001F691 Ambulance / fire-truck priority")
        st.caption("Simulates a CONFIRMED emergency-vehicle detection in a lane "
                   "(same effect as a real detector after multi-frame confirmation).")
        manual_emergency_lane = st.selectbox("Emergency vehicle seen in lane", ["(none)"] + LANE_IDS)

        if st.button("Send update", use_container_width=True):
            _, err = api_post("/detection/update", json={"lane_counts": counts})
            if err:
                st.error(err)
            elif manual_emergency_lane != "(none)":
                api_post("/emergency/manual", json={"lane_id": manual_emergency_lane, "active": True})
                st.success(f"Emergency confirmed on '{manual_emergency_lane}'.")
            else:
                st.success("Sent")

        if st.button("Clear emergency flags", use_container_width=True):
            for lane in LANE_IDS:
                api_post("/emergency/manual", json={"lane_id": lane, "active": False})
            st.success("Cleared")

        if st.button("Run signal cycle", use_container_width=True, type="primary"):
            result, err = api_post("/signal/cycle")
            if err:
                st.error(err)
            else:
                tag = " (EMERGENCY OVERRIDE \U0001F691)" if result["was_emergency"] else ""
                st.success(f"Green: {result['lane']} for {result['green_duration']}s{tag}")
    else:
        st.info("Signed in as **viewer** — read-only. Sign in as operator/admin to control signals.")
        counts = {lane: 0 for lane in LANE_IDS}

    if can_manage_users:
        st.divider()
        st.header("\U0001F464 Manage authority accounts (admin)")
        users, uerr = api_get("/auth/users")
        if uerr:
            st.error(uerr)
        elif users:
            st.table(pd.DataFrame(users)[["username", "role", "created_at"]])
        with st.form("new_user_form"):
            nu = st.text_input("New username")
            npw = st.text_input("New password", type="password")
            nrole = st.selectbox("Role", ["viewer", "operator", "admin"])
            if st.form_submit_button("Create account"):
                _, err = api_post("/auth/users", json={"username": nu, "password": npw, "role": nrole})
                if err:
                    st.error(err)
                else:
                    st.success(f"Created '{nu}' as {nrole}")
                    st.rerun()

    auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)

# ------------------------------------------------------------------ main view
health, herr = api_get("/health")
if herr:
    st.error(f"Backend unreachable: {herr}")
    st.stop()

if health.get("detection_mode") == "failsafe":
    st.warning(
        f"\u26A0\uFE0F **FAILSAFE MODE** — {health.get('detection_status_reason', 'reason unknown')}. "
        f"Signals are cycling on a fixed timer, NOT live vehicle density, until fresh detection data resumes."
    )
else:
    st.caption("\u2705 Detection healthy — signals are density/emergency-based.")

current, cerr = api_get("/signal/current")
if cerr:
    st.error(cerr)
    current = None

if current:
    st.subheader("Junction — live signal state")
    last_cycle = current.get("last_cycle")
    emergency_lane = last_cycle["lane"] if (last_cycle and last_cycle.get("was_emergency")) else None
    cols = st.columns(len(LANE_IDS))
    for col, lane in zip(cols, LANE_IDS):
        state = current["states"].get(lane, "RED")
        with col:
            st.markdown(lane_light(lane, state, lane == emergency_lane), unsafe_allow_html=True)

    if last_cycle:
        tag = (" \U0001F691 **EMERGENCY OVERRIDE** — this lane jumped the queue regardless of vehicle count."
               if last_cycle["was_emergency"] else "")
        st.info(f"Last decision: **{last_cycle['lane']}** green for {last_cycle['green_duration']}s "
                f"(vehicles counted: {last_cycle['vehicle_count']}).{tag}")

st.divider()

if can_control:
    st.subheader("\U0001F3A5 Upload a traffic video — real YOLOv8 detection")
    st.caption(
        "Runs real vehicle detection on the video you upload and feeds the counts into the "
        "signal logic above. **This host has limited CPU/RAM** (free-tier hosting) — keep clips "
        "short. The YOLO model takes ~30-60s to load on its very first use after a restart; "
        "after that it's cached and each frame takes roughly 1-2 seconds on CPU."
    )
    uploaded = st.file_uploader("Video file (mp4/avi, keep it short — a few seconds is enough)",
                                 type=["mp4", "avi", "mov"])
    max_frames = st.slider("Frames to analyze", min_value=3, max_value=20, value=8,
                            help="More frames = more accurate but slower and more likely to time out "
                                 "or run out of memory on a free-tier host.")
    if uploaded is not None and st.button("Analyze video", type="primary"):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = str(Path(tmpdir) / uploaded.name)
            with open(video_path, "wb") as f:
                f.write(uploaded.getbuffer())

            status = st.empty()
            try:
                status.info("Loading YOLOv8 model (first run after a restart can take ~30-60s)...")
                detector = get_detector()
                status.info(f"Running detection on up to {max_frames} frames...")
                from dashboard.video_processor import process_uploaded_video
                t0 = time.time()
                video_counts, annotated_frame, frames_done = process_uploaded_video(
                    video_path, LANE_IDS, detector, max_frames=max_frames,
                )
                elapsed = time.time() - t0
                status.empty()

                import cv2
                st.image(cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB),
                          caption=f"Last analyzed frame — {frames_done} frame(s) processed in {elapsed:.1f}s")
                st.write("Detected per-lane vehicle counts (summed across analyzed frames):")
                st.bar_chart(pd.Series(video_counts, name="vehicles"))

                _, err = api_post("/detection/update", json={"lane_counts": video_counts})
                if err:
                    st.error(f"Detected counts, but failed to send to signal system: {err}")
                else:
                    st.success("Counts sent to the signal system — click 'Run signal cycle' in the sidebar "
                               "to see it decide based on this real detection.")
            except Exception as exc:  # noqa: BLE001 - surface OOM/timeout/decode errors plainly
                status.empty()
                st.error(
                    f"Video analysis failed: {exc}\n\n"
                    f"On a free-tier host this is usually memory or time limits — try a shorter "
                    f"video, fewer frames, or a smaller resolution clip."
                )
    st.divider()

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("Per-lane vehicle counts (last sent)")
    st.bar_chart(pd.Series(counts, name="vehicles"))

with col2:
    st.subheader("Historical trend")
    logs, err = api_get("/logs", params={"limit": 100})
    if err:
        st.error(err)
    elif logs["items"]:
        df = pd.DataFrame(logs["items"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        st.line_chart(df.set_index("timestamp")["vehicle_count"])
        emergency_rows = df[df["is_emergency"]]
        if not emergency_rows.empty:
            st.caption(f"\U0001F691 {len(emergency_rows)} emergency-override cycle(s) in this log window.")
        st.dataframe(df[::-1], use_container_width=True, height=220)
    else:
        st.write("No log records yet — run a signal cycle first.")

if auto_refresh:
    time.sleep(5)
    st.rerun()
