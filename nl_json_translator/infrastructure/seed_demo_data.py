from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from nl_json_translator.domain.location_text import normalize_location_text

from .demo_map import (
    DEMO_GRID_HEIGHT,
    DEMO_GRID_WIDTH,
    DEMO_LOCATIONS,
    DEMO_OBSTACLE_COORDINATES,
    edge_id,
    node_id,
)
from .init_db import init_database
from .orm_models import (
    LocationAliasRecord,
    LocationRecord,
    MapEdgeRecord,
    MapNodeRecord,
    VehicleRecord,
)


def seed_demo_data(database_url: Optional[str] = None) -> int:
    database = init_database(database_url)
    with database.session() as session:
        inserted = seed_map_data(session)
        inserted += seed_vehicle_data(session)
    database.dispose()
    return inserted


def seed_vehicle_data(session: Session) -> int:
    if session.get(VehicleRecord, "vehicle_demo_01"):
        return 0
    session.add(
        VehicleRecord(
            id="vehicle_demo_01",
            name="Demo Vehicle 01",
            current_node_id=node_id(2, 2),
            heading=0.0,
            status="IDLE",
            capacity_weight=500.0,
            capacity_volume=3.0,
            battery_level=100.0,
            capabilities=["standard"],
        )
    )
    return 1


def seed_map_data(session: Session) -> int:
    """Insert missing demo topology and locations without overwriting edits."""

    inserted = 0
    existing_node_ids = set(session.scalars(select(MapNodeRecord.id)))
    traversable: set[tuple[int, int]] = set()
    for y in range(DEMO_GRID_HEIGHT):
        for x in range(DEMO_GRID_WIDTH):
            if (x, y) in DEMO_OBSTACLE_COORDINATES:
                continue
            traversable.add((x, y))
            current_node_id = node_id(x, y)
            if current_node_id not in existing_node_ids:
                session.add(MapNodeRecord(id=current_node_id, x=x, y=y))
                inserted += 1
    session.flush()

    existing_edge_ids = set(session.scalars(select(MapEdgeRecord.id)))
    for from_x, from_y in sorted(traversable):
        for to_x, to_y in (
            (from_x + 1, from_y),
            (from_x - 1, from_y),
            (from_x, from_y + 1),
            (from_x, from_y - 1),
        ):
            if (to_x, to_y) not in traversable:
                continue
            current_edge_id = edge_id(from_x, from_y, to_x, to_y)
            if current_edge_id not in existing_edge_ids:
                session.add(
                    MapEdgeRecord(
                        id=current_edge_id,
                        from_node_id=node_id(from_x, from_y),
                        to_node_id=node_id(to_x, to_y),
                        distance=1.0,
                        travel_time=1.0,
                        capacity=1,
                    )
                )
                inserted += 1
    session.flush()

    existing_location_ids = set(session.scalars(select(LocationRecord.id)))
    existing_aliases = set(session.scalars(select(LocationAliasRecord.normalized_alias)))
    for definition in DEMO_LOCATIONS:
        location_id = definition["id"]
        if location_id not in existing_location_ids:
            x, y = definition["coordinate"]
            session.add(
                LocationRecord(
                    id=location_id,
                    name=definition["name"],
                    location_type=definition["location_type"],
                    map_node_id=node_id(x, y),
                    metadata_json=definition["metadata"],
                )
            )
            inserted += 1
        session.flush()
        for alias in definition["aliases"]:
            normalized_alias = normalize_location_text(alias)
            if normalized_alias not in existing_aliases:
                session.add(
                    LocationAliasRecord(
                        location_id=location_id,
                        alias=alias,
                        normalized_alias=normalized_alias,
                    )
                )
                existing_aliases.add(normalized_alias)
                inserted += 1
    return inserted


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize and seed the demo database.")
    parser.add_argument("--database-url", help="SQLAlchemy URL; defaults to NL_JSON_DATABASE_URL.")
    args = parser.parse_args(argv)
    inserted = seed_demo_data(args.database_url)
    print(f"Demo database ready; inserted {inserted} row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
