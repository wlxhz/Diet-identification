from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.models.schemas import FoodTrack

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal runtimes.
    cv2 = None


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
    """Lightweight MVP detector for long, bright utensil-like shapes.

    This is intentionally conservative: it only emits candidates. Dedicated
    utensil models can replace this module without changing downstream schemas.
    """
    if rgb.size == 0:
        return []
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
