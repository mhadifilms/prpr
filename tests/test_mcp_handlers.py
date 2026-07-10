"""Execute the newly-wired MCP tool handlers against a mock-bridge Premiere.

Verifies the handler -> library -> snippet routing (arg names, snippet
selection) for the v0.2 tool surface, entirely offline.
"""

from __future__ import annotations

import pytest

from pmr.mcp.server import _Context, _PremiereCache, build_registry
from pmr.premiere import Premiere
from tests.conftest import SEQUENCE_INSPECT, MockBridge


@pytest.fixture
def ctx_and_bridge():
    bridge = MockBridge(
        {
            "sequence_inspect": SEQUENCE_INSPECT,
            "project_inspect": {"name": "P.prproj", "path": "/x/P.prproj"},
            "sequence_list": [{"name": "Edit_v1", "guid": "abc", "is_active": True}],
            "marker_move": {"moved": True, "to_seconds": 3.0},
            "work_area": {"in_point": {"seconds": 1.0}, "out_point": {"seconds": 5.0}},
            "keyframes_list": {"component": "Motion", "param": "Scale", "keyframes": []},
            "track_update": {"name": "V1", "muted": True},
            "sequence_clone": {"cloned": "Edit_v1"},
            "subsequence_create": {"name": "Sub"},
            "sequence_in_out": {"in_point": {"seconds": 1.0}},
            "sequence_from_media": {"name": "New", "guid": "z"},
            "selection_get": {"scope": "sequence", "items": []},
            "color_label": {"name": "a.mp4", "color_label": 3},
            "bin_rename": {"renamed": "Old", "to": "New"},
            "smart_bin_create": {"created": "Smart"},
            "footage_interpretation": {"frame_rate": 24.0},
            "scratch_disks": {"capture": "MyDocuments"},
            "ingest_settings": {"ingest_enabled": True},
            "color_settings": {"graphics_white_luminance": 203},
            "app_preference": {"key": "k", "value": "v"},
        }
    )
    premiere = Premiere(bridge=bridge)  # type: ignore[arg-type]
    cache = _PremiereCache(auto_launch=False, timeout=5.0)
    cache._premiere = premiere  # inject; skip real connect
    ctx = _Context(cache=cache)
    return ctx, bridge


def _tool(name: str):
    for spec in build_registry():
        if spec.name == name:
            return spec
    raise AssertionError(f"tool {name!r} not registered")


@pytest.mark.parametrize(
    "name,args,expect_snippet",
    [
        ("marker_move", {"to_seconds": 3.0}, "marker_move"),
        ("timeline_work_area", {"in_seconds": 1.0, "out_seconds": 5.0}, "work_area"),
        ("timeline_keyframes", {"component": "Motion", "param": "Scale"}, "keyframes_list"),
        ("timeline_track", {"track_index": 0, "mute": True}, "track_update"),
        ("timeline_clone", {}, "sequence_clone"),
        ("timeline_subsequence", {}, "subsequence_create"),
        ("timeline_in_out", {"in_seconds": 1.0}, "sequence_in_out"),
        ("timeline_selection", {}, "selection_get"),
        ("media_color_label", {"name": "a.mp4", "set_index": 3}, "color_label"),
        ("media_bin_rename", {"path": "Old", "new_name": "New"}, "bin_rename"),
        ("media_smart_bin", {"name": "Smart", "query": "x"}, "smart_bin_create"),
        ("media_footage_interpretation", {"name": "a.mp4"}, "footage_interpretation"),
        ("project_scratch_disks", {}, "scratch_disks"),
        ("project_ingest", {"enabled": True}, "ingest_settings"),
        ("project_color_settings", {}, "color_settings"),
        ("app_preference", {"key": "k"}, "app_preference"),
    ],
)
def test_new_tool_routes_to_snippet(ctx_and_bridge, name, args, expect_snippet) -> None:
    ctx, bridge = ctx_and_bridge
    result = _tool(name).handler(ctx, args)
    assert result is not None
    assert bridge.snippet_calls(expect_snippet), f"{name} did not call {expect_snippet}"


def test_timeline_create_from_media_routes(ctx_and_bridge) -> None:
    ctx, bridge = ctx_and_bridge
    _tool("timeline_create_from_media").handler(ctx, {"name": "New", "items": ["a.mp4"]})
    assert bridge.snippet_calls("sequence_from_media")


def test_all_new_tools_registered() -> None:
    names = {t.name for t in build_registry()}
    for name in (
        "marker_move",
        "timeline_work_area",
        "timeline_keyframes",
        "timeline_track",
        "timeline_clone",
        "timeline_subsequence",
        "timeline_in_out",
        "timeline_create_from_media",
        "timeline_selection",
        "media_color_label",
        "media_bin_rename",
        "media_smart_bin",
        "media_footage_interpretation",
        "media_purge_cache",
        "project_scratch_disks",
        "project_ingest",
        "project_color_settings",
        "project_import_sequences",
        "project_import_ae_comps",
        "app_preference",
    ):
        assert name in names, f"missing tool: {name}"
