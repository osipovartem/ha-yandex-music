"""Tests for cancellable Yandex Music stream sessions."""
from __future__ import annotations

import asyncio
import importlib.util
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "yandex_music"
    / "stream_manager.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "yandex_music_stream_manager",
    _MODULE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
YandexMusicStreamManager = _MODULE.YandexMusicStreamManager


class YandexMusicStreamManagerTest(unittest.IsolatedAsyncioTestCase):
    """Verify session invalidation and active task cancellation."""

    async def test_start_invalidates_previous_token(self) -> None:
        """Starting a track makes cached URLs for the old track unusable."""
        manager = YandexMusicStreamManager()

        first = manager.start("entry-1")
        second = manager.start("entry-1")

        self.assertNotEqual(first, second)
        self.assertFalse(manager.is_active("entry-1", first))
        self.assertTrue(manager.is_active("entry-1", second))

    async def test_rejects_unknown_session(self) -> None:
        """A request must present the current unguessable session token."""
        manager = YandexMusicStreamManager()
        manager.start("entry-1")

        self.assertFalse(
            manager.register("entry-1", "wrong", asyncio.current_task())
        )

    async def test_stop_cancels_active_handler(self) -> None:
        """Stopping playback closes the handler that proxies upstream audio."""
        manager = YandexMusicStreamManager()
        token = manager.start("entry-1")
        registered = asyncio.Event()

        async def stream_handler() -> None:
            task = asyncio.current_task()
            assert task is not None
            self.assertTrue(manager.register("entry-1", token, task))
            registered.set()
            try:
                await asyncio.Event().wait()
            finally:
                manager.unregister("entry-1", task)

        task = asyncio.create_task(stream_handler())
        await registered.wait()

        manager.stop("entry-1")

        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(manager.is_active("entry-1", token))


if __name__ == "__main__":
    unittest.main()
