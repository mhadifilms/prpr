"""prpr — the missing CLI, Python library, and MCP server for Adobe Premiere Pro.

Structural sibling of `dvr` (the same project for DaVinci Resolve):
same namespaces, same command routing, same error model. Operations one
app can't perform raise :class:`prpr.errors.NotSupportedError` loudly.

    from prpr import Premiere

    p = Premiere()
    tl = p.timeline.current
    print(tl.inspect())
"""

from __future__ import annotations

from . import (
    doctor,
    errors,
    interchange,
    media,
    render,
)
from .bridge import Bridge, RemoteRef
from .connection import connect, install_plugin, installed_apps, plugin_installed
from .effects import EffectsNamespace
from .events import EventsNamespace
from .media import MediaNamespace, media_kind_for_path, scan_media_files
from .premiere import App, Premiere
from .project import Project, ProjectNamespace
from .render import RenderJob, RenderNamespace
from .timeline import ItemQuery, Timeline, TimelineItem, TimelineNamespace

try:
    from ._version import __version__
except ImportError:  # pragma: no cover - version file generated at build time
    __version__ = "0.0.0+unknown"

__all__ = [
    "App",
    "Bridge",
    "EffectsNamespace",
    "EventsNamespace",
    "ItemQuery",
    "MediaNamespace",
    "Premiere",
    "Project",
    "ProjectNamespace",
    "RemoteRef",
    "RenderJob",
    "RenderNamespace",
    "Timeline",
    "TimelineItem",
    "TimelineNamespace",
    "__version__",
    "connect",
    "doctor",
    "errors",
    "install_plugin",
    "installed_apps",
    "interchange",
    "media",
    "media_kind_for_path",
    "plugin_installed",
    "render",
    "scan_media_files",
]
