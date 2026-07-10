"""Setup diagnostics — `pmr doctor`.

Fast, static checks by default (no live connection): Premiere installed?
running? bridge plugin installed? UPIA available? port free? With
``probe=True`` it additionally hosts the bridge and waits briefly for
the plugin to dial in.
"""

from __future__ import annotations

import platform
import socket
import sys
from typing import Any

from . import connection, errors
from .bridge import DEFAULT_PORTS


def _port_status(port: int) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        try:
            s.bind(("127.0.0.1", port))
            return "free"
        except OSError:
            return "in-use"


def diagnose(
    probe: bool = False, auto_launch: bool = False, timeout: float = 15.0
) -> dict[str, Any]:
    """Return a diagnostic dict describing this machine's pmr setup."""
    from . import __version__

    apps = connection.installed_apps()
    plugin = connection.plugin_installed()
    result: dict[str, Any] = {
        "pmr": __version__,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "premiere_installed": bool(apps),
        "premiere_apps": apps,
        "premiere_running": connection.premiere_process_running(),
        "plugin_installed": plugin["installed"],
        "plugin_detail": plugin,
        "upia_available": connection.upia_path() is not None,
        "ports": {port: _port_status(port) for port in DEFAULT_PORTS},
    }

    problems: list[str] = []
    fixes: list[str] = []
    if not apps:
        problems.append("Premiere Pro is not installed.")
        fixes.append("Install Premiere Pro 25.6+ from Creative Cloud.")
    if not plugin["installed"]:
        problems.append("The pmr bridge plugin is not installed.")
        fixes.append(
            "Run `pmr plugin install`, then restart Premiere (the headless bridge auto-starts)."
        )
    if not result["premiere_running"]:
        problems.append("Premiere Pro is not running.")
        fixes.append("Launch Premiere (pmr auto-launches it unless --no-launch).")

    if probe:
        try:
            bridge = connection.connect(auto_launch=auto_launch, timeout=timeout)
            hello = bridge.hello or {}
            result["probe"] = {
                "connected": True,
                "host": hello.get("host"),
                "plugin_version": hello.get("plugin"),
                "port": bridge.port,
            }
            bridge.close()
        except errors.PmrError as exc:
            result["probe"] = {"connected": False, "error": exc.to_dict()}
            problems.append("Live probe failed: " + exc.message)
            if exc.fix:
                fixes.append(exc.fix)

    result["problems"] = problems
    result["fixes"] = fixes
    result["ok"] = not problems
    return result


__all__ = ["diagnose"]
