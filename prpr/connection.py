"""Platform-aware connection to Adobe Premiere Pro.

Unlike DaVinci Resolve, Premiere has no external scripting socket: the
UXP API lives inside the app and only the bundled `prpr bridge` plugin can
reach it. The bridge is a **headless** UXP plugin (a `command` entrypoint
whose main.js connects at load), so once installed it runs automatically
at every Premiere launch — no panel, no menu. "Connecting" therefore means:

1. Host the local WebSocket bridge server (:class:`prpr.bridge.Bridge`).
2. Make sure Premiere Pro is running (auto-launch it if asked).
3. Make sure the bridge plugin is installed (UPIA-managed `.ccx`).
4. Wait for the plugin to dial in and say hello.

The plugin auto-reconnects every ~1.5s, so in steady state step 4
completes almost instantly.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from . import errors
from .bridge import Bridge

logger = logging.getLogger("prpr.connection")

_MAC_APP_GLOBS = (
    "/Applications/Adobe Premiere Pro */Adobe Premiere Pro *.app",
    "/Applications/Adobe Premiere Pro*.app",
)
_MAC_UPIA = (
    "/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/"
    "UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS/"
    "UnifiedPluginInstallerAgent"
)
_WIN_APP_GLOBS = (r"C:\Program Files\Adobe\Adobe Premiere Pro *\Adobe Premiere Pro.exe",)
_WIN_UPIA = (
    r"C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI"
    r"\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"
)

_PLUGIN_ID = "prpr.bridge"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def installed_apps() -> list[dict[str, Any]]:
    """Return installed Premiere Pro apps, newest version first."""
    apps: list[dict[str, Any]] = []
    if sys.platform == "darwin":
        seen: set[str] = set()
        for pattern in _MAC_APP_GLOBS:
            for path in glob.glob(pattern):
                if path in seen:
                    continue
                seen.add(path)
                version = _mac_app_version(path)
                apps.append({"path": path, "version": version, "beta": "Beta" in path})
    elif sys.platform == "win32":
        for pattern in _WIN_APP_GLOBS:
            for path in glob.glob(pattern):
                apps.append({"path": path, "version": None, "beta": "Beta" in path})
    apps.sort(key=lambda a: (a["beta"], a["version"] or ""), reverse=False)
    # Prefer highest non-beta version.
    apps.sort(key=lambda a: (not a["beta"], a["version"] or ""), reverse=True)
    return apps


def _mac_app_version(app_path: str) -> str | None:
    plist = Path(app_path) / "Contents" / "Info.plist"
    try:
        with open(plist, "rb") as fh:
            info = plistlib.load(fh)
        version = info.get("CFBundleShortVersionString")
        return str(version) if version is not None else None
    except Exception:
        return None


def premiere_process_running() -> bool:
    """Return True if an Adobe Premiere Pro process is running."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["pgrep", "-f", "Adobe Premiere Pro"], capture_output=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Adobe Premiere Pro.exe"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return "Adobe Premiere Pro.exe" in (result.stdout or "")
        except Exception:
            return False
    return False


def launch_premiere(app_path: str | None = None) -> str:
    """Launch Premiere Pro (newest installed version by default)."""
    if app_path is None:
        apps = installed_apps()
        if not apps:
            raise errors.NotInstalledError(
                "Adobe Premiere Pro does not appear to be installed.",
                fix="Install Premiere Pro 25.6+ from Creative Cloud.",
                state={"looked_in": list(_MAC_APP_GLOBS + _WIN_APP_GLOBS)},
            )
        app_path = apps[0]["path"]
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", app_path], check=False, timeout=15)
    else:
        subprocess.Popen([app_path])
    return app_path


# ---------------------------------------------------------------------------
# Plugin install
# ---------------------------------------------------------------------------


def plugin_source_dir() -> Path:
    """Locate the bundled UXP plugin sources (repo checkout or wheel asset)."""
    candidates = [
        Path(__file__).resolve().parent / "plugin_assets",  # installed wheel
        Path(__file__).resolve().parent.parent / "plugin",  # repo checkout
    ]
    for candidate in candidates:
        if (candidate / "manifest.json").exists():
            return candidate
    raise errors.PrprError(
        "Bundled bridge plugin sources not found.",
        state={"candidates": [str(c) for c in candidates]},
    )


def upia_path() -> str | None:
    path = _MAC_UPIA if sys.platform == "darwin" else _WIN_UPIA
    return path if os.path.exists(path) else None


def plugin_installed() -> dict[str, Any]:
    """Check whether the bridge plugin is installed (UPIA or dev-loaded)."""
    external = Path.home() / "Library/Application Support/Adobe/UXP/Plugins/External"
    if sys.platform == "win32":
        external = Path(os.environ.get("APPDATA", "")) / "Adobe/UXP/Plugins/External"
    found = sorted(external.glob(f"{_PLUGIN_ID}_*")) if external.exists() else []
    upia = upia_path()
    listed = False
    if upia:
        try:
            result = subprocess.run(
                [upia, "--list", "all"], capture_output=True, text=True, timeout=30
            )
            listed = "prpr bridge" in (result.stdout or "")
        except Exception:
            listed = False
    return {
        "installed": bool(found) or listed,
        "external_dirs": [str(p) for p in found],
        "upia_listed": listed,
    }


def build_ccx(out_path: str | Path | None = None) -> Path:
    """Package the bundled plugin into a .ccx archive (a zip of the plugin dir)."""
    src = plugin_source_dir()
    if out_path is None:
        out_path = Path(tempfile.mkdtemp(prefix="prpr-")) / "prpr-bridge.ccx"
    out_path = Path(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(src.rglob("*")):
            # Skip dev-tools session artifacts and OS cruft — they must not
            # ship inside the installed plugin.
            if file.name in (".uxprc", ".DS_Store"):
                continue
            if file.is_file():
                zf.write(file, file.relative_to(src))
    return out_path


def install_plugin() -> dict[str, Any]:
    """Install (or upgrade) the bridge plugin via UPIA. Returns a status dict."""
    upia = upia_path()
    if upia is None:
        raise errors.NotInstalledError(
            "Adobe's plugin installer (UPIA) was not found.",
            cause="Creative Cloud desktop app is missing or too old.",
            fix="Install/update the Creative Cloud desktop app, or load plugin/ manually "
            "with Adobe UXP Developer Tools.",
            state={"expected": _MAC_UPIA if sys.platform == "darwin" else _WIN_UPIA},
        )
    ccx = build_ccx()
    flag = "--install" if sys.platform == "darwin" else "/install"
    result = subprocess.run([upia, flag, str(ccx)], capture_output=True, text=True, timeout=120)
    output = (result.stdout or "") + (result.stderr or "")
    ok = result.returncode == 0 and "fail" not in output.lower()
    if not ok:
        raise errors.PrprError(
            "UPIA failed to install the bridge plugin.",
            cause=output.strip()[:500] or f"exit code {result.returncode}",
            fix="Quit Premiere and retry `prpr plugin install`; or load plugin/ with "
            "Adobe UXP Developer Tools.",
            state={"ccx": str(ccx)},
        )
    return {"installed": True, "ccx": str(ccx), "output": output.strip()[:500]}


def uninstall_plugin() -> dict[str, Any]:
    upia = upia_path()
    if upia is None:
        raise errors.NotInstalledError("Adobe's plugin installer (UPIA) was not found.")
    flag = "--remove" if sys.platform == "darwin" else "/remove"
    result = subprocess.run([upia, flag, _PLUGIN_ID], capture_output=True, text=True, timeout=120)
    output = (result.stdout or "") + (result.stderr or "")
    return {"removed": result.returncode == 0, "output": output.strip()[:500]}


# ---------------------------------------------------------------------------
# Headless startup
# ---------------------------------------------------------------------------
#
# The bridge is a HEADLESS UXP plugin: a `command` entrypoint whose main.js
# opens the WebSocket connection at module load. Once UPIA-installs it, its
# code runs automatically at every Premiere launch — no panel to dock, no
# menu to click. (Verified on Premiere 26.5: a UPIA-installed command-only
# plugin's main.js executes at app startup and connects on its own.)
#
# So the only setup is: `prpr plugin install`, then restart Premiere once so
# it registers the new plugin. After that it is fully automatic and
# reconnects to the daemon whenever either side restarts.


def bridge_reachable(timeout: float = 20.0) -> dict[str, Any]:
    """Check whether the headless plugin is running and connects to the bridge.

    Returns a status dict rather than raising — "not connected yet, restart
    Premiere" is a normal setup outcome, not an error.
    """
    if not premiere_process_running():
        return {
            "connected": False,
            "premiere_running": False,
            "action": "Launch Premiere Pro (the headless bridge starts with it).",
        }
    bridge = Bridge()
    try:
        bridge.start()
        if bridge._hello_event.wait(timeout=timeout):
            hello = bridge.hello or {}
            fresh = plugin_freshness(hello.get("plugin"))
            result = {
                "connected": True,
                "plugin": hello.get("plugin"),
                "bundled_plugin": fresh["bundled"],
                "up_to_date": not fresh["stale"],
                "host": hello.get("host"),
                "note": "Headless bridge is running. It starts automatically with "
                "Premiere and reconnects on its own.",
            }
            if fresh["stale"]:
                result["note"] = (
                    f"Bridge is v{fresh['connected']} but prpr ships v{fresh['bundled']}. "
                    "Run `prpr plugin install` and restart Premiere to update."
                )
            return result
    finally:
        bridge.close()
    return {
        "connected": False,
        "premiere_running": True,
        "plugin_installed": plugin_installed()["installed"],
        "action": "Restart Premiere Pro so it loads the installed bridge plugin. "
        "If it still doesn't connect, run `prpr doctor --probe`.",
    }


# ---------------------------------------------------------------------------
# Plugin freshness / auto-update
# ---------------------------------------------------------------------------
#
# The plugin ships inside the pip package (its version is in the bundled
# manifest). When you `pip install -U prpr`, the bundled plugin can be newer
# than the copy UPIA-installed into Premiere. On connect we compare the two
# and, by default, UPIA-reinstall the newer bundle so the *next* Premiere
# launch runs the current bridge. (A running UXP plugin can't be hot-swapped,
# so the refresh takes effect on restart — we log that clearly.) Opt out with
# ``PRPR_PLUGIN_AUTOUPDATE=0``.

_plugin_refresh_attempted = False


def bundled_plugin_version() -> str | None:
    """Version string from the bundled plugin manifest, or None."""
    try:
        data = json.loads((plugin_source_dir() / "manifest.json").read_text())
        version = data.get("version")
        return str(version) if version else None
    except Exception:
        return None


def _version_tuple(value: str | None) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def plugin_freshness(connected_version: str | None) -> dict[str, Any]:
    """Compare the connected plugin version to the bundled one."""
    bundled = bundled_plugin_version()
    stale = bool(
        bundled
        and connected_version
        and _version_tuple(connected_version) < _version_tuple(bundled)
    )
    return {"bundled": bundled, "connected": connected_version, "stale": stale}


def _maybe_refresh_plugin(bridge: Bridge) -> None:
    """UPIA-reinstall the bundled plugin if the connected one is older."""
    global _plugin_refresh_attempted
    if _plugin_refresh_attempted:
        return
    if os.environ.get("PRPR_PLUGIN_AUTOUPDATE", "1").strip().lower() in ("0", "false", "no"):
        return
    fresh = plugin_freshness((bridge.hello or {}).get("plugin"))
    if not fresh["stale"]:
        return
    _plugin_refresh_attempted = True
    if upia_path() is None:
        logger.warning(
            "bridge plugin in Premiere is v%s but prpr ships v%s; run `prpr plugin install` to update",
            fresh["connected"],
            fresh["bundled"],
        )
        return
    try:
        install_plugin()
        logger.warning(
            "Updated the bridge plugin to v%s — restart Premiere Pro to load it "
            "(it is still running v%s this session).",
            fresh["bundled"],
            fresh["connected"],
        )
    except errors.PrprError as exc:
        logger.warning("could not auto-update the bridge plugin: %s", exc)


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------


def connect(auto_launch: bool = True, timeout: float = 30.0) -> Bridge:
    """Host the bridge server and wait for the Premiere plugin to dial in."""
    port_env = os.environ.get("PRPR_PORT")
    bridge = Bridge(port=int(port_env)) if port_env else Bridge()
    bridge.start()

    # Fast path: plugin is already cycling its reconnect loop.
    deadline = time.monotonic() + timeout
    if bridge._hello_event.wait(timeout=min(4.0, timeout)):
        _maybe_refresh_plugin(bridge)
        return bridge

    running = premiere_process_running()
    if not running:
        if not auto_launch:
            bridge.close()
            raise errors.ConnectionError(
                "Premiere Pro is not running.",
                fix="Launch Premiere Pro (or omit --no-launch), then open the "
                "headless bridge plugin (`prpr plugin install`, then restart Premiere).",
                state={"auto_launch": False},
            )
        launch_premiere()

    remaining = max(1.0, deadline - time.monotonic())
    try:
        bridge.wait_for_plugin(timeout=remaining)
        _maybe_refresh_plugin(bridge)
    except errors.PluginNotConnectedError as exc:
        status = plugin_installed()
        exc.state.update(
            {
                "premiere_running": premiere_process_running(),
                "plugin_installed": status["installed"],
            }
        )
        if not status["installed"]:
            exc.fix = (
                "Install the bridge plugin with `prpr plugin install`, then restart "
                "Premiere so it loads the headless bridge."
            )
        bridge.close()
        raise
    return bridge


def which_premiere() -> str | None:
    """Return the path of the newest installed Premiere Pro app, if any."""
    apps = installed_apps()
    return apps[0]["path"] if apps else None


def quit_premiere(*, force: bool = False) -> bool:
    """Ask Premiere to quit (macOS). Returns True if a quit was attempted."""
    if sys.platform != "darwin":
        return False
    if force:
        subprocess.run(["pkill", "-f", "Adobe Premiere Pro"], check=False)
        return True
    script = 'tell application id "com.adobe.PremierePro" to quit'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=30)
        return True
    except Exception:
        return False


_ = shutil  # imported for future use in relocation helpers


__all__ = [
    "Bridge",
    "bridge_reachable",
    "build_ccx",
    "bundled_plugin_version",
    "connect",
    "install_plugin",
    "installed_apps",
    "launch_premiere",
    "plugin_freshness",
    "plugin_installed",
    "plugin_source_dir",
    "premiere_process_running",
    "quit_premiere",
    "uninstall_plugin",
    "upia_path",
    "which_premiere",
]
