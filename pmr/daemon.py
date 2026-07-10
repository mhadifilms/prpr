"""Local daemon that holds the Premiere bridge across CLI invocations.

Unlike Resolve, Premiere *requires* a resident server: the UXP plugin
can only dial out to one WebSocket endpoint at a time. The daemon owns
that endpoint (the :class:`pmr.bridge.Bridge`) and serves CLI/library
clients over a Unix-domain socket, so many short-lived `pmr` commands
share one live plugin connection with zero reconnect latency.

Wire format (identical to dvr's daemon)
---------------------------------------

Newline-delimited JSON. One request per line, one response per line:

    {"id": "<correlation-id>", "method": "timeline.inspect", "params": {}}
    -> {"id": "<correlation-id>", "ok": true,  "result": {...}}
    -> {"id": "<correlation-id>", "ok": false, "error": {...}}

Methods are dotted paths into the public library (``timeline.inspect``,
``project.list``, ``render.presets``, ...) validated against an explicit
allow-list, plus ``cli`` which runs any pmr CLI command in-process.

Socket location: ``$XDG_RUNTIME_DIR/pmr/pmr.sock`` if set, otherwise
``~/.cache/pmr/pmr.sock`` (mode 0600).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import socketserver
import sys
import threading
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from . import errors
from .premiere import Premiere

logger = logging.getLogger("pmr.daemon")


def socket_path() -> Path:
    """Return the conventional socket path for this user."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime_dir) if runtime_dir else Path.home() / ".cache"
    target = base / "pmr"
    target.mkdir(parents=True, exist_ok=True)
    return target / "pmr.sock"


def pid_path() -> Path:
    return socket_path().with_suffix(".pid")


# ---------------------------------------------------------------------------
# Method dispatch
# ---------------------------------------------------------------------------

# Allow-list: dotted attribute path on a Premiere instance + callable flag.
_METHODS: dict[str, tuple[str, bool]] = {
    "app.inspect": ("app.inspect", True),
    "app.version": ("app.version", False),
    "app.product": ("app.product", False),
    "inspect": ("inspect", True),
    "ping": ("ping", True),
    "project.list": ("project.list", True),
    "project.current": ("project.current", False),
    "project.ensure": ("project.ensure", True),
    "project.create": ("project.create", True),
    "project.load": ("project.load", True),
    "project.save": ("project.save", True),
    "project.delete": ("project.delete", True),
    "timeline.list": ("timeline.list", True),
    "timeline.current": ("timeline.current", False),
    "timeline.inspect": ("timeline.inspect", True),  # synthetic — see _dispatch
    "timeline.create": ("timeline.create", True),
    "timeline.ensure": ("timeline.ensure", True),
    "timeline.switch": ("timeline.set_current", True),
    "timeline.delete": ("timeline.delete", True),
    "media.inspect": ("media.inspect", True),
    "media.bins": ("media.bins", True),
    "media.import": ("media.import_", True),
    "render.presets": ("render.presets", True),
    "render.ame_status": ("render.ame_status", True),
    "effects.list": ("effects.list", True),
}


def methods() -> list[str]:
    """Return the sorted allow-list of RPC method names the daemon accepts."""
    return sorted([*_METHODS, "cli"])


# ---------------------------------------------------------------------------
# Full-CLI execution ("cli" method)
# ---------------------------------------------------------------------------

_CLI_LOCK = threading.Lock()


def run_cli(argv: list[str]) -> dict[str, Any]:
    """Execute a pmr CLI command in this process; return stdout/stderr/exit code."""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    from .cli.main import app

    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = 0
    with _CLI_LOCK, redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            rv = app(args=list(argv), prog_name="pmr", standalone_mode=False)
            if isinstance(rv, int):
                exit_code = rv
        except errors.PmrError as exc:
            from .cli import output as cli_output

            cli_output.emit_error(exc)
            exit_code = 1
        except SystemExit as exc:
            code = exc.code
            exit_code = code if isinstance(code, int) else (0 if code is None else 1)
        except Exception as exc:
            show = getattr(exc, "show", None)
            code = getattr(exc, "exit_code", None)
            if callable(show) and code is not None:  # ClickException / UsageError
                show(file=stderr)
                exit_code = int(code)
            elif code is not None:  # click.exceptions.Exit
                exit_code = int(code)
            elif type(exc).__name__ == "Abort":
                stderr.write("aborted\n")
                exit_code = 1
            else:
                raise
    return {"stdout": stdout.getvalue(), "stderr": stderr.getvalue(), "exit_code": exit_code}


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if hasattr(value, "inspect"):
        return _serialize(value.inspect())
    if hasattr(value, "to_dict"):
        return _serialize(value.to_dict())
    return str(value)


def _dispatch(premiere: Premiere, method: str, params: Any) -> Any:
    if method not in _METHODS:
        raise errors.PmrError(
            f"Unknown method {method!r}.",
            fix="See `pmr serve methods` for the allow-list.",
        )

    if method == "timeline.inspect":
        target = premiere.timeline.require_current()
        return target.inspect()

    path, callable_ = _METHODS[method]
    obj: Any = premiere
    for part in path.split("."):
        obj = getattr(obj, part)

    if not callable_:
        return obj

    if params is None:
        return obj()
    if isinstance(params, dict):
        return obj(**params)
    if isinstance(params, list):
        return obj(*params)
    return obj(params)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def handle(self) -> None:
        for raw_line in self.rfile:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except ValueError as exc:
                self._reply({"id": None, "ok": False, "error": {"message": f"bad JSON: {exc}"}})
                continue
            req_id = req.get("id") or str(uuid.uuid4())
            method = req.get("method", "")
            params = req.get("params")
            try:
                if method == "cli":
                    argv = list((params or {}).get("argv") or [])
                    self._reply({"id": req_id, "ok": True, "result": run_cli(argv)})
                    continue
                peer = self.server.get_premiere()
                result = _dispatch(peer, method, params)
                self._reply({"id": req_id, "ok": True, "result": _serialize(result)})
            except errors.PmrError as exc:
                self._reply({"id": req_id, "ok": False, "error": exc.to_dict()})
            except Exception as exc:
                self.server.invalidate_premiere()
                self._reply(
                    {
                        "id": req_id,
                        "ok": False,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                )

    def _reply(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload) + "\n"
        self.wfile.write(line.encode("utf-8"))
        with suppress(BrokenPipeError):
            self.wfile.flush()


_THREADING_UNIX_STREAM_SERVER: Any = getattr(socketserver, "ThreadingUnixStreamServer", object)


class _Server(_THREADING_UNIX_STREAM_SERVER):  # type: ignore[misc, valid-type, unused-ignore]
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self, path: str, *, auto_launch: bool = True, connect_timeout: float = 60.0
    ) -> None:
        super().__init__(path, _Handler)
        self._auto_launch = auto_launch
        self._connect_timeout = connect_timeout
        self._premiere: Premiere | None = None
        self._lock = threading.Lock()

    def get_premiere(self) -> Premiere:
        """Return a live Premiere handle, reconnecting if the plugin dropped."""
        with self._lock:
            if self._premiere is not None:
                if self._premiere.bridge.connected:
                    return self._premiere
                # Bridge server is still up; the plugin may just be
                # reconnecting (Premiere restart). Give it a moment.
                try:
                    self._premiere.bridge.wait_for_plugin(timeout=10.0)
                    return self._premiere
                except errors.PmrError:
                    logger.warning("plugin connection lost; keeping server for reconnect")
                    raise
            self._premiere = Premiere(
                auto_launch=self._auto_launch, timeout=self._connect_timeout
            )
            return self._premiere

    def invalidate_premiere(self) -> None:
        """Note: the bridge server stays bound; the plugin reconnects to it."""


def serve(*, auto_launch: bool = True, timeout: float = 60.0) -> None:
    """Run the daemon in the foreground until interrupted."""
    if sys.platform == "win32":
        raise errors.PmrError(
            "The daemon mode does not currently support Windows.",
            fix="Use the in-process Python library on Windows.",
        )

    sock = socket_path()
    if sock.exists():
        if _ping_existing():
            raise errors.PmrError(
                f"A pmr daemon is already running at {sock}.",
                fix="Run `pmr serve stop` first.",
            )
        sock.unlink()

    server = _Server(str(sock), auto_launch=auto_launch, connect_timeout=timeout)
    os.chmod(sock, 0o600)
    pid_path().write_text(str(os.getpid()))

    from .cli import session as cli_session

    cli_session.set_premiere_provider(server.get_premiere)

    try:
        premiere = server.get_premiere()
        logger.info(
            "Premiere %s connected; daemon listening on %s", premiere.app.version, sock
        )
    except errors.PmrError as exc:
        logger.warning(
            "could not connect to Premiere at startup; will retry on first request: %s", exc
        )

    try:
        server.serve_forever()
    finally:
        cli_session.set_premiere_provider(None)
        server.server_close()
        with suppress(FileNotFoundError):
            sock.unlink()
        with suppress(FileNotFoundError):
            pid_path().unlink()


def _ping_existing(timeout: float = 0.5) -> bool:
    sock = socket_path()
    if not sock.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:  # type: ignore[attr-defined, unused-ignore]
            s.settimeout(timeout)
            s.connect(str(sock))
            s.sendall(b'{"id":"ping","method":"ping"}\n')
            data = s.recv(4096)
            return b'"ok": true' in data or b'"ok":true' in data
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Client:
    """Synchronous client for a running daemon.

    ``timeout=None`` means block indefinitely — used for forwarded CLI
    commands whose runtime is unbounded (e.g. long exports).
    """

    def __init__(self, path: Path | None = None, timeout: float | None = 60.0) -> None:
        self._path = path or socket_path()
        self._timeout = timeout

    def call(self, method: str, params: Any = None) -> Any:
        if not self._path.exists():
            raise errors.ConnectionError(
                "No pmr daemon is running.",
                fix="Run `pmr serve start` first, or omit the daemon and use direct mode.",
                state={"socket": str(self._path)},
            )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:  # type: ignore[attr-defined, unused-ignore]
            s.settimeout(self._timeout)
            s.connect(str(self._path))
            req = {"id": str(uuid.uuid4()), "method": method, "params": params}
            s.sendall((json.dumps(req) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                data += chunk
            response = json.loads(data.decode("utf-8"))
        if not response.get("ok", False):
            err = response.get("error", {})
            raise errors.PmrError(
                err.get("message", "daemon call failed"),
                cause=err.get("cause"),
                fix=err.get("fix"),
                state=err.get("state", {}),
            )
        return response.get("result")


def stop_daemon() -> bool:
    """Stop a running daemon by sending SIGTERM. Returns True if one was stopped."""
    pid_file = pid_path()
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink()
        return False

    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pid_file.unlink()
        with suppress(FileNotFoundError):
            socket_path().unlink()
        return False
    return True


def status() -> dict[str, Any]:
    """Return ``{"running": bool, "pid": int | None, "socket": str}``."""
    pid_file = pid_path()
    sock = socket_path()
    if not pid_file.exists() or not sock.exists():
        return {"running": False, "pid": None, "socket": str(sock)}
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return {"running": False, "pid": None, "socket": str(sock)}

    try:
        os.kill(pid, 0)
        running = _ping_existing(timeout=1.0)
    except ProcessLookupError:
        running = False
    return {"running": running, "pid": pid, "socket": str(sock)}


__all__ = ["Client", "methods", "run_cli", "serve", "socket_path", "status", "stop_daemon"]
