"""Tests for default playback-source discovery and migration."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

_MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "yandex_music"
    / "source_catalog.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "yandex_music_source_catalog",
    _MODULE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

build_default_source_choices = _MODULE.build_default_source_choices
build_playlist_choices = _MODULE.build_playlist_choices
media_type_for_source = _MODULE.media_type_for_source
normalize_default_source = _MODULE.normalize_default_source
PLAYLIST_PICKER_VALUE = _MODULE.PLAYLIST_PICKER_VALUE
resolve_queue_position = _MODULE.resolve_queue_position
station_result_to_dict = _MODULE.station_result_to_dict


class SourceCatalogTest(unittest.TestCase):
    """Verify source IDs, catalog conversion, and selector choices."""

    def test_normalizes_legacy_station_keys(self) -> None:
        """Existing default_station values continue to work after upgrading."""
        self.assertEqual(normalize_default_source("calm"), "station:calm")
        self.assertEqual(
            normalize_default_source("playlist:42:7"),
            "playlist:42:7",
        )
        self.assertEqual(
            normalize_default_source("liked:tracks"),
            "liked:tracks",
        )
        self.assertEqual(normalize_default_source(None), "station:onyourwave")

    def test_detects_media_type(self) -> None:
        """Each selectable source is dispatched to its matching media type."""
        self.assertEqual(media_type_for_source("station:calm"), "station")
        self.assertEqual(
            media_type_for_source("station_id:mood:allrock"),
            "station",
        )
        self.assertEqual(media_type_for_source("playlist:42:7"), "playlist")
        self.assertEqual(media_type_for_source("liked:tracks"), "liked")

    def test_resolves_repeating_queue_boundaries(self) -> None:
        """Library queues wrap while non-repeating queues finish."""
        self.assertEqual(resolve_queue_position(1, 3, True), (1, False))
        self.assertEqual(resolve_queue_position(3, 3, True), (0, True))
        self.assertEqual(resolve_queue_position(3, 3, False), (None, False))

    def test_converts_personalized_station(self) -> None:
        """Dashboard results become serializable source-catalog entries."""
        result = SimpleNamespace(
            custom_name="Танцую",
            rup_title="Моя волна",
            station=SimpleNamespace(
                id=SimpleNamespace(type="activity", tag="dance"),
                name="Танцевальная",
                full_image_url="avatars.yandex.net/icon/%%",
                icon=None,
            ),
        )

        self.assertEqual(
            station_result_to_dict(result),
            {
                "station_id": "activity:dance",
                "title": "Танцую",
                "image_url": "https://avatars.yandex.net/icon/200x200",
            },
        )

    def test_builds_compact_source_and_playlist_choices(self) -> None:
        """Personal playlists are moved to a separate selector step."""
        predefined = {
            "onyourwave": {
                "name": "Моя волна",
                "label": "My Wave / Моя волна",
                "station_id": "user:onyourwave",
                "mood_energy": None,
            }
        }
        catalog = {
            "stations": [
                {"station_id": "user:onyourwave", "title": "Duplicate"},
                {"station_id": "activity:dance", "title": "Танцую"},
            ],
            "playlists": [
                {"uid": 42, "kind": 7, "title": "Road trip"},
            ],
        }

        choices = dict(
            build_default_source_choices(
                predefined,
                catalog,
                "playlist:42:7",
            )
        )

        self.assertIn("station:onyourwave", choices)
        self.assertIn("station_id:activity:dance", choices)
        self.assertNotIn("station_id:user:onyourwave", choices)
        self.assertIn("liked:tracks", choices)
        self.assertIn(PLAYLIST_PICKER_VALUE, choices)
        self.assertIn("→", choices[PLAYLIST_PICKER_VALUE])
        self.assertNotIn("playlist:42:7", choices)

        playlists = dict(
            build_playlist_choices(catalog, "playlist:42:7")
        )
        self.assertEqual(playlists["playlist:42:7"], "Road trip")

    def test_playlist_picker_handles_empty_or_deleted_catalog(self) -> None:
        """Hide an empty picker but preserve a previously selected playlist."""
        predefined = {
            "onyourwave": {
                "name": "Моя волна",
                "station_id": "user:onyourwave",
                "mood_energy": None,
            }
        }
        choices = dict(
            build_default_source_choices(
                predefined,
                {"playlists": []},
                "station:onyourwave",
            )
        )
        self.assertNotIn(PLAYLIST_PICKER_VALUE, choices)

        deleted = dict(
            build_playlist_choices({}, "playlist:42:99")
        )
        self.assertIn("playlist:42:99", deleted)


if __name__ == "__main__":
    unittest.main()
