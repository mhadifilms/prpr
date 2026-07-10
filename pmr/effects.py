"""Effects, transitions, and component (filter) operations.

Premiere's effect model: every track item has a component chain
(intrinsics like Motion/Opacity plus applied filters). Filters are
created by match name (``VideoFilterFactory``) or display name
(``AudioFilterFactory``) and appended to a clip's chain; parameters and
keyframes live on ``ComponentParam``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._js import snippet

if TYPE_CHECKING:
    from .premiere import Premiere


class EffectsNamespace:
    """``p.effects`` — effect/transition catalog and application."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere

    def list(self, kind: str = "video") -> dict[str, Any]:
        """List available effects. kind: video | audio | transition."""
        return self._p.eval_js(snippet("effects_list"), {"kind": kind}, timeout=120.0)

    def apply(
        self,
        name: str,
        *,
        kind: str = "video",
        timeline: str | None = None,
        clip_name: str | None = None,
        track_index: int | None = None,
    ) -> dict[str, Any]:
        """Apply an effect to matching clips (by matchName for video)."""
        return self._p.eval_js(
            snippet("effect_add"),
            {
                "kind": kind,
                "name": name,
                "sequence": timeline,
                "clip_name": clip_name,
                "track_index": track_index,
            },
        )

    def add_transition(
        self,
        match_name: str = "AE.ADBE Cross Dissolve New",
        *,
        timeline: str | None = None,
        clip_name: str | None = None,
        track_index: int | None = None,
        duration_seconds: float | None = None,
        apply_to_start: bool | None = None,
    ) -> dict[str, Any]:
        """Apply a video transition to matching clips."""
        return self._p.eval_js(
            snippet("transition_add"),
            {
                "match_name": match_name,
                "sequence": timeline,
                "clip_name": clip_name,
                "track_index": track_index,
                "duration_seconds": duration_seconds,
                "apply_to_start": apply_to_start,
            },
        )

    def components(
        self,
        *,
        timeline: str | None = None,
        clip_name: str | None = None,
        track_index: int | None = None,
        kind: str = "video",
        with_values: bool = False,
        at_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Inspect a clip's component chain (effects + parameters)."""
        return self._p.eval_js(
            snippet("clip_components"),
            {
                "sequence": timeline,
                "clip_name": clip_name,
                "track_index": track_index,
                "kind": kind,
                "with_values": with_values,
                "at_seconds": at_seconds,
            },
            timeout=120.0,
        )


__all__ = ["EffectsNamespace"]
