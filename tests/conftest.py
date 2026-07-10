"""Shared test fixtures.

`MockBridge` stands in for the WebSocket bridge: snippet evals are
answered from a canned-response table keyed by a marker comment in the
snippet source (each snippet body is unique), and explicit ops record
their calls for assertions. No Premiere required — mirrors dvr's
MockResolve approach at the equivalent boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from prpr import errors
from prpr.bridge import RemoteRef


class MockBridge:
    """Test double for prpr.bridge.Bridge."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        # responses: snippet-name -> value | callable(args) -> value | Exception
        self.responses: dict[str, Any] = responses or {}
        self.calls: list[tuple[str, Any]] = []
        self.hello = {
            "event": "hello",
            "plugin": "0.0-test",
            "host": {"name": "premierepro", "version": "26.5.0"},
            "ppro": True,
        }
        self.port = 8855
        self.connected = True
        self._event_handlers: list[Any] = []

    # -- bridge API used by the library --------------------------------

    def ping(self, timeout: float = 10.0) -> dict[str, Any]:
        self.calls.append(("ping", None))
        return {"pong": True, "plugin": "0.0-test", "host": self.hello["host"], "ppro": True}

    def eval_js(self, code: str, args: Any = None, *, timeout: float = 60.0) -> Any:
        name = self._snippet_name(code)
        self.calls.append((name, args))
        if name not in self.responses:
            raise AssertionError(f"MockBridge has no response for snippet {name!r}")
        value = self.responses[name]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(args)
        return value

    def request(self, op: str, *, timeout: float = 60.0, **payload: Any) -> Any:
        self.calls.append((f"op:{op}", payload))
        return self.responses.get(f"op:{op}")

    def get(self, target: Any, path: str, *, timeout: float = 30.0) -> Any:
        self.calls.append((f"get:{path}", target))
        return self.responses.get(f"get:{path}")

    def call(self, target: Any, path: str, *args: Any, timeout: float = 60.0) -> Any:
        self.calls.append((f"call:{path}", args))
        return self.responses.get(f"call:{path}")

    def on_event(self, handler: Any) -> None:
        self._event_handlers.append(handler)

    def wait_for_plugin(self, timeout: float = 30.0) -> dict[str, Any]:
        if not self.connected:
            raise errors.PluginNotConnectedError("mock plugin not connected")
        return self.hello

    def close(self) -> None:
        self.connected = False

    def make_ref(self, type_: str = "Object", snap: dict[str, Any] | None = None) -> RemoteRef:
        return RemoteRef("1", type_, snap, self)  # type: ignore[arg-type]

    def _queue_release(self, handle: str) -> None:
        pass

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _snippet_name(code: str) -> str:
        from prpr import _js

        for name, source in _js.SNIPPETS.items():
            if source == code:
                return name
        return "<raw-eval>"

    def snippet_calls(self, name: str) -> list[Any]:
        return [args for called, args in self.calls if called == name]


@pytest.fixture
def mock_bridge() -> MockBridge:
    return MockBridge()


@pytest.fixture
def premiere(mock_bridge: MockBridge):
    from prpr.premiere import Premiere

    return Premiere(bridge=mock_bridge)  # type: ignore[arg-type]


SEQUENCE_INSPECT = {
    "name": "Edit_v1",
    "guid": "abc-123",
    "project": "Test.prproj",
    "fps": 24.0,
    "frame_size": {"width": 1920, "height": 1080},
    "end": {"seconds": 10.0, "ticks": "x"},
    "zero_point": {"seconds": 0.0, "ticks": "0"},
    "tracks": {
        "video": [
            {
                "index": 0,
                "name": "Video 1",
                "id": 1,
                "muted": False,
                "clips": 2,
                "items": [
                    {
                        "name": "a.mp4",
                        "start": {"seconds": 0.0},
                        "end": {"seconds": 4.0},
                        "duration": {"seconds": 4.0},
                        "enabled": True,
                        "track_index": 0,
                        "speed": 1,
                    },
                    {
                        "name": "b.mp4",
                        "start": {"seconds": 4.0},
                        "end": {"seconds": 10.0},
                        "duration": {"seconds": 6.0},
                        "enabled": True,
                        "track_index": 0,
                        "speed": 1,
                    },
                ],
            }
        ],
        "audio": [],
        "caption": [],
    },
    "markers": [
        {
            "name": "m1",
            "comments": "note",
            "type": "Comment",
            "start": {"seconds": 1.0},
            "duration": {"seconds": 0.0},
            "color_index": 1,
        }
    ],
    "settings": {"audio_channel_count": 2},
}
"""Canned sequence_inspect payload used across tests."""
