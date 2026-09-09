"""Track and cancel active Yandex Music proxy streams."""
from __future__ import annotations

import asyncio
import secrets


class YandexMusicStreamManager:
    """Own short-lived stream sessions for each config entry."""

    def __init__(self) -> None:
        """Initialize the stream registry."""
        self._tokens: dict[str, str] = {}
        self._tasks: dict[str, set[asyncio.Task]] = {}

    def start(self, entry_id: str) -> str:
        """Cancel older streams and return a token for a new playback session."""
        self.stop(entry_id)
        token = secrets.token_urlsafe(18)
        self._tokens[entry_id] = token
        return token

    def stop(self, entry_id: str) -> None:
        """Invalidate the current session and cancel its active HTTP handlers."""
        self._tokens.pop(entry_id, None)
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        for task in tuple(self._tasks.pop(entry_id, set())):
            if task is not current and not task.done():
                task.cancel()

    def register(
        self,
        entry_id: str,
        token: str,
        task: asyncio.Task,
    ) -> bool:
        """Register a request task if its session is still active."""
        if self._tokens.get(entry_id) != token:
            return False
        self._tasks.setdefault(entry_id, set()).add(task)
        return True

    def unregister(self, entry_id: str, task: asyncio.Task) -> None:
        """Forget a completed request task."""
        tasks = self._tasks.get(entry_id)
        if tasks is None:
            return
        tasks.discard(task)
        if not tasks:
            self._tasks.pop(entry_id, None)

    def is_active(self, entry_id: str, token: str) -> bool:
        """Return whether a stream session may still send audio."""
        return self._tokens.get(entry_id) == token
