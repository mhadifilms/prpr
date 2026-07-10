"""Interchange format export (FCPXML / OTIO / AAF).

Premiere 26.3+ exposes ``ProjectConverter`` for sequence export to Final
Cut Pro XML, OpenTimelineIO, and AAF. Import of interchange formats was
removed from the UXP API in 26.3 — importing goes through
``project.importFiles`` (which accepts project-level formats Premiere
understands) or stays a dvr-only operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import errors
from ._js import snippet

if TYPE_CHECKING:
    from .premiere import Premiere

FORMATS = ("fcpxml", "otio", "aaf")


def export_timeline(
    premiere: Premiere,
    file_path: str,
    *,
    format: str | None = None,
    timeline: str | None = None,
) -> dict[str, Any]:
    """Export a sequence to an interchange format (by flag or extension)."""
    path = Path(file_path).expanduser()
    fmt = format
    if fmt is None:
        ext = path.suffix.lower().lstrip(".")
        fmt = {"xml": "fcpxml", "fcpxml": "fcpxml", "otio": "otio", "aaf": "aaf"}.get(ext)
    if fmt not in FORMATS:
        raise errors.InterchangeError(
            f"Unknown interchange format: {format or path.suffix}",
            fix=f"Use one of {FORMATS} (or an output extension of .xml/.otio/.aaf).",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return premiere.eval_js(
        snippet("interchange_export"),
        {"sequence": timeline, "path": str(path), "format": fmt},
        timeout=600.0,
    )


def import_timeline(premiere: Premiere, file_path: str) -> dict[str, Any]:
    raise errors.NotSupportedError(
        "Premiere's UXP API cannot import interchange timelines (removed in 26.3).",
        cause="ProjectConverter.import* APIs were removed from UXP.",
        fix="Import EDL/FCPXML manually via File > Import in Premiere; "
        "programmatic interchange import is a dvr-only operation.",
    )


__all__ = ["FORMATS", "export_timeline", "import_timeline"]
