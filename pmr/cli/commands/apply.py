"""``pmr apply`` and ``pmr plan`` — declarative reconciliation."""

from __future__ import annotations

from typing import Annotated

import typer

from ... import spec as spec_mod
from .. import output
from ..session import premiere_from_ctx as _premiere


def _action_rows(actions: list[spec_mod.Action]) -> list[dict[str, str]]:
    return [{"op": a.op, "target": a.target, "detail": a.detail} for a in actions]


def register(app: typer.Typer) -> None:
    """Register ``apply`` and ``plan`` as top-level commands."""

    @app.command("plan")
    def plan_cmd(
        ctx: typer.Context,
        spec_file: Annotated[str, typer.Argument(help="Path to a YAML or JSON spec.")],
    ) -> None:
        """Show the actions `pmr apply` would take, without executing."""
        cfg = ctx.obj or {}
        premiere = _premiere(ctx)
        spec = spec_mod.load_spec(spec_file)
        actions = spec_mod.plan(spec, premiere)
        output.emit(
            _action_rows(actions),
            fmt=cfg.get("format"),
            headline=f"plan: {spec.project}",
        )

    @app.command("apply")
    def apply_cmd(
        ctx: typer.Context,
        spec_file: Annotated[str, typer.Argument(help="Path to a YAML or JSON spec.")],
        dry_run: Annotated[
            bool,
            typer.Option("--dry-run", "-n", help="Print the plan without applying."),
        ] = False,
        yes: Annotated[
            bool,
            typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
        ] = False,
        verify: Annotated[
            bool,
            typer.Option(
                "--verify",
                help="Re-plan after applying; fail if anything did not reconcile.",
            ),
        ] = False,
    ) -> None:
        """Reconcile a spec against the live Premiere state."""
        cfg = ctx.obj or {}
        premiere = _premiere(ctx)
        spec = spec_mod.load_spec(spec_file)

        actions = spec_mod.plan(spec, premiere)
        output.emit(
            _action_rows(actions),
            fmt=cfg.get("format"),
            headline=f"plan: {spec.project}",
        )

        if dry_run:
            return

        if not yes:
            typer.confirm(f"Apply {len(actions)} action(s) to {spec.project!r}?", abort=True)

        result = spec_mod.apply(spec, premiere, dry_run=False, verify=verify)
        output.emit(
            {"applied": result.get("applied"), "project": spec.project},
            fmt=cfg.get("format"),
        )
