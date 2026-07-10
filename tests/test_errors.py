"""Error model: structure, serialization, hierarchy — mirrors dvr's tests."""

from __future__ import annotations

import pytest

from prpr import errors


def test_base_error_fields() -> None:
    err = errors.PrprError(
        "Something failed.",
        cause="the cause",
        fix="the fix",
        state={"key": "value"},
    )
    assert err.message == "Something failed."
    assert err.cause == "the cause"
    assert err.fix == "the fix"
    assert err.state == {"key": "value"}


def test_str_renders_diagnostics() -> None:
    err = errors.TimelineError("No sequence.", cause="nothing active", fix="create one")
    text = str(err)
    assert "No sequence." in text
    assert "Cause: nothing active" in text
    assert "Fix:   create one" in text


def test_to_dict_schema() -> None:
    err = errors.RenderError("Export failed.", state={"output": "/tmp/x.mp4"})
    data = err.to_dict()
    assert data == {
        "type": "RenderError",
        "message": "Export failed.",
        "cause": None,
        "fix": None,
        "state": {"output": "/tmp/x.mp4"},
    }


@pytest.mark.parametrize(
    "subclass",
    [
        errors.ConnectionError,
        errors.NotInstalledError,
        errors.PluginNotConnectedError,
        errors.BridgeError,
        errors.HostJSError,
        errors.NotSupportedError,
        errors.ProjectError,
        errors.TimelineError,
        errors.TimelineNotFoundError,
        errors.TrackError,
        errors.ClipError,
        errors.MediaError,
        errors.MediaImportError,
        errors.RenderError,
        errors.RenderJobError,
        errors.SettingsError,
        errors.EffectError,
        errors.MarkerError,
        errors.MetadataError,
        errors.InterchangeError,
        errors.SpecError,
    ],
)
def test_all_subclass_base(subclass: type) -> None:
    assert issubclass(subclass, errors.PrprError)
    instance = subclass("message")
    assert isinstance(instance, errors.PrprError)
    assert instance.to_dict()["type"] == subclass.__name__


def test_specialized_hierarchies() -> None:
    assert issubclass(errors.PluginNotConnectedError, errors.ConnectionError)
    assert issubclass(errors.HostJSError, errors.BridgeError)
    assert issubclass(errors.MediaImportError, errors.MediaError)
    assert issubclass(errors.RenderJobError, errors.RenderError)
    assert issubclass(errors.TimelineNotFoundError, errors.TimelineError)
