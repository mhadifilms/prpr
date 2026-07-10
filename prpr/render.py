"""Export / encode operations.

Premiere's UXP API exposes ``EncoderManager.exportSequence`` (immediate,
queue-to-app, or queue-to-Adobe-Media-Encoder) driven by ``.epr`` preset
files, plus render lifecycle *events* — but **no enumerable render
queue** like Resolve's. ``prpr`` keeps dvr's ``render`` namespace:

- ``presets()``   discovers ``.epr`` files (user + AME + ``PRPR_PRESET_DIRS``)
- ``submit()``    exports the current sequence (optionally waiting)
- ``watch()``     streams encoder events until completion
- ``queue()``/``formats()``/``codecs()`` raise :class:`NotSupportedError`
  with pointers to the closest Premiere equivalent, keeping cross-app
  routing explicit instead of silently diverging.
"""

from __future__ import annotations

import glob
import os
import queue as queue_module
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import errors
from ._js import snippet

if TYPE_CHECKING:
    from .premiere import Premiere

_ENCODER_EVENTS = [
    "encoder.complete",
    "encoder.error",
    "encoder.cancel",
    "encoder.queue",
    "encoder.progress",
]

_EVENT_CONSTANTS = {
    "encoder.complete": "EVENT_RENDER_COMPLETE",
    "encoder.error": "EVENT_RENDER_ERROR",
    "encoder.cancel": "EVENT_RENDER_CANCEL",
    "encoder.queue": "EVENT_RENDER_QUEUE",
    "encoder.progress": "EVENT_RENDER_PROGRESS",
}


def preset_search_dirs() -> list[Path]:
    """Directories scanned for .epr export presets."""
    dirs: list[Path] = []
    env = os.environ.get("PRPR_PRESET_DIRS")
    if env:
        dirs.extend(Path(part).expanduser() for part in env.split(os.pathsep) if part)
    documents = Path.home() / "Documents" / "Adobe"
    dirs.extend(sorted(documents.glob("Adobe Media Encoder/*/Presets")))
    for pattern in (
        "/Applications/Adobe Media Encoder */Adobe Media Encoder *.app/Contents/MediaIO/systempresets",
    ):
        dirs.extend(Path(p) for p in sorted(glob.glob(pattern)))
    return [d for d in dirs if d.is_dir()]


def find_presets(*, limit: int = 500) -> list[dict[str, str]]:
    """Discover .epr preset files on this machine."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for directory in preset_search_dirs():
        for file in sorted(directory.rglob("*.epr")):
            if len(out) >= limit:
                return out
            name = file.stem
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "path": str(file)})
    return out


def resolve_preset(name_or_path: str | None) -> str | None:
    """Resolve a preset by name (searched) or verbatim path."""
    if not name_or_path:
        return None
    candidate = Path(name_or_path).expanduser()
    if candidate.suffix == ".epr" and candidate.exists():
        return str(candidate)
    matches = [p for p in find_presets() if p["name"].lower() == str(name_or_path).lower()]
    if matches:
        return matches[0]["path"]
    raise errors.RenderError(
        f"Export preset not found: {name_or_path}",
        fix="Pass a path to a .epr file, or run `prpr render presets` to list "
        "discovered presets. Save presets from Premiere's Export mode.",
        state={"searched": [str(d) for d in preset_search_dirs()][:10]},
    )


class RenderJob:
    """A submitted export. Premiere doesn't expose job handles, so a job is
    tracked by the encoder-event stream started at submission time."""

    def __init__(self, namespace: RenderNamespace, output_path: str | None) -> None:
        self._ns = namespace
        self.output_path = output_path
        self.status = "submitted"
        self.progress: float | None = None
        self.error: str | None = None

    def wait(self, timeout: float = 3600.0, *, poll: float = 0.5) -> RenderJob:
        """Block until the export completes (event-driven, file-existence fallback)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self._ns._drain_events():
                name = event.get("name", "")
                if "PROGRESS" in name.upper():
                    payload = event.get("payload") or {}
                    self.progress = payload.get("progress") if isinstance(payload, dict) else None
                    self.status = "rendering"
                if "COMPLETE" in name.upper():
                    self.status = "complete"
                    return self
                if "ERROR" in name.upper():
                    self.status = "failed"
                    self.error = str(event.get("payload"))
                    raise errors.RenderJobError(
                        "Export failed inside Premiere/AME.",
                        cause=self.error,
                        state={"output": self.output_path},
                    )
                if "CANCEL" in name.upper():
                    self.status = "cancelled"
                    raise errors.RenderJobError("Export was cancelled.")
            if self.output_path and os.path.exists(self.output_path) and self.status == "submitted":
                # Fallback: some Premiere builds complete without firing events
                # back to a late subscriber. Existence + stable size = done.
                size1 = os.path.getsize(self.output_path)
                time.sleep(max(poll, 1.0))
                if os.path.getsize(self.output_path) == size1 and size1 > 0:
                    self.status = "complete"
                    return self
            time.sleep(poll)
        raise errors.RenderError(
            f"Export did not complete within {timeout}s.",
            state={"output": self.output_path, "status": self.status},
        )

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"

    def inspect(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "progress": self.progress,
            "output_path": self.output_path,
            "error": self.error,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.inspect()


class RenderNamespace:
    """``p.render`` — export operations mirroring dvr's render namespace."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere
        self._events: queue_module.Queue[dict[str, Any]] = queue_module.Queue()
        self._subscribed = False
        self._p.bridge.on_event(self._on_event)

    def _on_event(self, event: dict[str, Any]) -> None:
        if event.get("event") == "host-event":
            self._events.put(event)

    def _drain_events(self) -> list[dict[str, Any]]:
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue_module.Empty:
                return out

    def _ensure_subscribed(self) -> None:
        if self._subscribed:
            return
        code = "const manager = ppro.EncoderManager.getManager();\nreturn H.ref(manager);"
        manager = self._p.eval_js(code)
        for constant in _EVENT_CONSTANTS.values():
            event_name = self._p.bridge.get("ppro", f"EncoderManager.{constant}")
            if isinstance(event_name, str):
                self._p.bridge.request("subscribe", target=manager, event=event_name)
        self._subscribed = True

    # ------------------------------------------------------------------

    def presets(self) -> list[dict[str, str]]:
        """List discovered .epr export presets."""
        return find_presets()

    def submit(
        self,
        target_dir: str | None = None,
        *,
        custom_name: str | None = None,
        preset: str | None = None,
        timeline: str | None = None,
        queue_to: str | None = None,
        wait: bool = False,
        timeout: float = 3600.0,
    ) -> RenderJob:
        """Export a sequence.

        Args:
            target_dir:  Output directory (required unless the sequence has
                         applied export settings).
            custom_name: Output file name (extension derived from preset).
            preset:      .epr preset name or path.
            timeline:    Sequence name/guid (defaults to active).
            queue_to:    None = export immediately in Premiere;
                         "ame" = queue to Adobe Media Encoder;
                         "app" = queue in Premiere's export queue.
            wait:        Block until complete.
        """
        preset_path = resolve_preset(preset)
        output_file: str | None = None
        if target_dir:
            directory = Path(target_dir).expanduser()
            directory.mkdir(parents=True, exist_ok=True)
            name = custom_name
            if not name:
                inspected = self._p.eval_js(
                    snippet("sequence_inspect"), {"sequence": timeline, "names_only": True}
                )
                name = inspected.get("name") or "export"
            extension = ""
            if preset_path:
                try:
                    ext = self._p.eval_js(
                        snippet("export_file_extension"),
                        {"sequence": timeline, "preset_file": preset_path},
                    )
                    extension = ext.get("extension") or ""
                except errors.PrprError:
                    extension = ""
            if extension and not str(name).endswith(f".{extension}"):
                name = f"{name}.{extension}"
            output_file = str(directory / str(name))

        export_type = {None: "immediately", "ame": "queue_to_ame", "app": "queue_to_app"}.get(
            queue_to, queue_to or "immediately"
        )
        self._ensure_subscribed()
        self._drain_events()
        self._p.eval_js(
            snippet("export_sequence"),
            {
                "sequence": timeline,
                "output_file": output_file,
                "preset_file": preset_path,
                "export_type": export_type,
                "export_full": True,
            },
            timeout=600.0,
        )
        job = RenderJob(self, output_file)
        if wait:
            job.wait(timeout=timeout)
        return job

    def export_frame(
        self,
        seconds: float,
        file: str,
        *,
        timeline: str | None = None,
        width: int = 0,
        height: int = 0,
    ) -> dict[str, Any]:
        """Export a still frame (png/jpg/tif/exr/dpx/bmp/gif/tga by extension)."""
        path = Path(file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return self._p.eval_js(
            snippet("export_frame"),
            {
                "sequence": timeline,
                "seconds": seconds,
                "filename": path.name,
                "dir": str(path.parent),
                "width": width,
                "height": height,
            },
            timeout=300.0,
        )

    def watch(self, *, timeout: float = 3600.0) -> Any:
        """Yield encoder events until a terminal event or timeout."""
        self._ensure_subscribed()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for event in self._drain_events():
                yield event
                name = str(event.get("name", "")).upper()
                if "COMPLETE" in name or "ERROR" in name or "CANCEL" in name:
                    return
            time.sleep(0.25)

    def ame_status(self) -> dict[str, Any]:
        return self._p.eval_js(snippet("ame_status"))

    # ------------------------------------------------------------------
    # Explicit cross-app gaps (dvr parity)
    # ------------------------------------------------------------------

    def queue(self) -> list[dict[str, Any]]:
        raise errors.NotSupportedError(
            "Premiere's UXP API has no enumerable render queue.",
            cause="EncoderManager only submits jobs and emits events; queued jobs "
            "cannot be listed, reordered, or deleted.",
            fix="Use `prpr render submit --wait` and `prpr render watch` for status; "
            "the enumerable queue is a dvr-only operation.",
        )

    def formats(self) -> list[dict[str, Any]]:
        raise errors.NotSupportedError(
            "Premiere exports are driven by .epr presets, not format/codec enums.",
            fix="Use `prpr render presets` to discover .epr presets instead.",
        )

    def codecs(self, format: str) -> list[dict[str, Any]]:
        raise errors.NotSupportedError(
            "Premiere exports are driven by .epr presets, not format/codec enums.",
            fix="Use `prpr render presets` to discover .epr presets instead.",
        )

    def stop(self) -> dict[str, Any]:
        raise errors.NotSupportedError(
            "Premiere's UXP API cannot cancel a running export programmatically.",
            fix="Cancel from Premiere/AME's UI; watch for the cancel event with "
            "`prpr render watch`.",
        )

    def clear(self) -> dict[str, Any]:
        raise errors.NotSupportedError(
            "Premiere's UXP API has no render queue to clear.",
            fix="Manage queued exports in Premiere/AME's UI.",
        )


__all__ = [
    "RenderJob",
    "RenderNamespace",
    "find_presets",
    "preset_search_dirs",
    "resolve_preset",
]
