"""
Synthetic traffic generator - poore system ko YOLO/video ke bina demo karne ke liye.

Random-walk vehicle counts backend API ko bhejta hai, har N updates pe ek FSM
cycle chalata hai, aur beech-beech mein ek lane pe "emergency episode" bhi
chalata hai (multiple updates tak) taaki EmergencyTracker ka multi-frame
confirmation dikh sake.

    python simulate_traffic.py                       # 60 updates, default settings
    python simulate_traffic.py --updates 200 --interval 0.2
"""
from __future__ import annotations

import argparse
import random
import time
from typing import Dict, List, Optional

import requests


def next_counts(current: Dict[str, int], rng: random.Random) -> Dict[str, int]:
    """Har lane ka count thoda upar-neeche move karta hai (0..40 ke beech, random walk)."""
    return {lane: max(0, min(40, n + rng.randint(-3, 4))) for lane, n in current.items()}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Backend API ko synthetic traffic data se test karo")
    p.add_argument("--api-url", default="http://127.0.0.1:8000")
    p.add_argument("--lanes", default="north,south,east,west")
    p.add_argument("--updates", type=int, default=60)
    p.add_argument("--interval", type=float, default=0.5, help="updates ke beech seconds")
    p.add_argument("--cycle-every", type=int, default=5)
    p.add_argument("--emergency-every", type=int, default=25, help="har N updates ke baad ek emergency episode")
    p.add_argument("--emergency-length", type=int, default=8, help="episode kitne updates tak chalega")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--username", default="operator", help="account to run as (needs operator or admin role)")
    p.add_argument("--password", default="operator12345", help="password for --username")
    args = p.parse_args(argv)

    rng = random.Random(args.seed)
    lanes = [x.strip() for x in args.lanes.split(",") if x.strip()]
    counts = {lane: rng.randint(3, 20) for lane in lanes}
    emergency_lane: Optional[str] = None
    emergency_left = 0

    session = requests.Session()
    try:
        session.get(f"{args.api_url}/health", timeout=5).raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(f"Backend nahi mila ({args.api_url}). Pehle chalao: uvicorn backend.main:app\n{exc}")

    login_resp = session.post(f"{args.api_url}/auth/login",
                               data={"username": args.username, "password": args.password}, timeout=10)
    if login_resp.status_code != 200:
        raise SystemExit(
            f"Login failed for '{args.username}': {login_resp.text}\n"
            f"Default demo accounts: admin/admin12345, operator/operator12345, viewer/viewer12345"
        )
    session.headers["Authorization"] = f"Bearer {login_resp.json()['access_token']}"

    for i in range(1, args.updates + 1):
        counts = next_counts(counts, rng)

        if emergency_left == 0 and i % args.emergency_every == 0:
            emergency_lane, emergency_left = rng.choice(lanes), args.emergency_length
        active_emergency_lane = emergency_lane if emergency_left > 0 else None
        if emergency_left > 0:
            emergency_left -= 1

        r = session.post(
            f"{args.api_url}/detection/update",
            json={"lane_counts": counts, "emergency_lane": active_emergency_lane},
            timeout=10,
        )
        r.raise_for_status()
        info = r.json()
        line = f"[{i:3d}] {counts}"
        if info["emergency_lane"]:
            line += f"  \U0001F691 confirmed emergency: {info['emergency_lane']}"
        print(line)

        if i % args.cycle_every == 0:
            c = session.post(f"{args.api_url}/signal/cycle", timeout=10).json()
            tag = " (EMERGENCY OVERRIDE)" if c["was_emergency"] else ""
            print(f"      -> GREEN: {c['lane']} for {c['green_duration']}s{tag}")

        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
