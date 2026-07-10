"""Plugin version comparison / auto-update decision logic."""

from __future__ import annotations

from prpr import connection


def test_version_tuple_parsing() -> None:
    assert connection._version_tuple("0.3.0") == (0, 3, 0)
    assert connection._version_tuple("1.0") == (1, 0)
    assert connection._version_tuple("2.10.1") == (2, 10, 1)
    assert connection._version_tuple(None) == (0,)
    assert connection._version_tuple("v0.3.0-beta") == (0, 3, 0)  # digits only


def test_version_ordering() -> None:
    vt = connection._version_tuple
    assert vt("0.2.0") < vt("0.3.0")
    assert vt("0.3.0") < vt("0.10.0")
    assert vt("1.0.0") > vt("0.9.9")
    assert vt("0.3.0") == vt("0.3.0")


def test_bundled_version_matches_manifest() -> None:
    # Reads the real bundled plugin manifest.
    assert connection.bundled_plugin_version() is not None


def test_freshness_stale_when_connected_older() -> None:
    f = connection.plugin_freshness("0.0.1")
    assert f["stale"] is True
    assert f["connected"] == "0.0.1"


def test_freshness_current_when_equal() -> None:
    bundled = connection.bundled_plugin_version()
    f = connection.plugin_freshness(bundled)
    assert f["stale"] is False


def test_freshness_not_stale_when_connected_newer() -> None:
    f = connection.plugin_freshness("999.0.0")
    assert f["stale"] is False


def test_freshness_handles_unknown_connected() -> None:
    f = connection.plugin_freshness(None)
    assert f["stale"] is False
