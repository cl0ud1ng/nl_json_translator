"""Public transport protocol validation.

Legacy movement actions are intentionally not part of this public module. They are
internal implementation details of the map/Mission executor.
"""

from __future__ import annotations

from typing import Any

from .domain.schemas import Cargo, TransportIntentDraft, TransportOrder


def validate_transport_intent(value: Any) -> dict[str, Any]:
    return TransportIntentDraft.model_validate(value).model_dump(mode="json")


def validate_transport_order(value: Any) -> dict[str, Any]:
    return TransportOrder.model_validate(value).model_dump(mode="json")


__all__ = [
    "Cargo",
    "TransportIntentDraft",
    "TransportOrder",
    "validate_transport_intent",
    "validate_transport_order",
]
