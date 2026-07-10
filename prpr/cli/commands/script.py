"""``prpr eval`` / ``prpr exec`` / ``prpr repl`` — scripting escape hatches.

Unlike dvr (whose ``eval`` runs *Python* against the Resolve API), prpr's
``eval`` and ``exec`` run **JavaScript inside Premiere** via the bridge
plugin (``ppro`` and ``uxp`` are in scope). ``repl`` stays a Python REPL
with a live :class:`~prpr.premiere.Premiere` handle bound to ``p``.
"""

from __future__ import annotations

import code
import contextlib
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from ... import errors
from ...premiere import Premiere
from .. import output
from ..session import premiere_from_ctx


def register(app: typer.Typer) -> None:
    @app.command("eval")
    def eval_cmd(
        ctx: typer.Context,
        expression: Annotated[
            str,
            typer.Argument(
                help="JavaScript expression/body run inside Premiere (`ppro`, `uxp` in scope)."
            ),
        ],
    ) -> None:
        """Evaluate a JavaScript expression inside Premiere.

        Examples:

            prpr eval "ppro.Project.getActiveProject()"
            prpr eval "(await ppro.Project.getActiveProject()).name"
            prpr eval "return (await ppro.Project.getActiveProject()).name"
        """
        cfg = ctx.obj or {}
        p = premiere_from_ctx(ctx)
        code_body = expression if "return " in expression else f"return {expression}"
        try:
            value = p.eval_js(code_body)
        except errors.PrprError as exc:
            output.emit_error(exc, fmt=cfg.get("format"))
            raise typer.Exit(1) from exc
        output.emit(_to_jsonable(value), fmt=cfg.get("format"))

    @app.command("exec")
    def exec_cmd(
        ctx: typer.Context,
        file: Annotated[
            str, typer.Argument(help="JavaScript file whose body runs inside Premiere.")
        ],
    ) -> None:
        """Run a .js file body inside Premiere via the bridge.

        The file is executed as an async function body with ``ppro`` and
        ``uxp`` in scope; use ``return`` to emit a result.
        """
        cfg = ctx.obj or {}
        path = Path(file).expanduser().resolve()
        if not path.exists():
            typer.echo(f"file not found: {path}", err=True)
            raise typer.Exit(1)
        source = path.read_text(encoding="utf-8")
        p = premiere_from_ctx(ctx)
        try:
            value = p.eval_js(source)
        except errors.PrprError as exc:
            output.emit_error(exc, fmt=cfg.get("format"))
            raise typer.Exit(1) from exc
        output.emit(_to_jsonable(value), fmt=cfg.get("format"))

    @app.command("repl")
    def repl_cmd(ctx: typer.Context) -> None:
        """Open an interactive Python REPL with `p` bound to a live Premiere."""
        p = premiere_from_ctx(ctx)
        ns = _ns(p)
        banner = (
            f"prpr repl — {p.app.product} {p.app.version}\n"
            "Available: p, project, timeline, prpr\n"
            "Press Ctrl-D to exit."
        )
        with contextlib.suppress(ImportError):
            import readline  # noqa: F401 — enables history if available
        code.interact(banner=banner, local=ns, exitmsg="bye")


def _ns(p: Premiere) -> dict[str, Any]:
    import prpr

    project = p.project.current
    timeline = p.timeline.current
    return {
        "p": p,
        "project": project,
        "timeline": timeline,
        "prpr": prpr,
        "sys": sys,
    }


def _to_jsonable(value: Any) -> Any:
    if hasattr(value, "inspect") and callable(value.inspect):
        return value.inspect()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    return value
