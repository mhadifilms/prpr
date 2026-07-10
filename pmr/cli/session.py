"""Shared CLI helpers for opening a Premiere connection.

Every ``pmr`` sub-command shares this one connection factory, and
uncaught :class:`~pmr.errors.PmrError` exceptions are rendered as
structured output by the top-level handler in :mod:`pmr.cli.main` — so
commands can simply let library errors propagate.

When the CLI runs *inside* the pmr daemon (see :mod:`pmr.daemon`), the
daemon installs a premiere provider here so every command reuses the
daemon's persistent bridge connection instead of re-hosting the
WebSocket server and waiting for the plugin to dial in per invocation.
"""

from __future__ import annotations

from collections.abc import Callable

import typer

from ..premiere import Premiere
from ..project import Project

# Installed by the daemon (or tests) to reuse a persistent connection.
_premiere_provider: Callable[[], Premiere] | None = None


def set_premiere_provider(provider: Callable[[], Premiere] | None) -> None:
    """Install (or clear) a factory that supplies the Premiere connection.

    When set, :func:`premiere_from_ctx` calls it instead of constructing
    a fresh :class:`Premiere` — this is how the daemon shares one live
    bridge connection across every CLI command it executes.
    """
    global _premiere_provider
    _premiere_provider = provider


def premiere_from_ctx(ctx: typer.Context) -> Premiere:
    """Open a Premiere connection using the root command's global options."""
    if _premiere_provider is not None:
        return _premiere_provider()
    cfg = ctx.obj or {}
    return Premiere(auto_launch=cfg.get("auto_launch", True), timeout=cfg.get("timeout", 30.0))


# The task-level name for the same accessor; kept as an alias so both
# spellings work for callers and tests.
get_premiere = premiere_from_ctx


def current_project(ctx: typer.Context) -> Project:
    """Connect and return the current project, or raise a structured error."""
    return premiere_from_ctx(ctx).project.require_current()


__all__ = ["current_project", "get_premiere", "premiere_from_ctx", "set_premiere_provider"]
