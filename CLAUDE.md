# prpr — agent notes

CLI + Python library + MCP server for Adobe Premiere Pro, driven through a
bundled UXP bridge panel. Structural sibling of `../dvr` (DaVinci Resolve):
same namespaces, routing, output conventions, and error model.

## The one rule

**Keep prpr and dvr in sync.** Before adding or renaming any command, MCP
tool, or namespace: read `docs/parity.md`, update `PARITY` in
`prpr/schema.py` (and its dvr counterpart), and run
`python scripts/check_parity.py`. Operations the other app can't perform
must fail with `NotSupportedError` (cause + fix), never be silently absent.

## Architecture in one breath

Python hosts `ws://127.0.0.1:8855` (`prpr/bridge.py`); the UXP panel
(`plugin/main.js`, generic RPC executor) dials in from inside Premiere.
Host-side semantics live in JS snippets in `prpr/_js.py` (lockedAccess +
executeTransaction rules); Python wrappers in `premiere/project/timeline/
media/render/effects.py` mirror dvr's object model. Daemon
(`prpr/daemon.py`) shares one bridge across CLI calls — dvr's wire format.

## Working on this repo

- venv: `.venv/bin/python`; tests: `.venv/bin/python -m pytest -q` (mock
  bridge, no Premiere needed); lint: `ruff check prpr tests --fix`.
- Live testing needs Premiere running with the bridge panel open once:
  `prpr plugin install`, then Window > UXP Plugins > prpr bridge. For dev
  reloads use Adobe's devtools CLI (`uxp plugin load` from `plugin/`,
  x86_64 Node via Rosetta on Apple Silicon — see docs/getting-started.md).
- Time crosses the bridge in **seconds**; Premiere ticks are
  254,016,000,000/s. All mutations must run inside a snippet's
  `runTransaction` (single undo step). Sync DOM reads (`getTrackItems`,
  `markers.getMarkers`) must be wrapped in `project.lockedAccess`.
- Premiere quirks encoded in snippets: never pass `undefined` mid-argument
  to action factories; `importFiles` returns bare booleans (read back to
  confirm); export completion is event-driven (`EncoderManager` events)
  with a file-existence fallback.

## Version gating

Feature-detect (`typeof ppro.X !== "undefined"`), don't parse versions.
Premiere 25.6 is the UXP baseline; 26.3 added ProjectConverter (AAF/OTIO/
FCPXML export), subclips, SourceMonitor.setPosition; capabilities are
reported by `app.inspect()`.
