"""Host event subscriptions (Premiere's EventManager).

Premiere can push events to a UXP plugin — project opened/closed/dirty,
sequence activated/closed, encoder render progress, and more. The bridge
plugin already forwards subscribed events as ``host-event`` frames; this
module gives the Python side an ergonomic way to subscribe and receive
them on a background thread.

    p = Premiere()

    @p.events.on("project", "EVENT_ACTIVATED")
    def _(event):
        print("active project changed:", event)

    # ... events fire on the bridge thread until you unsubscribe ...
    p.events.off_all()

Event names are the string constants on the ppro static classes
(``ProjectEvent.EVENT_ACTIVATED``, ``SequenceEvent`` constants, etc.).
Because delivery is asynchronous over the socket, handlers run on the
bridge's event thread — keep them short and thread-safe.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from ._js import PRELUDE

if TYPE_CHECKING:
    from .premiere import Premiere

# Targets the plugin's `subscribe` op understands. "global" uses
# addGlobalEventListener; the rest resolve to a live host object first.
_TARGET_SNIPPETS = {
    "global": None,
    "project": "return H.ref(await activeProject());",
    "sequence": "const p = await activeProject(); return H.ref(await p.getActiveSequence());",
    "encoder": "return H.ref(ppro.EncoderManager.getManager());",
}

EventHandler = Callable[[dict[str, Any]], None]


class EventsNamespace:
    """``p.events`` — subscribe to Premiere host events."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, list[EventHandler]] = {}
        self._wired = False

    def _ensure_router(self) -> None:
        if self._wired:
            return
        self._p.bridge.on_event(self._route)
        self._wired = True

    def _route(self, frame: dict[str, Any]) -> None:
        if frame.get("event") != "host-event":
            return
        sub_id = str(frame.get("subscription", ""))
        for handler in self._handlers.get(sub_id, []):
            # boundary: a bad handler must not kill the router
            with suppress(Exception):
                handler(frame.get("payload", {}))

    def subscribe(self, target: str, event: str, handler: EventHandler) -> str:
        """Subscribe ``handler`` to ``event`` on ``target``.

        target: "global" | "project" | "sequence" | "encoder".
        Returns a subscription id (pass to :meth:`off`).
        """
        if target not in _TARGET_SNIPPETS:
            from . import errors

            raise errors.PmrError(
                f"Unknown event target: {target!r}",
                fix=f"Use one of {sorted(_TARGET_SNIPPETS)}.",
            )
        self._ensure_router()
        target_ref: Any = "global"
        snippet_body = _TARGET_SNIPPETS[target]
        if snippet_body is not None:
            target_ref = self._p.eval_js(PRELUDE + "\n" + snippet_body)
        result = self._p.bridge.request("subscribe", target=target_ref, event=event)
        sub_id = str(result.get("subscription"))
        self._subscriptions[sub_id] = {"target": target, "event": event}
        self._handlers.setdefault(sub_id, []).append(handler)
        return sub_id

    def on(self, target: str, event: str) -> Callable[[EventHandler], EventHandler]:
        """Decorator form of :meth:`subscribe`."""

        def decorator(handler: EventHandler) -> EventHandler:
            self.subscribe(target, event, handler)
            return handler

        return decorator

    def off(self, subscription_id: str) -> dict[str, Any]:
        """Remove one subscription."""
        self._handlers.pop(subscription_id, None)
        self._subscriptions.pop(subscription_id, None)
        return self._p.bridge.request("unsubscribe", subscription=subscription_id)

    def off_all(self) -> int:
        """Remove every subscription. Returns how many were removed."""
        count = 0
        for sub_id in list(self._subscriptions):
            self.off(sub_id)
            count += 1
        return count

    def active(self) -> list[dict[str, Any]]:
        """List active subscriptions."""
        return [{"id": sid, **info} for sid, info in self._subscriptions.items()]


__all__ = ["EventHandler", "EventsNamespace"]
