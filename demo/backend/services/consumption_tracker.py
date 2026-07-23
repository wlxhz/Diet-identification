from __future__ import annotations

from backend.models.schemas import FoodTrack, IntakeEvent
from backend.services.nutrition import profile_for_key
from backend.services.utensil_tracker import UtensilObservation
from backend.services.volume_estimator import estimate_bite_weight
from backend.services.calibration import ScaleMetadata


class ConsumptionTracker:
    def __init__(self) -> None:
        self.next_event_index = 1

    def build_events(
        self,
        *,
        timestamp_ms: int,
        foods: list[FoodTrack],
        utensils: list[UtensilObservation],
        scale: ScaleMetadata | None,
    ) -> list[IntakeEvent]:
        events: list[IntakeEvent] = []
        food_by_id = {food.track_id: food for food in foods}
        for utensil in utensils:
            if not utensil.contact_food_track_id:
                continue
            source = food_by_id.get(utensil.contact_food_track_id)
            if source is None:
                continue
            carried_area = max(0, utensil.carried_food_area_px)
            if carried_area <= 0:
                continue
            profile = profile_for_key(source.profile_key)
            bite = estimate_bite_weight(
                carried_food_area_px=carried_area,
                profile=profile,
                utensil_type=utensil.utensil_type,
                scale=scale,
                confidence=min(source.confidence, utensil.confidence),
            )
            event_state = "utensil_contact_food"
            intake_confidence = round(min(0.48, utensil.confidence * 0.46 + source.confidence * 0.24), 2)
            event_id = f"intake_{self.next_event_index:04d}"
            self.next_event_index += 1
            events.append(
                IntakeEvent(
                    event_id=event_id,
                    state=event_state,
                    utensil_type=utensil.utensil_type,
                    source_track_id=source.track_id,
                    source_profile_key=source.profile_key,
                    source_confidence=round(min(0.82, source.confidence * 0.62 + utensil.confidence * 0.24), 2),
                    estimated_bite_weight_g=bite.weight_g,
                    bite_weight_error_g=bite.weight_error_g,
                    bite_area_cm2=bite.area_cm2,
                    bite_volume_ml=bite.volume_ml,
                    weight_source=bite.weight_source,
                    reference_detected=bool(scale and scale.usable),
                    scale_confidence=round(scale.confidence, 2) if scale else 0,
                    trajectory_confidence=round(utensil.confidence * 0.45, 2),
                    intake_confidence=intake_confidence,
                    started_at_ms=timestamp_ms,
                )
            )
        return events


def summarize_confirmed_intake(events: list[IntakeEvent], track_id: str) -> tuple[float, int]:
    confirmed = [event for event in events if event.source_track_id == track_id and event.state == "intake_confirmed"]
    return round(sum(event.estimated_bite_weight_g for event in confirmed), 1), len(confirmed)
