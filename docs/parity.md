# dvr ↔ prpr parity

`prpr` (Adobe Premiere Pro) and [`dvr`](https://github.com/mhadifilms/dvr)
(DaVinci Resolve) are structural siblings. They are separate repos for
separate apps, but they follow **one convention**, so a human or agent
building on either doesn't have to learn — or implement — things twice.

## The contract

1. **Same routing.** A capability that exists in both apps has the same
   command path, tool name, and parameter names in both repos:
   `prpr timeline inspect` ↔ `dvr timeline inspect`, MCP `marker_add` ↔
   `marker_add`. Premiere calls timelines "sequences" — prpr still routes
   them under `timeline`.
2. **Same shapes.** Output envelopes (json/table/yaml selection, error
   JSON schema `{type, message, cause, fix, state}`) are identical.
3. **Loud gaps.** An operation one app can't perform still *exists* in
   that repo's CLI/MCP surface and fails with a structured
   `NotSupportedError` whose `fix` names the closest alternative. Nothing
   silently degrades, so cross-app scripts fail at the right line with an
   actionable message.
4. **A machine-readable matrix.** Both packages ship the same table in
   `schema.py` (`PARITY`); inspect it with:

   ```bash
   prpr schema show parity | jq '.operations["render.queue"]'
   # {"status": "dvr-only", "reason": "no enumerable render queue in UXP"}
   ```

## Adding a feature (human or agent checklist)

1. Implement it in the repo whose app supports it, following the existing
   namespace (`project`, `timeline`, `media`, `render`, ...).
2. Add the operation to `PARITY` in **both** repos with the same key:
   - supported by both apps → `both` (and implement it in both)
   - one-sided → `dvr-only` / `prpr-only` **with a reason**, and register a
     `NotSupportedError` surface in the other repo when the command path
     would otherwise exist.
3. Run `python scripts/check_parity.py` — with both repos checked out
   side-by-side it cross-checks statuses; CI runs the single-repo checks.

## Status meanings

| status | meaning |
|---|---|
| `both` | implemented in dvr and prpr with the same routing |
| `dvr-only` | Resolve supports it; prpr raises `NotSupportedError` with a fix |
| `prpr-only` | Premiere supports it; dvr raises `NotSupportedError` with a fix |

## Notable one-sided operations

Premiere (prpr) can't: enumerate/cancel the render queue, switch
workspaces/pages, import interchange timelines (removed in 26.3), color
grading, Fusion, gallery stills, project-manager database operations.

Resolve (dvr) can't: apply effects/transitions by matchName, component
parameter keyframing via a factory catalog, XMP metadata, source monitor
control, MOGRT insertion, per-project properties store.

See `prpr schema show parity` for the full, current matrix.
