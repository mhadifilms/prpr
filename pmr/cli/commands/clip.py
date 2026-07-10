"""``pmr clip`` — query and mutate clips on the active sequence.

Premiere's UXP API has no generic clip-property dict (dvr's ``--where``
+ ``set`` model), so filtering here uses simple flags::

    pmr clip ls --track video --duration-gt 2.5
    pmr clip ls --name-contains interview --track-index 1
    pmr clip disable "b-roll.mp4" --track video
"""

from __future__ import annotations

from typing import Annotated

import typer

from ...timeline import Timeline, TimelineItem
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="clip", help="Query and mutate clips on the active sequence.")


def _current(ctx: typer.Context) -> Timeline:
    p = _premiere(ctx)
    tl = p.timeline.current
    if tl is None:
        typer.echo("No sequence is currently active.", err=True)
        raise typer.Exit(1)
    return tl


def _filter_items(
    tl: Timeline,
    *,
    name_contains: str | None = None,
    track: str | None = None,
    track_index: int | None = None,
    duration_lt: float | None = None,
    duration_gt: float | None = None,
) -> list[TimelineItem]:
    items = tl.items(track) if track else [*tl.items("video"), *tl.items("audio")]
    out: list[TimelineItem] = []
    for item in items:
        if name_contains and (not item.name or name_contains not in item.name):
            continue
        if track_index is not None and item.track_index != track_index:
            continue
        if duration_lt is not None and (item.duration is None or item.duration >= duration_lt):
            continue
        if duration_gt is not None and (item.duration is None or item.duration <= duration_gt):
            continue
        out.append(item)
    return out


_NameContainsOpt = Annotated[
    str | None,
    typer.Option("--name-contains", help="Only clips whose name contains this substring."),
]
_TrackOpt = Annotated[
    str | None,
    typer.Option("--track", "-t", help="Track type filter: video | audio."),
]
_TrackIndexOpt = Annotated[
    int | None,
    typer.Option("--track-index", help="Track index filter (0-based)."),
]


@app.command("ls")
def ls_cmd(
    ctx: typer.Context,
    name_contains: _NameContainsOpt = None,
    track: _TrackOpt = None,
    track_index: _TrackIndexOpt = None,
    duration_lt: Annotated[
        float | None,
        typer.Option("--duration-lt", help="Only clips shorter than this many seconds."),
    ] = None,
    duration_gt: Annotated[
        float | None,
        typer.Option("--duration-gt", help="Only clips longer than this many seconds."),
    ] = None,
) -> None:
    """List clips on the active sequence, optionally filtered."""
    tl = _current(ctx)
    clips = _filter_items(
        tl,
        name_contains=name_contains,
        track=track,
        track_index=track_index,
        duration_lt=duration_lt,
        duration_gt=duration_gt,
    )
    rows = [{"track_type": c.track_type, **c.inspect()} for c in clips]
    output.emit(rows, fmt=ctx.obj["format"], headline=f"{len(rows)} clip(s)")


@app.command("rename")
def rename_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Current clip name (exact match).")],
    new_name: Annotated[str, typer.Argument(help="New clip name.")],
    track: _TrackOpt = None,
    track_index: _TrackIndexOpt = None,
) -> None:
    """Rename matching clips on the active sequence."""
    tl = _current(ctx)
    result = tl._clip_update(
        name=name,
        track_type=track or "video",
        track_index=track_index,
        set_name=new_name,
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("enable")
def enable_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Clip name (exact match).")],
    track: _TrackOpt = None,
    track_index: _TrackIndexOpt = None,
) -> None:
    """Enable matching clips on the active sequence."""
    tl = _current(ctx)
    result = tl._clip_update(
        name=name,
        track_type=track or "video",
        track_index=track_index,
        set_disabled=False,
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("disable")
def disable_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Clip name (exact match).")],
    track: _TrackOpt = None,
    track_index: _TrackIndexOpt = None,
) -> None:
    """Disable matching clips on the active sequence."""
    tl = _current(ctx)
    result = tl._clip_update(
        name=name,
        track_type=track or "video",
        track_index=track_index,
        set_disabled=True,
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("move")
def move_cmd(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Clip name (exact match).")],
    shift: Annotated[
        float | None,
        typer.Option("--shift", help="Shift by this many seconds (negative = earlier)."),
    ] = None,
    to: Annotated[
        float | None,
        typer.Option("--to", help="Move the clip start to this absolute second."),
    ] = None,
    track: _TrackOpt = None,
    track_index: _TrackIndexOpt = None,
) -> None:
    """Move matching clips in time on the active sequence."""
    if shift is None and to is None:
        raise typer.BadParameter("Pass --shift SECONDS or --to SECONDS.")
    if shift is not None and to is not None:
        raise typer.BadParameter("--shift and --to are mutually exclusive.")
    tl = _current(ctx)
    result = tl._clip_update(
        name=name,
        track_type=track or "video",
        track_index=track_index,
        shift_seconds=shift,
        set_start_seconds=to,
    )
    output.emit(result, fmt=ctx.obj["format"])
