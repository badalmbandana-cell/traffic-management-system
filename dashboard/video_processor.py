"""
Runs real YOLOv8 detection on an uploaded video and aggregates per-lane
vehicle counts - used by the dashboard's "Upload a traffic video" feature.

Kept as a separate, plain-Python module (no Streamlit imports) so it can be
unit-tested directly, without needing a browser or a running Streamlit app.

IMPORTANT (memory/CPU): on a small free-tier host, loading YOLOv8 + torch
can use several hundred MB of RAM - this module deliberately processes a
BOUNDED number of frames (max_frames) at a time, loads the model once and
reuses it, and never keeps more than one decoded frame in memory at once.
Even so, on very constrained hosts this can still be slow or get killed by
the host's memory limit - there is no way to fully eliminate that risk in
a 512MB-class container; bounding max_frames is the main lever available.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

from detection.lane_mapper import build_vertical_zones, count_per_lane, draw_zones
from detection.vehicle_detector import VehicleDetector


def process_uploaded_video(
    video_path: str,
    lane_ids: List[str],
    detector: VehicleDetector,
    max_frames: int = 10,
    stride: int = 1,
) -> Tuple[Dict[str, int], np.ndarray, int]:
    """
    Reads up to `max_frames` frames (every `stride`-th frame) from
    video_path, runs real YOLOv8 detection on each, splits the single
    camera view into `len(lane_ids)` vertical zones (same approach as
    run_pipeline.py - a real multi-camera junction would instead run one
    detector per camera, one per lane).

    Returns:
      - total per-lane vehicle counts, SUMMED across all processed frames
        (a rough density proxy - a real deployment would average per-frame
        counts instead, but summing makes the demo's effect visible even
        on a short clip)
      - one annotated frame (last processed frame, boxes + lane zones drawn)
        as a BGR numpy array, for display
      - how many frames were actually processed
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    total_counts = {lane: 0 for lane in lane_ids}
    zones = None
    last_annotated = None
    processed = 0
    frame_index = 0

    try:
        while processed < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % stride != 0:
                frame_index += 1
                continue
            frame_index += 1

            if zones is None:
                h, w = frame.shape[:2]
                zones = build_vertical_zones(lane_ids, w, h)

            detections = detector.detect_frame(frame)
            lane_counts = count_per_lane(detections, zones)
            for lane, n in lane_counts.items():
                total_counts[lane] += n

            annotated = detector.draw_detections(frame, detections)
            last_annotated = draw_zones(annotated, zones, lane_counts)
            processed += 1
    finally:
        cap.release()

    if last_annotated is None:
        # video opened but had zero readable frames
        last_annotated = np.zeros((360, 640, 3), dtype=np.uint8)

    return total_counts, last_annotated, processed
