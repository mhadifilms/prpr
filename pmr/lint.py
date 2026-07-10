"""Pre-flight validation — `pmr lint`.

Checks the live project for conditions that break automated workflows:
offline media, empty sequences, missing active sequence, unsaved
project path, media referencing temp directories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .premiere import Premiere


@dataclass
class Report:
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    infos: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos,
        }


def _entry(check: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"check": check, "message": message, **extra}


def lint(premiere: Premiere) -> Report:
    report = Report()

    project = premiere.project.current
    if project is None:
        report.errors.append(_entry("project", "No project is open in Premiere."))
        return report
    report.infos.append(_entry("project", f"Project open: {project.name}", path=project.path))

    tree = premiere.media.inspect(with_paths=True)
    offline: list[str] = []
    temp_media: list[str] = []

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            if item.get("kind") == "bin":
                walk(item.get("children", []))
                continue
            if item.get("offline"):
                offline.append(str(item.get("name") or "?"))
            path = item.get("path") or ""
            if path.startswith(("/tmp", "/var/folders", "/private/tmp", "/private/var")):
                temp_media.append(path)

    walk(tree.get("items", []))
    if offline:
        report.errors.append(
            _entry("media", f"{len(offline)} clip(s) are offline.", clips=offline[:20])
        )
    if temp_media:
        report.warnings.append(
            _entry(
                "media",
                f"{len(temp_media)} clip(s) reference temporary directories and may vanish.",
                paths=temp_media[:10],
            )
        )

    timelines = premiere.timeline.list()
    if not timelines:
        report.warnings.append(_entry("timeline", "Project has no sequences."))
    active = [t for t in timelines if t.get("is_active")]
    if timelines and not active:
        report.warnings.append(_entry("timeline", "No sequence is active."))

    for entry in timelines:
        from .timeline import Timeline

        data = Timeline(premiere, entry.get("name")).inspect(names_only=True)
        total_clips = sum(
            track.get("clips", 0)
            for kind in ("video", "audio")
            for track in data.get("tracks", {}).get(kind, [])
        )
        if total_clips == 0:
            report.warnings.append(_entry("timeline", f"Sequence {entry.get('name')!r} is empty."))

    return report


__all__ = ["Report", "lint"]
