"""Daemon dispatch, allow-list, serialization, status — no socket needed."""

from __future__ import annotations

import pytest

from pmr import daemon, errors


def test_methods_include_allowlist_and_cli() -> None:
    methods = daemon.methods()
    assert "cli" in methods
    assert "timeline.inspect" in methods
    assert "project.ensure" in methods
    assert methods == sorted(methods)


def test_socket_and_pid_paths_agree() -> None:
    sock = daemon.socket_path()
    assert sock.name == "pmr.sock"
    assert daemon.pid_path().name == "pmr.pid"
    assert daemon.pid_path().parent == sock.parent


def test_status_when_not_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daemon, "socket_path", lambda: tmp_path / "pmr.sock")
    monkeypatch.setattr(daemon, "pid_path", lambda: tmp_path / "pmr.pid")
    status = daemon.status()
    assert status["running"] is False
    assert status["pid"] is None


def test_serialize_unwraps_inspectable() -> None:
    class Fake:
        def inspect(self):
            return {"name": "x", "nested": {"a": 1}}

    assert daemon._serialize(Fake()) == {"name": "x", "nested": {"a": 1}}
    assert daemon._serialize([1, "a", True, None]) == [1, "a", True, None]


def test_serialize_prefers_to_dict() -> None:
    class Fake:
        def to_dict(self):
            return {"k": "v"}

    assert daemon._serialize(Fake()) == {"k": "v"}


def test_dispatch_rejects_unknown_method() -> None:
    with pytest.raises(errors.PmrError) as exc:
        daemon._dispatch(object(), "does.not.exist", None)  # type: ignore[arg-type]
    assert "Unknown method" in exc.value.message


def test_dispatch_property_read() -> None:
    class FakeApp:
        version = "26.5.0"

    class FakePremiere:
        app = FakeApp()

    result = daemon._dispatch(FakePremiere(), "app.version", None)  # type: ignore[arg-type]
    assert result == "26.5.0"


def test_dispatch_method_with_kwargs() -> None:
    class FakeNamespace:
        def ensure(self, name):
            return {"name": name}

    class FakePremiere:
        project = FakeNamespace()

    result = daemon._dispatch(FakePremiere(), "project.ensure", {"name": "X"})  # type: ignore[arg-type]
    assert result == {"name": "X"}


def test_dispatch_timeline_inspect_synthetic() -> None:
    class FakeTimeline:
        def inspect(self):
            return {"name": "T"}

    class FakeNamespace:
        def require_current(self):
            return FakeTimeline()

    class FakePremiere:
        timeline = FakeNamespace()

    result = daemon._dispatch(FakePremiere(), "timeline.inspect", None)  # type: ignore[arg-type]
    assert result == {"name": "T"}


def test_client_errors_without_socket(tmp_path) -> None:
    client = daemon.Client(path=tmp_path / "missing.sock")
    with pytest.raises(errors.ConnectionError):
        client.call("ping")
