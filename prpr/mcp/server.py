"""MCP server implementation.

Each tool is a thin wrapper around a single library method. Tools are
declared with explicit JSON schemas so MCP clients (Claude, Cursor,
others) can show the LLM exactly what arguments are accepted and what
shape the response will take.

Errors come back as :class:`prpr.errors.PrprError.to_dict` payloads
inside the tool's text content (with ``isError=True``) so the LLM can
read the ``cause`` / ``fix`` / ``state`` fields and recover.

Cross-app parity
----------------

Tools that exist in the sibling ``dvr`` project keep identical names
and parameter names wherever the semantic exists. Operations Premiere's
UXP API cannot perform (pages, clip properties, the render queue, ...)
are still registered and raise :class:`prpr.errors.NotSupportedError`,
which the error path serializes with ``cause``/``fix`` — agents get an
explicit, machine-readable "use the other app / do it manually" answer
instead of an unknown-tool failure. See ``prpr.schema.PARITY``.

Tool registry
-------------

The registry lives in :func:`build_registry`. Each entry pairs:

* a JSON schema understood by MCP clients,
* a description shown to the LLM,
* a handler ``(ctx, args) -> Any``,
* a flag indicating whether the handler needs a live Premiere connection.

Handlers that don't need Premiere (``version``, static schema topics,
``doctor``, ``media_scan``, ``render_presets``) work even without
Premiere Pro installed or running — useful for first-time setup and
Claude Desktop diagnostics.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__, errors
from .._js import snippet
from ..media import scan_media_files
from ..premiere import Premiere
from ..render import find_presets
from ..schema import TOPICS

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, Resource, TextContent, Tool
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The MCP server requires the `mcp` package. Reinstall with `pip install prpr`."
    ) from exc

logger = logging.getLogger("prpr.mcp")


# ---------------------------------------------------------------------------
# Connection cache (one per server lifetime)
# ---------------------------------------------------------------------------


class _PremiereCache:
    """Lazily connect on first tool call; reuse for the rest of the session.

    Also caches connection *failures* for ``failure_ttl`` seconds. Without
    this, every failed tool call would host a fresh bridge server and block
    waiting for the plugin to dial in; a series of failures (e.g. the bridge
    panel is closed) would each pay the full connect timeout. Caching the
    error lets the next 30+ tool calls return instantly with the same
    diagnostic instead.
    """

    def __init__(
        self,
        *,
        auto_launch: bool,
        timeout: float,
        failure_ttl: float = 30.0,
    ) -> None:
        self._auto_launch = auto_launch
        self._timeout = timeout
        self._failure_ttl = failure_ttl
        self._premiere: Premiere | None = None
        self._error: errors.PrprError | None = None
        self._error_at: float = 0.0

    def get(self) -> Premiere:
        """Return the cached :class:`Premiere` handle, connecting on first call.

        If the most recent connection attempt failed within the last
        ``failure_ttl`` seconds, re-raises the same structured error
        immediately rather than retrying.
        """
        import time

        if self._premiere is not None:
            return self._premiere
        if self._error is not None and (time.monotonic() - self._error_at) < self._failure_ttl:
            raise self._error
        try:
            self._premiere = Premiere(auto_launch=self._auto_launch, timeout=self._timeout)
            self._error = None
            self._error_at = 0.0
            return self._premiere
        except errors.PrprError as exc:
            self._error = exc
            self._error_at = time.monotonic()
            raise

    def reset(self) -> None:
        """Drop the cached connection and any cached error."""
        import contextlib

        if self._premiere is not None:
            with contextlib.suppress(Exception):  # boundary: best-effort cleanup
                self._premiere.close()
        self._premiere = None
        self._error = None
        self._error_at = 0.0


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ToolSpec:
    """One MCP tool: schema + handler + connection requirement."""

    name: str
    description: str
    schema: dict[str, Any] = field(default_factory=lambda: _empty_schema())
    needs_premiere: bool = True
    handler: Callable[[_Context, dict[str, Any]], Any] = lambda ctx, args: None


@dataclass
class _Context:
    """Per-call context passed to tool handlers."""

    cache: _PremiereCache

    def premiere(self) -> Premiere:
        return self.cache.get()


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


def _schema(
    properties: dict[str, dict[str, Any]],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        out["required"] = list(required)
    return out


def _not_supported(
    message: str,
    *,
    cause: str | None = None,
    fix: str | None = None,
) -> Callable[[_Context, dict[str, Any]], Any]:
    """Handler factory for the cross-app failure contract.

    The tool stays registered (identical name/params to dvr) but raises a
    structured :class:`NotSupportedError` without touching Premiere.
    """

    def handler(_ctx: _Context, _args: dict[str, Any]) -> Any:
        raise errors.NotSupportedError(message, cause=cause, fix=fix)

    return handler


def _timeline_for_args(ctx: _Context, args: dict[str, Any]) -> Any:
    """Resolve ``args['timeline']`` to a Timeline (default: the active one)."""
    p = ctx.premiere()
    name = args.get("timeline")
    if name:
        return p.timeline.get(name)
    tl = p.timeline.current
    if tl is None:
        raise errors.TimelineError(
            "No sequence is currently active.",
            fix="Open or create one (timeline_ensure), or pass `timeline` explicitly.",
        )
    return tl


# ---------------------------------------------------------------------------
# Handlers — meta
# ---------------------------------------------------------------------------


def _h_version(_ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    return {
        "prpr": __version__,
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }


def _h_doctor(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    """Diagnose the prpr <-> Premiere setup without raising on failure.

    By default this is a fast static probe (no connection attempt). Pass
    ``probe=true`` to additionally try a live connection (may take several
    seconds while the bridge waits for the plugin panel to dial in).
    """
    from ..doctor import diagnose

    out = diagnose(probe=False)
    # Whether the long-lived MCP cache already has a live connection or
    # is in the failure-cooldown window from a recent failed connect.
    out["connection_cached"] = ctx.cache._premiere is not None
    out["last_connection_error"] = (
        ctx.cache._error.to_dict() if ctx.cache._error is not None else None
    )
    if not bool(args.get("probe", False)):
        return out

    # Probe through the MCP connection cache (not a fresh Premiere()) so a
    # successful probe warms the cache for subsequent tool calls.
    try:
        p = ctx.cache.get()
        out["connected"] = True
        out["premiere_version"] = p.app.version
        out["premiere_product"] = p.app.product
        current = p.project.current
        out["current_project"] = current.name if current is not None else None
    except errors.PrprError as exc:
        out["connected"] = False
        out["connection_error"] = exc.to_dict()
    except Exception as exc:  # boundary
        out["connected"] = False
        out["connection_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    return out


def _h_reconnect(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    ctx.cache.reset()
    p = ctx.cache.get()
    return {
        "reconnected": True,
        "version": p.app.version,
        "product": p.app.product,
    }


def _h_ping(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    p = ctx.premiere()
    return {"connected": True, "version": p.app.version, "product": p.app.product}


def _h_inspect(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().inspect()


def _h_schema(ctx: _Context, args: dict[str, Any]) -> Any:
    from .. import schema as schema_mod

    topic = args["topic"]
    # Live topics connect lazily; static topics (and render-presets, which
    # scans disk) work without Premiere.
    if topic in ("effects", "audio-effects", "transitions"):
        return schema_mod.get_topic(topic, ctx.premiere())
    return schema_mod.get_topic(topic)


# ---------------------------------------------------------------------------
# Handlers — project
# ---------------------------------------------------------------------------


def _h_project_list(ctx: _Context, _args: dict[str, Any]) -> list[dict[str, Any]]:
    return list(ctx.premiere().project.list())


def _h_project_ensure(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().project.ensure(args["name"]).inspect()


def _h_project_current(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    current = ctx.premiere().project.current
    return current.inspect() if current else {"current": None}


def _h_project_save(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().project.save()


def _h_project_delete(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..project import _resolve_project_path

    p = ctx.premiere()
    name = args["name"]
    if bool(args.get("close_current", True)):
        current = p.project.current
        target = _resolve_project_path(name)
        if current is not None and current.path and Path(current.path) == target:
            current.close()
    return p.project.delete(name)


# ---------------------------------------------------------------------------
# Handlers — timeline
# ---------------------------------------------------------------------------


def _h_timeline_list(ctx: _Context, _args: dict[str, Any]) -> list[dict[str, Any]]:
    return list(ctx.premiere().timeline.list())


def _h_timeline_inspect(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    p = ctx.premiere()
    requested = args.get("name")
    tl = p.timeline.get(requested) if requested else p.timeline.current
    if tl is None:
        raise errors.TimelineError("No sequence is currently active.")
    return tl.inspect(names_only=bool(args.get("names_only", False)))


def _h_timeline_ensure(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().timeline.ensure(args["name"]).inspect(names_only=True)


def _h_timeline_switch(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().timeline.set_current(args["name"])


def _h_timeline_rename(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().timeline.get(args["name"]).rename(args["new_name"])


def _h_timeline_delete(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().timeline.delete(args["name"])


def _h_timeline_clear(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    tl = _timeline_for_args(ctx, args)
    track_type = args.get("track_type")
    track_indexes = args.get("track_indexes")
    ripple = bool(args.get("ripple", False))
    if track_indexes and not track_type:
        raise errors.TimelineError(
            "timeline_clear requires track_type when track_indexes is provided.",
            fix="Pass track_type='video', 'audio', or 'caption' with track_indexes.",
            state={"track_indexes": track_indexes},
        )
    kinds = [track_type] if track_type else ["video", "audio"]
    indexes = [int(i) for i in track_indexes] if track_indexes else None
    removed = 0
    for kind in kinds:
        result = tl.delete_clips(track_type=kind, track_indexes=indexes, ripple=ripple)
        removed += int(result.get("removed", 0) or 0)
    return {"timeline": tl.name, "deleted": removed, "ripple": ripple}


def _h_timeline_append(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    tl = _timeline_for_args(ctx, args)
    results: list[dict[str, Any]] = []
    for item in args["items"]:
        results.append(
            tl.insert(
                item.get("name"),
                item_path=item.get("path"),
                seconds=item.get("at_seconds"),
                video_track=int(item.get("video_track", 0)),
                audio_track=int(item.get("audio_track", 0)),
                # insert=true shifts later clips; default overwrites (append).
                overwrite=not bool(item.get("insert", False)),
            )
        )
    return {"timeline": tl.name, "appended": len(results), "results": results}


# ---------------------------------------------------------------------------
# Handlers — markers
# ---------------------------------------------------------------------------


def _h_marker_add(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    tl = _timeline_for_args(ctx, args)
    return tl.add_marker(
        float(args["seconds"]),
        name=args.get("name", "marker"),
        note=args.get("note", ""),
        marker_type=args.get("marker_type", "Comment"),
        duration_seconds=args.get("duration_seconds"),
        color_index=args.get("color_index"),
    )


def _h_marker_move(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.move_marker(
        float(args["to_seconds"]),
        name=args.get("name"),
        from_seconds=args.get("from_seconds"),
    )


def _h_marker_list(ctx: _Context, args: dict[str, Any]) -> list[dict[str, Any]]:
    return ctx.premiere().eval_js(
        snippet("marker_list"),
        {"sequence": args.get("timeline"), "clip_name": args.get("clip_name")},
    )


def _h_marker_remove(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    tl = _timeline_for_args(ctx, args)
    return tl.remove_marker(name=args.get("name"), seconds=args.get("seconds"))


# ---------------------------------------------------------------------------
# Handlers — clips
# ---------------------------------------------------------------------------


def _h_clip_where(ctx: _Context, args: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter clips on a timeline using safe predicate fields.

    The MCP boundary deliberately does *not* expose a Python lambda —
    instead, callers pick from a small, declarative DSL of safe filters.
    """
    tl = _timeline_for_args(ctx, args)
    track_type = args.get("track_type", "video")
    name_exact = args.get("name")
    name_contains = args.get("name_contains")
    track_index = args.get("track_index")
    duration_lt = args.get("duration_lt")
    duration_gt = args.get("duration_gt")

    rows: list[dict[str, Any]] = []
    for item in tl.items(track_type):
        if track_index is not None and item.track_index != int(track_index):
            continue
        if name_exact is not None and item.name != name_exact:
            continue
        if name_contains is not None and name_contains not in (item.name or ""):
            continue
        frames = item.duration_frames
        if duration_lt is not None and not (frames is not None and frames < int(duration_lt)):
            continue
        if duration_gt is not None and not (frames is not None and frames > int(duration_gt)):
            continue
        rows.append(
            {
                "name": item.name,
                "track_type": item.track_type,
                "track_index": item.track_index,
                "duration_frames": frames,
                "start_seconds": item.start,
                "end_seconds": item.end,
                "enabled": item.enabled,
            }
        )
    return rows


def _h_clip_update(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    tl = _timeline_for_args(ctx, args)
    kwargs: dict[str, Any] = {}
    for key in (
        "track_type",
        "track_index",
        "name",
        "name_contains",
        "set_name",
        "set_disabled",
        "shift_seconds",
    ):
        if args.get(key) is not None:
            kwargs[key] = args[key]
    return tl._clip_update(**kwargs)


# ---------------------------------------------------------------------------
# Handlers — effects / transitions / components (prpr-only)
# ---------------------------------------------------------------------------


def _h_effects_list(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().effects.list(args.get("kind", "video"))


def _h_effect_apply(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().effects.apply(
        args["name"],
        kind=args.get("kind", "video"),
        timeline=args.get("timeline"),
        clip_name=args.get("clip_name"),
        track_index=args.get("track_index"),
    )


def _h_transition_add(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().effects.add_transition(
        args.get("match_name", "AE.ADBE Cross Dissolve New"),
        timeline=args.get("timeline"),
        clip_name=args.get("clip_name"),
        track_index=args.get("track_index"),
        duration_seconds=args.get("duration_seconds"),
        apply_to_start=args.get("apply_to_start"),
    )


def _h_clip_components(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().effects.components(
        timeline=args.get("timeline"),
        clip_name=args.get("clip_name"),
        track_index=args.get("track_index"),
        kind=args.get("kind", "video"),
        with_values=bool(args.get("with_values", False)),
        at_seconds=float(args.get("at_seconds", 0.0)),
    )


def _h_effect_param_set(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().effects.set_param(
        args["component"],
        args["param"],
        args["value"],
        timeline=args.get("timeline"),
        clip_name=args.get("clip_name"),
        track_index=args.get("track_index"),
        kind=args.get("kind", "video"),
        at_seconds=args.get("at_seconds"),
    )


def _h_timeline_insert_mogrt(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.insert_mogrt(
        args["path"],
        seconds=args.get("seconds"),
        video_track=int(args.get("video_track", 0)),
        audio_track=int(args.get("audio_track", 0)),
    )


def _h_timeline_scene_detect(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.scene_edit_detection(
        operation=args.get("operation", "cut"),
        clip_name=args.get("clip_name"),
        track_index=args.get("track_index"),
    )


def _h_timeline_work_area(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.work_area(args.get("in_seconds"), args.get("out_seconds"))


def _h_timeline_keyframes(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.keyframes(
        args["component"],
        args["param"],
        clip_name=args.get("clip_name"),
        track_index=args.get("track_index"),
        kind=args.get("kind", "video"),
    )


def _h_timeline_track(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.track_update(
        int(args["track_index"]),
        track_type=args.get("track_type", "video"),
        mute=args.get("mute"),
        set_name=args.get("set_name"),
    )


def _h_timeline_clone(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.clone()


def _h_timeline_subsequence(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.create_subsequence(
        ignore_track_targeting=bool(args.get("ignore_track_targeting", True))
    )


def _h_timeline_in_out(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    return timeline.set_in_out(args.get("in_seconds"), args.get("out_seconds"))


def _h_timeline_create_from_media(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    tl = ctx.premiere().timeline.create_from_media(
        args["name"], list(args["items"]), bin=args.get("bin")
    )
    return tl.inspect(names_only=True)


def _h_timeline_selection(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from ..timeline import Timeline

    timeline = Timeline(ctx.premiere(), args.get("timeline"))
    if bool(args.get("clear", False)):
        return timeline.select(clear=True)
    return timeline.selection()


def _h_media_subclip(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.create_subclip(
        args["subclip_name"],
        float(args["start_seconds"]),
        float(args["end_seconds"]),
        name=args.get("name"),
        path=args.get("path"),
        hard_boundaries=bool(args.get("hard_boundaries", False)),
        take_video=args.get("take_video", True),
        take_audio=args.get("take_audio", True),
    )


def _h_media_attach_proxy(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.attach_proxy(
        args["proxy_path"],
        name=args.get("name"),
        path=args.get("path"),
        is_hi_res=bool(args.get("is_hi_res", False)),
    )


def _h_media_transcribe(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.transcript_export(name=args.get("name"), path=args.get("path"))


# ---------------------------------------------------------------------------
# Handlers — media
# ---------------------------------------------------------------------------


def _h_media_inspect(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.inspect(with_paths=bool(args.get("with_paths", True)))


def _h_media_bins(ctx: _Context, _args: dict[str, Any]) -> list[dict[str, Any]]:
    return ctx.premiere().media.bins()


def _h_media_ls(ctx: _Context, args: dict[str, Any]) -> list[dict[str, Any]]:
    return ctx.premiere().media.ls(args.get("bin"))


def _h_media_import(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.import_(args["paths"], bin=args.get("bin"))


def _h_media_scan(_ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    files = scan_media_files(
        args["path"],
        recursive=bool(args.get("recursive", True)),
        include_hidden=bool(args.get("include_hidden", False)),
        max_files=int(args.get("max_files", 10000)),
    )
    counts: dict[str, int] = {}
    for item in files:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "path": str(Path(args["path"]).expanduser()),
        "file_count": len(files),
        "counts": counts,
        "files": files,
    }


def _h_media_bin_ensure(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.bin_ensure(args["path"])


def _h_media_bin_delete(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.bin_delete(args["path"])


def _h_media_move(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.move(
        args["target_bin"],
        source_bin=args.get("source_bin"),
        name_contains=args.get("name_contains"),
        names=args.get("names"),
    )


def _h_media_color_label(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.color_label(
        name=args.get("name"),
        path=args.get("path"),
        set_index=args.get("set_index"),
    )


def _h_media_bin_rename(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.bin_rename(args["path"], args["new_name"])


def _h_media_smart_bin(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.smart_bin(args["name"], args["query"])


def _h_media_footage_interpretation(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.footage_interpretation(
        name=args.get("name"),
        path=args.get("path"),
        set=args.get("set"),
    )


def _h_media_purge_cache(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().media.purge_cache()


# ---------------------------------------------------------------------------
# Handlers — project (library surface)
# ---------------------------------------------------------------------------


def _h_project_scratch_disks(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return (
        ctx.premiere()
        .project.require_current()
        .scratch_disks(
            set_type=args.get("set_type"),
            set_path=args.get("set_path"),
        )
    )


def _h_project_ingest(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().project.require_current().ingest(args.get("enabled"))


def _h_project_color_settings(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().project.require_current().color_settings()


def _h_project_import_sequences(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return (
        ctx.premiere()
        .project.require_current()
        .import_sequences(
            args["project_path"],
            args.get("sequence_guids"),
        )
    )


def _h_project_import_ae_comps(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return (
        ctx.premiere()
        .project.require_current()
        .import_ae_comps(
            args["aep_path"],
            args.get("comp_names"),
            bin=args.get("bin"),
        )
    )


def _h_app_preference(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().app.preference(
        args["key"],
        args.get("value"),
        persistent=bool(args.get("persistent", True)),
    )


# ---------------------------------------------------------------------------
# Handlers — render / export
# ---------------------------------------------------------------------------


def _h_render_presets(_ctx: _Context, _args: dict[str, Any]) -> list[dict[str, str]]:
    return find_presets()


def _h_render_submit(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    job = ctx.premiere().render.submit(
        target_dir=args["target_dir"],
        custom_name=args.get("custom_name"),
        preset=args.get("preset"),
        timeline=args.get("timeline"),
        queue_to=args.get("queue_to"),
        wait=bool(args.get("wait", False)),
        timeout=float(args.get("timeout", 3600.0)),
    )
    return job.inspect()


def _h_render_frame(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().render.export_frame(
        float(args["seconds"]),
        args["file"],
        timeline=args.get("timeline"),
        width=int(args.get("width", 0)),
        height=int(args.get("height", 0)),
    )


def _h_render_watch(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    timeout = float(args.get("timeout", 60.0))
    events = list(ctx.premiere().render.watch(timeout=timeout))
    terminal = any(
        token in str(event.get("name", "")).upper()
        for event in events
        for token in ("COMPLETE", "ERROR", "CANCEL")
    )
    return {"events": events, "count": len(events), "terminal": terminal, "timeout": timeout}


def _h_render_ame_status(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().render.ame_status()


# ---------------------------------------------------------------------------
# Handlers — interchange / metadata / source monitor
# ---------------------------------------------------------------------------


def _h_interchange_export(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import interchange

    return interchange.export_timeline(
        ctx.premiere(),
        args["file_path"],
        format=args.get("format"),
        timeline=args.get("timeline"),
    )


def _h_interchange_import(_ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import interchange

    # Raises NotSupportedError before touching Premiere — single source of
    # truth for the message lives in prpr.interchange.
    return interchange.import_timeline(None, args.get("file_path", ""))  # type: ignore[arg-type]


def _h_metadata_get(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().eval_js(
        snippet("metadata_get"),
        {"name": args.get("name"), "path": args.get("path"), "kind": args.get("kind")},
    )


def _h_metadata_set_xmp(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().eval_js(
        snippet("metadata_set_xmp"),
        {"name": args.get("name"), "path": args.get("path"), "xmp": args["xmp"]},
    )


def _h_source_monitor(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    return ctx.premiere().eval_js(
        snippet("source_monitor"),
        {
            "op": args["op"],
            "path": args.get("path"),
            "name": args.get("name"),
            "seconds": args.get("seconds"),
            "speed": args.get("speed"),
        },
    )


# ---------------------------------------------------------------------------
# Handlers — diff / spec / snapshot / lint
# ---------------------------------------------------------------------------


def _h_diff_timelines(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import diff

    return diff.compare_timelines(ctx.premiere(), args["a"], args["b"]).to_dict()


def _h_diff_to_spec(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import diff
    from .. import spec as spec_mod

    parsed = spec_mod.load_spec(args["spec_path"])
    return diff.compare_to_spec(ctx.premiere(), parsed).to_dict()


def _h_apply_spec(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import spec as spec_mod

    parsed = spec_mod.load_spec(args["spec_path"])
    result = spec_mod.apply(
        parsed,
        ctx.premiere(),
        dry_run=bool(args.get("dry_run", False)),
        verify=bool(args.get("verify", False)),
    )
    return {"spec": str(args["spec_path"]), **result}


def _h_spec_export(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import spec as spec_mod

    data = spec_mod.from_live(ctx.premiere())
    out = args.get("out")
    if not out:
        return data
    import yaml

    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(data, indent=2))
    else:
        path.write_text(yaml.safe_dump(data, sort_keys=False))
    return {"written": str(path), "spec": data}


def _h_snapshot_save(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import snapshot as snap_mod

    snap = snap_mod.capture(ctx.premiere(), name=args.get("name") or None)
    snap_path = snap_mod.save(snap)
    return {
        "name": snap.name,
        "project": snap.project,
        "captured_at": snap.captured_at,
        "path": str(snap_path),
    }


def _h_snapshot_list(_ctx: _Context, _args: dict[str, Any]) -> list[dict[str, Any]]:
    from .. import snapshot as snap_mod

    return snap_mod.list_snapshots()


def _h_snapshot_restore(ctx: _Context, args: dict[str, Any]) -> dict[str, Any]:
    from .. import snapshot as snap_mod

    snap = snap_mod.load(args["name"])
    counts = snap_mod.restore(ctx.premiere(), snap, dry_run=bool(args.get("dry_run", False)))
    return {"snapshot": snap.name, "project": snap.project, **counts}


def _h_lint(ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    from .. import lint as lint_mod

    return lint_mod.lint(ctx.premiere()).to_dict()


# ---------------------------------------------------------------------------
# Handlers — plugin / setup
# ---------------------------------------------------------------------------


def _h_plugin_install(_ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    from .. import connection

    return connection.install_plugin()


def _h_plugin_status(_ctx: _Context, _args: dict[str, Any]) -> dict[str, Any]:
    from .. import connection

    status = connection.plugin_installed()
    status["premiere_running"] = connection.premiere_process_running()
    status["upia_available"] = connection.upia_path() is not None
    return status


# ---------------------------------------------------------------------------
# Handlers — power-user (eval, gated)
# ---------------------------------------------------------------------------


def _h_eval(ctx: _Context, args: dict[str, Any]) -> Any:
    if os.environ.get("PRPR_MCP_ENABLE_EVAL", "0") not in ("1", "true", "yes"):
        raise errors.PrprError(
            "The `eval` tool is disabled by default.",
            cause=(
                "Arbitrary JavaScript execution inside Premiere is risky in agent "
                "contexts; PRPR_MCP_ENABLE_EVAL is not set."
            ),
            fix=(
                "Restart the MCP server with PRPR_MCP_ENABLE_EVAL=1 in its environment "
                "if you really want to enable eval."
            ),
        )
    return ctx.premiere().eval_js(args["code"])


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_PAGE_NAMES = ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver")

_CLIP_FILTER_PROPS: dict[str, dict[str, Any]] = {
    "timeline": {"type": "string"},
    "track_type": {"type": "string", "enum": ["video", "audio", "caption"]},
    "track_index": {"type": "integer"},
    "name": {"type": "string"},
    "name_contains": {"type": "string"},
    "duration_lt": {"type": "integer"},
    "duration_gt": {"type": "integer"},
    "dry_run": {"type": "boolean", "default": False},
}


def build_registry() -> list[_ToolSpec]:
    return [
        # ---- meta / no Premiere required --------------------------------
        _ToolSpec(
            name="version",
            description="Return the prpr package version, Python version, and platform.",
            handler=_h_version,
            needs_premiere=False,
        ),
        _ToolSpec(
            name="doctor",
            description=(
                "Diagnose the prpr -> Adobe Premiere Pro setup. Reports installed apps, "
                "whether Premiere is running, bridge plugin install status, port "
                "availability, and any structured connection error. Fast by default; "
                "pass probe=true to also attempt a live connection. Never raises."
            ),
            schema=_schema(
                {
                    "probe": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "If true, attempt a live connection. May block several "
                            "seconds while the bridge waits for the plugin panel."
                        ),
                    }
                }
            ),
            handler=_h_doctor,
            needs_premiere=False,
        ),
        _ToolSpec(
            name="reconnect",
            description=(
                "Drop the cached Premiere connection and reconnect. Use after "
                "Premiere was relaunched or the bridge panel was just opened."
            ),
            handler=_h_reconnect,
            needs_premiere=False,
        ),
        _ToolSpec(
            name="schema",
            description=(
                "Discoverable catalog of valid values. Topics include parity (the "
                "dvr<->prpr support matrix), marker-types, marker-colors, export-types, "
                "interchange-formats, media-kinds, settings, plus live topics "
                "(effects, audio-effects, transitions require a running Premiere; "
                "render-presets scans .epr files on disk)."
            ),
            schema=_schema(
                {"topic": {"type": "string", "enum": list(TOPICS)}},
                required=["topic"],
            ),
            handler=_h_schema,
            needs_premiere=False,  # static topics skip the connect; live topics
            # connect lazily inside the handler.
        ),
        _ToolSpec(
            name="snapshot_list",
            description="List snapshots on disk, newest first. Does not require Premiere.",
            handler=_h_snapshot_list,
            needs_premiere=False,
        ),
        # ---- live: app ---------------------------------------------------
        _ToolSpec(
            name="ping",
            description="Verify the connection to Adobe Premiere Pro. Returns version info.",
            handler=_h_ping,
        ),
        _ToolSpec(
            name="inspect",
            description=(
                "One-call snapshot of app, current project, and current sequence. "
                "Most efficient way to read state before deciding what to do."
            ),
            handler=_h_inspect,
        ),
        _ToolSpec(
            name="page_get",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Premiere has no scriptable "
                "page/workspace switching; calling this returns a structured "
                "NotSupportedError explaining the gap."
            ),
            handler=_not_supported(
                "Premiere Pro has no scriptable page/workspace switching in the UXP API.",
                cause="DaVinci Resolve pages (edit/color/deliver) have no Premiere equivalent.",
                fix="Switch workspaces manually in Premiere; this is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="page_set",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Premiere has no scriptable "
                "page/workspace switching; calling this returns a structured "
                "NotSupportedError explaining the gap."
            ),
            schema=_schema(
                {"name": {"type": "string", "enum": list(_PAGE_NAMES)}},
                required=["name"],
            ),
            handler=_not_supported(
                "Premiere Pro has no scriptable page/workspace switching in the UXP API.",
                cause="DaVinci Resolve pages (edit/color/deliver) have no Premiere equivalent.",
                fix="Switch workspaces manually in Premiere; this is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        # ---- project -----------------------------------------------------
        _ToolSpec(
            name="project_list",
            description="List projects currently open in Premiere (name, path, guid).",
            handler=_h_project_list,
        ),
        _ToolSpec(
            name="project_ensure",
            description=(
                "Open a project by name, creating <projects-dir>/<name>.prproj if it "
                "does not exist (a path with '/' or '.prproj' is used verbatim). Idempotent."
            ),
            schema=_schema({"name": {"type": "string"}}, required=["name"]),
            handler=_h_project_ensure,
        ),
        _ToolSpec(
            name="project_current",
            description="Inspect the currently open project (sequences, bin/item counts).",
            handler=_h_project_current,
        ),
        _ToolSpec(
            name="project_settings_get",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Premiere's UXP API exposes no "
                "project-settings dict; sequence settings are readable via "
                "timeline_inspect (settings key)."
            ),
            schema=_schema({"keys": {"type": "array", "items": {"type": "string"}}}),
            handler=_not_supported(
                "Premiere's UXP API has no project-settings dictionary.",
                cause="Resolve's GetSetting/SetSetting project store has no Premiere equivalent.",
                fix=(
                    "Read per-sequence settings from timeline_inspect (the `settings` "
                    "key); project settings are a dvr-only operation."
                ),
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="project_save",
            description="Save the currently open project.",
            handler=_h_project_save,
        ),
        _ToolSpec(
            name="project_scratch_disks",
            description=(
                "Read (or set one of) the current project's scratch disk paths. "
                "Types: capture, video_preview, audio_preview, auto_save, "
                "ccl_libraries, capsule_media. prpr-only tool."
            ),
            schema=_schema(
                {
                    "set_type": {"type": "string"},
                    "set_path": {"type": "string"},
                }
            ),
            handler=_h_project_scratch_disks,
        ),
        _ToolSpec(
            name="project_ingest",
            description=(
                "Read (or set with enabled) whether ingest is enabled for the "
                "current project. prpr-only tool."
            ),
            schema=_schema({"enabled": {"type": "boolean"}}),
            handler=_h_project_ingest,
        ),
        _ToolSpec(
            name="project_color_settings",
            description=("Read the current project's color settings (graphics white luminance)."),
            handler=_h_project_color_settings,
        ),
        _ToolSpec(
            name="project_import_sequences",
            description=(
                "Import sequences from another .prproj into the current project "
                "(all of them when sequence_guids is omitted). prpr-only tool."
            ),
            schema=_schema(
                {
                    "project_path": {"type": "string"},
                    "sequence_guids": {"type": "array", "items": {"type": "string"}},
                },
                required=["project_path"],
            ),
            handler=_h_project_import_sequences,
        ),
        _ToolSpec(
            name="project_import_ae_comps",
            description=(
                "Import After Effects comps from an .aep into the current project "
                "(all of them when comp_names is omitted), optionally into a bin. "
                "prpr-only tool."
            ),
            schema=_schema(
                {
                    "aep_path": {"type": "string"},
                    "comp_names": {"type": "array", "items": {"type": "string"}},
                    "bin": {"type": "string"},
                },
                required=["aep_path"],
            ),
            handler=_h_project_import_ae_comps,
        ),
        _ToolSpec(
            name="project_delete",
            description=(
                "Delete a project file (.prproj) from disk. Closes it first when it "
                "is the currently open project and close_current is true."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "close_current": {"type": "boolean", "default": True},
                },
                required=["name"],
            ),
            handler=_h_project_delete,
        ),
        # ---- timeline (sequence) ------------------------------------------
        _ToolSpec(
            name="timeline_list",
            description="List sequences in the currently open project (name, fps, is_active).",
            handler=_h_timeline_list,
        ),
        _ToolSpec(
            name="timeline_inspect",
            description=(
                "Return a structured snapshot of a sequence (tracks, clips, markers, "
                "settings). Pass names_only=true for a faster track/count summary "
                "without per-clip detail."
            ),
            schema=_schema(
                {
                    "name": {
                        "type": "string",
                        "description": "Sequence name. Defaults to the active sequence.",
                    },
                    "names_only": {"type": "boolean", "default": False},
                }
            ),
            handler=_h_timeline_inspect,
        ),
        _ToolSpec(
            name="timeline_ensure",
            description="Get-or-create a sequence by name in the current project. Idempotent.",
            schema=_schema({"name": {"type": "string"}}, required=["name"]),
            handler=_h_timeline_ensure,
        ),
        _ToolSpec(
            name="timeline_switch",
            description="Set a sequence as the active one.",
            schema=_schema({"name": {"type": "string"}}, required=["name"]),
            handler=_h_timeline_switch,
        ),
        _ToolSpec(
            name="timeline_rename",
            description="Rename a sequence in the current project.",
            schema=_schema(
                {"name": {"type": "string"}, "new_name": {"type": "string"}},
                required=["name", "new_name"],
            ),
            handler=_h_timeline_rename,
        ),
        _ToolSpec(
            name="timeline_delete",
            description="Delete a sequence from the current project.",
            schema=_schema({"name": {"type": "string"}}, required=["name"]),
            handler=_h_timeline_delete,
        ),
        _ToolSpec(
            name="timeline_clear",
            description=(
                "Delete timeline items from the current or named sequence. Can be "
                "scoped by track_type and 0-based track_indexes. Without track_type, "
                "clears both video and audio tracks."
            ),
            schema=_schema(
                {
                    "timeline": {"type": "string"},
                    "track_type": {"type": "string", "enum": ["video", "audio", "caption"]},
                    "track_indexes": {"type": "array", "items": {"type": "integer"}},
                    "ripple": {"type": "boolean", "default": False},
                }
            ),
            handler=_h_timeline_clear,
        ),
        _ToolSpec(
            name="timeline_append",
            description=(
                "Add project items to a sequence in order. Each item is looked up by "
                "media-pool name or file path. Defaults to appending at the end "
                "(overwrite edit); pass at_seconds to place at a time, insert=true "
                "to shift later clips instead of overwriting. Track indexes are 0-based."
            ),
            schema=_schema(
                {
                    "timeline": {"type": "string"},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Project-panel item name (alternative to path).",
                                },
                                "path": {
                                    "type": "string",
                                    "description": "Media file path of an imported item.",
                                },
                                "video_track": {"type": "integer", "default": 0},
                                "audio_track": {"type": "integer", "default": 0},
                                "at_seconds": {
                                    "type": "number",
                                    "description": "Timeline position. Default: sequence end.",
                                },
                                "insert": {
                                    "type": "boolean",
                                    "default": False,
                                    "description": "Shift later clips instead of overwriting.",
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                required=["items"],
            ),
            handler=_h_timeline_append,
        ),
        _ToolSpec(
            name="timeline_add_title",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Premiere's UXP API cannot "
                "create title/text clips programmatically; calling this returns a "
                "structured NotSupportedError explaining the gap."
            ),
            schema=_schema(
                {
                    "title": {"type": "string", "default": "Text+"},
                    "text": {"type": "string"},
                    "font": {"type": "string"},
                    "size": {"type": "number"},
                    "color": {"description": "Hex '#ffcc00', a name, or [r,g,b] floats."},
                    "timecode": {"type": "string"},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_not_supported(
                "Premiere's UXP API cannot create title/text clips programmatically.",
                cause="There is no Text+/title factory in UXP; titles are MOGRT-based.",
                fix=(
                    "Add a Motion Graphics template (MOGRT) from the Essential Graphics "
                    "panel in Premiere; programmatic titles are a dvr-only operation."
                ),
            ),
            needs_premiere=False,
        ),
        # ---- markers -------------------------------------------------------
        _ToolSpec(
            name="marker_add",
            description="Add a marker to a sequence at the given time (seconds).",
            schema=_schema(
                {
                    "seconds": {"type": "number"},
                    "name": {"type": "string", "default": "marker"},
                    "note": {"type": "string"},
                    "marker_type": {
                        "type": "string",
                        "enum": ["Comment", "Chapter", "Segmentation", "WebLink"],
                        "default": "Comment",
                    },
                    "duration_seconds": {"type": "number"},
                    "color_index": {
                        "type": "integer",
                        "description": "0-6; see schema topic marker-colors.",
                    },
                    "timeline": {
                        "type": "string",
                        "description": "Sequence name. Defaults to the active sequence.",
                    },
                },
                required=["seconds"],
            ),
            handler=_h_marker_add,
        ),
        _ToolSpec(
            name="marker_move",
            description=(
                "Move a marker (matched by name and/or its current position, "
                "from_seconds) to a new time (to_seconds) on a sequence."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "from_seconds": {
                        "type": "number",
                        "description": "Current marker position to match.",
                    },
                    "to_seconds": {"type": "number"},
                    "timeline": {"type": "string"},
                },
                required=["to_seconds"],
            ),
            handler=_h_marker_move,
        ),
        _ToolSpec(
            name="marker_list",
            description=(
                "List markers on a sequence (default: the active one), or on a "
                "project-panel clip when clip_name is given."
            ),
            schema=_schema(
                {
                    "timeline": {"type": "string"},
                    "clip_name": {"type": "string"},
                }
            ),
            handler=_h_marker_list,
        ),
        _ToolSpec(
            name="marker_remove",
            description=(
                "Remove the first marker matching name and/or time (seconds) from a sequence."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "seconds": {"type": "number"},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_marker_remove,
        ),
        # ---- clips ---------------------------------------------------------
        _ToolSpec(
            name="clip_where",
            description=(
                "Find timeline items by safe declarative filters. Returns a list of "
                "{name, track_type, track_index, duration_frames, start_seconds, "
                "end_seconds, enabled}."
            ),
            schema=_schema(
                {
                    "track_type": {
                        "type": "string",
                        "enum": ["video", "audio", "caption"],
                        "default": "video",
                    },
                    "name": {"type": "string", "description": "Exact item name match."},
                    "name_contains": {
                        "type": "string",
                        "description": "Substring match on the item name.",
                    },
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "duration_lt": {
                        "type": "integer",
                        "description": "Match items with duration (frames) strictly less than this.",
                    },
                    "duration_gt": {
                        "type": "integer",
                        "description": "Match items with duration (frames) strictly greater than this.",
                    },
                    "timeline": {
                        "type": "string",
                        "description": "Sequence name. Defaults to the active sequence.",
                    },
                }
            ),
            handler=_h_clip_where,
        ),
        _ToolSpec(
            name="clip_update",
            description=(
                "Update timeline items selected by safe filters: rename (set_name), "
                "enable/disable (set_disabled), or move in time (shift_seconds). "
                "All updates land as one undo step."
            ),
            schema=_schema(
                {
                    "set_name": {"type": "string"},
                    "set_disabled": {"type": "boolean"},
                    "shift_seconds": {"type": "number"},
                    "timeline": {"type": "string"},
                    "track_type": {
                        "type": "string",
                        "enum": ["video", "audio", "caption"],
                        "default": "video",
                    },
                    "track_index": {"type": "integer"},
                    "name": {"type": "string"},
                    "name_contains": {"type": "string"},
                }
            ),
            handler=_h_clip_update,
        ),
        _ToolSpec(
            name="clip_set_properties",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Premiere has no generic "
                "clip-property dictionary; use clip_components to inspect a clip's "
                "effect chain and effect_apply to change it."
            ),
            schema=_schema(
                {
                    "properties": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    **_CLIP_FILTER_PROPS,
                },
                required=["properties"],
            ),
            handler=_not_supported(
                "Premiere has no generic clip-property dictionary.",
                cause="Resolve's TimelineItem SetProperty API has no UXP equivalent; "
                "clip attributes live on the component (effect) chain.",
                fix="Inspect with clip_components and modify via effect_apply; "
                "clip_set_properties is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="clip_transform",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Transform lives on the Motion "
                "component; use clip_components to read it."
            ),
            schema=_schema(
                {
                    "pan": {"type": "number"},
                    "tilt": {"type": "number"},
                    "zoom": {"type": "number"},
                    "rotation": {"type": "number"},
                    **_CLIP_FILTER_PROPS,
                }
            ),
            handler=_not_supported(
                "Premiere exposes transform via the Motion component chain, not clip properties.",
                cause="Resolve's Pan/Tilt/Zoom clip properties have no UXP equivalent.",
                fix="Use clip_components (component 'Motion') to inspect transform "
                "parameters; clip_transform is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="clip_crop",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Crop is an effect in Premiere; "
                "apply it with effect_apply and inspect it with clip_components."
            ),
            schema=_schema(
                {
                    "crop_left": {"type": "number"},
                    "crop_right": {"type": "number"},
                    "crop_top": {"type": "number"},
                    "crop_bottom": {"type": "number"},
                    **_CLIP_FILTER_PROPS,
                }
            ),
            handler=_not_supported(
                "Premiere has no crop clip properties; crop is an ordinary video effect.",
                fix="Apply the Crop effect with effect_apply and inspect it with "
                "clip_components; clip_crop is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="clip_reset",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). There are no resettable clip "
                "property groups; effects live on the component chain."
            ),
            schema=_schema(
                {
                    "groups": {"type": "array", "items": {"type": "string"}},
                    **_CLIP_FILTER_PROPS,
                }
            ),
            handler=_not_supported(
                "Premiere has no resettable clip property groups.",
                cause="Resolve's transform/crop/composite property groups have no UXP equivalent.",
                fix="Inspect the component chain with clip_components and adjust via "
                "effect_apply; clip_reset is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        # ---- effects / transitions (prpr-only) ------------------------------
        _ToolSpec(
            name="effects_list",
            description=(
                "List available effects by kind: video (match names + display names), "
                "audio (display names), or transition (match names). prpr-only tool."
            ),
            schema=_schema(
                {
                    "kind": {
                        "type": "string",
                        "enum": ["video", "audio", "transition"],
                        "default": "video",
                    }
                }
            ),
            handler=_h_effects_list,
        ),
        _ToolSpec(
            name="effect_apply",
            description=(
                "Apply an effect to timeline clips matched by clip_name / track_index "
                "(video: matchName from effects_list; audio: display name). prpr-only tool."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["video", "audio"], "default": "video"},
                    "clip_name": {"type": "string"},
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "timeline": {"type": "string"},
                },
                required=["name"],
            ),
            handler=_h_effect_apply,
        ),
        _ToolSpec(
            name="transition_add",
            description=(
                "Apply a video transition to matching clips (default: Cross Dissolve). "
                "Get match names from effects_list kind=transition. prpr-only tool."
            ),
            schema=_schema(
                {
                    "match_name": {
                        "type": "string",
                        "default": "AE.ADBE Cross Dissolve New",
                    },
                    "clip_name": {"type": "string"},
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "duration_seconds": {"type": "number"},
                    "apply_to_start": {
                        "type": "boolean",
                        "description": "Apply at the clip head instead of the tail.",
                    },
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_transition_add,
        ),
        _ToolSpec(
            name="clip_components",
            description=(
                "Inspect a timeline clip's component chain (intrinsics like "
                "Motion/Opacity plus applied effects) with parameter names, and "
                "values when with_values=true. prpr-only tool."
            ),
            schema=_schema(
                {
                    "clip_name": {"type": "string"},
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "kind": {"type": "string", "enum": ["video", "audio"], "default": "video"},
                    "with_values": {"type": "boolean", "default": False},
                    "at_seconds": {
                        "type": "number",
                        "default": 0.0,
                        "description": "Sample time for parameter values.",
                    },
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_clip_components,
        ),
        _ToolSpec(
            name="effect_param_set",
            description=(
                "Set a component parameter on a clip — transforms (Motion/Scale, "
                "Position, Rotation), Opacity, or any applied effect's params. "
                "Pass at_seconds to write a keyframe instead of a static value. "
                "Values: number, boolean, string, [x, y] point, or {r,g,b,a} "
                "color. prpr-only tool."
            ),
            schema=_schema(
                {
                    "component": {
                        "type": "string",
                        "description": "Component display or match name, e.g. 'Motion', 'Opacity'.",
                    },
                    "param": {
                        "type": "string",
                        "description": "Parameter display name, e.g. 'Scale', 'Position'.",
                    },
                    "value": {
                        "description": "number | boolean | string | [x, y] | {r,g,b,a}",
                    },
                    "clip_name": {"type": "string"},
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "kind": {"type": "string", "enum": ["video", "audio"], "default": "video"},
                    "at_seconds": {
                        "type": "number",
                        "description": "Keyframe time; omit for a static value.",
                    },
                    "timeline": {"type": "string"},
                },
                required=["component", "param", "value"],
            ),
            handler=_h_effect_param_set,
        ),
        _ToolSpec(
            name="timeline_insert_mogrt",
            description=(
                "Insert a Motion Graphics template (.mogrt) into a sequence at a "
                "time (defaults to the end). prpr-only tool."
            ),
            schema=_schema(
                {
                    "path": {"type": "string", "description": "Absolute path to the .mogrt."},
                    "seconds": {"type": "number"},
                    "video_track": {"type": "integer", "default": 0},
                    "audio_track": {"type": "integer", "default": 0},
                    "timeline": {"type": "string"},
                },
                required=["path"],
            ),
            handler=_h_timeline_insert_mogrt,
        ),
        _ToolSpec(
            name="timeline_scene_detect",
            description=(
                "Run scene edit detection on matching clips: apply cuts, create "
                "markers, or create subclips at detected scene changes. Long "
                "operation. prpr-only tool."
            ),
            schema=_schema(
                {
                    "operation": {
                        "type": "string",
                        "enum": ["cut", "marker", "subclip"],
                        "default": "cut",
                    },
                    "clip_name": {"type": "string"},
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_timeline_scene_detect,
        ),
        _ToolSpec(
            name="timeline_work_area",
            description=(
                "Read (or set) a sequence's work area in/out points (Premiere "
                "26.5+). Omit both args to read; pass in_seconds/out_seconds to set."
            ),
            schema=_schema(
                {
                    "in_seconds": {"type": "number"},
                    "out_seconds": {"type": "number"},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_timeline_work_area,
        ),
        _ToolSpec(
            name="timeline_keyframes",
            description=(
                "List keyframe times for a clip's component parameter. Identify "
                "the clip by clip_name / track_index; component/param are display "
                "or match names (see clip_components). prpr-only tool."
            ),
            schema=_schema(
                {
                    "component": {"type": "string"},
                    "param": {"type": "string"},
                    "clip_name": {"type": "string"},
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "kind": {"type": "string", "enum": ["video", "audio"], "default": "video"},
                    "timeline": {"type": "string"},
                },
                required=["component", "param"],
            ),
            handler=_h_timeline_keyframes,
        ),
        _ToolSpec(
            name="timeline_track",
            description=(
                "Mute/unmute (mute) or rename (set_name, Premiere 26.3+) a track "
                "on a sequence. track_index is 0-based."
            ),
            schema=_schema(
                {
                    "track_index": {"type": "integer", "description": "0-based track index."},
                    "track_type": {
                        "type": "string",
                        "enum": ["video", "audio", "caption"],
                        "default": "video",
                    },
                    "mute": {"type": "boolean"},
                    "set_name": {"type": "string"},
                    "timeline": {"type": "string"},
                },
                required=["track_index"],
            ),
            handler=_h_timeline_track,
        ),
        _ToolSpec(
            name="timeline_clone",
            description="Duplicate a sequence (Premiere names the copy).",
            schema=_schema({"timeline": {"type": "string"}}),
            handler=_h_timeline_clone,
        ),
        _ToolSpec(
            name="timeline_subsequence",
            description=(
                "Create a subsequence from the sequence's current in/out selection. "
                "ignore_track_targeting=true (default) includes all tracks."
            ),
            schema=_schema(
                {
                    "ignore_track_targeting": {"type": "boolean", "default": True},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_timeline_subsequence,
        ),
        _ToolSpec(
            name="timeline_in_out",
            description=("Read (with no args) or set a sequence's in/out points (seconds)."),
            schema=_schema(
                {
                    "in_seconds": {"type": "number"},
                    "out_seconds": {"type": "number"},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_timeline_in_out,
        ),
        _ToolSpec(
            name="timeline_create_from_media",
            description=(
                "Create a sequence pre-populated from project-panel items (by name), "
                "optionally placing the new sequence in a bin."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "Project-panel item names.",
                    },
                    "bin": {"type": "string"},
                },
                required=["name", "items"],
            ),
            handler=_h_timeline_create_from_media,
        ),
        _ToolSpec(
            name="timeline_selection",
            description=(
                "Read the current track-item selection, or clear it with clear=true "
                "(setting a selection by filter crashes Premiere 26.5 beta)."
            ),
            schema=_schema(
                {
                    "clear": {"type": "boolean", "default": False},
                    "timeline": {"type": "string"},
                }
            ),
            handler=_h_timeline_selection,
        ),
        # ---- media -----------------------------------------------------
        _ToolSpec(
            name="media_inspect",
            description=(
                "Full bin/clip tree of the project panel. Pass with_paths=false for "
                "a faster tree without media paths / offline flags."
            ),
            schema=_schema({"with_paths": {"type": "boolean", "default": True}}),
            handler=_h_media_inspect,
        ),
        _ToolSpec(
            name="media_bins",
            description="List top-level bins in the current project's panel.",
            handler=_h_media_bins,
        ),
        _ToolSpec(
            name="media_ls",
            description="List items in a bin (nested 'A/B/C' paths supported; default root).",
            schema=_schema({"bin": {"type": "string"}}),
            handler=_h_media_ls,
        ),
        _ToolSpec(
            name="media_import",
            description="Import file paths into the project panel, optionally into a bin.",
            schema=_schema(
                {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "bin": {"type": "string"},
                },
                required=["paths"],
            ),
            handler=_h_media_import,
        ),
        _ToolSpec(
            name="media_scan",
            description=(
                "Scan a filesystem path for importable media files. Returns "
                "video/audio/image files with kinds; skips hidden files by default."
            ),
            schema=_schema(
                {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean", "default": True},
                    "include_hidden": {"type": "boolean", "default": False},
                    "max_files": {"type": "integer", "default": 10000},
                },
                required=["path"],
            ),
            handler=_h_media_scan,
            needs_premiere=False,
        ),
        _ToolSpec(
            name="media_bin_ensure",
            description="Create a nested project-panel bin path if needed, e.g. `Picture/Plates`.",
            schema=_schema({"path": {"type": "string"}}, required=["path"]),
            handler=_h_media_bin_ensure,
        ),
        _ToolSpec(
            name="media_bin_delete",
            description="Delete a project-panel bin by slash path.",
            schema=_schema({"path": {"type": "string"}}, required=["path"]),
            handler=_h_media_bin_delete,
        ),
        _ToolSpec(
            name="media_move",
            description=(
                "Move project-panel clips between bins using safe filters "
                "(name_contains or an explicit names list)."
            ),
            schema=_schema(
                {
                    "target_bin": {"type": "string"},
                    "source_bin": {"type": "string", "description": "Default: the root bin."},
                    "name_contains": {"type": "string"},
                    "names": {"type": "array", "items": {"type": "string"}},
                },
                required=["target_bin"],
            ),
            handler=_h_media_move,
        ),
        _ToolSpec(
            name="media_color_label",
            description=(
                "Read (or set with set_index, 0-14) a project-panel item's color "
                "label. Identify the item by name or media path."
            ),
            schema=_schema(
                {
                    "name": {"type": "string", "description": "Project-item name."},
                    "path": {"type": "string", "description": "Media path of the item."},
                    "set_index": {
                        "type": "integer",
                        "description": "Color label index 0-14 to set; omit to read.",
                    },
                }
            ),
            handler=_h_media_color_label,
        ),
        _ToolSpec(
            name="media_bin_rename",
            description="Rename a project-panel bin identified by its current slash path.",
            schema=_schema(
                {
                    "path": {"type": "string"},
                    "new_name": {"type": "string"},
                },
                required=["path", "new_name"],
            ),
            handler=_h_media_bin_rename,
        ),
        _ToolSpec(
            name="media_smart_bin",
            description=(
                "Create a smart bin at the project root with a search query. prpr-only tool."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "query": {"type": "string"},
                },
                required=["name", "query"],
            ),
            handler=_h_media_smart_bin,
        ),
        _ToolSpec(
            name="media_footage_interpretation",
            description=(
                "Read (or update via set) a clip's footage interpretation. Identify "
                "the clip by name or media path. Settable keys: frame_rate, "
                "pixel_aspect_ratio, field_type, remove_pulldown, alpha_usage, "
                "ignore_alpha, invert_alpha, input_lut_id. prpr-only tool."
            ),
            schema=_schema(
                {
                    "name": {"type": "string", "description": "Project-item name."},
                    "path": {"type": "string", "description": "Media path of the clip."},
                    "set": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "Interpretation keys to update; omit to read.",
                    },
                }
            ),
            handler=_h_media_footage_interpretation,
        ),
        _ToolSpec(
            name="media_purge_cache",
            description="Purge Premiere's media cache (Premiere 26.5+). prpr-only tool.",
            handler=_h_media_purge_cache,
        ),
        _ToolSpec(
            name="media_subclip",
            description=(
                "Create a subclip from a source clip's time range (Premiere "
                "26.3+). Identify the source by project-item name or media path. "
                "prpr-only tool."
            ),
            schema=_schema(
                {
                    "subclip_name": {"type": "string"},
                    "start_seconds": {"type": "number"},
                    "end_seconds": {"type": "number"},
                    "name": {"type": "string", "description": "Source project-item name."},
                    "path": {"type": "string", "description": "Source media path."},
                    "hard_boundaries": {"type": "boolean", "default": False},
                    "take_video": {"type": "boolean", "default": True},
                    "take_audio": {"type": "boolean", "default": True},
                },
                required=["subclip_name", "start_seconds", "end_seconds"],
            ),
            handler=_h_media_subclip,
        ),
        _ToolSpec(
            name="media_attach_proxy",
            description=(
                "Attach a proxy (or hi-res alternate with is_hi_res=true) to a clip. Not undoable."
            ),
            schema=_schema(
                {
                    "proxy_path": {"type": "string"},
                    "name": {"type": "string", "description": "Project-item name."},
                    "path": {"type": "string", "description": "Media path of the clip."},
                    "is_hi_res": {"type": "boolean", "default": False},
                },
                required=["proxy_path"],
            ),
            handler=_h_media_attach_proxy,
        ),
        _ToolSpec(
            name="media_transcribe",
            description=(
                "Export a clip's speech-to-text transcript as JSON (Premiere "
                "26.3+; returns has_transcript=false when none exists)."
            ),
            schema=_schema(
                {
                    "name": {"type": "string", "description": "Project-item name."},
                    "path": {"type": "string", "description": "Media path of the clip."},
                }
            ),
            handler=_h_media_transcribe,
        ),
        _ToolSpec(
            name="media_relink",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). The UXP API has no batch "
                "relink; calling this returns a structured NotSupportedError."
            ),
            handler=_not_supported(
                "Premiere's UXP API has no batch media relink.",
                cause="Only per-clip changeMediaFilePath exists, with no folder-level relink.",
                fix="Relink manually in Premiere (right-click > Link Media...); "
                "batch relink is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        # ---- render / export -------------------------------------------
        _ToolSpec(
            name="render_presets",
            description=(
                "List discovered .epr export presets (user + Adobe Media Encoder + "
                "PRPR_PRESET_DIRS). Does not require Premiere."
            ),
            handler=_h_render_presets,
            needs_premiere=False,
        ),
        _ToolSpec(
            name="render_submit",
            description=(
                "Export a sequence via EncoderManager using an .epr preset. "
                "queue_to: omit to export immediately in Premiere, 'ame' to queue in "
                "Adobe Media Encoder, 'app' for Premiere's export queue. Pass "
                "wait=true to block until complete (event-driven, file fallback)."
            ),
            schema=_schema(
                {
                    "target_dir": {"type": "string"},
                    "custom_name": {"type": "string"},
                    "preset": {"type": "string", "description": ".epr preset name or path."},
                    "timeline": {"type": "string"},
                    "queue_to": {"type": "string", "enum": ["ame", "app"]},
                    "wait": {"type": "boolean", "default": False},
                    "timeout": {
                        "type": "number",
                        "default": 3600,
                        "description": "Max seconds to wait when wait=true.",
                    },
                },
                required=["target_dir"],
            ),
            handler=_h_render_submit,
        ),
        _ToolSpec(
            name="render_frame",
            description=(
                "Export a still frame from a sequence at a time (seconds). Output "
                "format follows the file extension (png/jpg/tif/exr/dpx/bmp/gif/tga)."
            ),
            schema=_schema(
                {
                    "seconds": {"type": "number"},
                    "file": {"type": "string"},
                    "timeline": {"type": "string"},
                    "width": {"type": "integer", "default": 0},
                    "height": {"type": "integer", "default": 0},
                },
                required=["seconds", "file"],
            ),
            handler=_h_render_frame,
        ),
        _ToolSpec(
            name="render_watch",
            description=(
                "Collect encoder events (progress/complete/error/cancel) until a "
                "terminal event or the timeout elapses, then return them. Use after "
                "render_submit instead of polling."
            ),
            schema=_schema(
                {
                    "timeout": {
                        "type": "number",
                        "default": 60,
                        "description": "Max seconds to collect events. Default 60.",
                    }
                }
            ),
            handler=_h_render_watch,
        ),
        _ToolSpec(
            name="render_ame_status",
            description="Report whether Adobe Media Encoder is installed/available.",
            handler=_h_render_ame_status,
        ),
        _ToolSpec(
            name="render_queue",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). The UXP API has no enumerable "
                "render queue; calling this returns a structured NotSupportedError."
            ),
            handler=_not_supported(
                "Premiere's UXP API has no enumerable render queue.",
                cause="EncoderManager only submits jobs and emits events; queued jobs "
                "cannot be listed, reordered, or deleted.",
                fix="Use render_submit with wait=true and render_watch for status; "
                "the enumerable queue is a dvr-only operation.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="render_formats",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Exports are driven by .epr "
                "presets, not format enums; use render_presets."
            ),
            handler=_not_supported(
                "Premiere exports are driven by .epr presets, not format/codec enums.",
                fix="Use render_presets to discover .epr presets instead.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="render_codecs",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Exports are driven by .epr "
                "presets, not codec enums; use render_presets."
            ),
            schema=_schema({"format": {"type": "string"}}, required=["format"]),
            handler=_not_supported(
                "Premiere exports are driven by .epr presets, not format/codec enums.",
                fix="Use render_presets to discover .epr presets instead.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="render_stop",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). The UXP API cannot cancel a "
                "running export; calling this returns a structured NotSupportedError."
            ),
            handler=_not_supported(
                "Premiere's UXP API cannot cancel a running export programmatically.",
                fix="Cancel from Premiere/AME's UI; watch for the cancel event with render_watch.",
            ),
            needs_premiere=False,
        ),
        _ToolSpec(
            name="render_clear",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). There is no render queue to "
                "clear; calling this returns a structured NotSupportedError."
            ),
            handler=_not_supported(
                "Premiere's UXP API has no render queue to clear.",
                fix="Manage queued exports in Premiere/AME's UI.",
            ),
            needs_premiere=False,
        ),
        # ---- interchange -------------------------------------------------
        _ToolSpec(
            name="interchange_export",
            description=(
                "Export a sequence to an interchange format: fcpxml, otio, or aaf "
                "(Premiere 26.3+). Format is inferred from the file extension "
                "(.xml/.otio/.aaf) when omitted."
            ),
            schema=_schema(
                {
                    "file_path": {"type": "string"},
                    "format": {"type": "string", "enum": ["fcpxml", "otio", "aaf"]},
                    "timeline": {"type": "string"},
                },
                required=["file_path"],
            ),
            handler=_h_interchange_export,
        ),
        _ToolSpec(
            name="interchange_import",
            description=(
                "NOT SUPPORTED in Premiere (dvr-only). Interchange import was removed "
                "from the UXP API in 26.3; calling this returns a structured "
                "NotSupportedError."
            ),
            schema=_schema({"file_path": {"type": "string"}}),
            handler=_h_interchange_import,
            needs_premiere=False,
        ),
        # ---- metadata (prpr-only) -----------------------------------------
        _ToolSpec(
            name="metadata_get",
            description=(
                "Read XMP and/or project metadata for a project-panel item found by "
                "name or media path. kind: xmp | project (default: both). prpr-only tool."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "kind": {"type": "string", "enum": ["xmp", "project"]},
                }
            ),
            handler=_h_metadata_get,
        ),
        _ToolSpec(
            name="metadata_set_xmp",
            description=(
                "Set the XMP metadata packet for a project-panel item found by name "
                "or media path. prpr-only tool."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "xmp": {"type": "string", "description": "Serialized XMP packet."},
                },
                required=["xmp"],
            ),
            handler=_h_metadata_set_xmp,
        ),
        # ---- source monitor (prpr-only) -------------------------------------
        _ToolSpec(
            name="source_monitor",
            description=(
                "Control Premiere's source monitor: open a file path or project item, "
                "play at a speed, get/set the position (seconds), or close clips. "
                "prpr-only tool."
            ),
            schema=_schema(
                {
                    "op": {
                        "type": "string",
                        "enum": [
                            "open_path",
                            "open_item",
                            "close",
                            "close_all",
                            "play",
                            "position",
                        ],
                    },
                    "path": {"type": "string", "description": "File path for open_path."},
                    "name": {
                        "type": "string",
                        "description": "Project-panel item name for open_item.",
                    },
                    "seconds": {"type": "number", "description": "Position to seek to."},
                    "speed": {"type": "number", "description": "Playback speed for play."},
                },
                required=["op"],
            ),
            handler=_h_source_monitor,
        ),
        # ---- diff / spec ----------------------------------------------
        _ToolSpec(
            name="diff_timelines",
            description=(
                "Structured diff between two sequences in the current project. "
                "Items align by name so reordering doesn't produce noise."
            ),
            schema=_schema(
                {"a": {"type": "string"}, "b": {"type": "string"}},
                required=["a", "b"],
            ),
            handler=_h_diff_timelines,
        ),
        _ToolSpec(
            name="diff_to_spec",
            description="Diff the live Premiere state against a spec (YAML/JSON file path).",
            schema=_schema({"spec_path": {"type": "string"}}, required=["spec_path"]),
            handler=_h_diff_to_spec,
        ),
        _ToolSpec(
            name="apply_spec",
            description=(
                "Reconcile the live Premiere state to match a declarative spec "
                "(YAML/JSON file path): project, bins, media imports, sequences, "
                "clips, markers. Returns the list of actions taken (or planned, when "
                "dry_run=true). Set verify=true to re-plan after applying and fail "
                "if anything did not reconcile."
            ),
            schema=_schema(
                {
                    "spec_path": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                    "verify": {"type": "boolean", "default": False},
                },
                required=["spec_path"],
            ),
            handler=_h_apply_spec,
        ),
        _ToolSpec(
            name="spec_export",
            description=(
                "Build a declarative spec from live project state (the inverse of "
                "apply_spec) — bins, media, sequences, markers. Pass `out` to write "
                "it to a YAML/JSON file; otherwise the spec is returned inline."
            ),
            schema=_schema(
                {
                    "out": {
                        "type": "string",
                        "description": "Optional output file path (.yaml or .json).",
                    }
                }
            ),
            handler=_h_spec_export,
        ),
        # ---- snapshot --------------------------------------------------
        _ToolSpec(
            name="snapshot_save",
            description=(
                "Capture the current project state (sequences, markers, media tree) "
                "to a snapshot on disk. Returns the snapshot name and path."
            ),
            schema=_schema(
                {
                    "name": {
                        "type": "string",
                        "description": "Snapshot name. Default: '<project>@<UTC timestamp>'.",
                    }
                }
            ),
            handler=_h_snapshot_save,
        ),
        _ToolSpec(
            name="snapshot_restore",
            description=(
                "Best-effort re-apply of a snapshot: recreates missing sequences and "
                "re-adds missing markers (clips cannot be reconstructed from JSON)."
            ),
            schema=_schema(
                {
                    "name": {"type": "string"},
                    "dry_run": {"type": "boolean", "default": False},
                },
                required=["name"],
            ),
            handler=_h_snapshot_restore,
        ),
        # ---- lint ------------------------------------------------------
        _ToolSpec(
            name="lint",
            description=(
                "Pre-flight validation of the current project: offline media, empty "
                "or missing sequences, media in temp directories. Returns structured "
                "error/warning/info issues."
            ),
            handler=_h_lint,
        ),
        # ---- plugin / setup ---------------------------------------------
        _ToolSpec(
            name="plugin_install",
            description=(
                "Install (or upgrade) the prpr bridge UXP plugin via Adobe's plugin "
                "installer (UPIA). After installing, open Window > UXP Plugins > "
                "prpr bridge in Premiere."
            ),
            handler=_h_plugin_install,
            needs_premiere=False,
        ),
        _ToolSpec(
            name="plugin_status",
            description=(
                "Report bridge plugin install status, whether Premiere is running, "
                "and whether Adobe's plugin installer (UPIA) is available."
            ),
            handler=_h_plugin_status,
            needs_premiere=False,
        ),
        # ---- app preferences -------------------------------------------
        _ToolSpec(
            name="app_preference",
            description=(
                "Read (or set with value) a Premiere application preference by key. "
                "persistent=true (default) writes it to the persistent store. "
                "prpr-only tool."
            ),
            schema=_schema(
                {
                    "key": {"type": "string"},
                    "value": {"description": "Value to set; omit to read."},
                    "persistent": {"type": "boolean", "default": True},
                },
                required=["key"],
            ),
            handler=_h_app_preference,
        ),
        # ---- power-user (eval, gated) ---------------------------------
        _ToolSpec(
            name="eval",
            description=(
                "Run a JavaScript async-function body inside Premiere with `ppro` "
                "and `uxp` in scope (return a JSON-able value). Disabled unless "
                "PRPR_MCP_ENABLE_EVAL=1 is set in the server's environment."
            ),
            schema=_schema({"code": {"type": "string"}}, required=["code"]),
            handler=_h_eval,
        ),
    ]


# ---------------------------------------------------------------------------
# Resources — live state agents can *read* instead of guessing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ResourceSpec:
    """One MCP resource: a URI backed by a JSON-producing reader."""

    uri: str
    name: str
    description: str
    handler: Callable[[_Context], Any]
    needs_premiere: bool = True


def _build_resource_registry() -> list[_ResourceSpec]:
    from .. import schema as schema_mod

    def _schema_reader(topic: str) -> Callable[[_Context], Any]:
        return lambda _ctx: schema_mod.get_topic(topic)

    specs = [
        _ResourceSpec(
            uri="prpr://inspect",
            name="Premiere state",
            description="One-call snapshot of Premiere, current project, and current sequence.",
            handler=lambda ctx: ctx.premiere().inspect(),
        ),
        _ResourceSpec(
            uri="prpr://timeline/current",
            name="Current timeline",
            description="Full inspect of the active sequence: tracks, items, markers, settings.",
            handler=lambda ctx: _read_current_timeline(ctx),
        ),
        _ResourceSpec(
            uri="prpr://media/bins",
            name="Project panel bins",
            description="The current project's top-level bin tree.",
            handler=lambda ctx: ctx.premiere().media.bins(),
        ),
        _ResourceSpec(
            uri="prpr://render/presets",
            name="Export presets",
            description="Discovered .epr export presets on this machine (no connection needed).",
            handler=lambda _ctx: find_presets(),
            needs_premiere=False,
        ),
        _ResourceSpec(
            uri="prpr://doctor",
            name="Setup diagnostics",
            description="Static prpr <-> Premiere environment diagnosis (no connection attempt).",
            handler=lambda ctx: _h_doctor(ctx, {}),
            needs_premiere=False,
        ),
    ]
    for topic in schema_mod.STATIC_TOPICS:
        specs.append(
            _ResourceSpec(
                uri=f"prpr://schema/{topic}",
                name=f"Schema: {topic}",
                description=f"Catalog of known-good values for {topic}.",
                handler=_schema_reader(topic),
                needs_premiere=False,
            )
        )
    return specs


def _read_current_timeline(ctx: _Context) -> dict[str, Any]:
    tl = ctx.premiere().timeline.current
    if tl is None:
        raise errors.TimelineError("No sequence is currently active.")
    return tl.inspect()


def list_resource_specs() -> list[_ResourceSpec]:
    """Return the resource registry. Public so tests / CLI can introspect."""
    return _build_resource_registry()


# ---------------------------------------------------------------------------
# Tool dispatch helpers
# ---------------------------------------------------------------------------


def _serialize(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def _ok(value: Any) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=_serialize(value))])


def _err(exc: errors.PrprError | Exception) -> CallToolResult:
    if isinstance(exc, errors.PrprError):
        payload = {"error": exc.to_dict()}
    else:
        payload = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "cause": None,
                "fix": None,
                "state": {},
            }
        }
    return CallToolResult(
        content=[TextContent(type="text", text=_serialize(payload))], isError=True
    )


def _dispatch(
    registry: dict[str, _ToolSpec],
    cache: _PremiereCache,
    name: str,
    args: dict[str, Any],
) -> CallToolResult:
    spec = registry.get(name)
    if spec is None:
        return _err(errors.PrprError(f"Unknown tool: {name!r}"))

    ctx = _Context(cache=cache)
    try:
        value = spec.handler(ctx, args or {})
    except errors.PrprError as exc:
        return _err(exc)
    except Exception as exc:  # boundary
        logger.exception("tool %r raised", name)
        return _err(errors.PrprError(f"{type(exc).__name__}: {exc}"))
    return _ok(value)


def tools_summary(detail: bool = False) -> list[dict[str, Any]]:
    """Return tools as plain dicts for the `prpr mcp tools` CLI command.

    With ``detail=False`` each entry carries the name, a one-line summary,
    and whether a live Premiere connection is needed; ``detail=True`` adds
    the full description and input schema.
    """
    out: list[dict[str, Any]] = []
    for spec in build_registry():
        entry: dict[str, Any] = {
            "name": spec.name,
            "needs_premiere": spec.needs_premiere,
            "summary": spec.description.split(". ")[0].strip().rstrip(".") + ".",
        }
        if detail:
            entry["description"] = spec.description
            entry["input_schema"] = spec.schema
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def build_server(*, auto_launch: bool = True, timeout: float = 30.0) -> Server:
    """Construct an MCP Server with all `prpr` tools and resources registered."""
    server = Server("prpr")
    cache = _PremiereCache(auto_launch=auto_launch, timeout=timeout)
    specs = build_registry()
    registry = {s.name: s for s in specs}
    tools = [Tool(name=s.name, description=s.description, inputSchema=s.schema) for s in specs]

    resource_specs = _build_resource_registry()
    resource_registry = {r.uri: r for r in resource_specs}
    resources = [
        Resource(
            uri=r.uri,  # type: ignore[arg-type]
            name=r.name,
            description=r.description,
            mimeType="application/json",
        )
        for r in resource_specs
    ]

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
        return _dispatch(registry, cache, name, arguments or {})

    @server.list_resources()
    async def _list_resources() -> list[Resource]:
        return resources

    @server.read_resource()
    async def _read_resource(uri: Any) -> str:
        spec = resource_registry.get(str(uri))
        if spec is None:
            raise errors.PrprError(
                f"Unknown resource: {uri}",
                fix=f"Available: {', '.join(resource_registry)}",
            )
        return _serialize(spec.handler(_Context(cache=cache)))

    return server


async def _run_async(*, auto_launch: bool, timeout: float) -> None:
    server = build_server(auto_launch=auto_launch, timeout=timeout)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def serve_stdio(*, auto_launch: bool = True, timeout: float = 30.0) -> None:
    """Run the MCP server over stdio. Blocks until stdin closes."""
    import asyncio

    asyncio.run(_run_async(auto_launch=auto_launch, timeout=timeout))


__all__ = [
    "build_registry",
    "build_server",
    "list_resource_specs",
    "serve_stdio",
    "tools_summary",
]
