"""Point-in-time project snapshots — `prpr snapshot`.

Captures the inspectable state of the current project (sequences with
tracks/items/markers, media tree) to JSON on disk, so agents can diff
against it or re-apply markers/sequences after destructive experiments.

Restore is best-effort and additive (Premiere can't reconstruct source
clips from JSON): it recreates missing sequences and re-adds missing
markers, and reports what it could not restore.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import errors

if TYPE_CHECKING:
    from .premiere import Premiere


def snapshots_dir() -> Path:
    target = Path.home() / ".prpr" / "snapshots"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@-]+", "_", name)


@dataclass
class Snapshot:
    name: str
    project: str
    captured_at: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "project": self.project,
            "captured_at": self.captured_at,
            "data": self.data,
        }


def capture(premiere: Premiere, name: str | None = None) -> Snapshot:
    """Capture the current project's state."""
    project = premiere.project.require_current()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project_name = project.name.replace(".prproj", "")
    snapshot_name = name or f"{project_name}@{stamp}"

    timelines: list[dict[str, Any]] = []
    for entry in premiere.timeline.list():
        from .timeline import Timeline

        timeline = Timeline(premiere, entry.get("name"))
        timelines.append(timeline.inspect())

    data = {
        "project": project.inspect(),
        "timelines": timelines,
        "media": premiere.media.inspect(with_paths=True),
    }
    return Snapshot(
        name=snapshot_name,
        project=project_name,
        captured_at=datetime.now(timezone.utc).isoformat(),
        data=data,
    )


def save(snapshot: Snapshot) -> Path:
    path = snapshots_dir() / f"{_safe_name(snapshot.name)}.json"
    path.write_text(json.dumps(snapshot.to_dict(), indent=2))
    return path


def load(name: str) -> Snapshot:
    path = snapshots_dir() / f"{_safe_name(name)}.json"
    if not path.exists():
        raise errors.PrprError(
            f"Snapshot not found: {name}",
            fix="Run `prpr snapshot list` to see saved snapshots.",
            state={"dir": str(snapshots_dir())},
        )
    raw = json.loads(path.read_text())
    return Snapshot(
        name=raw["name"],
        project=raw["project"],
        captured_at=raw["captured_at"],
        data=raw.get("data", {}),
    )


def list_snapshots() -> list[dict[str, Any]]:
    out = []
    for path in sorted(snapshots_dir().glob("*.json"), reverse=True):
        try:
            raw = json.loads(path.read_text())
            out.append(
                {
                    "name": raw.get("name", path.stem),
                    "project": raw.get("project"),
                    "captured_at": raw.get("captured_at"),
                    "timelines": len(raw.get("data", {}).get("timelines", [])),
                    "path": str(path),
                }
            )
        except ValueError:
            continue
    return out


def delete(name: str) -> None:
    path = snapshots_dir() / f"{_safe_name(name)}.json"
    if not path.exists():
        raise errors.PrprError(f"Snapshot not found: {name}")
    path.unlink()


def restore(premiere: Premiere, snapshot: Snapshot, *, dry_run: bool = False) -> dict[str, Any]:
    """Best-effort re-apply: recreate missing sequences, re-add missing markers."""
    timelines_created = 0
    markers_added = 0
    skipped: list[dict[str, Any]] = []
    existing = {entry.get("name") for entry in premiere.timeline.list()}

    for timeline_data in snapshot.data.get("timelines", []):
        timeline_name = timeline_data.get("name")
        if not timeline_name:
            continue
        if timeline_name not in existing:
            if not dry_run:
                premiere.timeline.ensure(timeline_name)
            timelines_created += 1
            skipped.append(
                {
                    "timeline": timeline_name,
                    "reason": "clips cannot be restored from a snapshot; sequence recreated empty",
                }
            )
        from .timeline import Timeline

        timeline = Timeline(premiere, timeline_name)
        current_markers = [] if dry_run else timeline.markers()
        have = {(m.get("name"), (m.get("start") or {}).get("seconds")) for m in current_markers}
        for marker in timeline_data.get("markers", []):
            key = (marker.get("name"), (marker.get("start") or {}).get("seconds"))
            if key in have:
                continue
            if not dry_run:
                timeline.add_marker(
                    (marker.get("start") or {}).get("seconds") or 0,
                    name=marker.get("name") or "marker",
                    note=marker.get("comments") or "",
                    marker_type=marker.get("type") or "Comment",
                    duration_seconds=(marker.get("duration") or {}).get("seconds"),
                    color_index=marker.get("color_index"),
                )
            markers_added += 1

    return {
        "timelines_created": timelines_created,
        "markers_added": markers_added,
        "skipped": skipped,
        "dry_run": dry_run,
    }


__all__ = [
    "Snapshot",
    "capture",
    "delete",
    "list_snapshots",
    "load",
    "restore",
    "save",
    "snapshots_dir",
]
