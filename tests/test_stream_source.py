"""Regression tests for Home Assistant HTTP client usage."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


_STREAM_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "yandex_music"
    / "stream.py"
)


class StreamSourceTest(unittest.TestCase):
    """Keep stream requests on Home Assistant's shared HTTP session."""

    def test_uses_home_assistant_shared_client_session(self) -> None:
        """Do not create and close a separate session for every stream."""
        tree = ast.parse(_STREAM_PATH.read_text(encoding="utf-8"))

        imported_helpers = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "homeassistant.helpers.aiohttp_client"
            for alias in node.names
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        aiohttp_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "aiohttp"
        }

        self.assertIn("async_get_clientsession", imported_helpers)
        self.assertIn("async_get_clientsession", called_names)
        self.assertNotIn("ClientSession", aiohttp_calls)


if __name__ == "__main__":
    unittest.main()
