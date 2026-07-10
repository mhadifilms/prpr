"""Spec parse/plan, diff comparison, schema topics — pure logic tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmr import errors, schema
from pmr.diff import compare
from pmr.spec import Spec, load_spec


class TestSpecParsing:
    def test_load_yaml(self, tmp_path: Path) -> None:
        file = tmp_path / "spec.yaml"
        file.write_text("project: Show\nbins:\n  - Footage\ntimelines:\n  - name: Edit_v1\n")
        spec = load_spec(str(file))
        assert spec.project == "Show"
        assert spec.bins == ["Footage"]
        assert spec.timelines[0]["name"] == "Edit_v1"

    def test_load_json(self, tmp_path: Path) -> None:
        file = tmp_path / "spec.json"
        file.write_text('{"project": "Show", "media": [{"path": "/x.mov"}]}')
        spec = load_spec(str(file))
        assert spec.media == [{"path": "/x.mov"}]

    def test_unknown_section_rejected(self, tmp_path: Path) -> None:
        file = tmp_path / "spec.yaml"
        file.write_text("project: X\nrenders: []\n")
        with pytest.raises(errors.SpecError):
            load_spec(str(file))

    def test_missing_file(self) -> None:
        with pytest.raises(errors.SpecError):
            load_spec("/no/such/spec.yaml")

    def test_bad_yaml(self, tmp_path: Path) -> None:
        file = tmp_path / "spec.yaml"
        file.write_text("{{{{not yaml")
        with pytest.raises(errors.SpecError):
            load_spec(str(file))

    def test_roundtrip_dict(self) -> None:
        spec = Spec(project="X", bins=["A"], media=[], timelines=[])
        assert spec.to_dict()["project"] == "X"


class TestDiff:
    def test_identical_clean(self) -> None:
        left = {"a": 1, "nested": {"b": [1, 2]}}
        diff = compare(left, dict(left))
        assert diff.clean
        assert diff.to_dict()["clean"] is True

    def test_modified_and_added(self) -> None:
        diff = compare({"a": 1, "b": 2}, {"a": 9, "c": 3})
        assert {m["key"] for m in diff.modified} == {"a"}
        assert diff.added == ["c"]
        assert diff.removed == ["b"]

    def test_list_items_keyed_by_name(self) -> None:
        left = {"items": [{"name": "x", "v": 1}]}
        right = {"items": [{"name": "x", "v": 2}]}
        diff = compare(left, right)
        assert diff.modified[0]["key"] == "items[x].v"

    def test_ignored_keys(self) -> None:
        diff = compare({"guid": "a"}, {"guid": "b"})
        assert diff.clean


class TestSchema:
    def test_parity_contains_core_operations(self) -> None:
        parity = schema.get_topic("parity")["operations"]
        assert parity["timeline.inspect"]["status"] == "both"
        assert parity["render.queue"]["status"] == "dvr-only"
        assert parity["effects.apply"]["status"] == "pmr-only"

    def test_all_static_topics_resolve(self) -> None:
        for topic in schema.STATIC_TOPICS:
            assert schema.get_topic(topic) is not None

    def test_live_topic_without_premiere_raises(self) -> None:
        with pytest.raises(errors.PmrError):
            schema.get_topic("effects")

    def test_unknown_topic(self) -> None:
        with pytest.raises(errors.PmrError):
            schema.get_topic("nope")

    def test_parity_status_lookup(self) -> None:
        assert schema.parity_status("fusion")["status"] == "dvr-only"
        assert schema.parity_status("brand-new-op")["status"] == "unknown"

    def test_render_presets_topic_is_static_call(self) -> None:
        result = schema.get_topic("render-presets")
        assert isinstance(result, list)
