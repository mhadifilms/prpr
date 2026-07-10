"""Declarative project state — `pmr apply` / `pmr spec`.

A spec is a YAML/JSON description of desired project state; ``apply``
reconciles the live project toward it idempotently (terraform-style),
and ``from_live`` reverse-engineers a spec from the current state.

Format (all sections optional):

    project: MyShow                # name or path of the .prproj
    bins:
      - Footage
      - Footage/Day1
    media:
      - path: /abs/clip_a.mp4
        bin: Footage
    timelines:
      - name: Edit_v1
        active: true
        clips:                     # appended in order if missing (by name)
          - clip_a.mp4
        markers:
          - seconds: 1.0
            name: start
            note: first pass
            color_index: 1
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from . import errors

if TYPE_CHECKING:
    from .premiere import Premiere


@dataclass
class Action:
    op: str  # create | update | import | skip
    target: str  # project | bin | media | timeline | clip | marker
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"op": self.op, "target": self.target, "detail": self.detail}


@dataclass
class Spec:
    project: str | None = None
    bins: list[str] = field(default_factory=list)
    media: list[dict[str, Any]] = field(default_factory=list)
    timelines: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "bins": self.bins,
            "media": self.media,
            "timelines": self.timelines,
        }


def load_spec(file_path: str) -> Spec:
    path = Path(file_path).expanduser()
    if not path.exists():
        raise errors.SpecError(f"Spec file not found: {path}")
    raw = path.read_text()
    try:
        data = json.loads(raw) if path.suffix == ".json" else yaml.safe_load(raw)
    except Exception as exc:
        raise errors.SpecError(
            f"Could not parse spec file: {path}",
            cause=str(exc),
            fix="Specs are YAML or JSON — check the syntax.",
        ) from exc
    if not isinstance(data, dict):
        raise errors.SpecError("Spec must be a mapping at the top level.")
    unknown = set(data) - {"project", "bins", "media", "timelines"}
    if unknown:
        raise errors.SpecError(
            f"Unknown spec sections: {sorted(unknown)}",
            fix="Valid sections: project, bins, media, timelines.",
        )
    return Spec(
        project=data.get("project"),
        bins=list(data.get("bins") or []),
        media=list(data.get("media") or []),
        timelines=list(data.get("timelines") or []),
    )


def from_live(premiere: Premiere) -> dict[str, Any]:
    """Reverse-engineer a spec dict from live state (inverse of apply)."""
    project = premiere.project.require_current()
    tree = premiere.media.inspect(with_paths=True)

    bins: list[str] = []
    media: list[dict[str, Any]] = []

    def walk(items: list[dict[str, Any]], prefix: str) -> None:
        for item in items:
            if item.get("kind") == "bin":
                bin_path = f"{prefix}/{item['name']}" if prefix else item["name"]
                bins.append(bin_path)
                walk(item.get("children", []), bin_path)
            elif item.get("path") and not item.get("is_sequence"):
                media.append({"path": item["path"], "bin": prefix or None})

    walk(tree.get("items", []), "")

    timelines = []
    for entry in premiere.timeline.list():
        from .timeline import Timeline

        data = Timeline(premiere, entry.get("name")).inspect()
        clips = [
            item.get("name")
            for track in data.get("tracks", {}).get("video", [])
            for item in track.get("items", [])
        ]
        markers = [
            {
                "seconds": (m.get("start") or {}).get("seconds", 0),
                "name": m.get("name"),
                "note": m.get("comments") or None,
                "color_index": m.get("color_index"),
            }
            for m in data.get("markers", [])
        ]
        timelines.append(
            {
                "name": data.get("name"),
                "active": bool(entry.get("is_active")),
                "clips": clips,
                "markers": markers,
            }
        )

    return {
        "project": project.name.replace(".prproj", ""),
        "bins": bins,
        "media": media,
        "timelines": timelines,
    }


def plan(spec: Spec, premiere: Premiere) -> list[Action]:
    """Compute the actions `apply` would take, without executing them."""
    actions: list[Action] = []

    current = premiere.project.current
    current_name = current.name.replace(".prproj", "") if current else None
    if spec.project and spec.project != current_name:
        actions.append(Action("create", "project", f"ensure project {spec.project!r}"))

    if spec.bins or spec.media or spec.timelines:
        tree = premiere.media.inspect(with_paths=True) if current else {"items": []}
        existing_bins: set[str] = set()
        existing_paths: set[str] = set()
        existing_names: set[str] = set()

        def walk(items: list[dict[str, Any]], prefix: str) -> None:
            for item in items:
                if item.get("kind") == "bin":
                    bin_path = f"{prefix}/{item['name']}" if prefix else item["name"]
                    existing_bins.add(bin_path)
                    walk(item.get("children", []), bin_path)
                else:
                    existing_names.add(item.get("name"))
                    if item.get("path"):
                        existing_paths.add(item["path"])

        walk(tree.get("items", []), "")

        for bin_path in spec.bins:
            if bin_path not in existing_bins:
                actions.append(Action("create", "bin", bin_path))
        for entry in spec.media:
            path = str(Path(entry["path"]).expanduser())
            if path not in existing_paths:
                actions.append(Action("import", "media", path))

        existing_timelines = (
            {t.get("name") for t in premiere.timeline.list()} if current else set()
        )
        for timeline_spec in spec.timelines:
            name = timeline_spec.get("name")
            if name not in existing_timelines:
                actions.append(Action("create", "timeline", name))
                for clip in timeline_spec.get("clips", []):
                    actions.append(Action("update", "clip", f"append {clip!r} to {name!r}"))
                for marker in timeline_spec.get("markers", []):
                    actions.append(
                        Action("update", "marker", f"add {marker.get('name')!r} to {name!r}")
                    )
            else:
                from .timeline import Timeline

                live = Timeline(premiere, name).inspect()
                live_clips = [
                    item.get("name")
                    for track in live.get("tracks", {}).get("video", [])
                    for item in track.get("items", [])
                ]
                for clip in timeline_spec.get("clips", []):
                    if clip not in live_clips:
                        actions.append(Action("update", "clip", f"append {clip!r} to {name!r}"))
                live_markers = {
                    (m.get("name"), (m.get("start") or {}).get("seconds"))
                    for m in live.get("markers", [])
                }
                for marker in timeline_spec.get("markers", []):
                    key = (marker.get("name"), marker.get("seconds"))
                    if key not in live_markers:
                        actions.append(
                            Action("update", "marker", f"add {marker.get('name')!r} to {name!r}")
                        )
    return actions


def apply(
    spec: Spec,
    premiere: Premiere,
    *,
    dry_run: bool = False,
    verify: bool = False,
) -> dict[str, Any]:
    """Reconcile live state toward the spec. Idempotent."""
    actions = plan(spec, premiere)
    if dry_run:
        return {"applied": 0, "planned": [a.to_dict() for a in actions], "dry_run": True}

    if spec.project:
        premiere.project.ensure(spec.project)
    for bin_path in spec.bins:
        premiere.media.bin_ensure(bin_path)
    for entry in spec.media:
        premiere.media.find_or_import(entry["path"], bin=entry.get("bin"))

    for timeline_spec in spec.timelines:
        name = timeline_spec.get("name")
        if not name:
            raise errors.SpecError("Every timeline in a spec needs a name.")
        timeline = premiere.timeline.ensure(name)
        live = timeline.inspect()
        live_clips = [
            item.get("name")
            for track in live.get("tracks", {}).get("video", [])
            for item in track.get("items", [])
        ]
        for clip in timeline_spec.get("clips", []):
            if clip not in live_clips:
                timeline.append(clip)
        live_markers = {
            (m.get("name"), (m.get("start") or {}).get("seconds"))
            for m in timeline.markers()
        }
        for marker in timeline_spec.get("markers", []):
            key = (marker.get("name"), marker.get("seconds"))
            if key not in live_markers:
                timeline.add_marker(
                    marker.get("seconds", 0),
                    name=marker.get("name") or "marker",
                    note=marker.get("note") or "",
                    duration_seconds=marker.get("duration_seconds"),
                    color_index=marker.get("color_index"),
                )
        if timeline_spec.get("active"):
            premiere.timeline.set_current(name)

    result: dict[str, Any] = {
        "applied": len(actions),
        "actions": [a.to_dict() for a in actions],
        "dry_run": False,
    }
    if verify:
        remaining = plan(spec, premiere)
        result["verified"] = not remaining
        result["unreconciled"] = [a.to_dict() for a in remaining]
        if remaining:
            raise errors.SpecError(
                f"{len(remaining)} spec item(s) did not reconcile.",
                state=result,
                fix="Inspect `unreconciled`; Premiere may have rejected them silently.",
            )
    return result


__all__ = ["Action", "Spec", "apply", "from_live", "load_spec", "plan"]
