# Roadmap: from live demo to a real physical junction

This is the honest, concrete path from "a live URL people can click" to
"actually controlling a real traffic light." Every step needs YOUR access
(college/municipal authority, physical hardware) — no AI can do these
remotely.

## Phase 1 — Live demo (done, see main README)
Public URL, real YOLOv8 detection, real signal logic, login system. Good
for showing recruiters/professors a working system.

## Phase 2 — Get authority buy-in
1. Identify a **low-stakes pilot location** — a college campus junction or
   a low-traffic municipal intersection is far easier to get approval for
   than a busy city junction.
2. Approach your **college's civil/traffic engineering department** or the
   **local municipal traffic police/PWD** with the live demo link. Ask
   specifically: "can I pilot this in an advisory/shadow mode (logging
   only, not actually switching lights) at [location]?"
3. Shadow mode is the key ask: the system watches real traffic and logs
   what IT would have decided, without touching the real lights. This
   needs zero safety sign-off and is the standard way pilots start.

## Phase 3 — Get your traffic controller's protocol
1. Ask the traffic authority which vendor's signal controller is
   installed (common Indian vendors vary by state/city).
2. Request the controller's **communication manual** (NTCIP, Modbus, or
   vendor-proprietary — see `hardware/adapter.py` for the stubs already
   built for this).
3. Implement that specific protocol in a new adapter class (the interface
   is already there — you're filling in one method, `apply()`).

## Phase 4 — Real emergency-vehicle dataset
1. Either license/download a real ambulance/fire-truck dataset (Roboflow
   Universe has several) or, better for local accuracy, **collect and
   label your own footage** from the pilot location's camera.
2. Run `training/train_emergency_model.py` on it (this part is
   already built and verified — see the main README).

## Phase 5 — Edge hardware
1. A GPU edge device (Jetson Nano/Orin Nano is the common choice) at the
   junction, running the detection pipeline locally — CPU inference is too
   slow for real-time (verified in this project: ~0.5-1s/frame on CPU).
2. RTSP feed from the junction's existing camera (or a new one) into
   `detection/live_stream.py` (already built and tested for reconnect
   handling).

## Phase 6 — Shadow-mode validation
Run the system logging its decisions for weeks/months alongside the real
(human/fixed-timer) control, comparing logs. This is what builds the
evidence an authority needs before letting software touch real lights.

## Phase 7 — Actual control, phased
Start with **advisory mode** (a human watches a screen and manually
approves the AI's suggestion), then, only after a proven track record,
**supervised automatic** control with a human able to override instantly,
and finally full automatic control — each phase typically takes months in
real deployments, and that timeline is normal, not a sign of a slow project.

---

None of Phases 2-7 can be done by an AI alone — they need your physical
presence, your institution's authority, and real-world time. What this
project gives you is Phase 1 fully working, plus everything technical
(adapters, training pipeline, RTSP support) already built and tested for
Phases 3-5 so that when you get authority buy-in, the software side isn't
the bottleneck.
