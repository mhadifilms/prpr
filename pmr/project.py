"""Project-level operations.

Premiere projects are files on disk (``.prproj``), not entries in a
database like Resolve's project manager. ``pmr`` keeps dvr's namespace
API (``list`` / ``current`` / ``ensure`` / ``create`` / ``load`` /
``save``) with these semantics:

- ``list()`` returns the projects **open** in Premiere right now.
- ``ensure(name)`` opens or creates ``<projects-dir>/<name>.prproj``
  (``PMR_PROJECTS_DIR`` overrides the default documents location); a
  path with ``/`` or ``.prproj`` is used verbatim.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import errors
from ._js import snippet

if TYPE_CHECKING:
    from .premiere import Premiere


def projects_dir() -> Path:
    env = os.environ.get("PMR_PROJECTS_DIR")
    if env:
        target = Path(env).expanduser()
    else:
        target = Path.home() / "Documents" / "pmr Projects"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _resolve_project_path(name_or_path: str) -> Path:
    raw = str(name_or_path)
    if raw.endswith(".prproj") or "/" in raw or "\\" in raw:
        return Path(raw).expanduser()
    return projects_dir() / f"{raw}.prproj"


class Project:
    """The currently open project (Premiere's active project)."""

    def __init__(self, premiere: Premiere, info: dict[str, Any]) -> None:
        self._p = premiere
        self._info = info

    @property
    def name(self) -> str:
        return str(self._info.get("name", ""))

    @property
    def path(self) -> str | None:
        return self._info.get("path")

    def inspect(self) -> dict[str, Any]:
        return self._p.eval_js(snippet("project_inspect"))

    def save(self) -> dict[str, Any]:
        return self._p.eval_js(snippet("project_save"))

    def save_as(self, path: str) -> dict[str, Any]:
        return self._p.eval_js(snippet("project_save_as"), {"path": str(path)})

    def close(self, *, prompt_if_dirty: bool = False) -> dict[str, Any]:
        return self._p.eval_js(snippet("project_close"), {"prompt_if_dirty": prompt_if_dirty})

    def to_dict(self) -> dict[str, Any]:
        return dict(self._info)

    def __repr__(self) -> str:
        return f"<Project {self.name!r}>"


class ProjectNamespace:
    """``p.project`` — project operations mirroring ``dvr``'s namespace."""

    def __init__(self, premiere: Premiere) -> None:
        self._p = premiere

    def list(self) -> list[dict[str, Any]]:
        """List projects currently open in Premiere."""
        return self._p.eval_js(snippet("project_list_open"))

    @property
    def current(self) -> Project | None:
        """The active project, or None when nothing is open."""
        try:
            info = self._p.eval_js(snippet("project_inspect"))
        except errors.HostJSError as exc:
            if "No active project" in (exc.message or ""):
                return None
            raise
        return Project(self._p, info)

    def require_current(self) -> Project:
        current = self.current
        if current is None:
            raise errors.ProjectError(
                "No project is currently open in Premiere.",
                fix="Open one with `pmr project ensure <name>` or `pmr project load <path>`.",
            )
        return current

    def create(self, name: str) -> Project:
        """Create a new project file and open it."""
        path = _resolve_project_path(name)
        if path.exists():
            raise errors.ProjectError(
                f"Project file already exists: {path}",
                fix=f"Use `ensure` to open-or-create, or `load {path}`.",
                state={"path": str(path)},
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        info = self._p.eval_js(snippet("project_create"), {"path": str(path)})
        return Project(self._p, info)

    def load(self, name: str) -> Project:
        """Open an existing project file."""
        path = _resolve_project_path(name)
        if not path.exists():
            raise errors.ProjectError(
                f"Project file not found: {path}",
                fix="Check the name/path, or use `ensure` to create it.",
                state={"path": str(path), "projects_dir": str(projects_dir())},
            )
        info = self._p.eval_js(snippet("project_open"), {"path": str(path)}, timeout=300.0)
        return Project(self._p, info)

    def ensure(self, name: str) -> Project:
        """Open the project if it exists, create it otherwise. Idempotent."""
        path = _resolve_project_path(name)
        current = self.current
        if current is not None and current.path and Path(current.path) == path:
            return current
        if path.exists():
            return self.load(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        info = self._p.eval_js(snippet("project_create"), {"path": str(path)})
        return Project(self._p, info)

    def save(self) -> dict[str, Any]:
        return self.require_current().save()

    def delete(self, name: str) -> dict[str, Any]:
        """Delete a project *file* from disk. Refuses if it's currently open."""
        path = _resolve_project_path(name)
        current = self.current
        if current is not None and current.path and Path(current.path) == path:
            raise errors.ProjectError(
                f"Project {path.name} is currently open in Premiere.",
                fix="Close it first (`pmr project close`), then delete.",
                state={"path": str(path)},
            )
        if not path.exists():
            raise errors.ProjectError(
                f"Project file not found: {path}", state={"path": str(path)}
            )
        path.unlink()
        return {"deleted": str(path)}


__all__ = ["Project", "ProjectNamespace", "projects_dir"]
