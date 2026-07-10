"""Timeline namespace against the mock bridge."""

from __future__ import annotations

import pytest

from prpr import errors
from tests.conftest import SEQUENCE_INSPECT, MockBridge


@pytest.fixture
def premiere_with_sequence(mock_bridge: MockBridge):
    from prpr.premiere import Premiere

    mock_bridge.responses.update(
        {
            "sequence_inspect": SEQUENCE_INSPECT,
            "sequence_list": [
                {"name": "Edit_v1", "guid": "abc-123", "fps": 24.0, "is_active": True},
                {"name": "Other", "guid": "def-456", "fps": 24.0, "is_active": False},
            ],
            "marker_list": SEQUENCE_INSPECT["markers"],
            "marker_add": {"added": "m2", "seconds": 2.0, "sequence": "Edit_v1"},
            "sequence_create": {"name": "New_v1", "guid": "new-789"},
            "sequence_set_active": {"current": "Other"},
            "sequence_delete": {"deleted": "Other"},
            "timeline_insert": {"inserted": "a.mp4", "at_seconds": 10.0},
            "clip_update": {"updated": 1, "names": ["a.mp4"]},
        }
    )
    return Premiere(bridge=mock_bridge)  # type: ignore[arg-type]


def test_list(premiere_with_sequence) -> None:
    entries = premiere_with_sequence.timeline.list()
    assert [e["name"] for e in entries] == ["Edit_v1", "Other"]


def test_current_inspect_computes_frames(premiere_with_sequence) -> None:
    timeline = premiere_with_sequence.timeline.current
    data = timeline.inspect()
    assert data["name"] == "Edit_v1"
    assert data["duration_seconds"] == 10.0
    assert data["duration_frames"] == 240  # 10s * 24fps


def test_items_and_query(premiere_with_sequence) -> None:
    timeline = premiere_with_sequence.timeline.current
    items = timeline.items("video")
    assert [i.name for i in items] == ["a.mp4", "b.mp4"]
    short = timeline.clips.where(lambda c: (c.duration or 0) < 5)
    assert short.count() == 1
    assert short.first().name == "a.mp4"


def test_get_missing_raises_not_found(premiere_with_sequence) -> None:
    with pytest.raises(errors.TimelineNotFoundError):
        premiere_with_sequence.timeline.get("Nope")


def test_ensure_returns_existing(premiere_with_sequence, mock_bridge: MockBridge) -> None:
    timeline = premiere_with_sequence.timeline.ensure("Edit_v1")
    assert timeline.name == "Edit_v1"
    assert mock_bridge.snippet_calls("sequence_create") == []


def test_ensure_creates_missing(premiere_with_sequence, mock_bridge: MockBridge) -> None:
    premiere_with_sequence.timeline.ensure("New_v1")
    assert len(mock_bridge.snippet_calls("sequence_create")) == 1


def test_create_duplicate_raises(premiere_with_sequence) -> None:
    with pytest.raises(errors.TimelineError):
        premiere_with_sequence.timeline.create("Edit_v1")


def test_add_marker_args(premiere_with_sequence, mock_bridge: MockBridge) -> None:
    timeline = premiere_with_sequence.timeline.current
    timeline.add_marker(2.0, name="m2", note="hello", color_index=3)
    (args,) = mock_bridge.snippet_calls("marker_add")
    assert args["seconds"] == 2.0
    assert args["name"] == "m2"
    assert args["comments"] == "hello"
    assert args["color_index"] == 3


def test_append_routes_to_insert(premiere_with_sequence, mock_bridge: MockBridge) -> None:
    timeline = premiere_with_sequence.timeline.current
    result = timeline.append("a.mp4")
    assert result["inserted"] == "a.mp4"
    (args,) = mock_bridge.snippet_calls("timeline_insert")
    assert args["overwrite"] is True
    assert args["seconds"] is None  # end-of-sequence


def test_current_none_when_no_project(mock_bridge: MockBridge) -> None:
    from prpr.premiere import Premiere

    mock_bridge.responses["sequence_inspect"] = errors.HostJSError("No active sequence")
    premiere = Premiere(bridge=mock_bridge)  # type: ignore[arg-type]
    assert premiere.timeline.current is None
