"""Diagnostic exception system.

Every error in `prpr` carries three structured fields:

- ``cause``: the most likely reason the operation failed
- ``fix``:   how to recover (often a snippet of code)
- ``state``: a snapshot of relevant state at the time of failure

Premiere's UXP API fails in its own ways — promises that reject with
one-line messages, actions that silently don't execute, a bridge plugin
that isn't connected. The goal of this module is that every wrapped call
decodes the failure into a ``PrprError`` whose ``__str__`` reads like a
diagnostic, not a Python traceback. LLM agents can branch on the error
type; humans can read the fix and move on.

The hierarchy intentionally mirrors ``dvr.errors`` (the DaVinci Resolve
sibling project) so that agents and humans working across both repos can
handle failures identically. ``NotSupportedError`` is the cross-app
contract: an operation that exists in one app's API but not the other's
fails loudly with it instead of pretending to succeed.
"""

from __future__ import annotations

from typing import Any


class PrprError(Exception):
    """Base exception for all `prpr` failures.

    Args:
        message: Short, present-tense description of what failed.
        cause:   The likely underlying reason. Computed by the caller from
                 read-back state where possible.
        fix:     How to recover. A code snippet or short imperative.
        state:   Relevant state snapshot for diagnostics (project name,
                 sequence name, bridge status, etc.).
    """

    def __init__(
        self,
        message: str,
        *,
        cause: str | None = None,
        fix: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause
        self.fix = fix
        self.state: dict[str, Any] = state or {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.cause:
            parts.append(f"  Cause: {self.cause}")
        if self.fix:
            parts.append(f"  Fix:   {self.fix}")
        if self.state:
            parts.append(f"  State: {self.state}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output / structured logs / MCP responses."""
        return {
            "type": type(self).__name__,
            "message": self.message,
            "cause": self.cause,
            "fix": self.fix,
            "state": self.state,
        }


class ConnectionError(PrprError):
    """Could not connect to a running Adobe Premiere Pro instance."""


class NotInstalledError(PrprError):
    """Adobe Premiere Pro does not appear to be installed on this system."""


class PluginNotConnectedError(ConnectionError):
    """Premiere is running but the prpr bridge plugin hasn't connected."""


class BridgeError(PrprError):
    """The bridge RPC itself failed (protocol error, handle expired, etc.)."""


class HostJSError(BridgeError):
    """JavaScript raised inside Premiere while executing a bridge request."""


class NotSupportedError(PrprError):
    """The operation exists in the sibling app (dvr) but Premiere's UXP API
    cannot perform it. Fails loudly instead of silently degrading — see the
    parity manifest (`prpr schema show parity`) for the full support matrix."""


class ProjectError(PrprError):
    """A project-level operation failed."""


class TimelineError(PrprError):
    """A timeline (sequence) level operation failed."""


class TrackError(PrprError):
    """A track-level operation failed (mute / items / etc.)."""


class ClipError(PrprError):
    """A clip-level (TrackItem or ProjectItem) operation failed."""


class MediaError(PrprError):
    """A media import / relink / proxy operation failed."""


class MediaImportError(MediaError):
    """A media import specifically — distinguishable from relink/proxy failures."""


class TimelineNotFoundError(TimelineError):
    """Looked up a sequence by name and it didn't exist in the current project."""


class RenderError(PrprError):
    """An export submission, monitoring, or completion failed."""


class RenderJobError(RenderError):
    """A single export job failed (vs. queue / config errors)."""


class SettingsError(PrprError):
    """Setting an invalid project or sequence setting key/value."""


class EffectError(PrprError):
    """An effect / transition / component operation failed."""


class MarkerError(PrprError):
    """A marker operation failed."""


class MetadataError(PrprError):
    """An XMP / project metadata operation failed."""


class InterchangeError(PrprError):
    """An import/export of an interchange format (AAF/FCPXML/OTIO/...) failed."""


class SpecError(PrprError):
    """A declarative spec failed to parse or reconcile."""


__all__ = [
    "BridgeError",
    "ClipError",
    "ConnectionError",
    "EffectError",
    "HostJSError",
    "InterchangeError",
    "MarkerError",
    "MediaError",
    "MediaImportError",
    "MetadataError",
    "NotInstalledError",
    "NotSupportedError",
    "PluginNotConnectedError",
    "ProjectError",
    "PrprError",
    "RenderError",
    "RenderJobError",
    "SettingsError",
    "SpecError",
    "TimelineError",
    "TimelineNotFoundError",
    "TrackError",
]
