"""
Turns "a list of boxes" into "vehicles per lane".

A camera usually sees the whole junction, so we split the frame into lane
ZONES and decide which zone each detection belongs to using the CENTRE POINT
of its bounding box (a box can overlap two zones, its centre cannot).

Default zones are equal vertical strips; pass your own dict for real cameras.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import cv2

Zone = Tuple[int, int, int, int]  # x1, y1, x2, y2
Zones = Dict[str, Zone]


def build_vertical_zones(lane_ids: Iterable[str], frame_width: int, frame_height: int) -> Zones:
    lanes = list(lane_ids)
    if not lanes:
        raise ValueError("lane_ids must not be empty")
    strip = frame_width / len(lanes)
    zones: Zones = {}
    for i, lane in enumerate(lanes):
        x1 = int(round(i * strip))
        x2 = frame_width if i == len(lanes) - 1 else int(round((i + 1) * strip))
        zones[lane] = (x1, 0, x2, frame_height)
    return zones


def bbox_center(bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def assign_lane(bbox: Tuple[int, int, int, int], zones: Zones) -> Optional[str]:
    cx, cy = bbox_center(bbox)
    for lane, (x1, y1, x2, y2) in zones.items():
        if x1 <= cx < x2 and y1 <= cy < y2:
            return lane
    return None  # outside every zone -> ignored


def count_per_lane(detections: List[Dict[str, Any]], zones: Zones) -> Dict[str, int]:
    counts = {lane: 0 for lane in zones}
    for det in detections:
        lane = assign_lane(det["bbox"], zones)
        if lane is not None:
            counts[lane] += 1
    return counts


def lanes_with_detections(detections: List[Dict[str, Any]], zones: Zones) -> Set[str]:
    return {lane for det in detections if (lane := assign_lane(det["bbox"], zones)) is not None}


def draw_zones(frame, zones: Zones, counts: Optional[Dict[str, int]] = None, active_lane: Optional[str] = None):
    """Return a copy of the frame with zone borders + lane names (+counts)."""
    out = frame.copy()
    for lane, (x1, y1, x2, y2) in zones.items():
        color = (0, 200, 0) if lane == active_lane else (200, 200, 200)
        cv2.rectangle(out, (x1, y1), (x2 - 1, y2 - 1), color, 2)
        text = lane if counts is None else f"{lane}: {counts.get(lane, 0)}"
        cv2.putText(out, text, (x1 + 8, y1 + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    return out
