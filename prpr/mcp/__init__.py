"""Model Context Protocol server for `prpr`.

Exposes the public library as MCP tools so LLM agents can drive
Adobe Premiere Pro through typed schemas instead of shell commands.

Run with::

    pip install prpr
    prpr mcp serve

The server uses stdio transport by default — clients spawn it as a
subprocess. Each MCP tool is one library call wrapped in error
serialization. Tools that exist in the sibling `dvr` project (DaVinci
Resolve) but that Premiere's UXP API cannot perform are still
registered and fail loudly with a structured
:class:`prpr.errors.NotSupportedError` payload — the explicit cross-app
failure contract (see ``prpr schema show parity``).
"""

from __future__ import annotations

from .server import (
    build_registry,
    build_server,
    list_resource_specs,
    serve_stdio,
    tools_summary,
)

__all__ = [
    "build_registry",
    "build_server",
    "list_resource_specs",
    "serve_stdio",
    "tools_summary",
]
