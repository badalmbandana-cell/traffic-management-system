"""
Module 1 - Vehicle detection with YOLOv8 + OpenCV.

Flow:  frame (numpy array, BGR)  ->  YOLO  ->  keep only vehicle classes above
the confidence threshold  ->  list of detection dicts  ->  per-class counts.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2

# COCO class IDs that count as "vehicles"
VEHICLE_CLASSES: Dict[int, str] = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# BGR colours used when drawing boxes
_COLORS = {
    "car": (0, 200, 0),
    "motorcycle": (0, 165, 255),
    "bus": (255, 128, 0),
    "truck": (0, 0, 255),
}


class VehicleDetector:
    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        confidence_threshold: float = 0.4,
        model: Optional[Any] = None,
    ) -> None:
        """
        model_path            - YOLO weights (downloaded automatically the first time).
        confidence_threshold  - detections below this score are dropped.
        model                 - optional pre-built model object (used by the unit tests
                                so they can run without downloading weights).
        """
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        self.confidence_threshold = confidence_threshold
        if model is None:
            # Imported lazily: importing torch is slow, and the rest of the
            # system (API, DB, FSM) should not need it.
            from ultralytics import YOLO

            model = YOLO(model_path)
        self.model = model

    def detect_frame(self, frame) -> List[Dict[str, Any]]:
        """Run YOLO on one frame -> [{class_name, confidence, bbox=(x1,y1,x2,y2)}]."""
        results = self.model(frame, conf=self.confidence_threshold, verbose=False)
        detections: List[Dict[str, Any]] = []
        for box in results[0].boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            if class_id not in VEHICLE_CLASSES or confidence < self.confidence_threshold:
                continue
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
            detections.append(
                {
                    "class_name": VEHICLE_CLASSES[class_id],
                    "confidence": round(confidence, 4),
                    "bbox": (x1, y1, x2, y2),
                }
            )
        return detections

    @staticmethod
    def count_vehicles(detections: List[Dict[str, Any]]) -> Dict[str, int]:
        """Per-class counts. Every vehicle class is present (0 if not seen)."""
        counts = {name: 0 for name in VEHICLE_CLASSES.values()}
        for det in detections:
            counts[det["class_name"]] += 1
        return counts

    @staticmethod
    def draw_detections(frame, detections: List[Dict[str, Any]]):
        """Return a COPY of the frame with boxes + labels drawn on it."""
        annotated = frame.copy()
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            color = _COLORS.get(det["class_name"], (255, 255, 255))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f'{det["class_name"]} {det["confidence"]:.2f}'
            (w, h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            top = max(y1 - h - baseline, 0)
            cv2.rectangle(annotated, (x1, top), (x1 + w, top + h + baseline), color, -1)
            cv2.putText(
                annotated, label, (x1, top + h), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
            )
        return annotated

    def process_video(self, video_path: str, output_path: str) -> Dict[str, Any]:
        """Detect on every frame, write an annotated video, return a summary."""
        if not Path(video_path).exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"OpenCV could not open video: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )

        frames = 0
        peak_total = 0
        totals = {name: 0 for name in VEHICLE_CLASSES.values()}
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                detections = self.detect_frame(frame)
                counts = self.count_vehicles(detections)
                annotated = self.draw_detections(frame, detections)
                cv2.putText(
                    annotated, f"Vehicles: {sum(counts.values())}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2,
                )
                writer.write(annotated)
                frames += 1
                peak_total = max(peak_total, sum(counts.values()))
                for name, n in counts.items():
                    totals[name] += n
        finally:
            cap.release()
            writer.release()

        return {
            "frames": frames,
            "peak_vehicles_in_a_frame": peak_total,
            "avg_per_frame": {k: round(v / frames, 2) if frames else 0.0 for k, v in totals.items()},
            "output_path": str(output_path),
        }
