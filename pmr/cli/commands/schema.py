"""``pmr schema`` — discoverable catalogs for valid types, colors, presets, parity."""

from __future__ import annotations

from typing import Annotated

import typer

from ... import schema as schema_mod
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="schema", help="Catalogs of marker types, export types, parity matrix.")


# Topics that need a live Premiere connection (render-presets is disk-only).
_LIVE_TOPICS = {"effects", "audio-effects", "transitions"}


@app.command("topics")
def topics(ctx: typer.Context) -> None:
    """List available schema topics."""
    rows = [
        {
            "topic": t,
            "needs_premiere_running": t in _LIVE_TOPICS,
        }
        for t in schema_mod.TOPICS
    ]
    output.emit(rows, fmt=ctx.obj["format"], headline="schema topics")


@app.command("show")
def show(
    ctx: typer.Context,
    topic: Annotated[str, typer.Argument(help=f"One of: {', '.join(schema_mod.TOPICS)}.")],
) -> None:
    """Print the catalog for a topic."""
    if topic in _LIVE_TOPICS:
        p = _premiere(ctx)
        data = schema_mod.get_topic(topic, p)
    else:
        data = schema_mod.get_topic(topic)
    output.emit(data, fmt=ctx.obj["format"], headline=f"schema: {topic}")
