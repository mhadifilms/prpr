"""``pmr metadata`` sub-commands (Premiere-specific XMP / project metadata)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ..._js import snippet
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="metadata", help="Read and write XMP / project metadata on clips.")


@app.command("get")
def get(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project-panel item name.")],
    kind: Annotated[
        str | None,
        typer.Option("--kind", help="Which metadata to read: xmp | project (default: both)."),
    ] = None,
) -> None:
    """Read a project item's XMP and/or project metadata."""
    if kind is not None and kind not in ("xmp", "project"):
        raise typer.BadParameter("--kind must be 'xmp' or 'project'.")
    p = _premiere(ctx)
    result = p.eval_js(snippet("metadata_get"), {"name": name, "kind": kind})
    output.emit(result, fmt=ctx.obj["format"], headline=f"metadata: {name}")


@app.command("set-xmp")
def set_xmp(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project-panel item name.")],
    file: Annotated[
        str | None,
        typer.Option("--file", help="Path to a file containing the XMP packet."),
    ] = None,
    value: Annotated[
        str | None,
        typer.Option("--value", help="Inline XMP packet string."),
    ] = None,
) -> None:
    """Set a project item's XMP metadata from a file or an inline string."""
    if (file is None) == (value is None):
        raise typer.BadParameter("Pass exactly one of --file or --value.")
    xmp = Path(file).expanduser().read_text(encoding="utf-8") if file else value
    p = _premiere(ctx)
    result = p.eval_js(snippet("metadata_set_xmp"), {"name": name, "xmp": xmp})
    output.emit(result, fmt=ctx.obj["format"])
