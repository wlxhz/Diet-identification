from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SessionStatus = Literal[
    "waiting_mobile",
    "mobile_connected",
    "camera_ready",
    "streaming",
    "measuring",
    "completed",
    "error",
]


class DeviceInfo(BaseModel):
    platform: str = "android"
    model: str = "unknown"
    user_agent: str = ""
    app_version: str = "web-demo"


class JoinSessionRequest(BaseModel):
    token: str
    device: DeviceInfo = Field(default_factory=DeviceInfo)


class CaptureEvent(BaseModel):
    token: str
    event: Literal[
        "camera_permission_granted",
        "camera_permission_denied",
        "stream_started",
        "stream_stopped",
        "capture_error",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class FrameUpload(BaseModel):
    token: str
    image: str
    width: int
    height: int
    timestamp_ms: int
    device_motion: dict[str, Any] = Field(default_factory=dict)


class Nutrition(BaseModel):
    calories_kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float = 0
    sodium_mg: float = 0


class FoodTrack(BaseModel):
    track_id: str
    name: str
    category: str
    profile_key: str = "unknown_food"
    cooking_method: str = "unknown"
    cooking_method_name: str = "未识别"
    cooking_confidence: float = 0
    raw_weight_g: float = 0
    area_ratio: float = 0
    bbox_area_ratio: float = 0
    scale_view_quality: float = 0
    scale_corrected: bool = False
    scale_confidence: float = 0
    scale_sample_count: int = 0
    scale_status: str = "calibrating"
    state: str = "tracking"
    bbox: list[int]
    polygon: list[list[int]] = Field(default_factory=list)
    mask_svg_path: str = ""
    color: str = "#7cf4bd"
    confidence: float
    volume_ml: float
    volume_confidence: float
    density_g_per_ml: float
    estimated_weight_g: float
    weight_error_g: float
    weight_confidence: float
    visible_frames: int = 1
    sample_count: int = 1
    stable_seconds: float = 0
    convergence: float = 0
    first_seen_seconds: float = 0
    last_seen_seconds: float = 0
    nutrition: Nutrition


class MeasurementQuality(BaseModel):
    angle_coverage: float = 0
    depth_completeness: float = 0
    mask_stability: float = 0
    motion_quality: float = 0
    lighting: float = 0
    blur: float = 0
    plate_visibility: float = 0
    overall: float = 0


class VideoInfo(BaseModel):
    fps: float = 0
    resolution: str = "0x0"
    quality: str = "waiting"
    last_frame_at: str | None = None


class Guidance(BaseModel):
    message: str = "请用手机扫码并授权摄像头。"
    needed_action: str = "connect_mobile"


class SessionState(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    session_id: str
    status: SessionStatus
    created_at: datetime
    expires_at: datetime
    elapsed_seconds: float = 0
    frame_count: int = 0
    analyzed_frame_count: int = 0
    analyzer: str = "not_loaded"
    model_name: str = "none"
    capture_url: str
    qr_code_url: str
    video: VideoInfo = Field(default_factory=VideoInfo)
    measurement_quality: MeasurementQuality = Field(default_factory=MeasurementQuality)
    foods: list[FoodTrack] = Field(default_factory=list)
    guidance: Guidance = Field(default_factory=Guidance)
    latest_frame_url: str | None = None
    device: DeviceInfo | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    token: str
    capture_url: str
    qr_code_url: str
    events_url: str
    expires_at: datetime


class Report(BaseModel):
    report_id: str
    session_id: str
    created_at: datetime
    meal_summary: dict[str, float]
    foods: list[dict[str, Any]]
    scan_quality: dict[str, Any]
    warnings: list[str]
