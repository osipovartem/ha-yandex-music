"""Constants for Yandex Music integration."""

DOMAIN = "yandex_music"

DATA_STREAM_MANAGER = "stream_manager"

CONF_TOKEN = "token"
CONF_TARGET_PLAYER = "target_player"
CONF_DEFAULT_STATION = "default_station"

PLATFORMS = ["media_player"]

UPDATE_INTERVAL_MINUTES = 30

# Predefined station configurations
PREDEFINED_STATIONS: dict[str, dict] = {
    "onyourwave": {
        "name": "Моя волна",
        "station_id": "user:onyourwave",
        "mood_energy": None,
        "icon": "mdi:radio",
    },
    "calm": {
        "name": "Спокойное",
        "station_id": "user:onyourwave",
        "mood_energy": "calm",
        "icon": "mdi:leaf",
    },
    "wordless": {
        "name": "Без слов",
        "station_id": "music:genre-ambient",
        "mood_energy": None,
        "icon": "mdi:music-note-off",
    },
    "energetic": {
        "name": "Энергичное",
        "station_id": "user:onyourwave",
        "mood_energy": "active",
        "icon": "mdi:lightning-bolt",
    },
}

DEFAULT_STATION = "onyourwave"

# Media content types used in browse/play_media
MEDIA_TYPE_STATION = "station"
MEDIA_TYPE_PLAYLIST = "playlist"
MEDIA_TYPE_LIKED = "liked"
MEDIA_TYPE_TRACK = "track"

# Thumbnail placeholder when track has no cover
PLACEHOLDER_IMAGE = "https://music.yandex.ru/blocks/player-pg/playlist-playlist.png"
