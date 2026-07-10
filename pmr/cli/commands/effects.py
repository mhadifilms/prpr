"""``pmr effects`` sub-commands (Premiere-specific; dvr has no effects CLI)."""

from __future__ import annotations

from typing import Annotated

import typer

from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(
    name="effects", help="Effects and transitions: list, apply, inspect component chains."
)

_ClipOpt = Annotated[
    str | None,
    typer.Option("--clip", help="Target clip name (default: every clip on the track)."),
]
_TrackIndexOpt = Annotated[
    int | None,
    typer.Option("--track-index", help="Target track index (default: all tracks)."),
]
_TimelineOpt = Annotated[
    str | None,
    typer.Option("--timeline", help="Sequence to target (default: the active one)."),
]


@app.command("list")
def list_effects(
    ctx: typer.Context,
    kind: Annotated[
        str, typer.Option("--kind", help="Catalog to list: video | audio | transition.")
    ] = "video",
) -> None:
    """List available effects or transitions."""
    p = _premiere(ctx)
    result = p.effects.list(kind)
    output.emit(result, fmt=ctx.obj["format"], headline=f"{kind} effects")


@app.command("apply")
def apply_effect(
    ctx: typer.Context,
    name: Annotated[
        str, typer.Argument(help="Effect matchName (video) or display name (audio).")
    ],
    clip: _ClipOpt = None,
    track_index: _TrackIndexOpt = None,
    kind: Annotated[str, typer.Option("--kind", help="Effect kind: video | audio.")] = "video",
    timeline: _TimelineOpt = None,
) -> None:
    """Apply an effect to matching clips on the active sequence."""
    p = _premiere(ctx)
    result = p.effects.apply(
        name, kind=kind, timeline=timeline, clip_name=clip, track_index=track_index
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("transition")
def transition(
    ctx: typer.Context,
    match_name: Annotated[
        str,
        typer.Argument(help="Transition matchName (see `pmr effects list --kind transition`)."),
    ] = "AE.ADBE Cross Dissolve New",
    clip: _ClipOpt = None,
    track_index: _TrackIndexOpt = None,
    duration: Annotated[
        float | None, typer.Option("--duration", help="Transition duration in seconds.")
    ] = None,
    start: Annotated[
        bool | None,
        typer.Option("--start/--end", help="Apply at the clip start instead of the end."),
    ] = None,
    timeline: _TimelineOpt = None,
) -> None:
    """Apply a video transition to matching clips."""
    p = _premiere(ctx)
    result = p.effects.add_transition(
        match_name,
        timeline=timeline,
        clip_name=clip,
        track_index=track_index,
        duration_seconds=duration,
        apply_to_start=start,
    )
    output.emit(result, fmt=ctx.obj["format"])


@app.command("components")
def components(
    ctx: typer.Context,
    clip: _ClipOpt = None,
    track_index: _TrackIndexOpt = None,
    kind: Annotated[
        str, typer.Option("--kind", help="Component chain to read: video | audio.")
    ] = "video",
    with_values: Annotated[
        bool,
        typer.Option("--with-values", help="Include current parameter values."),
    ] = False,
    at: Annotated[
        float, typer.Option("--at", help="Sequence time (seconds) at which to read values.")
    ] = 0.0,
    timeline: _TimelineOpt = None,
) -> None:
    """Inspect a clip's component chain (intrinsics + applied effects)."""
    p = _premiere(ctx)
    result = p.effects.components(
        timeline=timeline,
        clip_name=clip,
        track_index=track_index,
        kind=kind,
        with_values=with_values,
        at_seconds=at,
    )
    output.emit(result, fmt=ctx.obj["format"], headline="components")
