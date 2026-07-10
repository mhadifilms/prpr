"""CLI wiring against the mock bridge — command tree, routing, output.

Uses typer's CliRunner with a Premiere built on the mock bridge injected
via the session provider, so no real Premiere is touched.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pmr.cli import session
from pmr.cli.main import app
from tests.conftest import SEQUENCE_INSPECT, MockBridge

runner = CliRunner()


@pytest.fixture
def wired(monkeypatch):
    """Install a Premiere-on-mock-bridge as the CLI's provider."""
    from pmr.premiere import Premiere

    bridge = MockBridge(
        {
            "sequence_inspect": SEQUENCE_INSPECT,
            "sequence_list": [{"name": "Edit_v1", "guid": "abc", "fps": 24.0, "is_active": True}],
            "project_inspect": {
                "name": "Test.prproj",
                "path": "/x/Test.prproj",
                "sequences": [],
                "bin_count": 0,
                "item_count": 0,
            },
            "project_list_open": [{"name": "Test.prproj", "path": "/x/Test.prproj"}],
            "marker_add": {"added": "m", "seconds": 1.0, "sequence": "Edit_v1"},
            "effects_list": {"kind": "video", "match_names": ["PR.ADBE Gamma Correction"]},
        }
    )
    premiere = Premiere(bridge=bridge)  # type: ignore[arg-type]
    session.set_premiere_provider(lambda: premiere)
    monkeypatch.setenv("PMR_NO_DAEMON", "1")
    yield bridge
    session.set_premiere_provider(None)


def _run(args: list[str]):
    return runner.invoke(app, ["--format", "json", *args])


def test_help_lists_all_namespaces() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for ns in (
        "project",
        "timeline",
        "clip",
        "media",
        "render",
        "effects",
        "metadata",
        "monitor",
        "plugin",
        "diff",
        "snapshot",
        "spec",
        "schema",
        "serve",
        "mcp",
    ):
        assert ns in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0


def test_schema_topics_offline() -> None:
    result = _run(["schema", "topics"])
    assert result.exit_code == 0
    assert "parity" in result.output


def test_schema_show_parity_offline() -> None:
    result = _run(["schema", "show", "parity"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["operations"]["render.queue"]["status"] == "dvr-only"


def test_media_scan_offline(tmp_path) -> None:
    (tmp_path / "a.mov").write_bytes(b"x")
    result = _run(["media", "scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "a.mov" in result.output


def test_timeline_list(wired) -> None:
    result = _run(["timeline", "list"])
    assert result.exit_code == 0
    assert "Edit_v1" in result.output


def test_timeline_inspect(wired) -> None:
    result = _run(["timeline", "inspect"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "Edit_v1"
    assert data["duration_frames"] == 240


def test_timeline_mark(wired) -> None:
    result = _run(["timeline", "mark", "--at", "1.0", "--name", "m"])
    assert result.exit_code == 0
    assert wired.snippet_calls("marker_add")


def test_effects_list(wired) -> None:
    result = _run(["effects", "list", "--kind", "video"])
    assert result.exit_code == 0
    assert "Gamma" in result.output


def test_render_queue_not_supported(wired) -> None:
    # CliRunner invokes `app` directly, so PmrError propagates as an
    # exception (main() is what renders it to stderr + exit 1 in real use).
    from pmr import errors

    result = _run(["render", "queue"])
    assert result.exit_code != 0
    assert isinstance(result.exception, errors.NotSupportedError)


def test_page_not_supported() -> None:
    from pmr import errors

    result = _run(["page", "edit"])
    assert result.exit_code != 0
    assert isinstance(result.exception, errors.NotSupportedError)
