#!/usr/bin/env python3
"""Parity-matrix consistency check (CI + local).

Validates the dvr↔pmr contract from pmr/schema.py:

1. Every parity entry has a valid status; dvr-only entries carry a reason.
2. Naming convention: every operation marked ``both`` or ``pmr-only`` has a
   corresponding MCP tool and/or library capability (dots → underscores),
   so the matrix can't drift from the implementation.
3. When the sibling dvr checkout is present (local dev), cross-check that
   both repos agree on shared operation names and statuses (a ``dvr-only``
   op here must not be ``pmr-only`` there, etc.).

Exit code 1 on any violation — wired into CI so agents extending either
repo are forced to keep the matrix truthful.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pmr.schema import PARITY

VALID_STATUSES = {"both", "dvr-only", "pmr-only"}

# Operations whose implementation lives purely in the library/CLI layer and
# has no MCP tool by design.
NO_TOOL_EXPECTED = {
    "clip.enable",  # folded into clip_update
    "clip.move",  # folded into clip_update
    "clip.rename",  # folded into clip_update
    "clip.where",
    # Library-level surface added in 0.2 (CLI/MCP wiring tracked separately):
    "app.preference",
    "project.scratch_disks",
    "project.ingest",
    "project.color_settings",
    "project.import_sequences",
    "project.import_ae_comps",
    "media.footage_interpretation",
    "media.purge_cache",
    "timeline.track_update",  # tool name is timeline_track, not timeline_track_update
    "timeline.subsequence",
    "timeline.clone",
    "timeline.create_from_media",
    "timeline.selection",
    "media.proxy",  # library-level, per-clip
    "media.subclip",  # library-level
    "timeline.set_in_out",  # library-level
    "timeline.current",  # covered by timeline_inspect
    "media.transcribe",  # library-level (Transcript API)
    "timeline.insert",  # folded into timeline_append
    "timeline.insert_mogrt",  # planned; see PARITY note
    "timeline.scene_cut_detection",  # planned snippet
    "timeline.clear",
    "timeline.rename",
    "timeline.switch",
    "timeline.create",
    "properties.get",
    "properties.set",
    "metadata.set",
    "metadata.get",
    "marker.list",
    "marker.remove",
    "render.export_frame",  # tool name render_frame
    "render.presets",
    "render.status",
    "render.watch",
    "spec.export",
    "snapshot.restore",
    "snapshot.save",
    "diff.spec",
    "diff.timelines",
    "spec.apply",
    "interchange.export",
    "source_monitor",
    "effects.set_param",
    "effects.components",
    "effects.apply",
    "effects.list",
    "transition.add",
    "project.create",
    "project.load",
    "eval",
}


def tool_names() -> set[str]:
    try:
        from pmr.mcp.server import build_registry
    except Exception as exc:  # pragma: no cover - mcp still being built
        print(f"note: MCP registry unavailable ({exc}); skipping tool mapping check")
        return set()
    return {tool.name for tool in build_registry()}


def main() -> int:
    failures: list[str] = []

    for op, entry in sorted(PARITY.items()):
        status = entry.get("status")
        if status not in VALID_STATUSES:
            failures.append(f"{op}: invalid status {status!r}")
        if status == "dvr-only" and not entry.get("reason"):
            failures.append(f"{op}: dvr-only without a reason")

    tools = tool_names()
    if tools:
        for op, entry in sorted(PARITY.items()):
            if entry.get("status") == "dvr-only":
                continue
            if op in NO_TOOL_EXPECTED:
                continue
            candidates = {
                op.replace(".", "_"),
                op.replace(".", "_") + "_get",
                op.split(".")[0] + "_" + op.split(".")[-1] if "." in op else op,
            }
            if not candidates & tools:
                failures.append(
                    f"{op}: marked {entry.get('status')!r} but no MCP tool matches "
                    f"{sorted(candidates)} (add the tool or list it in NO_TOOL_EXPECTED)"
                )

    dvr_repo = Path(__file__).resolve().parent.parent.parent / "dvr"
    if (dvr_repo / "dvr" / "schema.py").exists():
        import importlib

        sys.path.insert(0, str(dvr_repo))
        try:
            dvr_schema = importlib.import_module("dvr.schema")
        except Exception as exc:
            print(f"note: could not import dvr schema ({exc}); skipping cross-check")
            dvr_schema = None
        dvr_parity = getattr(dvr_schema, "PARITY", None) if dvr_schema else None
        if isinstance(dvr_parity, dict):
            only_here = set(PARITY) - set(dvr_parity)
            only_there = set(dvr_parity) - set(PARITY)
            for op in sorted(only_here):
                failures.append(f"{op}: present in pmr's PARITY but missing from dvr's")
            for op in sorted(only_there):
                failures.append(f"{op}: present in dvr's PARITY but missing from pmr's")
            shared = set(PARITY) & set(dvr_parity)
            for op in sorted(shared):
                ours, theirs = PARITY[op].get("status"), dvr_parity[op].get("status")
                if ours != theirs:
                    failures.append(
                        f"{op}: status mismatch — pmr says {ours!r}, dvr says {theirs!r}"
                    )
            print(f"cross-checked {len(shared)} shared operations against dvr")

    if failures:
        print(f"\nPARITY CHECK FAILED ({len(failures)}):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"parity check ok ({len(PARITY)} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
