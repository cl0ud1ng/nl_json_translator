import tempfile
import unittest
from pathlib import Path

from nl_json_translator.domain.location_text import normalize_location_text
from nl_json_translator.infrastructure.database import Database
from nl_json_translator.infrastructure.orm_models import LocationRecord, MapNodeRecord
from nl_json_translator.infrastructure.seed_demo_data import seed_demo_data
from nl_json_translator.repositories.locations import LocationRepository
from nl_json_translator.services.location_resolver import (
    AmbiguousLocationError,
    LocationResolutionStatus,
    LocationResolver,
    UnknownLocationError,
)


class LocationTextTests(unittest.TestCase):
    def test_normalizes_width_spacing_punctuation_and_chinese_numbers(self):
        self.assertEqual(normalize_location_text(" Ｐｏｉｎｔ－一号！ "), "point1号")
        self.assertEqual(normalize_location_text("十一号库"), "11号库")


class LocationResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{Path(self.temp_dir.name) / 'resolver.db'}"
        seed_demo_data(self.url)
        self.database = Database(self.url)

    def tearDown(self):
        self.database.dispose()
        self.temp_dir.cleanup()

    def _resolver(self, **kwargs):
        session = self.database.session_factory()
        self.addCleanup(session.close)
        return LocationResolver(LocationRepository(session), **kwargs)

    def test_resolves_standard_name_alias_and_fuzzy_text(self):
        resolver = self._resolver()

        self.assertEqual(resolver.resolve(" LAB ").location_id, "loc_lab")
        self.assertEqual(resolver.resolve("实验室").location_id, "loc_lab")
        fuzzy = resolver.resolve("laborator")
        self.assertEqual(fuzzy.location_id, "loc_lab")
        self.assertEqual(fuzzy.candidates[0].matched_by, "alias")

    def test_new_database_location_is_available_without_code_changes(self):
        with self.database.session() as session:
            session.add(MapNodeRecord(id="node_custom", x=30, y=30))
            session.add(
                LocationRecord(
                    id="loc_custom",
                    name="临时仓库",
                    map_node_id="node_custom",
                )
            )

        self.assertEqual(self._resolver().resolve("临时仓库").location_id, "loc_custom")

    def test_reports_ambiguous_and_unknown_locations(self):
        with self.database.session() as session:
            session.add_all(
                [
                    MapNodeRecord(id="node_east", x=30, y=31),
                    MapNodeRecord(id="node_west", x=30, y=32),
                    LocationRecord(
                        id="loc_assembly_east",
                        name="assembly east",
                        map_node_id="node_east",
                    ),
                    LocationRecord(
                        id="loc_assembly_west",
                        name="assembly west",
                        map_node_id="node_west",
                    ),
                ]
            )

        resolver = self._resolver(fuzzy_threshold=0.65, ambiguity_margin=0.1)
        ambiguous = resolver.resolve("assembly")
        self.assertEqual(ambiguous.status, LocationResolutionStatus.AMBIGUOUS)
        with self.assertRaises(AmbiguousLocationError):
            ambiguous.require_location_id()

        unknown = resolver.resolve("火星基地")
        self.assertEqual(unknown.status, LocationResolutionStatus.UNKNOWN)
        with self.assertRaises(UnknownLocationError):
            unknown.require_location_id()

    def test_ignores_disabled_locations(self):
        with self.database.session() as session:
            location = session.get(LocationRecord, "loc_b")
            location.enabled = False

        self.assertEqual(
            self._resolver().resolve("B").status,
            LocationResolutionStatus.UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main()
