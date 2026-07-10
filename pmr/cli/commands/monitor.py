"""``pmr monitor`` sub-commands (Premiere's source monitor; dvr has no equivalent)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..._js import snippet
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="monitor", help="Source monitor: open, close, play, position.")


@app.command("open")
def open_cmd(
    ctx: typer.Context,
    path: Annotated[
        str | None,
        typer.Argument(help="Media file path to open (or use --item for a project item)."),
    ] = None,
    item: Annotated[
        str | None,
        typer.Option("--item", help="Open a project-panel item by name instead of a path."),
    ] = None,
) -> None:
    """Open a file or project item in the source monitor."""
    if (path is None) == (item is None):
        raise typer.BadParameter("Pass a PATH or --item NAME (exactly one).")
    p = _premiere(ctx)
    if item is not None:
        result = p.eval_js(snippet("source_monitor"), {"op": "open_item", "name": item})
    else:
        resolved = str(Path(path).expanduser().resolve())
        result = p.eval_js(snippet("source_monitor"), {"op": "open_path", "path": resolved})
    output.emit(result, fmt=ctx.obj["format"])


@app.command("close")
def close_cmd(ctx: typer.Context) -> None:
    """Close the clip currently open in the source monitor."""
    p = _premiere(ctx)
    result = p.eval_js(snippet("source_monitor"), {"op": "close"})
    output.emit(result, fmt=ctx.obj["format"])


@app.command("close-all")
def close_all_cmd(ctx: typer.Context) -> None:
    """Close every clip open in the source monitor."""
    p = _premiere(ctx)
    result = p.eval_js(snippet("source_monitor"), {"op": "close_all"})
    output.emit(result, fmt=ctx.obj["format"])


@app.command("play")
def play_cmd(
    ctx: typer.Context,
    speed: Annotated[
        float, typer.Option("--speed", help="Playback speed (1.0 = normal, negative = reverse).")
    ] = 1.0,
) -> None:
    """Start playback in the source monitor."""
    p = _premiere(ctx)
    result = p.eval_js(snippet("source_monitor"), {"op": "play", "speed": speed})
    output.emit(result, fmt=ctx.obj["format"])


@app.command("position")
def position_cmd(
    ctx: typer.Context,
    seconds: Annotated[
        float | None,
        typer.Argument(help="Seek to this second before reading (default: just read)."),
    ] = None,
) -> None:
    """Read (or set, then read) the source monitor playhead position."""
    p = _premiere(ctx)
    params: dict[str, object] = {"op": "position"}
    if seconds is not None:
        params["seconds"] = seconds
    result = p.eval_js(snippet("source_monitor"), params)
    output.emit(result, fmt=ctx.obj["format"])
