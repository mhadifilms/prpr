"""Events namespace: subscribe/route/unsubscribe against the mock bridge."""

from __future__ import annotations

import pytest

from pmr import errors
from tests.conftest import MockBridge


@pytest.fixture
def premiere(mock_bridge: MockBridge):
    from pmr.premiere import Premiere

    # eval_js for target resolution + subscribe/unsubscribe ops.
    mock_bridge.responses["<raw-eval>"] = mock_bridge.make_ref("Project")
    mock_bridge.responses["op:subscribe"] = {"subscription": "1"}
    mock_bridge.responses["op:unsubscribe"] = {"unsubscribed": True}
    return Premiere(bridge=mock_bridge)  # type: ignore[arg-type]


def test_subscribe_global_routes_events(premiere, mock_bridge: MockBridge) -> None:
    received = []
    sub_id = premiere.events.subscribe("global", "EVENT_OPENED", received.append)
    assert sub_id == "1"

    # Simulate the plugin pushing a host-event frame through the bridge.
    for handler in mock_bridge._event_handlers:
        handler({"event": "host-event", "subscription": "1", "payload": {"name": "P"}})
    assert received == [{"name": "P"}]


def test_unknown_target_raises(premiere) -> None:
    with pytest.raises(errors.PmrError):
        premiere.events.subscribe("nope", "X", lambda e: None)


def test_off_all(premiere) -> None:
    premiere.events.subscribe("global", "A", lambda e: None)
    assert len(premiere.events.active()) == 1
    removed = premiere.events.off_all()
    assert removed == 1
    assert premiere.events.active() == []


def test_bad_handler_does_not_break_router(premiere, mock_bridge: MockBridge) -> None:
    good = []
    premiere.events.subscribe("global", "A", lambda e: (_ for _ in ()).throw(ValueError("boom")))
    premiere.events.subscribe("global", "A", good.append)
    for handler in mock_bridge._event_handlers:
        handler({"event": "host-event", "subscription": "1", "payload": {"ok": 1}})
    # Second handler still fires despite the first raising.
    assert {"ok": 1} in good


def test_decorator_form(premiere) -> None:
    @premiere.events.on("global", "EVENT_DIRTY")
    def _handler(event):
        return None

    assert len(premiere.events.active()) == 1
