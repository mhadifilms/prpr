"""``prpr render`` sub-commands.

Premiere exports are driven by ``.epr`` presets through
``EncoderManager``; there is no enumerable render queue. The dvr-only
commands (``queue`` / ``formats`` / ``codecs`` / ``stop`` / ``clear``)
still exist here and fail with the library's structured
:class:`~prpr.errors.NotSupportedError` — same routing, clear failure.
"""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

from ... import errors
from ...render import RenderNamespace, find_presets
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(
    name="render",
    help="Exports: submit, watch, frame, presets (queue/formats/codecs are dvr-only).",
)


@app.command("presets")
def presets(ctx: typer.Context) -> None:
    """List discovered .epr export presets (no Premiere needed)."""
    output.emit(find_presets(), fmt=ctx.obj["format"], headline="presets")


@app.command("submit")
def submit(
    ctx: typer.Context,
    target_dir: Annotated[str, typer.Option("--target-dir", "-o", help="Output directory.")],
    custom_name: Annotated[
        str | None,
        typer.Option("--name", help="Custom output filename (extension derived from preset)."),
    ] = None,
    preset: Annotated[
        str | None, typer.Option("--preset", help=".epr preset name or path.")
    ] = None,
    timeline: Annotated[
        str | None,
        typer.Option("--timeline", help="Sequence to export (default: the active one)."),
    ] = None,
    queue_to: Annotated[
        str | None,
        typer.Option(
            "--queue-to",
            help="Queue instead of exporting now: ame (Adobe Media Encoder) | app (Premiere).",
        ),
    ] = None,
    wait: Annotated[bool, typer.Option("--wait", help="Block until the export finishes.")] = False,
) -> None:
    """Export the current sequence (immediately, or queued to Premiere/AME)."""
    p = _premiere(ctx)
    job = p.render.submit(
        target_dir=target_dir,
        custom_name=custom_name,
        preset=preset,
        timeline=timeline,
        queue_to=queue_to,
        wait=wait,
    )
    if wait:
        output.emit(job.inspect(), fmt=ctx.obj["format"], headline="export")
        return
    output.emit(
        {"submitted": True, "output_path": job.output_path, "queue_to": queue_to},
        fmt=ctx.obj["format"],
    )


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Get render job status by id (dvr parity; not supported in Premiere)."""
    raise errors.NotSupportedError(
        "Premiere's UXP API has no render job ids to query.",
        cause="Exports are tracked by encoder events, not enumerable job handles.",
        fix="Use `prpr render submit --wait` or stream events with `prpr render watch`.",
    )


@app.command("watch")
def watch(
    ctx: typer.Context,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Stop after this many seconds.")
    ] = 3600.0,
) -> None:
    """Stream newline-delimited JSON encoder events until a terminal event."""
    p = _premiere(ctx)
    for event in p.render.watch(timeout=timeout):
        sys.stdout.write(json.dumps(event, default=str) + "\n")
        sys.stdout.flush()


@app.command("frame")
def frame(
    ctx: typer.Context,
    seconds: Annotated[float, typer.Argument(help="Sequence time of the frame, in seconds.")],
    file: Annotated[
        str, typer.Argument(help="Output image path (png/jpg/tif/exr/dpx/bmp/gif/tga).")
    ],
    timeline: Annotated[
        str | None,
        typer.Option("--timeline", help="Sequence to grab from (default: the active one)."),
    ] = None,
    width: Annotated[int, typer.Option("--width", help="Output width (0 = sequence size).")] = 0,
    height: Annotated[int, typer.Option("--height", help="Output height (0 = sequence size).")] = 0,
) -> None:
    """Export a still frame from a sequence."""
    p = _premiere(ctx)
    result = p.render.export_frame(seconds, file, timeline=timeline, width=width, height=height)
    output.emit(result, fmt=ctx.obj["format"])


# ---------------------------------------------------------------------------
# dvr-parity commands — exist, route identically, fail with the library's
# structured NotSupportedError (Premiere's UXP API can't do these).
# ---------------------------------------------------------------------------


@app.command("queue")
def queue(ctx: typer.Context) -> None:
    """List jobs in the render queue (dvr parity; not supported in Premiere)."""
    RenderNamespace.queue(None)  # type: ignore[arg-type]  # raises NotSupportedError


@app.command("formats")
def formats(ctx: typer.Context) -> None:
    """List render container formats (dvr parity; not supported in Premiere)."""
    RenderNamespace.formats(None)  # type: ignore[arg-type]  # raises NotSupportedError


@app.command("codecs")
def codecs(
    ctx: typer.Context,
    format_name: Annotated[str, typer.Argument(help="Container format (e.g. mov, mxf).")],
) -> None:
    """List codecs for a format (dvr parity; not supported in Premiere)."""
    RenderNamespace.codecs(None, format_name)  # type: ignore[arg-type]  # raises NotSupportedError


@app.command("stop")
def stop(ctx: typer.Context) -> None:
    """Stop the active render (dvr parity; not supported in Premiere)."""
    RenderNamespace.stop(None)  # type: ignore[arg-type]  # raises NotSupportedError


@app.command("clear")
def clear(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Clear the render queue (dvr parity; not supported in Premiere)."""
    RenderNamespace.clear(None)  # type: ignore[arg-type]  # raises NotSupportedError
