"""
End-to-end pipeline - saare modules ko jodta hai:

    video/image -> YOLOv8 detect (Module 1) -> lane-wise counts (lane_mapper)
                -> POST /detection/update (Module 4) -> har K frames pe
                   POST /signal/cycle -> SQLite log (Module 6) -> dashboard (Module 5)

Emergency vehicles ke liye COCO mein class nahi hai, isliye is script mein
--simulate-emergency hai: ek lane ko frame-range ke liye "emergency dikhi"
maan lo, taaki poora pipeline (Module 3 ka multi-frame confirmation included)
bina custom-trained model ke bhi end-to-end demo ho sake. Custom model ho toh
--emergency-model se use karo.

Backend pehle chalao:  uvicorn backend.main:app --reload

Examples:
    python run_pipeline.py --source data/sample_videos/bus.jpg --repeat 30
    python run_pipeline.py --source traffic.mp4 --simulate-emergency east:20-45
    python run_pipeline.py --source traffic.mp4 --emergency-model best.pt
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, Iterator, List, Optional, Tuple

import cv2
import requests

from detection.emergency_detector import EmergencyDetector
from detection.lane_mapper import build_vertical_zones, count_per_lane, draw_zones

Simulation = Tuple[str, int, int]  # (lane, start_frame, end_frame) - processed-frame index


# ----------------------------------------------------------------- helpers
def parse_simulations(specs: Optional[List[str]]) -> List[Simulation]:
    """'east:20-45' -> ('east', 20, 45)"""
    parsed = []
    for spec in specs or []:
        try:
            lane, rng = spec.split(":")
            start, end = rng.split("-")
            parsed.append((lane, int(start), int(end)))
        except ValueError:
            raise SystemExit(f"Galat --simulate-emergency format: '{spec}' (sahi format: east:20-45)")
    return parsed


def simulated_flag_for(index: int, sims: List[Simulation]) -> Optional[str]:
    for lane, start, end in sims:
        if start <= index <= end:
            return lane
    return None


def frames_from(source: str, repeat: int) -> Iterator:
    """Video ho toh frames yield karo; image ho toh wahi frame `repeat` baar (demo ke liye)."""
    image = cv2.imread(source)
    if image is not None:
        for _ in range(repeat):
            yield image
        return
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Source open nahi hua: {source}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


def login(session: requests.Session, api_url: str, username: str, password: str) -> None:
    """Logs in and attaches the Bearer token to every future request this session makes."""
    resp = session.post(f"{api_url}/auth/login", data={"username": username, "password": password}, timeout=10)
    if resp.status_code != 200:
        raise SystemExit(
            f"Login failed for user '{username}' ({resp.status_code}): {resp.text}\n"
            f"Default demo accounts: admin/admin12345, operator/operator12345, viewer/viewer12345 "
            f"(operator or admin can drive the pipeline; change these before real deployment)."
        )
    token = resp.json()["access_token"]
    session.headers["Authorization"] = f"Bearer {token}"


def post(session: requests.Session, url: str, payload: Optional[dict]) -> dict:
    resp = session.post(url, json=payload, timeout=10)
    if resp.status_code >= 400:
        raise SystemExit(f"API error {resp.status_code} on {url}: {resp.text}")
    return resp.json()


# -------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Traffic pipeline: detect -> count -> API -> signal cycle")
    p.add_argument("--source", required=True, help="video ya image path")
    p.add_argument("--lanes", default="north,south,east,west", help="comma-separated lane IDs (backend jaisi hi)")
    p.add_argument("--api-url", default="http://127.0.0.1:8000")
    p.add_argument("--model", default="yolov8n.pt", help="vehicle detection model")
    p.add_argument("--emergency-model", default=None, help="custom YOLO weights (ambulance / fire truck)")
    p.add_argument("--confidence", type=float, default=0.4)
    p.add_argument("--stride", type=int, default=1, help="har N-th frame process karo (CPU pe speed ke liye)")
    p.add_argument("--cycle-every", type=int, default=10, help="kitne processed frames baad ek FSM cycle")
    p.add_argument("--max-frames", type=int, default=0, help="0 = poora video/repeat count")
    p.add_argument("--repeat", type=int, default=20, help="image source ho toh kitni baar repeat")
    p.add_argument("--delay", type=float, default=0.0, help="har processed frame ke baad wait (seconds)")
    p.add_argument("--simulate-emergency", action="append", metavar="LANE:START-END",
                    help="demo: is lane mein frame START..END tak emergency vehicle 'dikhao' (repeatable)")
    p.add_argument("--username", default="operator", help="account to drive the pipeline as (needs operator or admin role)")
    p.add_argument("--password", default="operator12345", help="password for --username (change from the demo default in real use)")
    p.add_argument("--save-annotated", default=None, help="annotated output video path (.mp4)")
    args = p.parse_args(argv)

    lane_ids = [x.strip() for x in args.lanes.split(",") if x.strip()]
    sims = parse_simulations(args.simulate_emergency)

    # Heavy imports yahin: taaki --help chalane ke liye torch load na karna pade.
    from detection.vehicle_detector import VehicleDetector

    detector = VehicleDetector(args.model, args.confidence)
    emergency = EmergencyDetector(args.emergency_model)
    if not emergency.enabled and not sims:
        print("[info] Emergency model nahi diya - emergency detection off "
              "(demo ke liye --simulate-emergency use karo).")

    session = requests.Session()
    try:
        session.get(f"{args.api_url}/health", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(f"Backend nahi mila ({args.api_url}). Pehle chalao: uvicorn backend.main:app\n{exc}")
    login(session, args.api_url, args.username, args.password)

    writer = None
    zones = None
    processed = 0
    for i, frame in enumerate(frames_from(args.source, args.repeat)):
        if i % args.stride:
            continue
        if args.max_frames and processed >= args.max_frames:
            break

        height, width = frame.shape[:2]
        if zones is None:
            zones = build_vertical_zones(lane_ids, width, height)

        detections = detector.detect_frame(frame)
        counts = count_per_lane(detections, zones)

        emergency_seen_lane = None
        if emergency.enabled:
            emergency_seen_lane = next(
                (lane for lane in lane_ids if emergency.detect_emergency(frame)), None
            )
        sim_lane = simulated_flag_for(processed, sims)
        active_emergency_lane = sim_lane or emergency_seen_lane

        update = post(session, f"{args.api_url}/detection/update",
                      {"lane_counts": counts, "emergency_lane": active_emergency_lane})

        line = f"frame {processed:4d} counts={counts}"
        if update["emergency_lane"]:
            line += f"  \U0001F691 confirmed emergency={update['emergency_lane']}"
        print(line)

        if (processed + 1) % args.cycle_every == 0:
            cycle = post(session, f"{args.api_url}/signal/cycle", None)
            tag = " (EMERGENCY OVERRIDE)" if cycle["was_emergency"] else ""
            print(f"  -> CYCLE: lane={cycle['lane']} green={cycle['green_duration']}s "
                  f"yellow={cycle['yellow_duration']}s{tag}")

        if args.save_annotated:
            if writer is None:
                writer = cv2.VideoWriter(args.save_annotated, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (width, height))
            annotated = detector.draw_detections(frame, detections)
            annotated = draw_zones(annotated, zones, counts, active_lane=update["emergency_lane"])
            writer.write(annotated)

        processed += 1
        if args.delay:
            time.sleep(args.delay)

    if writer is not None:
        writer.release()
        print(f"Annotated video saved: {args.save_annotated}")
    print(f"Done. {processed} frame(s) processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
