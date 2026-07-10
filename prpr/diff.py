"""Structural comparison — `prpr diff`.

Compares timeline inspections (live vs live, live vs spec, live vs
snapshot) as flattened key paths, mirroring dvr's Diff shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .premiere import Premiere
    from .spec import Spec


@dataclass
class Diff:
    left_label: str
    right_label: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.added or self.removed or self.modified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left_label,
            "right": self.right_label,
            "clean": self.clean,
            "added": self.added,
            "removed": self.removed,
            "modified": self.modified,
            "unchanged_count": len(self.unchanged),
        }


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, val in value.items():
            out.update(_flatten(val, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        for index, val in enumerate(value):
            key = val.get("name", index) if isinstance(val, dict) else index
            out.update(_flatten(val, f"{prefix}[{key}]"))
        return out
    out[prefix] = value
    return out


def compare(
    left: dict[str, Any],
    right: dict[str, Any],
    left_label: str = "left",
    right_label: str = "right",
    *,
    ignore: tuple[str, ...] = ("guid", "player_position", "project"),
) -> Diff:
    """Compare two inspection dicts as flattened key paths."""
    flat_left = {k: v for k, v in _flatten(left).items() if not _ignored(k, ignore)}
    flat_right = {k: v for k, v in _flatten(right).items() if not _ignored(k, ignore)}
    diff = Diff(left_label, right_label)
    for key in sorted(set(flat_left) | set(flat_right)):
        if key not in flat_left:
            diff.added.append(key)
        elif key not in flat_right:
            diff.removed.append(key)
        elif flat_left[key] != flat_right[key]:
            diff.modified.append({"key": key, "left": flat_left[key], "right": flat_right[key]})
        else:
            diff.unchanged.append(key)
    return diff


def _ignored(key: str, ignore: tuple[str, ...]) -> bool:
    parts = key.replace("]", "").replace("[", ".").split(".")
    return any(part in ignore for part in parts)


def compare_timelines(premiere: Premiere, a: str, b: str) -> Diff:
    """Diff two sequences by name."""
    from .timeline import Timeline

    left = Timeline(premiere, a).inspect()
    right = Timeline(premiere, b).inspect()
    return compare(left, right, a, b, ignore=("guid", "player_position", "name", "project"))


def compare_to_spec(premiere: Premiere, spec: Spec) -> Diff:
    """Diff live state against a declarative spec."""
    from .spec import from_live

    live = from_live(premiere)
    return compare(live, spec.to_dict(), "live", "spec", ignore=("guid", "player_position"))


def compare_to_snapshot(premiere: Premiere, snapshot_name: str) -> Diff:
    """Diff live timelines against a saved snapshot."""
    from . import snapshot as snapshot_module
    from .timeline import Timeline

    snap = snapshot_module.load(snapshot_name)
    live_timelines = {}
    for entry in premiere.timeline.list():
        name = entry.get("name")
        live_timelines[name] = Timeline(premiere, name).inspect()
    snap_timelines = {t.get("name"): t for t in snap.data.get("timelines", [])}
    return compare(
        {"timelines": live_timelines},
        {"timelines": snap_timelines},
        "live",
        f"snapshot:{snapshot_name}",
    )


__all__ = ["Diff", "compare", "compare_timelines", "compare_to_snapshot", "compare_to_spec"]
