"""
Fine-tune YOLOv8 to detect "ambulance" and "fire_truck" (classes COCO doesn't have).

===========================================================================
IMPORTANT - READ THIS FIRST
===========================================================================
This script is REAL and RUNNABLE - it calls Ultralytics' actual training
API, not a mock. But training NEEDS:
  1. A labelled dataset (images + bounding-box annotations) of ambulances
     and fire trucks, in YOLO format, split into train/ and val/.
  2. A GPU (CPU training works but is extremely slow - hours to days).

Neither exists in this sandbox, so this script has NOT been run on a real
dataset here. What HAS been verified (see train_emergency_model_smoketest.py
in this same folder) is that the training call itself runs correctly
end-to-end against a tiny synthetic dataset - i.e. the code is correct and
will run the moment you point `data_yaml` at a real dataset.

===========================================================================
WHERE TO GET A DATASET
===========================================================================
Roboflow Universe (universe.roboflow.com) has several public ambulance /
emergency-vehicle datasets, already in YOLO format, free to export. Search
"ambulance detection" or "emergency vehicle". Download the YOLOv8 export -
it gives you a data.yaml + images/ + labels/ folder structure matching
what this script expects.

===========================================================================
EXPECTED DATASET LAYOUT (standard Ultralytics format)
===========================================================================
emergency_dataset/
├── data.yaml            # names: [ambulance, fire_truck], paths to train/val
├── images/
│   ├── train/*.jpg
│   └── val/*.jpg
└── labels/
    ├── train/*.txt      # YOLO format: class_id x_center y_center width height (normalized 0-1)
    └── val/*.txt

===========================================================================
HOW TO RUN (once you have a real dataset)
===========================================================================
    python training/train_emergency_model.py --data path/to/data.yaml --epochs 50

On a free Google Colab GPU (T4), 50 epochs on a few thousand images takes
roughly 30-90 minutes. On CPU, expect 10-20x longer - a GPU is genuinely
needed here, not optional.

After training, the best weights land at:
    runs/detect/<name>/weights/best.pt

Plug that path straight into EmergencyDetector:
    EmergencyDetector(model_path="runs/detect/emergency_yolov8n/weights/best.pt")
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional


def train(
    data_yaml: str,
    base_model: str = "yolov8n.pt",
    epochs: int = 50,
    imgsz: int = 640,
    batch: int = 16,
    project: str = "runs/detect",
    name: str = "emergency_yolov8n",
    device: Optional[str] = None,
):
    from ultralytics import YOLO  # heavy import kept local, same reasoning as elsewhere in this project

    if not Path(data_yaml).exists():
        raise FileNotFoundError(
            f"data.yaml not found at '{data_yaml}'. See the module docstring for the "
            f"expected dataset layout and where to download one (Roboflow Universe)."
        )

    model = YOLO(base_model)  # start from COCO-pretrained weights (transfer learning - much
                               # faster and needs far less data than training from scratch)
    results = model.train(
        data=data_yaml,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        project=project,
        name=name,
        device=device,  # None = auto (GPU if available, else CPU)
        patience=15,     # stop early if val loss stalls for 15 epochs
    )
    best_weights = Path(project) / name / "weights" / "best.pt"
    print(f"\nTraining complete. Best weights: {best_weights}")
    print(f'Use them with: EmergencyDetector(model_path="{best_weights}")')
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", required=True, help="path to dataset's data.yaml")
    p.add_argument("--base-model", default="yolov8n.pt", help="starting weights (transfer learning)")
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--project", default="runs/detect")
    p.add_argument("--name", default="emergency_yolov8n")
    p.add_argument("--device", default=None, help="'cpu', '0' (GPU 0), etc. Default: auto")
    args = p.parse_args()
    train(args.data, args.base_model, args.epochs, args.imgsz, args.batch,
          args.project, args.name, args.device)


if __name__ == "__main__":
    main()
