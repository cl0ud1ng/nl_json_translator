"""Public transport protocol validation.

Legacy movement actions are intentionally not part of this public module. They are
internal implementation details of the map/Mission executor.
"""

from __future__ import annotations

from typing import Any

from .domain.schemas import (
    Cargo,
    DispatchConstraints,
    TransportOrder,
    TransportOrderDraft,
    TransportRequestDraft,
)


def validate_transport_request(value: Any) -> dict[str, Any]:
    return TransportRequestDraft.model_validate(value).model_dump(mode="json")


def validate_transport_order(value: Any) -> dict[str, Any]:
    return TransportOrder.model_validate(value).model_dump(mode="json")


__all__ = [
    "Cargo",
    "DispatchConstraints",
    "TransportOrderDraft",
    "TransportRequestDraft",
    "TransportOrder",
    "validate_transport_request",
    "validate_transport_order",
]
