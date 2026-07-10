"""``pmr timeline`` sub-commands (Premiere sequences)."""

from __future__ import annotations

from typing import Annotated

import typer

from ... import interchange
from ...timeline import Timeline
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(
    name="timeline", help="Timeline (sequence) operations: list, inspect, ensure, current, switch."
)


def _current(ctx: typer.Context) -> Timeline:
    p = _premiere(ctx)
    tl = p.timeline.current
    if tl is None:
        typer.echo("No sequence is currently active.", err=True)
        raise typer.Exit(1)
    return tl


@app.command("list")
def list_timelines(ctx: typer.Context) -> None:
    """List sequences in the currently open project."""
    p = _premiere(ctx)
    rows = p.timeline.list()
    output.emit(rows, fmt=ctx.obj["format"], headline="timelines")


@app.command("current")
def current(ctx: typer.Context) -> None:
    """Inspect the currently active sequence."""
    p = _premiere(ctx)
    tl = p.timeline.current
    if tl is None:
        output.emit({"current": None}, fmt=ctx.obj["format"])
        return
    output.emit(tl.inspect(), fmt=ctx.obj["format"], headline=tl.name)


@app.command("inspect")
def inspect_timeline(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(help="Sequence name; defaults to the active sequence."),
    ] = None,
) -> None:
    """Return a structured snapshot of a sequence."""
    p = _premiere(ctx)
    tl = p.timeline.get(name) if name else p.timeline.current
    if tl is None:
        typer.echo("No sequence is currently active.", err=True)
        raise typer.Exit(1)
    output.emit(tl.inspect(), fmt=ctx.obj["format"], headline=tl.name)


@app.command("ensure")
def ensure(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Sequence name to open-or-create.")],
) -> None:
    """Get-or-create a sequence by name."""
    p = _premiere(ctx)
    tl = p.timeline.ensure(name)
    output.emit(tl.inspect(), fmt=ctx.obj["format"], headline=f"ensured: {tl.name}")


@app.command("create")
def create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Sequence name (must be unique).")],
    preset: Annotated[
        str | None,
        typer.Option("--preset", help="Path to a .sqpreset sequence preset file."),
    ] = None,
) -> None:
    """Create an empty sequence."""
    p = _premiere(ctx)
    tl = p.timeline.create(name, preset_path=preset)
    output.emit(tl.inspect(), fmt=ctx.obj["format"], headline=f"created: {tl.name}")


@app.command("switch")
def switch(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Sequence name to set as active.")],
) -> None:
    """Set a sequence as the active one."""
    p = _premiere(ctx)
    p.timeline.set_current(name)
    output.emit({"current": name}, fmt=ctx.obj["format"])


@app.command("delete")
def delete(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Sequence name to delete.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Delete a sequence."""
    if not yes:
        typer.confirm(f"Really delete sequence {name!r}?", abort=True)
    p = _premiere(ctx)
    p.timeline.delete(name)
    output.emit({"deleted": name}, fmt=ctx.obj["format"])


@app.command("rename")
def rename(
    ctx: typer.Context,
    new_name: Annotated[str, typer.Argument(help="New sequence name.")],
    timeline: Annotated[
        str | None,
        typer.Option("--timeline", help="Sequence to rename (default: the active one)."),
    ] = None,
) -> None:
    """Rename a sequence (the active one by default)."""
    p = _premiere(ctx)
    tl = p.timeline.get(timeline) if timeline else _current(ctx)
    result = tl.rename(new_name)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("append")
def append(
    ctx: typer.Context,
    item: Annotated[
        str | None,
        typer.Argument(help="Project-panel item name to place (or use --path)."),
    ] = None,
    path: Annotated[
        str | None,
        typer.Option("--path", help="Media file path — imported first if missing."),
    ] = None,
    at: Annotated[
        float | None,
        typer.Option("--at", help="Place at this many seconds instead of the sequence end."),
    ] = None,
    video_track: Annotated[
        int, typer.Option("--video-track", help="Target video track index.")
    ] = 0,
    audio_track: Annotated[
        int, typer.Option("--audio-track", help="Target audio track index.")
    ] = 0,
    insert: Annotated[
        bool,
        typer.Option("--insert", help="Insert (shift later clips) instead of overwrite."),
    ] = False,
) -> None:
    """Append (or insert) a project item onto the active sequence."""
    if item is None and path is None:
        raise typer.BadParameter("Pass an ITEM name or --path.")
    tl = _current(ctx)
    if at is not None or insert:
        result = tl.insert(
            item,
            item_path=path,
            seconds=at,
            video_track=video_track,
            audio_track=audio_track,
            overwrite=not insert,
        )
    else:
        result = tl.append(item, item_path=path, video_track=video_track, audio_track=audio_track)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("clear")
def clear(
    ctx: typer.Context,
    track_type: Annotated[
        str, typer.Option("--track-type", help="Track type: video | audio.")
    ] = "video",
    track_indexes: Annotated[
        list[int] | None,
        typer.Option("--track-indexes", help="Track index (repeatable). Default: all tracks."),
    ] = None,
    name_contains: Annotated[
        str | None,
        typer.Option("--name-contains", help="Only remove clips whose name contains this."),
    ] = None,
    ripple: Annotated[
        bool, typer.Option("--ripple", help="Ripple-delete (close the gaps).")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Remove clips from the active sequence's tracks."""
    if not yes:
        typer.confirm("Really remove matching clips from the active sequence?", abort=True)
    tl = _current(ctx)
    result = tl.delete_clips(
        track_type=track_type,
        track_indexes=track_indexes or None,
        name_contains=name_contains,
        ripple=ripple,
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("mark")
def mark(
    ctx: typer.Context,
    at: Annotated[float, typer.Option("--at", help="Marker position in seconds.")],
    name: Annotated[str, typer.Option("--name", help="Marker name.")] = "marker",
    note: Annotated[str, typer.Option("--note", help="Marker note/comments.")] = "",
    marker_type: Annotated[
        str,
        typer.Option("--type", help="Marker type: Comment | Chapter | Segmentation | WebLink."),
    ] = "Comment",
    color_index: Annotated[
        int | None,
        typer.Option(
            "--color-index", help="Color index 0-6 (see `pmr schema show marker-colors`)."
        ),
    ] = None,
    duration: Annotated[
        float | None, typer.Option("--duration", help="Marker duration in seconds.")
    ] = None,
) -> None:
    """Add a marker to the active sequence."""
    tl = _current(ctx)
    result = tl.add_marker(
        at,
        name=name,
        note=note,
        marker_type=marker_type,
        duration_seconds=duration,
        color_index=color_index,
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("markers")
def markers(ctx: typer.Context) -> None:
    """List markers on the active sequence."""
    tl = _current(ctx)
    rows = tl.markers()
    output.emit(rows, fmt=ctx.obj["format"], headline=f"markers on {tl.name}")


@app.command("unmark")
def unmark(
    ctx: typer.Context,
    name: Annotated[
        str | None, typer.Option("--name", help="Remove markers with this name.")
    ] = None,
    at: Annotated[
        float | None, typer.Option("--at", help="Remove the marker at this second.")
    ] = None,
) -> None:
    """Remove a marker from the active sequence (by name and/or position)."""
    if name is None and at is None:
        raise typer.BadParameter("Pass --name and/or --at to select a marker.")
    tl = _current(ctx)
    result = tl.remove_marker(name=name, seconds=at)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("export")
def export(
    ctx: typer.Context,
    file: Annotated[str, typer.Argument(help="Output path (.xml | .otio | .aaf).")],
    format: Annotated[
        str | None,
        typer.Option(
            "--format", help="Interchange format: fcpxml | otio | aaf (default: by extension)."
        ),
    ] = None,
    timeline: Annotated[
        str | None,
        typer.Option("--timeline", help="Sequence to export (default: the active one)."),
    ] = None,
) -> None:
    """Export a sequence to an interchange format (FCPXML / OTIO / AAF)."""
    p = _premiere(ctx)
    result = interchange.export_timeline(p, file, format=format, timeline=timeline)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("track")
def track_cmd(
    ctx: typer.Context,
    track_index: Annotated[int, typer.Argument(help="Track index (0-based).")],
    track_type: Annotated[
        str, typer.Option("--track-type", "-t", help="video | audio | caption.")
    ] = "video",
    mute: Annotated[
        bool | None, typer.Option("--mute/--unmute", help="Mute or unmute the track.")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Rename the track (Premiere 26.3+).")
    ] = None,
    timeline: Annotated[str | None, typer.Option("--timeline", help="Sequence name.")] = None,
) -> None:
    """Mute/unmute or rename a track on the active (or named) sequence."""
    p = _premiere(ctx)
    tl = Timeline(p, timeline) if timeline else _current(ctx)
    result = tl.track_update(track_index, track_type=track_type, mute=mute, set_name=name)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("clone")
def clone_cmd(
    ctx: typer.Context,
    timeline: Annotated[str | None, typer.Option("--timeline", help="Sequence name.")] = None,
) -> None:
    """Duplicate a sequence (Premiere names the copy)."""
    p = _premiere(ctx)
    tl = Timeline(p, timeline) if timeline else _current(ctx)
    output.emit(tl.clone(), fmt=ctx.obj["format"])


@app.command("from-media")
def from_media_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Name for the new sequence.")],
    items: Annotated[list[str], typer.Argument(help="Project-item names to include.")],
    bin: Annotated[str | None, typer.Option("--bin", "-b", help="Target bin.")] = None,
) -> None:
    """Create a sequence pre-populated from project items."""
    p = _premiere(ctx)
    tl = p.timeline.create_from_media(name, items, bin=bin)
    output.emit(tl.inspect(names_only=True), fmt=ctx.obj["format"], headline=tl.name)


@app.command("selection")
def selection_cmd(
    ctx: typer.Context,
    clear: Annotated[bool, typer.Option("--clear", help="Clear the selection.")] = False,
    timeline: Annotated[str | None, typer.Option("--timeline", help="Sequence name.")] = None,
) -> None:
    """Show (or clear) the current track-item selection."""
    p = _premiere(ctx)
    tl = Timeline(p, timeline) if timeline else _current(ctx)
    result = tl.select(clear=True) if clear else tl.selection()
    output.emit(result, fmt=ctx.obj["format"])


@app.command("in-out")
def in_out_cmd(
    ctx: typer.Context,
    in_seconds: Annotated[
        float | None, typer.Option("--in", help="Set the in point (seconds).")
    ] = None,
    out_seconds: Annotated[
        float | None, typer.Option("--out", help="Set the out point (seconds).")
    ] = None,
    timeline: Annotated[str | None, typer.Option("--timeline", help="Sequence name.")] = None,
) -> None:
    """Show or set a sequence's in/out points."""
    p = _premiere(ctx)
    tl = Timeline(p, timeline) if timeline else _current(ctx)
    output.emit(tl.set_in_out(in_seconds, out_seconds), fmt=ctx.obj["format"])


@app.command("mogrt")
def mogrt_cmd(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="Path to a .mogrt file.")],
    at: Annotated[float | None, typer.Option("--at", help="Insertion time (seconds).")] = None,
    video_track: Annotated[int, typer.Option("--video-track", help="Video track index.")] = 0,
    audio_track: Annotated[int, typer.Option("--audio-track", help="Audio track index.")] = 0,
    timeline: Annotated[str | None, typer.Option("--timeline", help="Sequence name.")] = None,
) -> None:
    """Insert a Motion Graphics template into a sequence."""
    p = _premiere(ctx)
    tl = Timeline(p, timeline) if timeline else _current(ctx)
    result = tl.insert_mogrt(path, seconds=at, video_track=video_track, audio_track=audio_track)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("scene-detect")
def scene_detect_cmd(
    ctx: typer.Context,
    operation: Annotated[
        str, typer.Option("--operation", "-o", help="cut | marker | subclip.")
    ] = "cut",
    clip_name: Annotated[str | None, typer.Option("--clip", help="Limit to one clip.")] = None,
    track_index: Annotated[int | None, typer.Option("--track-index", help="Track index.")] = None,
    timeline: Annotated[str | None, typer.Option("--timeline", help="Sequence name.")] = None,
) -> None:
    """Run scene edit detection on matching clips."""
    p = _premiere(ctx)
    tl = Timeline(p, timeline) if timeline else _current(ctx)
    result = tl.scene_edit_detection(
        operation=operation, clip_name=clip_name, track_index=track_index
    )
    output.emit(result, fmt=ctx.obj["format"])
