from __future__ import annotations

from enum import Enum


class StringEnum(str, Enum):
    """String-backed enum that serializes cleanly in JSON and database rows."""


class LocationType(StringEnum):
    PICKUP = "pickup"
    DROPOFF = "dropoff"
    BOTH = "both"
    CHARGING = "charging"


class OrderPriority(StringEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class OrderStatus(StringEnum):
    CREATED = "CREATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    RESOLVED = "RESOLVED"
    ASSIGNED = "ASSIGNED"
    PICKING = "PICKING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class VehicleStatus(StringEnum):
    IDLE = "IDLE"
    RESERVED = "RESERVED"
    TO_PICKUP = "TO_PICKUP"
    LOADING = "LOADING"
    TO_DROPOFF = "TO_DROPOFF"
    UNLOADING = "UNLOADING"
    CHARGING = "CHARGING"
    BLOCKED = "BLOCKED"
    OFFLINE = "OFFLINE"
    FAILED = "FAILED"


class MissionStatus(StringEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class MissionStepType(StringEnum):
    REPOSITION = "REPOSITION"
    LOAD = "LOAD"
    TRANSPORT = "TRANSPORT"
    UNLOAD = "UNLOAD"
    WAIT = "WAIT"
    COMPLETE = "COMPLETE"


class MissionStepStatus(StringEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AgentEventType(StringEnum):
    ORDER_ASSIGNED = "ORDER_ASSIGNED"
    VEHICLE_RESERVED = "VEHICLE_RESERVED"
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_BLOCKED = "MISSION_BLOCKED"
    MISSION_FAILED = "MISSION_FAILED"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    VEHICLE_POSITION_UPDATED = "VEHICLE_POSITION_UPDATED"
