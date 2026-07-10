"""Top-level entry point: the :class:`Premiere` handle.

Mirrors ``dvr.resolve.Resolve`` — the sibling project for DaVinci Resolve —
so agents and humans can drive both apps with the same object model:

    from pmr import Premiere

    p = Premiere()                 # hosts the bridge, waits for the plugin
    print(p.inspect())             # one call, full state
    tl = p.timeline.current
    p.media.import_(["/path/a.mov"], bin="Footage")
    p.render.submit(target_dir="/tmp/out", preset="/path/preset.epr")
"""

from __future__ import annotations

import os
from typing import Any

from . import connection, errors
from ._js import snippet
from .bridge import Bridge
from .effects import EffectsNamespace
from .events import EventsNamespace
from .media import MediaNamespace
from .project import ProjectNamespace
from .render import RenderNamespace
from .timeline import TimelineNamespace


class App:
    """Application-level state (version, capabilities)."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere

    @property
    def version(self) -> str:
        info = self._p.bridge.hello or self._p.bridge.ping()
        host = info.get("host") or {}
        return str(host.get("version", "unknown"))

    @property
    def product(self) -> str:
        info = self._p.bridge.hello or self._p.bridge.ping()
        host = info.get("host") or {}
        return str(host.get("name", "Premiere Pro"))

    def inspect(self) -> dict[str, Any]:
        return self._p.eval_js(snippet("app_info"))

    @property
    def page(self) -> str:
        raise errors.NotSupportedError(
            "Premiere Pro has no scriptable page/workspace switching in the UXP API.",
            cause="DaVinci Resolve pages (edit/color/deliver) have no Premiere equivalent.",
            fix="Switch workspaces manually in Premiere; this is a dvr-only operation.",
        )

    @page.setter
    def page(self, name: str) -> None:
        raise errors.NotSupportedError(
            "Premiere Pro has no scriptable page/workspace switching in the UXP API.",
            cause="DaVinci Resolve pages (edit/color/deliver) have no Premiere equivalent.",
            fix="Switch workspaces manually in Premiere; this is a dvr-only operation.",
        )

    def quit(self) -> bool:
        """Ask Premiere Pro to quit."""
        return connection.quit_premiere()

    def preference(self, key: str, value: Any = None, *, persistent: bool = True) -> dict[str, Any]:
        """Read (or set, when ``value`` is given) an application preference.

        Known keys: AppPreference constants like ``AutoPeakGeneration`` — see
        ``ppro.AppPreference.KEY_*`` (Adobe documents only a few)."""
        payload: dict[str, Any] = {"key": key}
        if value is not None:
            payload.update({"set": True, "value": value, "persistent": persistent})
        return self._p.eval_js(snippet("app_preference"), payload)


class Premiere:
    """A live handle on Adobe Premiere Pro via the pmr bridge plugin."""

    def __init__(
        self,
        auto_launch: bool = True,
        timeout: float = 30.0,
        *,
        bridge: Bridge | None = None,
    ) -> None:
        if bridge is not None:
            self._bridge = bridge
        else:
            env_timeout = os.environ.get("PMR_TIMEOUT")
            if env_timeout:
                timeout = float(env_timeout)
            self._bridge = connection.connect(auto_launch=auto_launch, timeout=timeout)
        self._app = App(self)
        self._project = ProjectNamespace(self)
        self._timeline = TimelineNamespace(self)
        self._media = MediaNamespace(self)
        self._render = RenderNamespace(self)
        self._effects = EffectsNamespace(self)
        self._events = EventsNamespace(self)

    # ------------------------------------------------------------------
    # Namespaces
    # ------------------------------------------------------------------

    @property
    def bridge(self) -> Bridge:
        return self._bridge

    @property
    def app(self) -> App:
        return self._app

    @property
    def project(self) -> ProjectNamespace:
        return self._project

    @property
    def timeline(self) -> TimelineNamespace:
        return self._timeline

    @property
    def media(self) -> MediaNamespace:
        return self._media

    @property
    def render(self) -> RenderNamespace:
        return self._render

    @property
    def effects(self) -> EffectsNamespace:
        return self._effects

    @property
    def events(self) -> EventsNamespace:
        return self._events

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def eval_js(self, code: str, args: Any = None, *, timeout: float = 120.0) -> Any:
        """Run an async JS function body inside Premiere (ppro, uxp in scope)."""
        return self._bridge.eval_js(code, args, timeout=timeout)

    def inspect(self) -> dict[str, Any]:
        """One-call snapshot: app + current project + current timeline."""
        app = self.app.inspect()
        result: dict[str, Any] = {"app": app}
        try:
            result["project"] = self.project.current.inspect() if self.project.current else None
        except errors.PmrError as exc:
            result["project"] = {"error": exc.message}
        try:
            current = self.timeline.current
            result["timeline"] = current.inspect(names_only=True) if current else None
        except errors.PmrError as exc:
            result["timeline"] = {"error": exc.message}
        return result

    def ping(self) -> dict[str, Any]:
        return self._bridge.ping()

    def close(self) -> None:
        """Shut down the bridge server (Premiere keeps running)."""
        self._bridge.close()

    def __enter__(self) -> Premiere:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["App", "Premiere"]
