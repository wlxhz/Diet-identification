from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from backend.models.schemas import FoodTrack

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal runtimes.
    cv2 = None


DEFAULT_UTENSIL_MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "utensil_det_v1.pt"
_model_lock = threading.Lock()
_model_attempted = False
_model: Any | None = None
_model_name = "opencv-fallback"


@dataclass(frozen=True)
class UtensilObservation:
    utensil_id: str
    utensil_type: str
    bbox: list[int]
    confidence: float
    tip_point: list[float] | None = None
    motion_vector: list[float] = field(default_factory=lambda: [0.0, 0.0])
    contact_food_track_id: str | None = None
    carried_food_area_px: int = 0


def detect_utensils(rgb: np.ndarray, foods: list[FoodTrack]) -> list[UtensilObservation]:
    """Detect utensils with the deployed YOLO model, then fall back to OpenCV."""
    if rgb.size == 0:
        return []
    model = _load_model()
    if model is not None:
        try:
            observations = _detect_with_model(model, rgb, foods)
            if observations:
                return observations
        except Exception:
            # Camera streaming and food recognition must continue even when an
            # optional accelerator/model runtime fails on a particular frame.
            pass
    return _detect_with_opencv(rgb, foods)


def detector_name() -> str:
    _load_model()
    return _model_name


def _load_model() -> Any | None:
    global _model_attempted, _model, _model_name
    if _model_attempted:
        return _model
    with _model_lock:
        if _model_attempted:
            return _model
        _model_attempted = True
        if os.getenv("UTENSIL_MODEL_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
            _model_name = "opencv-fallback (disabled)"
            return None
        model_path = Path(os.getenv("UTENSIL_MODEL_PATH", str(DEFAULT_UTENSIL_MODEL_PATH)))
        if not model_path.is_file():
            _model_name = "opencv-fallback (model-missing)"
            return None
        try:
            from ultralytics import YOLO  # type: ignore

            _model = YOLO(str(model_path))
            _model_name = model_path.name
        except Exception as exc:  # pragma: no cover - optional runtime path
            _model = None
            _model_name = f"opencv-fallback ({exc.__class__.__name__})"
        return _model


def _detect_with_model(
    model: Any,
    rgb: np.ndarray,
    foods: list[FoodTrack],
) -> list[UtensilObservation]:
    height, width = rgb.shape[:2]
    confidence_threshold = float(os.getenv("UTENSIL_MODEL_CONFIDENCE", "0.25"))
    result = model.predict(rgb, imgsz=640, conf=confidence_threshold, verbose=False)[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    names = getattr(result, "names", {}) or {}
    observations: list[UtensilObservation] = []
    for index, box in enumerate(boxes):
        xyxy = box.xyxy[0].tolist()
        bbox = [
            int(max(0, xyxy[0])),
            int(max(0, xyxy[1])),
            int(min(width, xyxy[2])),
            int(min(height, xyxy[3])),
        ]
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        class_id = int(box.cls[0].item()) if getattr(box, "cls", None) is not None else -1
        raw_label = str(names.get(class_id, "unknown")).strip().lower()
        utensil_type = _normalise_utensil_type(raw_label)
        confidence = float(box.conf[0].item()) if getattr(box, "conf", None) is not None else 0.5
        contact_id, carried_area = _contact_food(bbox, foods)
        observations.append(
            UtensilObservation(
                utensil_id=f"utensil_{index + 1}",
                utensil_type=utensil_type,
                bbox=bbox,
                confidence=round(min(1.0, confidence), 3),
                tip_point=[float(bbox[2]), float((bbox[1] + bbox[3]) / 2)],
                contact_food_track_id=contact_id,
                carried_food_area_px=carried_area,
            )
        )
    observations.sort(key=lambda item: item.confidence, reverse=True)
    return observations[:5]


def _normalise_utensil_type(label: str) -> str:
    if "chopstick" in label or "筷" in label:
        return "chopsticks"
    if "spoon" in label or "勺" in label:
        return "spoon"
    if "fork" in label or "叉" in label:
        return "fork"
    if "hand" in label or "手" in label:
        return "hand"
    return "unknown"


def _detect_with_opencv(rgb: np.ndarray, foods: list[FoodTrack]) -> list[UtensilObservation]:
    if cv2 is None:
        return []
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 70, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=55, minLineLength=max(42, width // 9), maxLineGap=12)
    if lines is None:
        return []

    observations: list[UtensilObservation] = []
    for idx, line in enumerate(lines[:24]):
        x1, y1, x2, y2 = [int(v) for v in line.reshape(-1)[:4]]
        length = float(np.hypot(x2 - x1, y2 - y1))
        if length < max(42, min(width, height) * 0.12):
            continue
        x_min, x_max = sorted([x1, x2])
        y_min, y_max = sorted([y1, y2])
        pad = 8
        bbox = [max(0, x_min - pad), max(0, y_min - pad), min(width, x_max + pad), min(height, y_max + pad)]
        crop = rgb[bbox[1] : bbox[3], bbox[0] : bbox[2]]
        if crop.size == 0:
            continue
        brightness = float(crop.mean() / 255)
        channel_std = float(np.std(crop.reshape(-1, 3), axis=0).mean() / 80)
        slenderness = length / max(1, min(bbox[2] - bbox[0], bbox[3] - bbox[1]))
        if slenderness < 3.0 and brightness < 0.58:
            continue

        utensil_type = "chopsticks" if slenderness > 6.5 else "unknown"
        confidence = min(0.68, 0.18 + min(slenderness / 9.0, 1.0) * 0.28 + brightness * 0.12 + min(channel_std, 1.0) * 0.10)
        contact_id, carried_area = _contact_food(bbox, foods)
        if contact_id:
            confidence = min(0.78, confidence + 0.12)
        observations.append(
            UtensilObservation(
                utensil_id=f"utensil_{idx + 1}",
                utensil_type=utensil_type,
                bbox=bbox,
                confidence=round(confidence, 2),
                tip_point=[float(x2), float(y2)],
                contact_food_track_id=contact_id,
                carried_food_area_px=carried_area,
            )
        )
    observations.sort(key=lambda item: item.confidence, reverse=True)
    return observations[:3]


def _contact_food(bbox: list[int], foods: list[FoodTrack]) -> tuple[str | None, int]:
    ux1, uy1, ux2, uy2 = bbox
    best_id: str | None = None
    best_overlap = 0
    for food in foods:
        fx1, fy1, fx2, fy2 = food.bbox
        ix1 = max(ux1, fx1)
        iy1 = max(uy1, fy1)
        ix2 = min(ux2, fx2)
        iy2 = min(uy2, fy2)
        overlap = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if overlap > best_overlap:
            best_overlap = overlap
            best_id = food.track_id
    return best_id, int(best_overlap)
