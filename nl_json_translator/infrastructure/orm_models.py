from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nl_json_translator.domain.enums import LocationType

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
