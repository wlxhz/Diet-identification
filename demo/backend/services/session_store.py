from __future__ import annotations

import asyncio
import math
import secrets
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import WebSocket

from backend.models.schemas import (
    CaptureEvent,
    CreateSessionResponse,
    DeviceInfo,
    FoodTrack,
    FrameUpload,
    Guidance,
    MeasurementQuality,
    Report,
    SessionState,
    VideoInfo,
)
from backend.services.analyzer import DecodedFrame, FoodAnalyzer
from backend.services.nutrition import cooking_method_for_key, nutrition_for_weight, profile_for_key


CHINA_TZ = timezone(timedelta(hours=8))
DESSERT_SNACK_CATEGORIES = {"甜点", "零食", "水果"}


def _display_name_for_track(profile_key: str, profile_display_name: str, cooking_method: str, cooking_display_name: str) -> str:
    if profile_key == "pork_floss_pastry" or cooking_method in {"unknown", "raw_light"}:
        return profile_display_name
    return f"{cooking_display_name}{profile_display_name}"


@dataclass
class TrackAggregate:
    track_id: str
    track: FoodTrack
    first_seen_seconds: float
    last_seen_seconds: float
    visible_frames: int = 1
    missed_frames: int = 0
    raw_weight_samples: list[float] = field(default_factory=list)
    accepted_weight_samples: list[float] = field(default_factory=list)
    accepted_area_ratios: list[float] = field(default_factory=list)
    accepted_view_qualities: list[float] = field(default_factory=list)
    reference_weight_g: float | None = None
    reference_area_ratio: float | None = None
    scale_correction_events: int = 0


class SessionRecord:
    def __init__(self, session_id: str, token: str, public_base_url: str) -> None:
        now = datetime.now(CHINA_TZ)
        capture_url = f"{public_base_url}/capture?session_id={session_id}&token={token}"
        self.token = token
        self.created_monotonic = time.monotonic()
        self.latest_frame_bytes: bytes | None = None
        self.pending_frame: tuple[DecodedFrame, int, float] | None = None
        self.analysis_lock = asyncio.Lock()
        self.track_memory: dict[str, TrackAggregate] = {}
        self.next_track_index = 1
        self.report: Report | None = None
        self.state = SessionState(
            session_id=session_id,
            status="waiting_mobile",
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            capture_url=capture_url,
            qr_code_url=f"/api/sessions/{session_id}/qrcode",
            analyzer="not_loaded",
            model_name="none",
        )


class SessionStore:
    def __init__(self, analyzer: FoodAnalyzer) -> None:
        self.analyzer = analyzer
        self.sessions: dict[str, SessionRecord] = {}
        self.websockets: dict[str, set[WebSocket]] = {}

    def create_session(self, public_base_url: str) -> CreateSessionResponse:
        session_id = f"sess_{datetime.now(CHINA_TZ).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        token = f"once_{secrets.token_urlsafe(12)}"
        record = SessionRecord(session_id, token, public_base_url.rstrip("/"))
        record.state.analyzer = self.analyzer.backend_name
        record.state.model_name = self.analyzer.model_name
        self.sessions[session_id] = record
        return CreateSessionResponse(
            session_id=session_id,
            token=token,
            capture_url=record.state.capture_url,
            qr_code_url=record.state.qr_code_url,
            events_url=f"/ws/sessions/{session_id}/events",
            expires_at=record.state.expires_at,
        )

    def get(self, session_id: str) -> SessionRecord:
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return self.sessions[session_id]

    def validate_token(self, session_id: str, token: str) -> SessionRecord:
        record = self.get(session_id)
        if not secrets.compare_digest(record.token, token):
            raise PermissionError("invalid token")
        return record

    async def add_socket(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.websockets.setdefault(session_id, set()).add(websocket)
        await websocket.send_json({"type": "state_snapshot", "state": self.get(session_id).state.model_dump(mode="json")})

    def remove_socket(self, session_id: str, websocket: WebSocket) -> None:
        sockets = self.websockets.get(session_id)
        if sockets and websocket in sockets:
            sockets.remove(websocket)

    async def broadcast(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        sockets = list(self.websockets.get(session_id, set()))
        dead: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json({"type": event_type, **payload})
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.remove_socket(session_id, websocket)

    async def join_mobile(self, session_id: str, token: str, device: DeviceInfo) -> SessionState:
        record = self.validate_token(session_id, token)
        record.state.status = "mobile_connected"
        record.state.device = device
        record.state.guidance = Guidance(message="手机已连接，请授权摄像头。", needed_action="grant_camera")
        await self.broadcast(session_id, "mobile_connected", {"state": record.state.model_dump(mode="json")})
        return record.state

    async def capture_event(self, session_id: str, event: CaptureEvent) -> SessionState:
        record = self.validate_token(session_id, event.token)
        if event.event == "camera_permission_granted":
            record.state.status = "camera_ready"
            record.state.guidance = Guidance(message="摄像头已授权，请开始连续推流。", needed_action="start_stream")
        elif event.event == "stream_started":
            record.state.status = "streaming"
            record.state.guidance = Guidance(message="正在接收手机视频帧，请缓慢移动手机，系统会持续修正主体克重。", needed_action="scan_plate")
        elif event.event == "stream_stopped":
            record.state.status = "mobile_connected"
            record.state.guidance = Guidance(message="采集已暂停，可重新开始推流。", needed_action="start_stream")
        elif event.event == "camera_permission_denied":
            record.state.status = "error"
            record.state.guidance = Guidance(message="摄像头权限被拒绝，请在浏览器设置中允许摄像头。", needed_action="grant_camera")
        else:
            record.state.status = "error"
            record.state.guidance = Guidance(message=str(event.payload.get("message", "采集端发生错误。")), needed_action="check_mobile")
        await self.broadcast(session_id, event.event, {"state": record.state.model_dump(mode="json")})
        return record.state

    async def process_frame(self, session_id: str, upload: FrameUpload) -> SessionState:
        record = self.validate_token(session_id, upload.token)
        decoded = self.analyzer.decode_data_url(upload.image)
        record.latest_frame_bytes = decoded.jpg_bytes
        record.state.frame_count += 1
        record.state.status = "measuring"
        record.state.elapsed_seconds = round(time.monotonic() - record.created_monotonic, 1)
        record.state.latest_frame_url = f"/api/sessions/{session_id}/latest-frame?t={record.state.frame_count}"
        record.state.video = VideoInfo(
            fps=self._estimate_fps(record.state.frame_count, record.state.elapsed_seconds),
            resolution=f"{decoded.width}x{decoded.height}",
            quality="good",
            last_frame_at=datetime.now(CHINA_TZ).isoformat(),
        )

        # Keep only the newest pending frame while the analyzer is busy. The
        # dashboard still receives every camera frame immediately.
        record.pending_frame = (decoded, record.state.frame_count, record.state.elapsed_seconds)
        await self.broadcast(session_id, "frame_received", {"state": record.state.model_dump(mode="json")})
        if not record.analysis_lock.locked():
            asyncio.create_task(self._drain_analysis(session_id))
        return record.state

    async def _drain_analysis(self, session_id: str) -> None:
        try:
            record = self.get(session_id)
        except KeyError:
            return
        async with record.analysis_lock:
            while record.pending_frame is not None:
                decoded, frame_count, elapsed_seconds = record.pending_frame
                record.pending_frame = None
                await self._analyze_and_update(session_id, record, decoded, frame_count, elapsed_seconds)

    async def _analyze_and_update(
        self,
        session_id: str,
        record: SessionRecord,
        decoded: DecodedFrame,
        frame_count: int,
        elapsed_seconds: float,
    ) -> None:
        try:
            foods, quality, guidance = await asyncio.to_thread(self.analyzer.analyze, decoded, frame_count, elapsed_seconds)
        except Exception as exc:
            record.state.guidance = Guidance(message=f"当前帧分析失败：{exc}", needed_action="continue_scan")
            await self.broadcast(session_id, "frame_analyzed", {"state": record.state.model_dump(mode="json")})
            return

        record.state.analyzer = self.analyzer.backend_name
        record.state.model_name = self.analyzer.model_name
        record.state.analyzed_frame_count += 1
        record.state.foods = self._merge_tracks(record, foods, elapsed_seconds)
        record.state.measurement_quality = self._merge_quality(quality, record.state.foods)
        if record.state.foods:
            guidance = self._temporal_guidance(record.state.foods, guidance)
        record.state.guidance = Guidance(message=guidance, needed_action=self._guidance_action(guidance))
        await self.broadcast(session_id, "frame_analyzed", {"state": record.state.model_dump(mode="json")})

    def _merge_tracks(self, record: SessionRecord, detections: list[FoodTrack], elapsed_seconds: float) -> list[FoodTrack]:
        matched_track_ids: set[str] = set()
        for detection in detections:
            best_id = self._best_match(record.track_memory, detection, matched_track_ids)
            if best_id is None:
                best_id = f"food_{record.next_track_index}"
                record.next_track_index += 1
                detection.track_id = best_id
                detection.first_seen_seconds = round(elapsed_seconds, 1)
                detection.last_seen_seconds = round(elapsed_seconds, 1)
                detection.visible_frames = 1
                detection.sample_count = 1
                detection.stable_seconds = 0
                detection.convergence = self._convergence(detection.visible_frames, detection.stable_seconds)
                aggregate = TrackAggregate(
                    track_id=best_id,
                    track=detection,
                    first_seen_seconds=elapsed_seconds,
                    last_seen_seconds=elapsed_seconds,
                )
                self._prime_scale_memory(aggregate, detection)
                record.track_memory[best_id] = aggregate
            else:
                aggregate = record.track_memory[best_id]
                aggregate.track = self._smooth_track(aggregate.track, detection, aggregate, elapsed_seconds)
                aggregate.visible_frames += 1
                aggregate.missed_frames = 0
                aggregate.last_seen_seconds = elapsed_seconds
            matched_track_ids.add(best_id)

        for track_id, aggregate in list(record.track_memory.items()):
            if track_id not in matched_track_ids:
                aggregate.missed_frames += 1
                if aggregate.missed_frames > 10:
                    del record.track_memory[track_id]
                    continue
                aggregate.track.state = "lost"
                aggregate.track.confidence = round(max(0.12, aggregate.track.confidence * 0.92), 2)
                aggregate.track.weight_confidence = round(max(0.12, aggregate.track.weight_confidence * 0.92), 2)

        tracks = [aggregate.track for aggregate in record.track_memory.values() if aggregate.missed_frames <= 6]
        tracks = self._filter_subject_tracks(tracks)
        tracks.sort(key=lambda item: (item.state != "tracking", -item.weight_confidence, -item.estimated_weight_g, item.track_id))
        return tracks[:4]

    def _smooth_track(
        self,
        previous: FoodTrack,
        detection: FoodTrack,
        aggregate: TrackAggregate,
        elapsed_seconds: float,
    ) -> FoodTrack:
        alpha = 0.74 if aggregate.visible_frames >= 4 else 0.62
        stable_seconds = max(0.0, elapsed_seconds - aggregate.first_seen_seconds)
        sample_count = aggregate.visible_frames + 1
        scale_result = self._scale_adjusted_measurement(previous, detection, aggregate)
        smoothed_weight = self._ema(previous.estimated_weight_g, scale_result["weight_g"], scale_result["alpha"])
        smoothed_volume = self._ema(previous.volume_ml, scale_result["volume_ml"], scale_result["alpha"])
        smoothed_confidence = min(
            0.96,
            self._ema(previous.weight_confidence, detection.weight_confidence, 0.7)
            + min(0.14, math.log1p(max(scale_result["accepted_count"], sample_count)) * 0.035),
        )
        base_error = self._ema(previous.weight_error_g, detection.weight_error_g, 0.62)
        error_floor = max(3.5, smoothed_weight * (0.075 if scale_result["accepted_count"] >= 4 else 0.11))
        temporal_error = max(
            error_floor,
            base_error / math.sqrt(min(max(scale_result["accepted_count"], 1), 18)) + smoothed_weight * scale_result["error_ratio"],
        )
        bbox = [round(self._ema(a, b, alpha)) for a, b in zip(previous.bbox, detection.bbox)]

        profile = profile_for_key(self._stable_profile_key(previous, detection, scale_result))
        cooking_method = self._stable_cooking_method(previous, detection)
        cooking = cooking_method_for_key(cooking_method)
        updated = detection.model_copy(deep=True)
        updated.track_id = aggregate.track_id
        updated.name = _display_name_for_track(profile.key, profile.display_name, cooking_method, cooking.display_name)
        updated.category = profile.category
        updated.profile_key = profile.key
        updated.cooking_method = cooking_method
        updated.cooking_method_name = cooking.display_name
        updated.cooking_confidence = round(max(previous.cooking_confidence * 0.92, detection.cooking_confidence), 2)
        updated.raw_weight_g = round(detection.raw_weight_g or detection.estimated_weight_g, 1)
        updated.area_ratio = round(detection.area_ratio, 4)
        updated.bbox_area_ratio = round(detection.bbox_area_ratio, 4)
        updated.scale_view_quality = round(detection.scale_view_quality, 2)
        updated.scale_corrected = bool(scale_result["corrected"])
        updated.scale_confidence = round(scale_result["confidence"], 2)
        updated.scale_sample_count = scale_result["accepted_count"]
        updated.scale_status = str(scale_result["status"])
        updated.state = "tracking"
        updated.bbox = [int(v) for v in bbox]
        updated.polygon = detection.polygon or previous.polygon
        updated.mask_svg_path = detection.mask_svg_path or previous.mask_svg_path
        updated.confidence = round(max(previous.confidence * 0.96, detection.confidence), 2)
        updated.volume_ml = round(smoothed_volume, 1)
        updated.volume_confidence = round(min(0.94, self._ema(previous.volume_confidence, detection.volume_confidence, 0.72) + min(0.10, math.log1p(sample_count) * 0.025)), 2)
        updated.density_g_per_ml = profile.density_g_per_ml
        updated.estimated_weight_g = round(smoothed_weight, 1)
        updated.weight_error_g = round(temporal_error, 1)
        updated.weight_confidence = round(max(0.12, min(smoothed_confidence, scale_result["confidence"] * 0.68 + smoothed_confidence * 0.32)), 2)
        updated.visible_frames = sample_count
        updated.sample_count = sample_count
        updated.stable_seconds = round(stable_seconds, 1)
        updated.convergence = self._convergence(sample_count, stable_seconds)
        updated.first_seen_seconds = round(aggregate.first_seen_seconds, 1)
        updated.last_seen_seconds = round(elapsed_seconds, 1)
        updated.nutrition = nutrition_for_weight(profile, updated.estimated_weight_g, cooking_method)
        return updated

    def _prime_scale_memory(self, aggregate: TrackAggregate, detection: FoodTrack) -> None:
        raw_weight = detection.raw_weight_g or detection.estimated_weight_g
        aggregate.raw_weight_samples.append(raw_weight)
        if self._scale_sample_is_usable(aggregate, detection, allow_rebase=True):
            self._remember_scale_sample(aggregate, detection)
            detection.scale_sample_count = len(aggregate.accepted_weight_samples)
            detection.scale_confidence = self._scale_confidence(aggregate, detection)
            detection.scale_status = "calibrating"
        else:
            detection.scale_status = "needs_reference"
            detection.scale_confidence = 0.12

    def _scale_adjusted_measurement(
        self,
        previous: FoodTrack,
        detection: FoodTrack,
        aggregate: TrackAggregate,
    ) -> dict[str, float | int | bool | str]:
        raw_weight = detection.raw_weight_g or detection.estimated_weight_g
        detection.raw_weight_g = round(raw_weight, 1)
        aggregate.raw_weight_samples.append(raw_weight)
        del aggregate.raw_weight_samples[:-80]

        accepted = self._scale_sample_is_usable(aggregate, detection, allow_rebase=False)
        if accepted:
            self._remember_scale_sample(aggregate, detection)
        else:
            aggregate.scale_correction_events += 1

        accepted_count = len(aggregate.accepted_weight_samples)
        reference_weight = aggregate.reference_weight_g
        reference_area = aggregate.reference_area_ratio
        has_reference = reference_weight is not None and accepted_count > 0
        corrected = not accepted and has_reference

        if accepted and reference_weight is not None:
            target_weight = reference_weight
            status = "stable" if accepted_count >= 4 else "calibrating"
            alpha = 0.68 if accepted_count >= 4 else 0.58
            error_ratio = 0.032 if accepted_count >= 6 else 0.045
        elif has_reference:
            target_weight = reference_weight
            status = self._scale_status_from_geometry(detection, reference_area)
            alpha = 0.88
            error_ratio = 0.065
        else:
            target_weight = raw_weight
            status = "needs_reference"
            alpha = 0.82
            error_ratio = 0.12

        profile = profile_for_key(detection.profile_key or previous.profile_key)
        target_volume = target_weight / max(profile.density_g_per_ml, 0.1)
        confidence = self._scale_confidence(aggregate, detection)
        if corrected:
            confidence = max(0.16, confidence - 0.08)
        if not has_reference:
            confidence = min(confidence, 0.24)

        return {
            "weight_g": round(target_weight, 1),
            "volume_ml": round(target_volume, 1),
            "alpha": alpha,
            "confidence": round(confidence, 2),
            "accepted_count": accepted_count,
            "corrected": corrected,
            "status": status,
            "error_ratio": error_ratio,
        }

    def _scale_sample_is_usable(self, aggregate: TrackAggregate, detection: FoodTrack, allow_rebase: bool) -> bool:
        raw_weight = detection.raw_weight_g or detection.estimated_weight_g
        if raw_weight <= 4:
            return False
        area_ratio = detection.area_ratio or self._bbox_area_ratio(detection.bbox)
        bbox_ratio = detection.bbox_area_ratio or self._bbox_area_ratio(detection.bbox)
        view_quality = detection.scale_view_quality or 0
        if bbox_ratio > 0.58 or area_ratio > 0.34:
            return False
        if bbox_ratio < 0.018 and area_ratio < 0.009:
            return False
        if view_quality < 0.34:
            return False

        reference_area = aggregate.reference_area_ratio
        if reference_area is None:
            return view_quality >= 0.42 and 0.025 <= area_ratio <= 0.21 and bbox_ratio <= 0.42

        ratio = area_ratio / max(reference_area, 0.0001)
        within_reference = 0.76 <= ratio <= 1.26
        if within_reference:
            return True

        previous_quality = aggregate.accepted_view_qualities[-1] if aggregate.accepted_view_qualities else 0
        better_standard_view = allow_rebase or (view_quality >= max(0.62, previous_quality + 0.16) and bbox_ratio <= 0.34 and area_ratio <= 0.22)
        return better_standard_view

    def _remember_scale_sample(self, aggregate: TrackAggregate, detection: FoodTrack) -> None:
        raw_weight = detection.raw_weight_g or detection.estimated_weight_g
        area_ratio = detection.area_ratio or self._bbox_area_ratio(detection.bbox)
        aggregate.accepted_weight_samples.append(raw_weight)
        aggregate.accepted_area_ratios.append(area_ratio)
        aggregate.accepted_view_qualities.append(detection.scale_view_quality or 0.42)
        del aggregate.accepted_weight_samples[:-40]
        del aggregate.accepted_area_ratios[:-40]
        del aggregate.accepted_view_qualities[:-40]
        aggregate.reference_weight_g = round(self._trimmed_median(aggregate.accepted_weight_samples), 1)
        aggregate.reference_area_ratio = round(self._trimmed_median(aggregate.accepted_area_ratios), 5)

    def _scale_confidence(self, aggregate: TrackAggregate, detection: FoodTrack) -> float:
        accepted_count = len(aggregate.accepted_weight_samples)
        if accepted_count == 0:
            return 0.12
        avg_quality = sum(aggregate.accepted_view_qualities[-12:]) / min(len(aggregate.accepted_view_qualities), 12)
        current_quality = detection.scale_view_quality or 0
        sample_score = min(0.46, math.log1p(accepted_count) * 0.14)
        quality_score = max(avg_quality, current_quality * 0.75) * 0.38
        stability_penalty = min(0.16, aggregate.scale_correction_events * 0.012)
        return max(0.18, min(0.92, 0.12 + sample_score + quality_score - stability_penalty))

    @staticmethod
    def _scale_status_from_geometry(detection: FoodTrack, reference_area: float | None) -> str:
        area_ratio = detection.area_ratio or 0
        bbox_ratio = detection.bbox_area_ratio or 0
        relative_area = area_ratio / max(reference_area or area_ratio or 1, 0.0001)
        if bbox_ratio > 0.48 or area_ratio > 0.26 or relative_area > 1.26:
            return "too_close"
        if reference_area and relative_area < 0.76:
            return "too_far"
        return "corrected"

    @staticmethod
    def _trimmed_median(values: list[float]) -> float:
        if not values:
            return 0
        ordered = sorted(values)
        if len(ordered) >= 8:
            trim = max(1, len(ordered) // 6)
            ordered = ordered[trim:-trim]
        return float(statistics.median(ordered))

    @staticmethod
    def _stable_cooking_method(previous: FoodTrack, detection: FoodTrack) -> str:
        if detection.category in DESSERT_SNACK_CATEGORIES:
            return detection.cooking_method
        if detection.cooking_confidence >= 0.52:
            return detection.cooking_method
        if previous.cooking_confidence >= 0.45:
            return previous.cooking_method
        return detection.cooking_method or previous.cooking_method or "unknown"

    @staticmethod
    def _stable_profile_key(previous: FoodTrack, detection: FoodTrack, scale_result: dict[str, float | int | bool | str]) -> str:
        if previous.profile_key == detection.profile_key:
            return detection.profile_key
        previous_likely_chicken_bias = (
            previous.profile_key == "chicken"
            and previous.sample_count <= 5
            and previous.confidence < 0.64
            and detection.profile_key
            and detection.profile_key != "chicken"
        )
        if previous_likely_chicken_bias:
            return detection.profile_key
        if detection.profile_key == "unknown_food" and previous.sample_count < 4 and previous.confidence < 0.58:
            return detection.profile_key
        if detection.category in DESSERT_SNACK_CATEGORIES or previous.category in DESSERT_SNACK_CATEGORIES:
            return detection.profile_key or previous.profile_key
        if previous.profile_key == "unknown_food" and detection.confidence >= previous.confidence * 0.9:
            return detection.profile_key or previous.profile_key
        if scale_result["corrected"] and previous.sample_count >= 3:
            return previous.profile_key
        if previous.convergence >= 0.34 and previous.confidence >= detection.confidence * 0.88:
            return previous.profile_key
        return detection.profile_key or previous.profile_key

    @staticmethod
    def _filter_subject_tracks(tracks: list[FoodTrack]) -> list[FoodTrack]:
        if not tracks:
            return []
        active = [track for track in tracks if track.state == "tracking"]
        reference = active or tracks
        max_weight = max(track.estimated_weight_g for track in reference) if reference else 0
        primary_by_profile: dict[str, FoodTrack] = {}
        for track in sorted(reference, key=lambda item: item.estimated_weight_g, reverse=True):
            primary_by_profile.setdefault(track.profile_key, track)
        filtered: list[FoodTrack] = []
        for track in tracks:
            relative_weight = track.estimated_weight_g / max(max_weight, 1)
            stable_enough = track.sample_count >= 3 or track.stable_seconds >= 1.2
            meaningful_size = track.estimated_weight_g >= max(12, max_weight * 0.16)
            primary = primary_by_profile.get(track.profile_key)
            likely_same_food_fragment = (
                primary is not None
                and primary.track_id != track.track_id
                and primary.sample_count >= 5
                and track.estimated_weight_g < primary.estimated_weight_g * 0.36
                and track.scale_sample_count < 6
            )
            if likely_same_food_fragment:
                continue
            if track.state == "lost" and (track.sample_count < 8 or relative_weight < 0.28):
                continue
            if not stable_enough and relative_weight < 0.5:
                continue
            if meaningful_size or track.cooking_method == "deep_fried":
                filtered.append(track)
        return filtered[:4]

    @staticmethod
    def _best_match(memory: dict[str, TrackAggregate], detection: FoodTrack, already_matched: set[str]) -> str | None:
        best_id: str | None = None
        best_score = 0.0
        for track_id, aggregate in memory.items():
            if track_id in already_matched:
                continue
            current = aggregate.track
            same_profile = current.profile_key == detection.profile_key
            same_category = current.category == detection.category
            category_shift = current.category != detection.category
            iou = SessionStore._bbox_iou(current.bbox, detection.bbox)
            proximity = SessionStore._center_proximity(current.bbox, detection.bbox)
            area_ratio = SessionStore._bbox_scale_ratio(current.bbox, detection.bbox)
            scale_compatible = 0.20 <= area_ratio <= 5.0
            score = iou * 0.46 + proximity * 0.34 + (0.15 if same_profile else 0.07 if same_category else 0) + (0.05 if scale_compatible else 0)
            if category_shift and (current.category in DESSERT_SNACK_CATEGORIES or detection.category in DESSERT_SNACK_CATEGORIES):
                score -= 0.18
            if score > best_score:
                best_id = track_id
                best_score = score
        return best_id if best_score >= 0.25 else None

    @staticmethod
    def _bbox_iou(a: list[int], b: list[int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        intersection = iw * ih
        union = max(1, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
        return intersection / union

    @staticmethod
    def _bbox_scale_ratio(a: list[int], b: list[int]) -> float:
        a_area = max(1, (a[2] - a[0]) * (a[3] - a[1]))
        b_area = max(1, (b[2] - b[0]) * (b[3] - b[1]))
        return b_area / a_area

    @staticmethod
    def _bbox_area_ratio(_bbox: list[int]) -> float:
        return 0.0

    @staticmethod
    def _center_proximity(a: list[int], b: list[int]) -> float:
        ax = (a[0] + a[2]) / 2
        ay = (a[1] + a[3]) / 2
        bx = (b[0] + b[2]) / 2
        by = (b[1] + b[3]) / 2
        scale = max(1, max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]))
        return max(0.0, 1.0 - math.hypot(ax - bx, ay - by) / (scale * 1.8))

    @staticmethod
    def _ema(previous: float, current: float, alpha: float) -> float:
        return previous * alpha + current * (1 - alpha)

    @staticmethod
    def _convergence(sample_count: int, stable_seconds: float) -> float:
        sample_score = min(1.0, sample_count / 18)
        time_score = min(1.0, stable_seconds / 14)
        return round(sample_score * 0.62 + time_score * 0.38, 2)

    @staticmethod
    def _merge_quality(quality: MeasurementQuality, foods: list[FoodTrack]) -> MeasurementQuality:
        if not foods:
            return quality
        convergence = sum(food.convergence for food in foods) / len(foods)
        confidence = sum(food.weight_confidence for food in foods) / len(foods)
        quality.mask_stability = round(max(quality.mask_stability, min(0.96, convergence * 0.9 + 0.08)), 2)
        quality.motion_quality = round(max(quality.motion_quality, min(0.93, 0.42 + convergence * 0.48)), 2)
        quality.overall = round(min(0.96, (quality.overall * 0.72 + convergence * 0.18 + confidence * 0.10)), 2)
        return quality

    @staticmethod
    def _temporal_guidance(foods: list[FoodTrack], fallback: str) -> str:
        avg_convergence = sum(food.convergence for food in foods) / len(foods)
        avg_error_ratio = sum(food.weight_error_g / max(food.estimated_weight_g, 1) for food in foods) / len(foods)
        scale_corrected = [food for food in foods if food.scale_corrected]
        if scale_corrected:
            if any(food.scale_status == "too_close" for food in scale_corrected):
                return "检测到镜头距离过近，当前克重已使用历史尺度基准校正；请稍微后退并保持主体完整入镜。"
            if any(food.scale_status == "too_far" for food in scale_corrected):
                return "检测到主体占画面过小，当前克重已使用历史尺度基准校正；请让食物保持在画面中间并缓慢移动。"
            return "检测到视角尺度变化，当前克重已使用历史稳定帧校正；继续采集可进一步降低误差。"
        methods = [food.cooking_method_name for food in foods if food.cooking_method not in {"unknown", "raw_light"}]
        method_tip = f"，已识别烹饪方式：{'、'.join(sorted(set(methods)))}" if methods else ""
        if avg_convergence < 0.28:
            return f"已识别食物主体{method_tip}，正在积累视频帧；请保持连续推流，缓慢绕餐盘移动 5-10 秒。"
        if avg_error_ratio > 0.28:
            return f"主体重量误差仍偏大{method_tip}，请继续采集不同角度，系统会用多帧结果继续收敛。"
        if avg_convergence >= 0.72:
            return f"主体结果已较稳定{method_tip}，可继续采集以微调，或生成报告。"
        return fallback

    async def finish(self, session_id: str) -> Report:
        record = self.get(session_id)
        record.state.status = "completed"
        totals = self._totals(record.state.foods)
        report = Report(
            report_id=f"report_{session_id.split('_')[-1]}",
            session_id=session_id,
            created_at=datetime.now(CHINA_TZ),
            meal_summary=totals,
            foods=[
                {
                    "track_id": food.track_id,
                    "name": food.name,
                    "category": food.category,
                    "profile_key": food.profile_key,
                    "item_type": "food",
                    "cooking_method": food.cooking_method,
                    "cooking_method_name": food.cooking_method_name,
                    "cooking_confidence": food.cooking_confidence,
                    "bbox": food.bbox,
                    "polygon": food.polygon,
                    "mask_svg_path": food.mask_svg_path,
                    "weight_g": food.estimated_weight_g,
                    "weight_error_g": food.weight_error_g,
                    "volume_ml": food.volume_ml,
                    "calories_kcal": food.nutrition.calories_kcal,
                    "protein_g": food.nutrition.protein_g,
                    "carbs_g": food.nutrition.carbs_g,
                    "fat_g": food.nutrition.fat_g,
                    "confidence": food.weight_confidence,
                    "sample_count": food.sample_count,
                    "stable_seconds": food.stable_seconds,
                    "convergence": food.convergence,
                }
                for food in record.state.foods
            ],
            scan_quality=record.state.measurement_quality.model_dump(),
            warnings=self._warnings(record.state),
        )
        record.report = report
        await self.broadcast(session_id, "measurement_completed", {"state": record.state.model_dump(mode="json"), "report": report.model_dump(mode="json")})
        return report

    def report(self, report_id: str) -> Report:
        for record in self.sessions.values():
            if record.report and record.report.report_id == report_id:
                return record.report
        raise KeyError(report_id)

    @staticmethod
    def _estimate_fps(frame_count: int, elapsed_seconds: float) -> float:
        if elapsed_seconds <= 0:
            return 0
        return round(min(12, frame_count / elapsed_seconds), 1)

    @staticmethod
    def _guidance_action(message: str) -> str:
        if "光照" in message:
            return "improve_lighting"
        if "靠近" in message:
            return "move_closer"
        if "角度" in message:
            return "change_angle"
        if "连续" in message or "积累" in message:
            return "continue_scan"
        if "稳定" in message:
            return "hold_still"
        return "continue_scan"

    @staticmethod
    def _totals(foods: list[Any]) -> dict[str, float]:
        confidence = sum(food.weight_confidence for food in foods) / len(foods) if foods else 0
        convergence = sum(food.convergence for food in foods) / len(foods) if foods else 0
        return {
            "total_weight_g": round(sum(food.estimated_weight_g for food in foods), 1),
            "total_weight_error_g": round(math.sqrt(sum(food.weight_error_g**2 for food in foods)), 1) if foods else 0,
            "total_calories_kcal": round(sum(food.nutrition.calories_kcal for food in foods), 1),
            "total_protein_g": round(sum(food.nutrition.protein_g for food in foods), 1),
            "total_carbs_g": round(sum(food.nutrition.carbs_g for food in foods), 1),
            "total_fat_g": round(sum(food.nutrition.fat_g for food in foods), 1),
            "overall_confidence": round(confidence, 2),
            "convergence": round(convergence, 2),
        }

    @staticmethod
    def _warnings(state: SessionState) -> list[str]:
        warnings: list[str] = []
        if state.analyzer == "opencv-fallback":
            warnings.append("当前使用 OpenCV fallback 算法；下载并配置 YOLOv11 食物分割模型后可启用模型推理。")
        if state.measurement_quality.depth_completeness < 0.62:
            warnings.append("深度完整度不足，体积和克重误差可能偏高。")
        if state.measurement_quality.angle_coverage < 0.6:
            warnings.append("视角覆盖不足，请补充侧面视角以提高估重稳定性。")
        if state.foods and sum(food.convergence for food in state.foods) / len(state.foods) < 0.5:
            warnings.append("采集时间较短，建议继续推流 5-10 秒让主体结果收敛。")
        if not warnings:
            warnings.append("第一版估重仅用于产品验证，不能替代精密称重。")
        return warnings
