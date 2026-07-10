"""``pmr media`` sub-commands (Premiere's project panel)."""

from __future__ import annotations

from typing import Annotated

import typer

from ...media import scan_media_files
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="media", help="Project panel: bins, clips, import, scan, move.")


@app.command("inspect")
def inspect_pool(ctx: typer.Context) -> None:
    """Inspect the current project's full bin/clip tree."""
    p = _premiere(ctx)
    output.emit(p.media.inspect(), fmt=ctx.obj["format"], headline="project panel")


@app.command("bins")
def bins(ctx: typer.Context) -> None:
    """List top-level bins in the project panel."""
    p = _premiere(ctx)
    rows = p.media.bins()
    output.emit(rows, fmt=ctx.obj["format"], headline="bins")


@app.command("ls")
def ls_bin(
    ctx: typer.Context,
    bin: Annotated[
        str | None,
        typer.Argument(help="Bin name or `A/B` path to list. Defaults to the root."),
    ] = None,
) -> None:
    """List items in a bin."""
    p = _premiere(ctx)
    rows = p.media.ls(bin)
    output.emit(rows, fmt=ctx.obj["format"], headline=f"items in {bin or 'root'}")


@app.command("scan")
def scan(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help="File or directory to scan for media files.")],
    recursive: Annotated[
        bool,
        typer.Option("--recursive/--no-recursive", help="Recurse into subdirectories."),
    ] = True,
    include_hidden: Annotated[
        bool,
        typer.Option("--include-hidden", help="Include hidden and AppleDouble (._*) files."),
    ] = False,
    max_files: Annotated[
        int,
        typer.Option("--max-files", help="Stop after this many matches.", min=1),
    ] = 10000,
) -> None:
    """Preview which media files an import would pick up (no Premiere needed)."""
    files = scan_media_files(
        path,
        recursive=recursive,
        include_hidden=include_hidden,
        max_files=max_files,
    )
    output.emit(files, fmt=ctx.obj["format"], headline=f"media files under {path}")


@app.command("mkbin")
def mkbin(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Bin name or `A/B` path to create.")],
) -> None:
    """Create (or get-or-create) a bin. Accepts nested `A/B` paths."""
    p = _premiere(ctx)
    result = p.media.bin_ensure(name)
    output.emit(result, fmt=ctx.obj["format"], headline=f"bin: {name}")


@app.command("rmbin")
def rmbin(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Bin name or `A/B` path to delete.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Delete a bin from the project panel."""
    if not yes:
        typer.confirm(f"Really delete bin {name!r}?", abort=True)
    p = _premiere(ctx)
    result = p.media.bin_delete(name)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("import")
def import_files(
    ctx: typer.Context,
    paths: Annotated[list[str], typer.Argument(help="One or more file paths to import.")],
    bin: Annotated[
        str | None,
        typer.Option("--bin", "-b", help="Target bin (created if missing)."),
    ] = None,
) -> None:
    """Import media files into the project panel."""
    p = _premiere(ctx)
    result = p.media.import_(paths, bin=bin)
    output.emit(result, fmt=ctx.obj["format"], headline=f"imported into {bin or 'root'}")


@app.command("move")
def move(
    ctx: typer.Context,
    target_bin: Annotated[str, typer.Argument(help="Destination bin name or `A/B` path.")],
    source_bin: Annotated[
        str | None,
        typer.Option("--source-bin", help="Only move clips out of this bin."),
    ] = None,
    name_contains: Annotated[
        str | None,
        typer.Option("--name-contains", help="Only move clips whose name contains this."),
    ] = None,
    name: Annotated[
        list[str] | None,
        typer.Option("--name", help="Exact clip name to move (repeatable)."),
    ] = None,
) -> None:
    """Move clips between bins."""
    p = _premiere(ctx)
    result = p.media.move(
        target_bin,
        source_bin=source_bin,
        name_contains=name_contains,
        names=name or None,
    )
    output.emit(result, fmt=ctx.obj["format"])
