"""Timeline (sequence) operations.

Premiere calls them *sequences*; ``prpr`` keeps dvr's ``timeline``
namespace so commands route identically across both apps. Times cross
the bridge as seconds; frame math uses the sequence fps from
``getTimebase()`` (Premiere ticks: 254,016,000,000 per second).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from . import errors
from ._js import snippet

if TYPE_CHECKING:
    from .premiere import Premiere


def _seconds(value: dict[str, Any] | None) -> float | None:
    if not value:
        return None
    seconds = value.get("seconds")
    return float(seconds) if seconds is not None else None


class TimelineItem:
    """A clip on a sequence track (VideoClipTrackItem / AudioClipTrackItem)."""

    def __init__(self, timeline: Timeline, detail: dict[str, Any], track_type: str) -> None:
        self._timeline = timeline
        self._detail = detail
        self.track_type = track_type

    @property
    def name(self) -> str | None:
        return self._detail.get("name")

    @property
    def start(self) -> float | None:
        return _seconds(self._detail.get("start"))

    @property
    def end(self) -> float | None:
        return _seconds(self._detail.get("end"))

    @property
    def duration(self) -> float | None:
        return _seconds(self._detail.get("duration"))

    @property
    def duration_frames(self) -> int | None:
        duration = self.duration
        fps = self._timeline.fps
        if duration is None or not fps:
            return None
        return round(duration * fps)

    @property
    def enabled(self) -> bool | None:
        return self._detail.get("enabled")

    @property
    def track_index(self) -> int | None:
        return self._detail.get("track_index")

    @property
    def speed(self) -> float | None:
        return self._detail.get("speed")

    def inspect(self) -> dict[str, Any]:
        return dict(self._detail)

    def rename(self, name: str) -> dict[str, Any]:
        return self._timeline._clip_update(
            name=self.name, track_index=self.track_index, track_type=self.track_type, set_name=name
        )

    def enable(self) -> dict[str, Any]:
        return self._timeline._clip_update(
            name=self.name,
            track_index=self.track_index,
            track_type=self.track_type,
            set_disabled=False,
        )

    def disable(self) -> dict[str, Any]:
        return self._timeline._clip_update(
            name=self.name,
            track_index=self.track_index,
            track_type=self.track_type,
            set_disabled=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.inspect()

    def __repr__(self) -> str:
        return f"<TimelineItem {self.name!r} {self.track_type}{self.track_index}>"


class ItemQuery:
    """Chainable query over timeline items (mirrors dvr's clip query)."""

    def __init__(self, items: list[TimelineItem]) -> None:
        self._items = items

    def where(self, predicate: Callable[[TimelineItem], bool]) -> ItemQuery:
        return ItemQuery([item for item in self._items if predicate(item)])

    def count(self) -> int:
        return len(self._items)

    def first(self) -> TimelineItem | None:
        return self._items[0] if self._items else None

    def each(self, fn: Callable[[TimelineItem], Any]) -> list[Any]:
        return [fn(item) for item in self._items]

    def __iter__(self) -> Any:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> TimelineItem:
        return self._items[index]


class Timeline:
    """A Premiere sequence, addressed by name/guid; state is read live."""

    def __init__(
        self, premiere: Premiere, ref: str | None = None, info: dict[str, Any] | None = None
    ) -> None:
        self._p = premiere
        self._ref = ref  # None = active sequence
        self._info = info or {}
        self._inspect_cache: dict[str, Any] | None = None

    # -- identity ------------------------------------------------------

    @property
    def name(self) -> str:
        if self._info.get("name"):
            return str(self._info["name"])
        return str(self._quick().get("name", ""))

    @property
    def guid(self) -> str | None:
        return self._info.get("guid") or self._quick().get("guid")

    def _quick(self) -> dict[str, Any]:
        if not self._info:
            self._info = self._p.eval_js(
                snippet("sequence_inspect"), {"sequence": self._ref, "names_only": True}
            )
        return self._info

    # -- inspection ----------------------------------------------------

    def inspect(self, *, names_only: bool = False) -> dict[str, Any]:
        result = self._p.eval_js(
            snippet("sequence_inspect"), {"sequence": self._ref, "names_only": names_only}
        )
        fps = result.get("fps")
        end = _seconds(result.get("end"))
        result["duration_seconds"] = end
        result["duration_frames"] = round(end * fps) if end is not None and fps else None
        self._inspect_cache = result
        self._info = {"name": result.get("name"), "guid": result.get("guid")}
        return result

    @property
    def fps(self) -> float | None:
        cache = self._inspect_cache or self.inspect(names_only=True)
        return cache.get("fps")

    @property
    def duration_frames(self) -> int | None:
        cache = self._inspect_cache or self.inspect(names_only=True)
        return cache.get("duration_frames")

    # -- items ---------------------------------------------------------

    def items(self, track_type: str = "video") -> list[TimelineItem]:
        data = self.inspect()
        out: list[TimelineItem] = []
        for track in data.get("tracks", {}).get(track_type, []):
            for detail in track.get("items", []):
                out.append(TimelineItem(self, detail, track_type))
        return out

    @property
    def clips(self) -> ItemQuery:
        return ItemQuery(self.items("video") + self.items("audio"))

    def tracks(self, track_type: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        data = self.inspect(names_only=True)
        tracks = data.get("tracks", {})
        if track_type:
            return list(tracks.get(track_type, []))
        return dict(tracks)

    # -- markers -------------------------------------------------------

    def markers(self) -> list[dict[str, Any]]:
        return self._p.eval_js(snippet("marker_list"), {"sequence": self._ref})

    def add_marker(
        self,
        seconds: float,
        *,
        name: str = "marker",
        note: str = "",
        marker_type: str = "Comment",
        duration_seconds: float | None = None,
        color_index: int | None = None,
    ) -> dict[str, Any]:
        return self._p.eval_js(
            snippet("marker_add"),
            {
                "sequence": self._ref,
                "seconds": seconds,
                "name": name,
                "comments": note,
                "marker_type": marker_type,
                "duration_seconds": duration_seconds,
                "color_index": color_index,
            },
        )

    def remove_marker(
        self, *, name: str | None = None, seconds: float | None = None
    ) -> dict[str, Any]:
        return self._p.eval_js(
            snippet("marker_remove"), {"sequence": self._ref, "name": name, "seconds": seconds}
        )

    def move_marker(
        self, to_seconds: float, *, name: str | None = None, from_seconds: float | None = None
    ) -> dict[str, Any]:
        """Move a marker (matched by name or current position) to a new time."""
        return self._p.eval_js(
            snippet("marker_move"),
            {
                "sequence": self._ref,
                "name": name,
                "from_seconds": from_seconds,
                "to_seconds": to_seconds,
            },
        )

    def work_area(
        self, in_seconds: float | None = None, out_seconds: float | None = None
    ) -> dict[str, Any]:
        """Read (or set) the sequence work area in/out points (26.5+)."""
        return self._p.eval_js(
            snippet("work_area"),
            {"sequence": self._ref, "in_seconds": in_seconds, "out_seconds": out_seconds},
        )

    def keyframes(
        self,
        component: str,
        param: str,
        *,
        clip_name: str | None = None,
        track_index: int | None = None,
        kind: str = "video",
    ) -> dict[str, Any]:
        """List keyframe times for a clip's component parameter."""
        return self._p.eval_js(
            snippet("keyframes_list"),
            {
                "sequence": self._ref,
                "component": component,
                "param": param,
                "clip_name": clip_name,
                "track_index": track_index,
                "kind": kind,
            },
        )

    def set_settings(self, **settings: Any) -> dict[str, Any]:
        """Read (with no args) or write sequence settings. Settable keys:
        max_bit_depth, max_render_quality, editing_mode,
        video_pixel_aspect_ratio, video_field_type,
        composite_in_linear_color, preview_file_format, preview_codec."""
        return self._p.eval_js(
            snippet("sequence_settings_set"), {"sequence": self._ref, "set": settings}
        )

    def insert_mogrt_from_library(
        self,
        library_name: str,
        element_name: str,
        *,
        seconds: float | None = None,
        video_track: int = 0,
        audio_track: int = 0,
    ) -> dict[str, Any]:
        """Insert a MOGRT from a Creative Cloud / local library by name."""
        return self._p.eval_js(
            snippet("mogrt_from_library"),
            {
                "sequence": self._ref,
                "library_name": library_name,
                "element_name": element_name,
                "seconds": seconds,
                "video_track": video_track,
                "audio_track": audio_track,
            },
        )

    # -- editing -------------------------------------------------------

    def insert(
        self,
        item_name: str | None = None,
        *,
        item_path: str | None = None,
        seconds: float | None = None,
        video_track: int = 0,
        audio_track: int = 0,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Insert (or overwrite) a project item into this sequence."""
        return self._p.eval_js(
            snippet("timeline_insert"),
            {
                "sequence": self._ref,
                "item_name": item_name,
                "item_path": item_path,
                "seconds": seconds,
                "video_track": video_track,
                "audio_track": audio_track,
                "overwrite": overwrite,
            },
        )

    def append(
        self,
        item_name: str | None = None,
        *,
        item_path: str | None = None,
        video_track: int = 0,
        audio_track: int = 0,
    ) -> dict[str, Any]:
        """Append a project item at the current end of the sequence."""
        return self.insert(
            item_name,
            item_path=item_path,
            seconds=None,
            video_track=video_track,
            audio_track=audio_track,
            overwrite=True,
        )

    def delete_clips(
        self,
        *,
        track_type: str = "video",
        track_indexes: list[int] | None = None,
        name_contains: str | None = None,
        ripple: bool = False,
    ) -> dict[str, Any]:
        return self._p.eval_js(
            snippet("timeline_remove_items"),
            {
                "sequence": self._ref,
                "track_type": track_type,
                "track_indexes": track_indexes,
                "name_contains": name_contains,
                "ripple": ripple,
            },
        )

    def _clip_update(self, **kwargs: Any) -> dict[str, Any]:
        return self._p.eval_js(snippet("clip_update"), {"sequence": self._ref, **kwargs})

    def rename(self, new_name: str) -> dict[str, Any]:
        result = self._p.eval_js(
            snippet("sequence_rename"), {"sequence": self._ref, "new_name": new_name}
        )
        self._info = {}
        self._ref = new_name
        return result

    def insert_mogrt(
        self,
        path: str,
        *,
        seconds: float | None = None,
        video_track: int = 0,
        audio_track: int = 0,
    ) -> dict[str, Any]:
        """Insert a Motion Graphics template (.mogrt) into this sequence."""
        return self._p.eval_js(
            snippet("mogrt_insert"),
            {
                "sequence": self._ref,
                "path": path,
                "seconds": seconds,
                "video_track": video_track,
                "audio_track": audio_track,
            },
        )

    def scene_edit_detection(
        self,
        *,
        operation: str = "cut",
        clip_name: str | None = None,
        track_index: int | None = None,
    ) -> dict[str, Any]:
        """Run scene edit detection on matching clips (cut | marker | subclip)."""
        return self._p.eval_js(
            snippet("scene_edit_detection"),
            {
                "sequence": self._ref,
                "operation": operation,
                "clip_name": clip_name,
                "track_index": track_index,
            },
            timeout=1800.0,
        )

    def set_in_out(
        self, in_seconds: float | None = None, out_seconds: float | None = None
    ) -> dict[str, Any]:
        """Set (or read, with no args) the sequence in/out points."""
        return self._p.eval_js(
            snippet("sequence_in_out"),
            {"sequence": self._ref, "in_seconds": in_seconds, "out_seconds": out_seconds},
        )

    def track_update(
        self,
        track_index: int,
        *,
        track_type: str = "video",
        mute: bool | None = None,
        set_name: str | None = None,
    ) -> dict[str, Any]:
        """Mute/unmute or rename a track (rename needs Premiere 26.3+)."""
        return self._p.eval_js(
            snippet("track_update"),
            {
                "sequence": self._ref,
                "track_index": track_index,
                "track_type": track_type,
                "mute": mute,
                "set_name": set_name,
            },
        )

    def create_subsequence(self, *, ignore_track_targeting: bool = True) -> dict[str, Any]:
        """Create a subsequence from the current in/out selection."""
        return self._p.eval_js(
            snippet("subsequence_create"),
            {"sequence": self._ref, "ignore_track_targeting": ignore_track_targeting},
        )

    def clone(self) -> dict[str, Any]:
        """Duplicate this sequence (Premiere names the copy)."""
        return self._p.eval_js(snippet("sequence_clone"), {"sequence": self._ref})

    def selection(self) -> dict[str, Any]:
        """The current track-item selection."""
        return self._p.eval_js(snippet("selection_get"), {"sequence": self._ref})

    def select(
        self,
        *,
        name: str | None = None,
        name_contains: str | None = None,
        track_type: str = "video",
        track_index: int | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Clear the sequence selection (``clear=True``).

        Setting a selection by filters is currently unavailable: Premiere
        26.5 beta crashes on ``Sequence.setSelection``. Only ``clear=True``
        is honored; anything else raises :class:`NotSupportedError` until
        Adobe fixes the host crash.
        """
        if not clear:
            raise errors.NotSupportedError(
                "Setting a timeline selection crashes Premiere 26.5 beta.",
                cause="Sequence.setSelection() takes the host down on this build.",
                fix="Use timeline.select(clear=True) to clear, or timeline.selection() "
                "to read the current selection. Filter clips with timeline.clips.where(...) "
                "instead of selecting them in the UI.",
            )
        return self._p.eval_js(
            snippet("selection_set"),
            {
                "sequence": self._ref,
                "track_type": track_type,
                "track_index": track_index,
                "clear": True,
            },
        )

    # -- transport ------------------------------------------------------

    @property
    def current_time(self) -> float | None:
        result = self._p.eval_js(snippet("sequence_player_position"), {"sequence": self._ref})
        return _seconds(result.get("position"))

    @current_time.setter
    def current_time(self, seconds: float) -> None:
        self._p.eval_js(
            snippet("sequence_player_position"), {"sequence": self._ref, "seconds": seconds}
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "guid": self.guid}

    def __repr__(self) -> str:
        return f"<Timeline {self._info.get('name') or self._ref or 'current'!r}>"


class TimelineNamespace:
    """``p.timeline`` — sequence operations mirroring dvr's namespace."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere

    def list(self) -> list[dict[str, Any]]:
        return self._p.eval_js(snippet("sequence_list"))

    @property
    def current(self) -> Timeline | None:
        try:
            info = self._p.eval_js(
                snippet("sequence_inspect"), {"sequence": None, "names_only": True}
            )
        except errors.HostJSError as exc:
            message = exc.message or ""
            if "No active sequence" in message or "No active project" in message:
                return None
            raise
        return Timeline(self._p, None, {"name": info.get("name"), "guid": info.get("guid")})

    def require_current(self) -> Timeline:
        current = self.current
        if current is None:
            raise errors.TimelineError(
                "No sequence is currently active.",
                fix="Create one with `prpr timeline create <name>` or open one in Premiere.",
            )
        return current

    def get(self, name: str) -> Timeline:
        for entry in self.list():
            if entry.get("name") == name or entry.get("guid") == name:
                return Timeline(self._p, name, entry)
        raise errors.TimelineNotFoundError(
            f"Sequence not found: {name}",
            state={"available": [entry.get("name") for entry in self.list()]},
        )

    def create(self, name: str, *, preset_path: str | None = None) -> Timeline:
        for entry in self.list():
            if entry.get("name") == name:
                raise errors.TimelineError(
                    f"Sequence already exists: {name}",
                    fix="Use `ensure` for open-or-create semantics.",
                )
        info = self._p.eval_js(
            snippet("sequence_create"), {"name": name, "preset_path": preset_path}
        )
        return Timeline(self._p, name, info)

    def ensure(self, name: str) -> Timeline:
        for entry in self.list():
            if entry.get("name") == name:
                return Timeline(self._p, name, entry)
        info = self._p.eval_js(snippet("sequence_create"), {"name": name})
        return Timeline(self._p, name, info)

    def set_current(self, name: str) -> dict[str, Any]:
        return self._p.eval_js(snippet("sequence_set_active"), {"sequence": name})

    def delete(self, name: str) -> dict[str, Any]:
        return self._p.eval_js(snippet("sequence_delete"), {"sequence": name})

    def create_from_media(
        self, name: str, items: Sequence[str], *, bin: str | None = None
    ) -> Timeline:
        """Create a sequence pre-populated from project items (by name)."""
        info = self._p.eval_js(
            snippet("sequence_from_media"), {"name": name, "items": items, "bin": bin}
        )
        return Timeline(self._p, name, info)


__all__ = ["ItemQuery", "Timeline", "TimelineItem", "TimelineNamespace"]
