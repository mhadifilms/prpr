"""``pmr project`` sub-commands."""

from __future__ import annotations

from typing import Annotated

import typer

from .. import output
from ..session import premiere_from_ctx as _premiere

app = typer.Typer(
    name="project", help="Project operations: list, current, ensure, create, load, delete, save."
)


@app.command("list")
def list_projects(ctx: typer.Context) -> None:
    """List projects currently open in Premiere."""
    p = _premiere(ctx)
    rows = p.project.list()
    output.emit(rows, fmt=ctx.obj["format"], headline="projects")


@app.command("current")
def current(ctx: typer.Context) -> None:
    """Inspect the currently open project."""
    p = _premiere(ctx)
    proj = p.project.current
    if proj is None:
        output.emit({"current": None}, fmt=ctx.obj["format"])
        return
    output.emit(proj.inspect(), fmt=ctx.obj["format"], headline=proj.name)


@app.command("ensure")
def ensure(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project name or .prproj path to open-or-create.")],
) -> None:
    """Open the project if it exists, otherwise create it."""
    p = _premiere(ctx)
    proj = p.project.ensure(name)
    output.emit(proj.inspect(), fmt=ctx.obj["format"], headline=f"ensured: {proj.name}")


@app.command("create")
def create(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project name or .prproj path (must not exist).")],
) -> None:
    """Create a new project file and open it."""
    p = _premiere(ctx)
    proj = p.project.create(name)
    output.emit(proj.inspect(), fmt=ctx.obj["format"], headline=f"created: {proj.name}")


@app.command("load")
def load(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project name or .prproj path to open.")],
) -> None:
    """Open an existing project file."""
    p = _premiere(ctx)
    proj = p.project.load(name)
    output.emit(proj.inspect(), fmt=ctx.obj["format"], headline=f"loaded: {proj.name}")


@app.command("delete")
def delete(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Project name or .prproj path to delete.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
) -> None:
    """Delete a project file from disk (must be closed first)."""
    if not yes:
        typer.confirm(f"Really delete project {name!r}?", abort=True)
    p = _premiere(ctx)
    result = p.project.delete(name)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("save")
def save(ctx: typer.Context) -> None:
    """Save the currently open project."""
    p = _premiere(ctx)
    proj = p.project.current
    if proj is None:
        typer.echo("No project is currently open.", err=True)
        raise typer.Exit(1)
    proj.save()
    output.emit({"saved": proj.name}, fmt=ctx.obj["format"])
