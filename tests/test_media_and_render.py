"""Media scanning/import and render preset logic against the mock bridge."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmr import errors
from pmr.media import media_kind_for_path, scan_media_files
from tests.conftest import MockBridge


class TestScan:
    def test_kind_classification(self) -> None:
        assert media_kind_for_path("/x/a.mov") == "video"
        assert media_kind_for_path("/x/a.WAV") == "audio"
        assert media_kind_for_path("/x/a.png") == "image"
        assert media_kind_for_path("/x/a.txt") is None

    def test_scan_filters_and_limits(self, tmp_path: Path) -> None:
        (tmp_path / "a.mov").write_bytes(b"x")
        (tmp_path / "b.wav").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        (tmp_path / ".hidden.mov").write_bytes(b"x")
        found = scan_media_files(str(tmp_path))
        kinds = {f["kind"] for f in found}
        assert len(found) == 2
        assert kinds == {"video", "audio"}

    def test_scan_single_file(self, tmp_path: Path) -> None:
        file = tmp_path / "c.mp4"
        file.write_bytes(b"x")
        found = scan_media_files(str(file))
        assert found == [{"path": str(file), "kind": "video"}]


class TestImport:
    def test_missing_files_fail_before_bridge(self, premiere, mock_bridge: MockBridge) -> None:
        with pytest.raises(errors.MediaImportError):
            premiere.media.import_(["/definitely/not/here.mov"])
        assert mock_bridge.snippet_calls("media_import") == []

    def test_import_absolutizes(self, premiere, mock_bridge: MockBridge, tmp_path: Path) -> None:
        file = tmp_path / "a.mov"
        file.write_bytes(b"x")
        mock_bridge.responses["media_import"] = {"imported": 1, "requested": 1, "items": []}
        premiere.media.import_([str(file)], bin="Footage")
        (args,) = mock_bridge.snippet_calls("media_import")
        assert args["paths"] == [str(file)]
        assert args["bin"] == "Footage"


class TestBins:
    def test_ls_nested(self, premiere, mock_bridge: MockBridge) -> None:
        mock_bridge.responses["media_tree"] = {
            "project": "P",
            "items": [
                {
                    "kind": "bin",
                    "name": "Footage",
                    "children": [
                        {"kind": "bin", "name": "Day1", "children": [
                            {"kind": "clip", "name": "a.mov", "path": "/x/a.mov"},
                        ]},
                    ],
                },
            ],
        }
        items = premiere.media.ls("Footage/Day1")
        assert [i["name"] for i in items] == ["a.mov"]

    def test_ls_missing_bin(self, premiere, mock_bridge: MockBridge) -> None:
        mock_bridge.responses["media_tree"] = {"project": "P", "items": []}
        with pytest.raises(errors.MediaError):
            premiere.media.ls("Nope")


class TestRenderPresets:
    def test_resolve_preset_by_path(self, tmp_path: Path) -> None:
        from pmr.render import resolve_preset

        preset = tmp_path / "custom.epr"
        preset.write_bytes(b"<xml/>")
        assert resolve_preset(str(preset)) == str(preset)

    def test_resolve_preset_missing_raises(self) -> None:
        from pmr.render import resolve_preset

        with pytest.raises(errors.RenderError):
            resolve_preset("no-such-preset-xyz")

    def test_resolve_none_passthrough(self) -> None:
        from pmr.render import resolve_preset

        assert resolve_preset(None) is None


class TestRenderNotSupported:
    def test_queue_raises(self, premiere) -> None:
        with pytest.raises(errors.NotSupportedError):
            premiere.render.queue()

    def test_formats_codecs_stop_clear_raise(self, premiere) -> None:
        for call in (
            premiere.render.formats,
            lambda: premiere.render.codecs("mp4"),
            premiere.render.stop,
            premiere.render.clear,
        ):
            with pytest.raises(errors.NotSupportedError):
                call()


class TestAppParity:
    def test_page_raises_not_supported(self, premiere) -> None:
        with pytest.raises(errors.NotSupportedError):
            _ = premiere.app.page
        with pytest.raises(errors.NotSupportedError):
            premiere.app.page = "edit"
