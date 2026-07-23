from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal runtimes.
    cv2 = None


MARKER_SIZE_MM = 50.0
VALID_MARKER_IDS = {23, 42}
MIN_SCALE_CONFIDENCE = 0.55


@dataclass(frozen=True)
class ScaleMetadata:
    detected: bool = False
    marker_id: int | None = None
    marker_size_mm: float = MARKER_SIZE_MM
    corners_px: list[list[float]] = field(default_factory=list)
    edge_lengths_px: list[float] = field(default_factory=list)
    mm_per_px: float = 0.0
    px_per_mm: float = 0.0
    marker_area_px: float = 0.0
    marker_area_ratio: float = 0.0
    perspective_score: float = 0.0
    sharpness_score: float = 0.0
    confidence: float = 0.0
    status: str = "not_found"

    @property
    def usable(self) -> bool:
        return self.detected and self.confidence >= MIN_SCALE_CONFIDENCE and self.mm_per_px > 0


def detect_scale_marker(rgb: np.ndarray) -> ScaleMetadata:
    if rgb.size == 0:
        return ScaleMetadata(status="empty_frame")
    if cv2 is None:
        return ScaleMetadata(status="opencv_unavailable")
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        return ScaleMetadata(status="aruco_unavailable")

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    try:
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_5X5_100)
        parameters = aruco.DetectorParameters()
        if hasattr(aruco, "ArucoDetector"):
            detector = aruco.ArucoDetector(dictionary, parameters)
            corners, ids, _ = detector.detectMarkers(gray)
        else:
            corners, ids, _ = aruco.detectMarkers(gray, dictionary, parameters=parameters)
    except Exception:
        return ScaleMetadata(status="aruco_error")

    if ids is None or len(ids) == 0:
        return ScaleMetadata(status="not_found")

    candidates: list[ScaleMetadata] = []
    frame_area = max(1, gray.shape[0] * gray.shape[1])
    for raw_corners, raw_id in zip(corners, ids.flatten()):
        marker_id = int(raw_id)
        if marker_id not in VALID_MARKER_IDS:
            continue
        points = np.asarray(raw_corners, dtype=np.float32).reshape(-1, 2)
        if points.shape != (4, 2):
            continue
        candidates.append(_metadata_from_corners(points, marker_id, gray, frame_area))

    if not candidates:
        return ScaleMetadata(status="invalid_id")
    return max(candidates, key=lambda item: (item.confidence, item.marker_area_px))


def _metadata_from_corners(points: np.ndarray, marker_id: int, gray: np.ndarray, frame_area: int) -> ScaleMetadata:
    edges = [
        _distance(points[0], points[1]),
        _distance(points[1], points[2]),
        _distance(points[2], points[3]),
        _distance(points[3], points[0]),
    ]
    edge_px = float(np.mean(edges))
    if edge_px <= 1:
        return ScaleMetadata(marker_id=marker_id, status="too_small")

    area_px = float(abs(cv2.contourArea(points)))
    area_ratio = area_px / frame_area
    min_edge = max(1e-6, min(edges))
    max_edge = max(edges)
    edge_ratio = min_edge / max(max_edge, 1e-6)
    perspective_score = _clamp((edge_ratio - 0.55) / (0.90 - 0.55))
    area_score = _clamp(area_ratio / 0.015)
    sharpness_score = _marker_sharpness(gray, points)
    confidence = _clamp(area_score * 0.30 + perspective_score * 0.30 + sharpness_score * 0.25 + 0.15)

    status = "detected"
    if area_score < 0.25:
        status = "too_small"
    elif perspective_score < 0.25:
        status = "too_skewed"
    elif sharpness_score < 0.25:
        status = "too_blurry"

    mm_per_px = MARKER_SIZE_MM / edge_px
    return ScaleMetadata(
        detected=True,
        marker_id=marker_id,
        marker_size_mm=MARKER_SIZE_MM,
        corners_px=[[float(x), float(y)] for x, y in points.tolist()],
        edge_lengths_px=[round(float(edge), 3) for edge in edges],
        mm_per_px=round(float(mm_per_px), 6),
        px_per_mm=round(float(1.0 / mm_per_px), 3),
        marker_area_px=round(area_px, 2),
        marker_area_ratio=round(area_ratio, 5),
        perspective_score=round(perspective_score, 3),
        sharpness_score=round(sharpness_score, 3),
        confidence=round(confidence, 3),
        status=status,
    )


def _marker_sharpness(gray: np.ndarray, points: np.ndarray) -> float:
    x, y, w, h = cv2.boundingRect(points.astype(np.int32))
    pad = max(3, int(max(w, h) * 0.08))
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(gray.shape[1], x + w + pad)
    y2 = min(gray.shape[0], y + h + pad)
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    lap_var = float(cv2.Laplacian(crop, cv2.CV_64F).var())
    return _clamp(lap_var / 260.0)


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(math.hypot(float(a[0] - b[0]), float(a[1] - b[1])))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
