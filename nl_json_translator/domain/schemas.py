from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import OrderPriority


class DomainSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Cargo(DomainSchema):
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, gt=0)
    weight_kg: Optional[float] = Field(default=None, gt=0)
    volume_m3: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, min_length=1, max_length=100)
    required_capabilities: list[str] = Field(default_factory=list)


class TransportIntentDraft(DomainSchema):
    """LLM-produced draft that deliberately retains user-facing location text."""

    intent: Literal["create_transport_order"]
    cargo: Cargo
    pickup_location_text: str = Field(min_length=1, max_length=200)
    dropoff_location_text: str = Field(min_length=1, max_length=200)
    vehicle_text: Optional[str] = Field(default=None, min_length=1, max_length=200)
    priority: OrderPriority = OrderPriority.NORMAL

    @model_validator(mode="after")
    def locations_must_differ(self) -> "TransportIntentDraft":
        if self.pickup_location_text.casefold() == self.dropoff_location_text.casefold():
            raise ValueError("pickup and dropoff locations must differ")
        return self


class TransportOrder(DomainSchema):
    """Resolved transport protocol containing stable location identifiers."""

    type: Literal["transport_order"] = "transport_order"
    cargo: Cargo
    pickup_location_id: str = Field(min_length=1, max_length=100)
    dropoff_location_id: str = Field(min_length=1, max_length=100)
    requested_vehicle_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    priority: OrderPriority = OrderPriority.NORMAL
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def location_ids_must_differ(self) -> "TransportOrder":
        if self.pickup_location_id == self.dropoff_location_id:
            raise ValueError("pickup and dropoff location ids must differ")
        return self
