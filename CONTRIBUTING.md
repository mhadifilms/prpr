# Contributing to prpr

Thanks for your interest! `prpr` wraps Premiere's UXP API — which runs
inside the app and fails in its own peculiar ways. Edge cases are
everywhere, and contributions filling them in are exactly what this
project needs. `prpr` is the sibling of [`dvr`](https://github.com/mhadifilms/dvr);
please read [the parity contract](docs/parity.md) before adding surface.

## Setup

```bash
git clone https://github.com/mhadifilms/pmr
cd prpr
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Premiere Pro 25.6+ must be installed for live/integration testing. Unit
tests run without it (they mock the bridge).

## Running checks

```bash
ruff check prpr tests            # lint
ruff format prpr tests           # format
mypy prpr                        # type check
pytest                          # unit tests (no Premiere needed)
python scripts/check_parity.py  # dvr↔prpr parity matrix
python scripts/smoke_live.py clip.mov   # full live E2E (needs Premiere)
node --check plugin/main.js     # bridge plugin syntax
```

CI runs lint, format, tests, and the parity check on macOS and Linux
against Python 3.10 and 3.12. PRs must pass.

## Architecture

- `plugin/` — the UXP bridge panel (generic RPC executor). Rarely needs
  changing; semantics live in Python.
- `prpr/bridge.py` — local WebSocket server + synchronous request broker.
- `prpr/_js.py` — host-side JavaScript snippets. **This is where new
  Premiere capabilities are added.** Each snippet is one bridge
  round-trip; mutations go through `runTransaction`, sync DOM reads
  through `lockedAccess`.
- `prpr/{premiere,project,timeline,media,render,effects}.py` — the typed
  Python wrappers that call snippets.
- `prpr/{cli,mcp}/` — CLI and MCP surfaces over the same library.

## Adding a capability

1. Write the JS snippet in `prpr/_js.py` (test it live with
   `p.eval_js(...)` first).
2. Add the typed Python wrapper.
3. Surface it in the CLI (`prpr/cli/commands/`) and MCP
   (`prpr/mcp/server.py`) using the existing names — check what `dvr`
   calls the equivalent.
4. Add it to `PARITY` in `prpr/schema.py` **and** dvr's, with a reason if
   one-sided. Run `scripts/check_parity.py`.
5. Add a unit test (mock bridge) and, ideally, a `smoke_live.py` stage.

## Premiere gotchas (hard-won)

- Never pass `undefined` mid-argument to an action factory — throws
  "Illegal Parameter type". Use concrete zero values.
- Sync getters (`getTrackItems`, `markers.getMarkers`, component params)
  must run inside `project.lockedAccess`.
- `Sequence.setSelection` crashes Premiere 26.5 beta — guarded off.
- Times cross the bridge in seconds; ticks are 254,016,000,000/s.
- Export completion is event-driven; there's no render queue to poll.

## License

By contributing you agree your contributions are licensed under MIT.
