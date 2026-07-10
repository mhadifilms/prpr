"""Discoverable catalogs — `pmr schema`.

Static topics work without a running Premiere; live topics query the
bridge. The ``parity`` topic is the machine-readable dvr↔pmr support
matrix: agents adding features to either repo consult it to know what
must be mirrored and what fails with ``NotSupportedError`` where.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import errors

if TYPE_CHECKING:
    from .premiere import Premiere

STATIC_TOPICS = (
    "parity",
    "marker-types",
    "marker-colors",
    "export-types",
    "interchange-formats",
    "media-kinds",
    "settings",
)
LIVE_TOPICS = (
    "effects",
    "audio-effects",
    "transitions",
    "render-presets",
)
TOPICS = STATIC_TOPICS + LIVE_TOPICS


# ---------------------------------------------------------------------------
# Parity matrix (the dvr ↔ pmr contract)
# ---------------------------------------------------------------------------
# status values:
#   both       — implemented in dvr and pmr with the same routing
#   dvr-only   — Resolve API supports it; pmr raises NotSupportedError
#   pmr-only   — Premiere API supports it; dvr raises NotSupportedError
# Keep in sync with the sibling repo's schema.py. CI checks this table
# against the registered CLI commands and MCP tools.

PARITY: dict[str, dict[str, Any]] = {
    "ping": {"status": "both"},
    "inspect": {"status": "both"},
    "version": {"status": "both"},
    "doctor": {"status": "both"},
    "reconnect": {"status": "both"},
    "page.get": {"status": "dvr-only", "reason": "Premiere has no scriptable workspaces"},
    "page.set": {"status": "dvr-only", "reason": "Premiere has no scriptable workspaces"},
    "project.list": {"status": "both", "note": "pmr lists open projects (file-based, no PM database)"},
    "project.current": {"status": "both"},
    "project.ensure": {"status": "both"},
    "project.create": {"status": "both"},
    "project.load": {"status": "both"},
    "project.save": {"status": "both"},
    "project.delete": {"status": "both", "note": "pmr deletes the .prproj file when closed"},
    "project.export": {"status": "dvr-only", "reason": "no .drp equivalent; Premiere projects are already files"},
    "project.import": {"status": "dvr-only", "reason": "no .drp equivalent; use project.load"},
    "project.color_groups": {"status": "dvr-only", "reason": "no color-group API in UXP"},
    "timeline.list": {"status": "both"},
    "timeline.current": {"status": "both"},
    "timeline.inspect": {"status": "both"},
    "timeline.ensure": {"status": "both"},
    "timeline.create": {"status": "both"},
    "timeline.switch": {"status": "both"},
    "timeline.delete": {"status": "both"},
    "timeline.rename": {"status": "both"},
    "timeline.append": {"status": "both"},
    "timeline.insert": {"status": "both"},
    "timeline.clear": {"status": "both"},
    "timeline.add_title": {"status": "dvr-only", "reason": "no title/text-clip creation in UXP (use MOGRTs)"},
    "timeline.insert_mogrt": {"status": "pmr-only", "reason": "MOGRT insertion is a Premiere feature"},
    "timeline.subtitles": {"status": "dvr-only", "reason": "no caption-generation API in UXP"},
    "timeline.scene_cut_detection": {"status": "pmr-only", "reason": "SequenceUtils scene edit detection"},
    "marker.add": {"status": "both"},
    "marker.list": {"status": "both"},
    "marker.remove": {"status": "both"},
    "clip.where": {"status": "both"},
    "clip.rename": {"status": "both"},
    "clip.enable": {"status": "both"},
    "clip.move": {"status": "both"},
    "clip.set_properties": {"status": "dvr-only", "reason": "no generic clip-property dict; use effects/components"},
    "clip.transform": {"status": "dvr-only", "reason": "Motion params reachable via component chain (planned)"},
    "effects.list": {"status": "pmr-only", "reason": "effect factories are a Premiere UXP feature"},
    "effects.apply": {"status": "pmr-only"},
    "effects.components": {"status": "pmr-only"},
    "transition.add": {"status": "pmr-only", "reason": "dvr has no transition API"},
    "media.inspect": {"status": "both"},
    "media.bins": {"status": "both"},
    "media.ls": {"status": "both"},
    "media.import": {"status": "both"},
    "media.scan": {"status": "both"},
    "media.bin_ensure": {"status": "both"},
    "media.bin_delete": {"status": "both"},
    "media.move": {"status": "both"},
    "media.relink": {"status": "dvr-only", "reason": "per-clip changeMediaFilePath only; no batch relink"},
    "media.proxy": {"status": "both", "note": "pmr: attachProxy per clip"},
    "media.transcribe": {"status": "both", "note": "pmr: Transcript API (26.3+)"},
    "render.submit": {"status": "both", "note": "pmr: .epr presets via EncoderManager"},
    "render.presets": {"status": "both", "note": "pmr discovers .epr files on disk"},
    "render.status": {"status": "both", "note": "pmr: event-driven, no job ids"},
    "render.watch": {"status": "both"},
    "render.queue": {"status": "dvr-only", "reason": "no enumerable render queue in UXP"},
    "render.formats": {"status": "dvr-only", "reason": "presets replace format/codec enums"},
    "render.codecs": {"status": "dvr-only", "reason": "presets replace format/codec enums"},
    "render.stop": {"status": "dvr-only", "reason": "no cancel API in UXP"},
    "render.clear": {"status": "dvr-only", "reason": "no queue to clear"},
    "render.export_frame": {"status": "both", "note": "pmr: Exporter.exportSequenceFrame"},
    "interchange.export": {"status": "both", "note": "pmr: fcpxml/otio/aaf (26.3+)"},
    "interchange.import": {"status": "dvr-only", "reason": "removed from UXP in 26.3"},
    "metadata.get": {"status": "pmr-only", "reason": "XMP metadata API"},
    "metadata.set": {"status": "pmr-only"},
    "source_monitor": {"status": "pmr-only", "reason": "source monitor control is Premiere-specific"},
    "properties.get": {"status": "pmr-only", "reason": "per-project key-value store"},
    "properties.set": {"status": "pmr-only"},
    "color.grade": {"status": "dvr-only", "reason": "no color-page equivalent in UXP"},
    "fusion": {"status": "dvr-only", "reason": "no Fusion equivalent in Premiere"},
    "gallery.stills": {"status": "dvr-only", "reason": "no gallery in Premiere"},
    "spec.apply": {"status": "both"},
    "spec.export": {"status": "both"},
    "diff.timelines": {"status": "both"},
    "diff.spec": {"status": "both"},
    "snapshot.save": {"status": "both"},
    "snapshot.restore": {"status": "both"},
    "lint": {"status": "both"},
    "eval": {"status": "both", "note": "dvr: Python; pmr: JavaScript inside Premiere"},
}

MARKER_TYPES = ["Comment", "Chapter", "Segmentation", "WebLink"]

MARKER_COLORS = [
    {"index": 0, "name": "Green"},
    {"index": 1, "name": "Red"},
    {"index": 2, "name": "Magenta"},
    {"index": 3, "name": "Orange"},
    {"index": 4, "name": "Yellow"},
    {"index": 5, "name": "Blue"},
    {"index": 6, "name": "Cyan"},
]

EXPORT_TYPES = [
    {"name": "immediately", "description": "Export now inside Premiere"},
    {"name": "queue_to_app", "description": "Queue in Premiere's export queue"},
    {"name": "queue_to_ame", "description": "Queue in Adobe Media Encoder"},
]

INTERCHANGE_FORMATS = [
    {"name": "fcpxml", "extension": ".xml", "direction": "export"},
    {"name": "otio", "extension": ".otio", "direction": "export"},
    {"name": "aaf", "extension": ".aaf", "direction": "export"},
]

SETTINGS_TOPIC = {
    "sequence": {
        "audio_channel_count": {"type": "int", "readonly": True},
        "audio_channel_type": {"type": "enum", "values": ["mono", "stereo", "5.1", "multi"]},
        "editing_mode": {"type": "str"},
        "video_pixel_aspect_ratio": {"type": "str"},
        "max_bit_depth": {"type": "bool"},
        "max_render_quality": {"type": "bool"},
    },
    "notes": "Premiere sequence settings are read via getSettings(); most video "
    "geometry is fixed by the sequence preset at creation time.",
}


def get_topic(topic: str, premiere: Premiere | None = None) -> Any:
    """Return the catalog for a topic. Live topics need a Premiere handle."""
    if topic == "parity":
        return {"operations": PARITY, "statuses": ["both", "dvr-only", "pmr-only"]}
    if topic == "marker-types":
        return MARKER_TYPES
    if topic == "marker-colors":
        return MARKER_COLORS
    if topic == "export-types":
        return EXPORT_TYPES
    if topic == "interchange-formats":
        return INTERCHANGE_FORMATS
    if topic == "media-kinds":
        from . import media

        return {
            "video": sorted(media.VIDEO_EXTENSIONS),
            "audio": sorted(media.AUDIO_EXTENSIONS),
            "image": sorted(media.IMAGE_EXTENSIONS),
        }
    if topic == "settings":
        return SETTINGS_TOPIC
    if topic == "render-presets":
        from .render import find_presets

        return find_presets()
    if topic in ("effects", "audio-effects", "transitions"):
        if premiere is None:
            raise errors.PmrError(
                f"Topic {topic!r} requires a running Premiere.",
                fix="Start Premiere with the pmr bridge panel open and retry.",
            )
        kind = {"effects": "video", "audio-effects": "audio", "transitions": "transition"}[topic]
        return premiere.effects.list(kind)
    raise errors.PmrError(
        f"Unknown schema topic: {topic!r}",
        fix=f"Valid topics: {', '.join(TOPICS)}",
    )


def parity_status(operation: str) -> dict[str, Any]:
    """Look up one operation in the parity matrix."""
    entry = PARITY.get(operation)
    if entry is None:
        return {"operation": operation, "status": "unknown"}
    return {"operation": operation, **entry}


__all__ = ["LIVE_TOPICS", "PARITY", "STATIC_TOPICS", "TOPICS", "get_topic", "parity_status"]
