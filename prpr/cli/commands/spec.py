"""``prpr spec`` sub-commands — spec file tooling."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from ... import spec as spec_mod
from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(name="spec", help="Spec tooling: adopt live projects into declarative specs.")


@app.command("export")
def export(
    ctx: typer.Context,
    out: Annotated[
        str | None,
        typer.Option("--out", "-o", help="Write the spec to this file (YAML) instead of stdout."),
    ] = None,
) -> None:
    """Build a spec from the live project state (the inverse of `prpr apply`).

    Captures the bin tree, imported media paths, and each sequence's
    clips and markers — so an existing project can be adopted into a
    spec file and managed with `prpr plan` / `prpr apply` from then on.
    """
    p = _premiere(ctx)
    data = spec_mod.from_live(p)
    if out:
        Path(out).expanduser().write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        output.emit({"exported": data["project"], "path": out}, fmt=ctx.obj["format"])
        return
    output.emit(data, fmt=ctx.obj["format"], headline=f"spec: {data['project']}")
