from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nl_json_translator.domain.enums import (
    LocationType,
    OrderPriority,
    OrderStatus,
    MissionStatus,
    MissionStepStatus,
    MissionStepType,
    VehicleStatus,
)

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MapNodeRecord(Base):
    __tablename__ = "map_nodes"
    __table_args__ = (UniqueConstraint("x", "y", name="uq_map_nodes_coordinates"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    x: Mapped[int] = mapped_column(Integer, nullable=False)
    y: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    locations: Mapped[list["LocationRecord"]] = relationship(back_populates="map_node")


class MapEdgeRecord(Base):
    __tablename__ = "map_edges"
    __table_args__ = (
        UniqueConstraint("from_node_id", "to_node_id", name="uq_map_edges_direction"),
    )

    id: Mapped[str] = mapped_column(String(220), primary_key=True)
    from_node_id: Mapped[str] = mapped_column(
        ForeignKey("map_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_node_id: Mapped[str] = mapped_column(
        ForeignKey("map_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distance: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    travel_time: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    from_node: Mapped[MapNodeRecord] = relationship(foreign_keys=[from_node_id])
    to_node: Mapped[MapNodeRecord] = relationship(foreign_keys=[to_node_id])


class LocationRecord(Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    location_type: Mapped[str] = mapped_column(String(30), nullable=False, default=LocationType.BOTH.value)
    map_node_id: Mapped[str] = mapped_column(
        ForeignKey("map_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    map_node: Mapped[MapNodeRecord] = relationship(back_populates="locations")
    aliases: Mapped[list["LocationAliasRecord"]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )


class LocationAliasRecord(Base):
    __tablename__ = "location_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    location_id: Mapped[str] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    location: Mapped[LocationRecord] = relationship(back_populates="aliases")


class VehicleRecord(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("capacity_weight >= 0", name="ck_vehicles_capacity_weight"),
        CheckConstraint("capacity_volume >= 0", name="ck_vehicles_capacity_volume"),
        CheckConstraint("battery_level >= 0 AND battery_level <= 100", name="ck_vehicles_battery"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    current_node_id: Mapped[str] = mapped_column(
        ForeignKey("map_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    heading: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=VehicleStatus.IDLE.value)
    capacity_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    capacity_volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    battery_level: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    telemetry_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    current_node: Mapped[MapNodeRecord] = relationship(foreign_keys=[current_node_id])


class TransportOrderRecord(Base):
    __tablename__ = "transport_orders"
    __table_args__ = (
        CheckConstraint(
            "pickup_location_id IS NULL OR dropoff_location_id IS NULL "
            "OR pickup_location_id <> dropoff_location_id",
            name="ck_transport_orders_distinct_locations",
        ),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    pickup_location_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    dropoff_location_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    pickup_location_text: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    dropoff_location_text: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cargo_json: Mapped[dict[str, Any]] = mapped_column("cargo", JSON, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default=OrderPriority.NORMAL.value)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=OrderStatus.CREATED.value)
    requested_vehicle_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    earliest_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    pickup_location: Mapped[Optional[LocationRecord]] = relationship(
        foreign_keys=[pickup_location_id]
    )
    dropoff_location: Mapped[Optional[LocationRecord]] = relationship(
        foreign_keys=[dropoff_location_id]
    )
    requested_vehicle: Mapped[Optional[VehicleRecord]] = relationship(
        foreign_keys=[requested_vehicle_id]
    )


class MissionRecord(Base):
    __tablename__ = "missions"
    __table_args__ = (
        Index(
            "uq_missions_active_order",
            "order_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
        Index(
            "uq_missions_active_vehicle",
            "vehicle_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        ForeignKey("transport_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MissionStatus.CREATED.value
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    order: Mapped[TransportOrderRecord] = relationship(foreign_keys=[order_id])
    vehicle: Mapped[VehicleRecord] = relationship(foreign_keys=[vehicle_id])
    steps: Mapped[list["MissionStepRecord"]] = relationship(
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="MissionStepRecord.sequence_no",
    )


class MissionStepRecord(Base):
    __tablename__ = "mission_steps"
    __table_args__ = (
        UniqueConstraint("mission_id", "sequence_no", name="uq_mission_steps_sequence"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MissionStepType.WAIT.value
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=MissionStepStatus.PENDING.value
    )
    start_node_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("map_nodes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    end_node_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("map_nodes.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    details_json: Mapped[dict[str, Any]] = mapped_column(
        "details", JSON, nullable=False, default=dict
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    mission: Mapped[MissionRecord] = relationship(back_populates="steps")
    start_node: Mapped[Optional[MapNodeRecord]] = relationship(foreign_keys=[start_node_id])
    end_node: Mapped[Optional[MapNodeRecord]] = relationship(foreign_keys=[end_node_id])


class AgentEventRecord(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    order_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("transport_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mission_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("missions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        "payload", JSON, nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )

    order: Mapped[Optional[TransportOrderRecord]] = relationship(foreign_keys=[order_id])
    mission: Mapped[Optional[MissionRecord]] = relationship(foreign_keys=[mission_id])
    vehicle: Mapped[Optional[VehicleRecord]] = relationship(foreign_keys=[vehicle_id])


class TransportBatchRecord(Base):
    __tablename__ = "transport_batches"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    natural_language: Mapped[Optional[str]] = mapped_column(String(4000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    constraints_json: Mapped[dict[str, Any]] = mapped_column(
        "constraints", JSON, nullable=False, default=dict
    )
    provider_response_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    provider_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    provider_usage_json: Mapped[dict[str, Any]] = mapped_column(
        "provider_usage", JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AgentCommandRecord(Base):
    __tablename__ = "agent_commands"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    target_agent_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=True, index=True
    )
    mission_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        "payload", JSON, nullable=False, default=dict
    )
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class VehicleAgentStateRecord(Base):
    __tablename__ = "vehicle_agent_states"

    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    active_command_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("agent_commands.id", ondelete="SET NULL"), nullable=True
    )
    active_mission_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("missions.id", ondelete="SET NULL"), nullable=True
    )
    execution_cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    carrying_cargo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class RouteReservationRecord(Base):
    __tablename__ = "route_reservations"
    __table_args__ = (
        UniqueConstraint(
            "mission_id",
            "resource_type",
            "resource_id",
            "time_slot",
            "route_version",
            name="uq_route_reservation_mission_resource_slot",
        ),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    time_slot: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
