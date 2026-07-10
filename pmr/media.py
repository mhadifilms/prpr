"""Media pool (project panel) operations.

Premiere's project panel plays the role of Resolve's media pool: bins
(FolderItems) and clips (ClipProjectItems). ``pmr`` keeps dvr's
``media`` namespace: ``inspect`` / ``bins`` / ``ls`` / ``import_`` /
``bin_ensure`` / ``move`` plus the pure-Python ``scan_media_files``
helper that needs no running Premiere.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._js import snippet

if TYPE_CHECKING:
    from .premiere import Premiere

VIDEO_EXTENSIONS = {
    ".mov",
    ".mp4",
    ".m4v",
    ".mxf",
    ".avi",
    ".mkv",
    ".webm",
    ".r3d",
    ".braw",
    ".ari",
    ".dng",
    ".prores",
    ".mts",
    ".m2ts",
    ".wmv",
    ".flv",
    ".3gp",
}
AUDIO_EXTENSIONS = {
    ".wav",
    ".aif",
    ".aiff",
    ".mp3",
    ".m4a",
    ".flac",
    ".ogg",
    ".caf",
    ".bwf",
}
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".exr",
    ".dpx",
    ".tga",
    ".psd",
    ".ai",
    ".bmp",
    ".gif",
    ".heic",
    ".webp",
}


def media_kind_for_path(file_path: str) -> str | None:
    """Classify a file as video/audio/image by extension, else None."""
    ext = Path(file_path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    return None


def scan_media_files(
    path: str,
    *,
    recursive: bool = True,
    include_hidden: bool = False,
    max_files: int = 10000,
) -> list[dict[str, str]]:
    """Preview importable media files under a path. No Premiere required."""
    root = Path(path).expanduser()
    out: list[dict[str, str]] = []
    if root.is_file():
        kind = media_kind_for_path(str(root))
        if kind:
            out.append({"path": str(root), "kind": kind})
        return out
    walker = root.rglob("*") if recursive else root.glob("*")
    for file in sorted(walker):
        if len(out) >= max_files:
            break
        if not file.is_file():
            continue
        if not include_hidden and any(part.startswith(".") for part in file.parts):
            continue
        kind = media_kind_for_path(str(file))
        if kind:
            out.append({"path": str(file), "kind": kind})
    return out


class MediaNamespace:
    """``p.media`` — project panel operations mirroring dvr's media pool."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere

    def inspect(self, *, with_paths: bool = True) -> dict[str, Any]:
        """Full bin/clip tree of the project panel."""
        return self._p.eval_js(snippet("media_tree"), {"with_paths": with_paths}, timeout=300.0)

    def bins(self) -> list[dict[str, Any]]:
        """Top-level bins."""
        tree = self.inspect(with_paths=False)
        return [item for item in tree.get("items", []) if item.get("kind") == "bin"]

    def ls(self, bin_path: str | None = None) -> list[dict[str, Any]]:
        """List items in a bin (nested ``A/B/C`` paths supported)."""
        tree = self.inspect(with_paths=True)
        items = tree.get("items", [])
        if bin_path:
            for part in str(bin_path).split("/"):
                match = next(
                    (i for i in items if i.get("kind") == "bin" and i.get("name") == part), None
                )
                if match is None:
                    from . import errors

                    raise errors.MediaError(
                        f"Bin not found: {bin_path}",
                        state={"available": [i["name"] for i in items if i.get("kind") == "bin"]},
                    )
                items = match.get("children", [])
        return items

    def import_(
        self,
        paths: list[str],
        *,
        bin: str | None = None,
        as_numbered_stills: bool = False,
    ) -> dict[str, Any]:
        """Import media files, optionally into a (created-if-missing) bin."""
        from . import errors

        absolute: list[str] = []
        missing: list[str] = []
        for p in paths:
            resolved = str(Path(p).expanduser().resolve())
            if not os.path.exists(resolved):
                missing.append(resolved)
            absolute.append(resolved)
        if missing:
            raise errors.MediaImportError(
                f"{len(missing)} file(s) do not exist.",
                fix="Check the paths — Premiere silently skips missing files.",
                state={"missing": missing[:20]},
            )
        return self._p.eval_js(
            snippet("media_import"),
            {"paths": absolute, "bin": bin, "as_numbered_stills": as_numbered_stills},
            timeout=600.0,
        )

    def find_or_import(self, path: str, *, bin: str | None = None) -> dict[str, Any]:
        """Idempotent import: reuse an existing clip for this path if present."""
        resolved = str(Path(path).expanduser().resolve())
        existing = self.find_clip(path=resolved)
        if existing is not None:
            return {"imported": 0, "existing": existing}
        return self.import_([resolved], bin=bin)

    def find_clip(
        self, *, name: str | None = None, path: str | None = None
    ) -> dict[str, Any] | None:
        """Find a clip in the project panel by name or media path."""
        from . import errors

        try:
            return self._p.eval_js(snippet("media_inspect_item"), {"name": name, "path": path})
        except errors.HostJSError as exc:
            if "not found" in (exc.message or ""):
                return None
            raise

    def bin_ensure(self, path: str) -> dict[str, Any]:
        """Create a bin path (``A/B/C``) if missing. Idempotent."""
        return self._p.eval_js(snippet("bin_ensure"), {"path": path})

    def bin_delete(self, path: str) -> dict[str, Any]:
        return self._p.eval_js(snippet("bin_delete"), {"path": path})

    def bin_rename(self, path: str, new_name: str) -> dict[str, Any]:
        """Rename a bin (identified by its current path)."""
        return self._p.eval_js(snippet("bin_rename"), {"path": path, "new_name": new_name})

    def smart_bin(self, name: str, query: str) -> dict[str, Any]:
        """Create a smart bin at the project root with a search query."""
        return self._p.eval_js(snippet("smart_bin_create"), {"name": name, "query": query})

    def color_label(
        self,
        *,
        name: str | None = None,
        path: str | None = None,
        set_index: int | None = None,
    ) -> dict[str, Any]:
        """Read (or set) a project item's color label index (0-14)."""
        return self._p.eval_js(
            snippet("color_label"), {"name": name, "path": path, "set_index": set_index}
        )

    def move(
        self,
        target_bin: str,
        *,
        source_bin: str | None = None,
        name_contains: str | None = None,
        names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Move clips between bins."""
        return self._p.eval_js(
            snippet("media_move"),
            {
                "target_bin": target_bin,
                "source_bin": source_bin,
                "name_contains": name_contains,
                "names": names,
            },
        )

    def scan(self, path: str, **kwargs: Any) -> list[dict[str, str]]:
        return scan_media_files(path, **kwargs)

    def attach_proxy(
        self,
        proxy_path: str,
        *,
        name: str | None = None,
        path: str | None = None,
        is_hi_res: bool = False,
    ) -> dict[str, Any]:
        """Attach a proxy (or hi-res alternate) to a clip. Not undoable."""
        return self._p.eval_js(
            snippet("proxy_attach"),
            {
                "name": name,
                "path": path,
                "proxy_path": str(Path(proxy_path).expanduser()),
                "is_hi_res": is_hi_res,
            },
        )

    def transcript_export(
        self, *, name: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        """Export a clip's speech-to-text transcript as JSON (26.3+)."""
        return self._p.eval_js(snippet("transcript_export"), {"name": name, "path": path})

    def transcript_import(
        self, json_text: str, *, name: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        """Import transcript JSON onto a clip (26.3+)."""
        return self._p.eval_js(
            snippet("transcript_import"), {"name": name, "path": path, "json": json_text}
        )

    def footage_interpretation(
        self,
        *,
        name: str | None = None,
        path: str | None = None,
        set: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read (or update) a clip's footage interpretation. Settable keys:
        frame_rate, pixel_aspect_ratio, field_type, remove_pulldown,
        alpha_usage, ignore_alpha, invert_alpha, input_lut_id."""
        return self._p.eval_js(
            snippet("footage_interpretation"), {"name": name, "path": path, "set": set}
        )

    def purge_cache(self) -> dict[str, Any]:
        """Purge Premiere's media cache (26.5+)."""
        return self._p.eval_js(snippet("purge_cache"), timeout=300.0)

    def selection(self) -> dict[str, Any]:
        """Project-panel selection (the items selected in the project view)."""
        return self._p.eval_js(snippet("selection_get"), {"scope": "project"})

    def create_subclip(
        self,
        subclip_name: str,
        start_seconds: float,
        end_seconds: float,
        *,
        name: str | None = None,
        path: str | None = None,
        hard_boundaries: bool = False,
        take_video: bool = True,
        take_audio: bool = True,
    ) -> dict[str, Any]:
        """Create a subclip from a source clip (26.3+)."""
        return self._p.eval_js(
            snippet("subclip_create"),
            {
                "name": name,
                "path": path,
                "subclip_name": subclip_name,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "hard_boundaries": hard_boundaries,
                "take_video": take_video,
                "take_audio": take_audio,
            },
        )


__all__ = [
    "AUDIO_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "MediaNamespace",
    "media_kind_for_path",
    "scan_media_files",
]
