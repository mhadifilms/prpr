"""WebSocket bridge between Python and the prpr UXP plugin inside Premiere.

Premiere Pro has no external scripting interface: its UXP API runs as
JavaScript *inside* the app, and UXP plugins can only open *outgoing*
network connections. So prpr inverts the connection: this module hosts a
WebSocket server on localhost, and the bundled `prpr bridge` panel inside
Premiere connects out to it and executes structured RPC requests against
the `premierepro` module.

Wire protocol (JSON text frames)
--------------------------------

Python -> plugin:  ``{"id": "<uuid>", "op": "call", ...}``
plugin -> Python:  ``{"id": "<uuid>", "ok": true, "result": ...}``
                   ``{"id": "<uuid>", "ok": false, "error": {name, message, stack}}``
plugin -> Python (unsolicited): ``{"event": "hello", ...}`` on connect and
                   ``{"event": "host-event", ...}`` for subscribed host events.

Ops: ``ping``, ``eval``, ``call``, ``get``, ``set``, ``release``,
``transaction``, ``subscribe``, ``unsubscribe`` — see ``plugin/main.js``.

Host objects cross the wire as handle references
(``{"$h": id, "$type": name, "$snap": {...}}``) wrapped here in
:class:`RemoteRef`. The plugin keeps the live objects in a registry;
Python releases them explicitly (or via garbage collection, batched onto
the next request).

The server runs an asyncio loop in a daemon thread; :meth:`Bridge.request`
is synchronous and thread-safe, so the rest of the library reads like
ordinary Python.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
import weakref
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from . import errors

logger = logging.getLogger("prpr.bridge")

DEFAULT_PORTS = (8855, 8856, 8857)


class RemoteRef:
    """A reference to a live object inside Premiere (held by the plugin).

    Carries the handle id, the host-side constructor name, and a cheap
    snapshot of synchronous properties (``name``, ``seconds``, ``guid``,
    ...) inlined by the plugin at serialization time.
    """

    __slots__ = ("__weakref__", "_bridge", "h", "snap", "type")

    def __init__(self, h: str, type_: str, snap: dict[str, Any] | None, bridge: Bridge) -> None:
        self.h = h
        self.type = type_
        self.snap: dict[str, Any] = snap or {}
        self._bridge = bridge
        weakref.finalize(self, bridge._queue_release, h)

    def to_wire(self) -> dict[str, Any]:
        return {"$h": self.h}

    def __repr__(self) -> str:
        extra = f" {self.snap}" if self.snap else ""
        return f"<RemoteRef {self.type}#{self.h}{extra}>"


def _encode(value: Any) -> Any:
    """Encode Python values (incl. RemoteRefs) for the wire."""
    if isinstance(value, RemoteRef):
        return value.to_wire()
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


class Bridge:
    """Owns the local WS server and the single plugin connection."""

    def __init__(self, port: int | None = None, *, ports: tuple[int, ...] | None = None) -> None:
        self._ports = (port,) if port else (ports or DEFAULT_PORTS)
        self.port: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._conn: Any = None
        self._conn_lock = threading.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._hello: dict[str, Any] | None = None
        self._hello_event = threading.Event()
        self._release_queue: list[str] = []
        self._release_lock = threading.Lock()
        self._event_handlers: list[Callable[[dict[str, Any]], None]] = []
        self._started = threading.Event()
        self._start_error: BaseException | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Bind the WS server and start the loop thread. Raises on bind failure."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, name="prpr-bridge", daemon=True)
        self._thread.start()
        self._started.wait(timeout=10.0)
        if self._start_error is not None:
            err = self._start_error
            self._thread = None
            self._start_error = None
            if isinstance(err, OSError):
                raise errors.ConnectionError(
                    f"Could not bind the bridge server on ports {self._ports}.",
                    cause="Another prpr process (daemon, MCP server, or CLI) already owns the port.",
                    fix="Use the running `prpr serve` daemon, or stop the other process.",
                    state={"ports": list(self._ports), "oserror": str(err)},
                ) from err
            raise err
        if self.port is None:
            raise errors.ConnectionError("Bridge server failed to start (unknown error).")

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as exc:  # propagate bind errors to start()
            self._start_error = exc
            self._started.set()
            return
        self._loop.run_forever()

    async def _serve(self) -> None:
        import websockets

        last_err: OSError | None = None
        for candidate in self._ports:
            try:
                self._server = await websockets.serve(
                    self._on_connection,
                    "127.0.0.1",
                    candidate,
                    max_size=64 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                )
                self.port = candidate
                break
            except OSError as exc:
                last_err = exc
        if self.port is None and last_err is not None:
            raise last_err
        self._started.set()
        logger.info("bridge listening on ws://127.0.0.1:%s", self.port)

    async def _on_connection(self, websocket: Any) -> None:
        with self._conn_lock:
            self._conn = websocket
        logger.info("plugin connected from %s", getattr(websocket, "remote_address", "?"))
        try:
            async for raw in websocket:
                self._on_frame(raw)
        except Exception as exc:
            logger.debug("plugin connection closed: %s", exc)
        finally:
            with self._conn_lock:
                if self._conn is websocket:
                    self._conn = None
                    self._hello_event.clear()

    def _on_frame(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            logger.warning("bad frame from plugin: %r", raw[:200])
            return
        if "id" in msg and msg.get("id") in self._pending:
            future = self._pending.pop(msg["id"])
            if not future.done():
                future.set_result(msg)
            return
        event = msg.get("event")
        if event == "hello":
            self._hello = msg
            self._hello_event.set()
            logger.info("plugin hello: %s", msg)
            return
        if event is not None:
            for handler in list(self._event_handlers):
                try:
                    handler(msg)
                except Exception:
                    logger.exception("event handler failed")

    def close(self) -> None:
        self._closed = True
        loop = self._loop
        if loop is None:
            return

        async def _shutdown() -> None:
            with self._conn_lock:
                conn = self._conn
                self._conn = None
            if conn is not None:
                with suppress(Exception):
                    await conn.close()
            if self._server is not None:
                self._server.close()
                with suppress(Exception):
                    await self._server.wait_closed()
            loop.call_soon(loop.stop)

        with suppress(Exception):
            asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        with self._conn_lock:
            return self._conn is not None

    @property
    def hello(self) -> dict[str, Any] | None:
        return self._hello

    def wait_for_plugin(self, timeout: float = 30.0) -> dict[str, Any]:
        """Block until the plugin has connected and said hello."""
        if not self._hello_event.wait(timeout=timeout):
            raise errors.PluginNotConnectedError(
                "The prpr bridge plugin did not connect.",
                cause="Premiere Pro isn't running, or the headless bridge plugin isn't loaded yet.",
                fix="Launch Premiere Pro (the headless bridge starts with it). If it "
                "was just installed, restart Premiere once. Run `prpr doctor`.",
                state={"port": self.port, "timeout_s": timeout},
            )
        return self._hello or {}

    def on_event(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self._event_handlers.append(handler)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def _queue_release(self, handle: str) -> None:
        if self._closed:
            return
        with self._release_lock:
            self._release_queue.append(handle)

    def _drain_releases(self) -> list[str]:
        with self._release_lock:
            drained, self._release_queue = self._release_queue, []
            return drained

    def request(self, op: str, *, timeout: float = 60.0, **payload: Any) -> Any:
        """Send one RPC request to the plugin and return the decoded result."""
        loop = self._loop
        if loop is None:
            raise errors.BridgeError(
                "Bridge is not running.", fix="Call Bridge.start() or use prpr.Premiere()."
            )
        with self._conn_lock:
            conn = self._conn
        if conn is None:
            raise errors.PluginNotConnectedError(
                "No plugin connection.",
                cause="Premiere Pro isn't running, or the headless bridge plugin isn't loaded yet.",
                fix="Open Premiere Pro and the prpr bridge panel, or run `prpr doctor`.",
                state={"port": self.port},
            )

        # Piggy-back garbage-collected handle releases onto this request.
        stale = self._drain_releases()
        if stale and op != "release":
            with suppress(errors.PrprError):
                self._request_raw(conn, loop, {"op": "release", "handles": stale}, timeout=10.0)

        message = {"op": op, **_encode(payload)}
        response = self._request_raw(conn, loop, message, timeout=timeout)
        if response.get("ok"):
            return self.decode(response.get("result"))

        err = response.get("error") or {}
        raise errors.HostJSError(
            err.get("message", "JavaScript error inside Premiere."),
            cause=err.get("name"),
            state={"op": op, "stack": err.get("stack")},
        )

    def _request_raw(
        self,
        conn: Any,
        loop: asyncio.AbstractEventLoop,
        message: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        req_id = str(uuid.uuid4())
        message = {"id": req_id, **message}

        async def _send() -> asyncio.Future[dict[str, Any]]:
            future: asyncio.Future[dict[str, Any]] = loop.create_future()
            self._pending[req_id] = future
            await conn.send(json.dumps(message))
            return future

        async def _send_and_wait() -> dict[str, Any]:
            future = await _send()
            return await asyncio.wait_for(future, timeout=timeout)

        try:
            return asyncio.run_coroutine_threadsafe(_send_and_wait(), loop).result(
                timeout=timeout + 5
            )
        except (TimeoutError, asyncio.TimeoutError) as exc:
            self._pending.pop(req_id, None)
            raise errors.BridgeError(
                f"Bridge request '{message.get('op')}' timed out after {timeout}s.",
                cause="Premiere is busy (modal dialog, long export) or the plugin hung.",
                fix="Check Premiere for open modal dialogs; increase the timeout for long operations.",
                state={"op": message.get("op")},
            ) from exc
        except Exception as exc:
            self._pending.pop(req_id, None)
            raise errors.BridgeError(
                f"Bridge request failed: {exc}", state={"op": message.get("op")}
            ) from exc

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def decode(self, value: Any) -> Any:
        """Convert wire values into Python values (handle refs -> RemoteRef)."""
        if isinstance(value, dict):
            if "$h" in value:
                return RemoteRef(
                    str(value["$h"]), value.get("$type", "?"), value.get("$snap"), self
                )
            return {k: self.decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.decode(v) for v in value]
        return value

    # ------------------------------------------------------------------
    # Convenience ops
    # ------------------------------------------------------------------

    def ping(self, timeout: float = 10.0) -> dict[str, Any]:
        return self.request("ping", timeout=timeout)

    def eval_js(self, code: str, args: Any = None, *, timeout: float = 60.0) -> Any:
        """Run an async JS function body inside Premiere.

        The code runs as ``async (ppro, uxp, H, args) => { <code> }`` — use
        ``return`` to produce a result.
        """
        return self.request("eval", code=code, args=args, timeout=timeout)

    def call(self, target: Any, path: str, *args: Any, timeout: float = 60.0) -> Any:
        return self.request("call", target=target, path=path, args=list(args), timeout=timeout)

    def get(self, target: Any, path: str, *, timeout: float = 30.0) -> Any:
        return self.request("get", target=target, path=path, timeout=timeout)

    def set(self, target: Any, path: str, value: Any, *, timeout: float = 30.0) -> Any:
        return self.request("set", target=target, path=path, value=value, timeout=timeout)

    def transaction(
        self,
        project: RemoteRef,
        steps: list[dict[str, Any]],
        *,
        label: str = "prpr",
        timeout: float = 60.0,
    ) -> Any:
        """Create actions inside lockedAccess and execute them as one undo step.

        Each step is ``{"target": RemoteRef, "method": str, "args": [...]}``.
        """
        return self.request(
            "transaction", project=project, steps=steps, label=label, timeout=timeout
        )


__all__ = ["DEFAULT_PORTS", "Bridge", "RemoteRef"]
