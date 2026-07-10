"""``prpr project`` sub-commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ...project import Project
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


def _current(ctx: typer.Context) -> Project:
    p = _premiere(ctx)
    proj = p.project.current
    if proj is None:
        typer.echo("No project is currently open.", err=True)
        raise typer.Exit(1)
    return proj


@app.command("scratch-disks")
def scratch_disks_cmd(
    ctx: typer.Context,
    set_type: Annotated[
        str | None,
        typer.Option(
            "--set-type",
            help="Scratch disk type to set (capture, video_preview, audio_preview, "
            "auto_save, ccl_libraries, capsule_media).",
        ),
    ] = None,
    set_path: Annotated[
        str | None, typer.Option("--set-path", help="New path for --set-type.")
    ] = None,
) -> None:
    """Read or set the current project's scratch disk paths."""
    proj = _current(ctx)
    result = proj.scratch_disks(set_type=set_type, set_path=set_path)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("ingest")
def ingest_cmd(
    ctx: typer.Context,
    enabled: Annotated[
        bool | None,
        typer.Option("--enable/--disable", help="Enable or disable ingest; omit to read."),
    ] = None,
) -> None:
    """Read or set whether ingest is enabled for the current project."""
    proj = _current(ctx)
    result = proj.ingest(enabled)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("color-settings")
def color_settings_cmd(ctx: typer.Context) -> None:
    """Read the current project's color settings."""
    proj = _current(ctx)
    output.emit(proj.color_settings(), fmt=ctx.obj["format"])


@app.command("import-sequences")
def import_sequences_cmd(
    ctx: typer.Context,
    project_path: Annotated[str, typer.Argument(help="Source .prproj to import from.")],
    guid: Annotated[
        list[str] | None,
        typer.Option("--guid", help="Sequence GUID to import (repeatable). Default: all."),
    ] = None,
) -> None:
    """Import sequences from another .prproj into the current project."""
    proj = _current(ctx)
    result = proj.import_sequences(project_path, guid or None)
    output.emit(result, fmt=ctx.obj["format"])


@app.command("import-ae")
def import_ae_cmd(
    ctx: typer.Context,
    aep_path: Annotated[str, typer.Argument(help="Source .aep to import comps from.")],
    comp: Annotated[
        list[str] | None,
        typer.Option("--comp", help="Comp name to import (repeatable). Default: all."),
    ] = None,
    bin: Annotated[
        str | None, typer.Option("--bin", "-b", help="Target bin for imported comps.")
    ] = None,
) -> None:
    """Import After Effects comps into the current project."""
    proj = _current(ctx)
    result = proj.import_ae_comps(aep_path, comp or None, bin=bin)
    output.emit(result, fmt=ctx.obj["format"])
