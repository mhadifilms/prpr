"""MCP registry: naming, schemas, parity contract — no Premiere required."""

from __future__ import annotations

import json
import os

import pytest

from prpr.mcp.server import build_registry


@pytest.fixture(scope="module")
def registry():
    return build_registry()


def test_tool_names_unique_and_snake_case(registry) -> None:
    names = [tool.name for tool in registry]
    assert len(names) == len(set(names))
    for name in names:
        assert name == name.lower()
        assert " " not in name


def test_dvr_parity_tool_names_present(registry) -> None:
    names = {tool.name for tool in registry}
    # The shared-surface contract: these exact names exist in dvr's MCP too.
    shared = {
        "version",
        "doctor",
        "reconnect",
        "schema",
        "ping",
        "inspect",
        "page_get",
        "page_set",
        "project_list",
        "project_ensure",
        "project_current",
        "project_save",
        "project_delete",
        "timeline_list",
        "timeline_inspect",
        "timeline_ensure",
        "timeline_switch",
        "timeline_rename",
        "timeline_delete",
        "timeline_clear",
        "timeline_append",
        "marker_add",
        "clip_where",
        "media_inspect",
        "media_bins",
        "media_ls",
        "media_import",
        "media_scan",
        "media_bin_ensure",
        "media_bin_delete",
        "media_move",
        "render_presets",
        "render_submit",
        "render_queue",
        "render_formats",
        "render_codecs",
        "render_stop",
        "render_clear",
        "diff_timelines",
        "diff_to_spec",
        "apply_spec",
        "spec_export",
        "snapshot_save",
        "snapshot_list",
        "snapshot_restore",
        "lint",
    }
    missing = shared - names
    assert not missing, f"dvr-parity tools missing: {sorted(missing)}"


def test_schemas_are_valid_json_objects(registry) -> None:
    for tool in registry:
        schema = tool.schema
        assert isinstance(schema, dict)
        assert schema.get("type") == "object"
        json.dumps(schema)  # serializable


def test_not_supported_tools_fail_structurally(registry) -> None:
    from prpr import errors

    by_name = {tool.name: tool for tool in registry}
    for name in ("render_queue", "page_set", "interchange_import", "media_relink"):
        tool = by_name[name]
        with pytest.raises(errors.NotSupportedError) as exc_info:
            tool.handler(None, {})  # NotSupported handlers never touch ctx
        assert exc_info.value.fix, f"{name} NotSupportedError needs a fix"


def test_offline_tools_do_not_need_premiere(registry) -> None:
    offline = {t.name for t in registry if not t.needs_premiere}
    for expected in ("version", "doctor", "media_scan", "render_presets", "snapshot_list"):
        assert expected in offline


def test_eval_gated_by_env(monkeypatch, registry) -> None:
    """eval is always registered but its handler refuses without the env gate
    (handler-level gating: agents see the tool and get an actionable error)."""
    from prpr import errors

    by_name = {tool.name: tool for tool in registry}
    assert "eval" in by_name
    monkeypatch.delenv("PRPR_MCP_ENABLE_EVAL", raising=False)
    with pytest.raises(errors.PrprError) as exc_info:
        by_name["eval"].handler(None, {"code": "return 1"})
    assert "PRPR_MCP_ENABLE_EVAL" in str(exc_info.value)


def test_parity_matrix_agrees_with_registry() -> None:
    """Every prpr-only op in PARITY that maps to a tool exists; every
    dvr-only tool that is registered raises NotSupportedError."""
    from prpr import errors
    from prpr.schema import PARITY

    registry = build_registry()
    by_name = {tool.name: tool for tool in registry}
    dvr_only_tools = (
        "render_queue",
        "render_formats",
        "render_codecs",
        "render_stop",
        "render_clear",
        "page_get",
        "page_set",
    )
    for name in dvr_only_tools:
        tool = by_name[name]
        with pytest.raises(errors.NotSupportedError):
            tool.handler(None, {"name": "x", "format": "x", "topic": "x"})

    assert PARITY["effects.apply"]["status"] == "prpr-only"
    assert "effect_apply" in by_name


_ = os  # keep import for monkeypatch clarity
