import unittest

from nl_json_translator.repositories.maps import MapData, MapEdgeData, MapNodeData
from nl_json_translator.services.cooperative_routing_service import (
    CooperativeRoutingService,
    ReservationTable,
)


def _test_map() -> MapData:
    nodes = {
        "a": MapNodeData("a", 0, 0, {}),
        "b": MapNodeData("b", 1, 0, {}),
        "c": MapNodeData("c", 2, 0, {}),
        "d": MapNodeData("d", 1, 1, {}),
    }
    pairs = (
        ("a", "b"),
        ("b", "a"),
        ("b", "c"),
        ("c", "b"),
        ("b", "d"),
        ("d", "b"),
    )
    edges = {
        f"{start}_{end}": MapEdgeData(
            f"{start}_{end}", start, end, 1.0, 1.0, 1, {}
        )
        for start, end in pairs
    }
    adjacency = {
        node_id: tuple(
            edge.to_node_id for edge in edges.values() if edge.from_node_id == node_id
        )
        for node_id in nodes
    }
    return MapData(nodes=nodes, adjacency=adjacency, locations={}, edges=edges)


class CooperativeRoutingTests(unittest.TestCase):
    def test_inserts_wait_when_a_transit_node_is_reserved(self):
        map_data = _test_map()
        reservations = ReservationTable(map_data)
        routing = CooperativeRoutingService()
        first = routing.plan(
            map_data,
            reservations,
            start_node_id="a",
            goal_node_id="c",
            start_time=0,
        )
        reservations.reserve_timeline(first.node_ids)

        second = routing.plan(
            map_data,
            reservations,
            start_node_id="d",
            goal_node_id="b",
            start_time=0,
        )

        self.assertEqual(first.node_ids, ("a", "b", "c"))
        self.assertEqual(second.node_ids, ("d", "d", "b"))
        self.assertEqual(second.wait_count, 1)

    def test_canonical_edge_reservation_prevents_head_on_swap(self):
        map_data = _test_map()
        reservations = ReservationTable(map_data)
        routing = CooperativeRoutingService()
        first = routing.plan(
            map_data,
            reservations,
            start_node_id="a",
            goal_node_id="b",
            start_time=0,
        )
        reservations.reserve_timeline(first.node_ids)

        second = routing.plan(
            map_data,
            reservations,
            start_node_id="b",
            goal_node_id="a",
            start_time=0,
        )

        self.assertNotEqual(second.node_ids[:2], ("b", "a"))
        self.assertEqual(len(second.node_ids), 4)
        self.assertIn(second.node_ids[1], {"c", "d"})
        self.assertEqual(second.node_ids[-2:], ("b", "a"))


if __name__ == "__main__":
    unittest.main()
