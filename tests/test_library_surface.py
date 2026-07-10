"""v0.2 library surface: routing, arg shaping, guarded crash paths."""

from __future__ import annotations

import pytest

from prpr import errors
from tests.conftest import MockBridge


@pytest.fixture
def premiere(mock_bridge: MockBridge):
    from prpr.premiere import Premiere

    return Premiere(bridge=mock_bridge)  # type: ignore[arg-type]


class TestSelectionGuard:
    def test_select_without_clear_refuses(self, premiere) -> None:
        from prpr.timeline import Timeline

        timeline = Timeline(premiere, "Edit_v1")
        with pytest.raises(errors.NotSupportedError) as exc:
            timeline.select(name_contains="a")
        assert "crashes Premiere" in exc.value.message

    def test_select_clear_calls_bridge(self, premiere, mock_bridge: MockBridge) -> None:
        from prpr.timeline import Timeline

        mock_bridge.responses["selection_set"] = {"cleared": True}
        Timeline(premiere, "Edit_v1").select(clear=True)
        (args,) = mock_bridge.snippet_calls("selection_set")
        assert args["clear"] is True


class TestTrackUpdate:
    def test_track_update_routes_args(self, premiere, mock_bridge: MockBridge) -> None:
        from prpr.timeline import Timeline

        mock_bridge.responses["track_update"] = {"name": "V1", "muted": True}
        Timeline(premiere, "Edit_v1").track_update(0, mute=True, set_name="Hero")
        (args,) = mock_bridge.snippet_calls("track_update")
        assert args["track_index"] == 0
        assert args["mute"] is True
        assert args["set_name"] == "Hero"


class TestEffectsSetParam:
    def test_point_value_passes_through(self, premiere, mock_bridge: MockBridge) -> None:
        mock_bridge.responses["param_set"] = {"set": "Position"}
        premiere.effects.set_param("Motion", "Position", [0.5, 0.5], clip_name="a.mp4")
        (args,) = mock_bridge.snippet_calls("param_set")
        assert args["value"] == [0.5, 0.5]
        assert args["component"] == "Motion"

    def test_keyframe_carries_at_seconds(self, premiere, mock_bridge: MockBridge) -> None:
        mock_bridge.responses["param_set"] = {"set": "Opacity", "keyframed": True}
        premiere.effects.set_param("Opacity", "Opacity", 0, clip_name="a.mp4", at_seconds=2.0)
        (args,) = mock_bridge.snippet_calls("param_set")
        assert args["at_seconds"] == 2.0


class TestProjectSettings:
    def test_scratch_disks_read(self, premiere, mock_bridge: MockBridge) -> None:
        from prpr.project import Project

        mock_bridge.responses["scratch_disks"] = {"capture": "MyDocuments"}
        proj = Project(premiere, {"name": "P"})
        result = proj.scratch_disks()
        assert result["capture"] == "MyDocuments"

    def test_ingest_toggle(self, premiere, mock_bridge: MockBridge) -> None:
        from prpr.project import Project

        mock_bridge.responses["ingest_settings"] = {"ingest_enabled": True}
        Project(premiere, {"name": "P"}).ingest(enabled=True)
        (args,) = mock_bridge.snippet_calls("ingest_settings")
        assert args["enabled"] is True


class TestMediaSurface:
    def test_footage_interpretation_set(self, premiere, mock_bridge: MockBridge) -> None:
        mock_bridge.responses["footage_interpretation"] = {"frame_rate": 24.0}
        premiere.media.footage_interpretation(name="a.mp4", set={"frame_rate": 24.0})
        (args,) = mock_bridge.snippet_calls("footage_interpretation")
        assert args["set"] == {"frame_rate": 24.0}

    def test_subclip_args(self, premiere, mock_bridge: MockBridge) -> None:
        mock_bridge.responses["subclip_create"] = {"created": "sub"}
        premiere.media.create_subclip("sub", 1.0, 4.0, name="a.mp4")
        (args,) = mock_bridge.snippet_calls("subclip_create")
        assert args["start_seconds"] == 1.0
        assert args["end_seconds"] == 4.0


class TestMainErrorRendering:
    def test_main_renders_pmr_error_json(self, monkeypatch, capsys) -> None:
        """main() must catch PrprError and emit JSON to stderr, exit 1."""
        import sys

        from prpr.cli import main as cli_main
        from prpr.cli import session

        def boom() -> None:
            raise errors.TimelineError("boom", cause="c", fix="f")

        session.set_premiere_provider(boom)  # type: ignore[arg-type]
        monkeypatch.setenv("PRPR_NO_DAEMON", "1")
        monkeypatch.setenv("PRPR_FORMAT", "json")
        monkeypatch.setattr(sys, "argv", ["prpr", "timeline", "list"])
        try:
            with pytest.raises(SystemExit) as exc:
                cli_main.main()
            assert exc.value.code == 1
        finally:
            session.set_premiere_provider(None)
