"""Helpers for Yandex Music playback-source discovery and compatibility."""
from __future__ import annotations

from typing import Any

DEFAULT_LEGACY_STATION = "onyourwave"

_SOURCE_PREFIXES = (
    "station:",
    "station_id:",
    "playlist:",
    "liked:",
    "track:",
)


def normalize_default_source(source: str | None) -> str:
    """Convert a legacy station key into a playable media content ID."""
    source = source or DEFAULT_LEGACY_STATION
    if source.startswith(_SOURCE_PREFIXES):
        return source
    return f"station:{source}"


def media_type_for_source(source: str) -> str:
    """Return the Home Assistant media type for a content ID."""
    if source.startswith(("station:", "station_id:")):
        return "station"
    if source.startswith("playlist:"):
        return "playlist"
    if source.startswith("liked:"):
        return "liked"
    if source.startswith("track:"):
        return "track"
    return "music"


def station_result_to_dict(result: Any) -> dict[str, str] | None:
    """Convert a yandex-music StationResult into serializable catalog data."""
    station = getattr(result, "station", None)
    station_id = getattr(station, "id", None)
    station_type = getattr(station_id, "type", None)
    station_tag = getattr(station_id, "tag", None)
    if not station or not station_type or not station_tag:
        return None

    title = (
        getattr(result, "custom_name", None)
        or getattr(station, "name", None)
        or getattr(result, "rup_title", None)
        or f"{station_type}:{station_tag}"
    )

    image_url = getattr(station, "full_image_url", None)
    if not image_url:
        icon = getattr(station, "icon", None)
        image_url = getattr(icon, "image_url", None)
    if image_url:
        image_url = image_url.replace("%%", "200x200")
        if not image_url.startswith(("http://", "https://")):
            image_url = f"https://{image_url.lstrip('/')}"

    data = {
        "station_id": f"{station_type}:{station_tag}",
        "title": str(title),
    }
    if image_url:
        data["image_url"] = image_url
    return data


def build_default_source_choices(
    predefined_stations: dict[str, dict[str, Any]],
    catalog_data: dict[str, Any],
    current_source: str | None = None,
) -> list[tuple[str, str]]:
    """Build stable values and readable labels for the options selector."""
    choices: list[tuple[str, str]] = []
    values: set[str] = set()

    def add(value: str, label: str) -> None:
        if value in values:
            return
        values.add(value)
        choices.append((value, label))

    static_station_ids: set[str] = set()
    for key, config in predefined_stations.items():
        add(
            f"station:{key}",
            f"📻 {config.get('label', config['name'])}",
        )
        if config.get("mood_energy") is None:
            static_station_ids.add(config["station_id"])

    for station in catalog_data.get("stations", []):
        station_id = station.get("station_id")
        title = station.get("title")
        if not station_id or not title or station_id in static_station_ids:
            continue
        add(f"station_id:{station_id}", f"📻 {title}")

    add("liked:tracks", "❤️ Liked tracks / Мне нравится")

    playlists = sorted(
        catalog_data.get("playlists", []),
        key=lambda item: str(item.get("title", "")).casefold(),
    )
    for playlist in playlists:
        uid = playlist.get("uid")
        kind = playlist.get("kind")
        title = playlist.get("title")
        if uid is None or kind is None or not title:
            continue
        add(f"playlist:{uid}:{kind}", f"🎵 {title}")

    normalized_current = normalize_default_source(current_source)
    if normalized_current not in values:
        add(
            normalized_current,
            f"Current / Текущий: {normalized_current}",
        )

    return choices
