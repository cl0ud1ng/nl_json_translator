from __future__ import annotations

from typing import Any


DEMO_GRID_WIDTH = 20
DEMO_GRID_HEIGHT = 14

DEMO_OBSTACLE_COORDINATES = {
    *((x, 5) for x in range(4, 11)),
    *((x, 9) for x in range(8, 13)),
    *((12, y) for y in range(2, 7)),
    *((15, y) for y in range(8, 13)),
    (5, 1),
    (5, 2),
    (5, 3),
    (6, 8),
    (7, 8),
    (12, 12),
    (13, 12),
}

DEMO_LOCATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "loc_a",
        "name": "A",
        "location_type": "both",
        "coordinate": (2, 2),
        "aliases": ("A点", "point A", "一号点"),
        "metadata": {"label": "A", "color": "#dc2626"},
    },
    {
        "id": "loc_b",
        "name": "B",
        "location_type": "both",
        "coordinate": (16, 3),
        "aliases": ("B点", "point B", "二号点"),
        "metadata": {"label": "B", "color": "#2563eb"},
    },
    {
        "id": "loc_c",
        "name": "C",
        "location_type": "both",
        "coordinate": (6, 11),
        "aliases": ("C点", "point C", "三号点"),
        "metadata": {"label": "C", "color": "#7c3aed"},
    },
    {
        "id": "loc_lab",
        "name": "lab",
        "location_type": "both",
        "coordinate": (17, 11),
        "aliases": ("laboratory", "实验室"),
        "metadata": {"label": "Lab", "color": "#0891b2"},
    },
    {
        "id": "loc_charging_station",
        "name": "charging station",
        "location_type": "charging",
        "coordinate": (1, 11),
        "aliases": ("charge", "charger", "充电站", "充电桩"),
        "metadata": {"label": "Charge", "color": "#ca8a04"},
    },
)


def node_id(x: int, y: int) -> str:
    return f"node_{x}_{y}"


def edge_id(from_x: int, from_y: int, to_x: int, to_y: int) -> str:
    return f"edge_{from_x}_{from_y}__{to_x}_{to_y}"
