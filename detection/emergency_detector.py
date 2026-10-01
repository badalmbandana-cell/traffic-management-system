"""
Module 3 - Emergency-vehicle priority.

COCO (the dataset the stock YOLOv8 weights were trained on) has NO "ambulance"
class, so there are three ways to feed this module:

  1. Custom-trained weights that know "ambulance"/"fire truck"
        EmergencyDetector(model_path="emergency_best.pt")      <- production route
  2. A manual / scheduled flag for demos
        the API endpoint POST /emergency/manual, or
        run_pipeline.py --manual-emergency east@5-15
  3. (rejected) colour/siren heuristics - fragile under real lighting.

Whatever the source, the SAME EmergencyTracker sits behind it. It only confirms
an emergency after several consecutive positive readings, and only releases it
after several consecutive negatives (hysteresis), so one lucky/unlucky frame
can never flip the junction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_EMERGENCY_CLASSES = ("ambulance", "fire truck", "police car")


def _normalize(name: str) -> str:
    """'Fire_Truck' / 'fire-truck' / 'FIRE TRUCK' -> 'fire truck'."""
    return name.strip().lower().replace("_", " ").replace("-", " ")


class EmergencyDetector:
    """Looks at ONE frame and reports emergency-vehicle detections."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        emergency_classes: Iterable[str] = DEFAULT_EMERGENCY_CLASSES,
        confidence_threshold: float = 0.5,
        model: Optional[Any] = None,
    ) -> None:
        self.emergency_classes = {_normalize(c) for c in emergency_classes}
        self.confidence_threshold = confidence_threshold
        if model is None and model_path:
            from ultralytics import YOLO

            model = YOLO(model_path)
        self.model = model

    @property
    def enabled(self) -> bool:
        """False when no emergency model is loaded (manual mode only)."""
        return self.model is not None

    def detect_frame(self, frame) -> List[Dict[str, Any]]:
        """[{class_name, confidence, bbox}] for emergency classes only."""
        if self.model is None:
            return []
        results = self.model(frame, conf=self.confidence_threshold, verbose=False)
        found: List[Dict[str, Any]] = []
        for box in results[0].boxes:
            name = self.model.names[int(box.cls[0])]
            confidence = float(box.conf[0])
            if _normalize(name) in self.emergency_classes and confidence >= self.confidence_threshold:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                found.append({"class_name": name, "confidence": round(confidence, 4), "bbox": (x1, y1, x2, y2)})
        return found

    def detect_emergency(self, frame, manual_flag: bool = False) -> bool:
        """True if this frame shows an emergency vehicle (or the manual flag is set)."""
        return manual_flag or bool(self.detect_frame(frame))


@dataclass
class _LaneEmergencyState:
    consecutive_hits: int = 0
    consecutive_misses: int = 0
    active: bool = False
    activated_seq: int = 0  # order of activation, so the OLDEST emergency wins


class EmergencyTracker:
    """Per-lane multi-reading confirmation with hysteresis."""

    def __init__(self, lane_ids: Iterable[str], trigger_frames: int = 5, release_frames: int = 15) -> None:
        if trigger_frames < 1 or release_frames < 1:
            raise ValueError("trigger_frames and release_frames must be >= 1")
        self.trigger_frames = trigger_frames
        self.release_frames = release_frames
        self.states: Dict[str, _LaneEmergencyState] = {l: _LaneEmergencyState() for l in lane_ids}
        self._seq = 0

    def update(self, lane_id: str, emergency_seen: bool) -> bool:
        """Feed one reading for one lane; returns whether the lane is now in emergency."""
        if lane_id not in self.states:
            raise ValueError(f"Unknown lane '{lane_id}'")
        s = self.states[lane_id]
        if emergency_seen:
            s.consecutive_hits += 1
            s.consecutive_misses = 0
            if not s.active and s.consecutive_hits >= self.trigger_frames:
                s.active = True
                self._seq += 1
                s.activated_seq = self._seq
        else:
            s.consecutive_misses += 1
            s.consecutive_hits = 0
            if s.active and s.consecutive_misses >= self.release_frames:
                s.active = False
        return s.active

    def update_all(self, flags: Dict[str, bool]) -> None:
        """One reading for EVERY lane (lanes missing from `flags` count as 'not seen')."""
        for lane in self.states:
            self.update(lane, bool(flags.get(lane, False)))

    def active_lanes(self) -> List[str]:
        active = [(s.activated_seq, lane) for lane, s in self.states.items() if s.active]
        return [lane for _, lane in sorted(active)]

    def get_emergency_lane(self) -> Optional[str]:
        """Oldest confirmed emergency lane, or None."""
        lanes = self.active_lanes()
        return lanes[0] if lanes else None

    def reset(self) -> None:
        for s in self.states.values():
            s.consecutive_hits = s.consecutive_misses = 0
            s.active = False
