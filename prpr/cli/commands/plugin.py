"""``prpr plugin`` sub-commands — manage the bundled UXP bridge plugin."""

from __future__ import annotations

import typer

from ... import connection
from .. import output

app = typer.Typer(name="plugin", help="Bridge plugin: install, uninstall, status (via UPIA).")


@app.command("install")
def install(ctx: typer.Context) -> None:
    """Install (or upgrade) the prpr bridge plugin via Adobe's UPIA installer."""
    cfg = ctx.obj or {}
    result = connection.install_plugin()
    result["next_step"] = (
        "Restart Premiere Pro once so it loads the plugin. The headless bridge "
        "then starts automatically with Premiere on every launch — no panel, "
        "no menu. Verify with `prpr plugin status` or `prpr doctor --probe`."
    )
    output.emit(result, fmt=cfg.get("format"), headline="plugin install")


@app.command("check")
def check(ctx: typer.Context) -> None:
    """Check that the headless bridge is running and reachable.

    The bridge is a headless plugin — it starts automatically with Premiere
    once installed. This confirms it's connected (and tells you to restart
    Premiere if it was just installed).
    """
    cfg = ctx.obj or {}
    result = connection.bridge_reachable(timeout=cfg.get("timeout", 20.0))
    output.emit(result, fmt=cfg.get("format"), headline="prpr plugin check")


@app.command("uninstall")
def uninstall(
    ctx: typer.Context,
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Remove the prpr bridge plugin via UPIA."""
    if not yes:
        typer.confirm("Really uninstall the prpr bridge plugin?", abort=True)
    cfg = ctx.obj or {}
    result = connection.uninstall_plugin()
    output.emit(result, fmt=cfg.get("format"), headline="plugin uninstall")


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Show plugin install state plus the surrounding setup (no live probe)."""
    cfg = ctx.obj or {}
    plugin = connection.plugin_installed()
    report = {
        "installed": plugin["installed"],
        "upia_listed": plugin.get("upia_listed"),
        "external_dirs": plugin.get("external_dirs"),
        "upia_available": connection.upia_path() is not None,
        "premiere_installed": bool(connection.installed_apps()),
        "premiere_running": connection.premiere_process_running(),
    }
    output.emit(report, fmt=cfg.get("format"), headline="prpr plugin")
