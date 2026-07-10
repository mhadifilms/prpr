# Contributing to pmr

Thanks for your interest! `pmr` wraps Premiere's UXP API — which runs
inside the app and fails in its own peculiar ways. Edge cases are
everywhere, and contributions filling them in are exactly what this
project needs. `pmr` is the sibling of [`dvr`](https://github.com/mhadifilms/dvr);
please read [the parity contract](docs/parity.md) before adding surface.

## Setup

```bash
git clone https://github.com/mhadifilms/pmr
cd pmr
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Premiere Pro 25.6+ must be installed for live/integration testing. Unit
tests run without it (they mock the bridge).

## Running checks

```bash
ruff check pmr tests            # lint
ruff format pmr tests           # format
mypy pmr                        # type check
pytest                          # unit tests (no Premiere needed)
python scripts/check_parity.py  # dvr↔pmr parity matrix
python scripts/smoke_live.py clip.mov   # full live E2E (needs Premiere)
node --check plugin/main.js     # bridge plugin syntax
```

CI runs lint, format, tests, and the parity check on macOS and Linux
against Python 3.10 and 3.12. PRs must pass.

## Architecture

- `plugin/` — the UXP bridge panel (generic RPC executor). Rarely needs
  changing; semantics live in Python.
- `pmr/bridge.py` — local WebSocket server + synchronous request broker.
- `pmr/_js.py` — host-side JavaScript snippets. **This is where new
  Premiere capabilities are added.** Each snippet is one bridge
  round-trip; mutations go through `runTransaction`, sync DOM reads
  through `lockedAccess`.
- `pmr/{premiere,project,timeline,media,render,effects}.py` — the typed
  Python wrappers that call snippets.
- `pmr/{cli,mcp}/` — CLI and MCP surfaces over the same library.

## Adding a capability

1. Write the JS snippet in `pmr/_js.py` (test it live with
   `p.eval_js(...)` first).
2. Add the typed Python wrapper.
3. Surface it in the CLI (`pmr/cli/commands/`) and MCP
   (`pmr/mcp/server.py`) using the existing names — check what `dvr`
   calls the equivalent.
4. Add it to `PARITY` in `pmr/schema.py` **and** dvr's, with a reason if
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
