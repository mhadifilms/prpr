"""``pmr diff`` — compare timelines, snapshots, and specs."""

from __future__ import annotations

from typing import Annotated

import typer

from ... import diff as diff_mod
from ... import spec as spec_mod
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="diff", help="Compare timelines, snapshots, and specs.")


@app.command("timelines")
def diff_timelines(
    ctx: typer.Context,
    a: Annotated[str, typer.Argument(help="Left sequence name.")],
    b: Annotated[str, typer.Argument(help="Right sequence name.")],
) -> None:
    """Diff two sequences in the current project."""
    p = _premiere(ctx)
    result = diff_mod.compare_timelines(p, a, b)
    output.emit(result.to_dict(), fmt=ctx.obj["format"], headline=f"diff {a} vs {b}")


@app.command("spec")
def diff_spec(
    ctx: typer.Context,
    spec_file: Annotated[str, typer.Argument(help="Path to a YAML or JSON spec.")],
) -> None:
    """Diff the live state against a spec file."""
    p = _premiere(ctx)
    parsed = spec_mod.load_spec(spec_file)
    result = diff_mod.compare_to_spec(p, parsed)
    output.emit(result.to_dict(), fmt=ctx.obj["format"], headline=f"diff live vs {spec_file}")


@app.command("snapshot")
def diff_snapshot(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Snapshot name to compare against the live state.")],
) -> None:
    """Diff a saved snapshot against the live project state."""
    p = _premiere(ctx)
    result = diff_mod.compare_to_snapshot(p, name)
    output.emit(result.to_dict(), fmt=ctx.obj["format"], headline=f"diff {name} vs live")
