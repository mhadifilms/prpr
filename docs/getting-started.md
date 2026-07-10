# Getting started

## Install

```bash
pip install prpr
```

Requirements: Adobe Premiere Pro **25.6+** (built and tested against 26.x)
and Python 3.10+.

## One-time setup: the bridge plugin

Premiere's UXP API lives inside the app, so `prpr` ships a tiny headless
plugin that connects Premiere to the CLI/library/MCP server.

```bash
prpr plugin install
```

This packages the bundled plugin into a `.ccx` and installs it through
Adobe's own installer (UPIA, part of Creative Cloud). Then **restart
Premiere once** so it registers the plugin.

The bridge is **headless** — a command-entrypoint plugin whose code runs
at Premiere startup. There's no panel to dock or keep open: it dials into
the local `prpr` server automatically and reconnects forever, including
across Premiere and daemon restarts. Confirm with `prpr plugin check`.

Verify the whole chain:

```bash
prpr doctor --probe
```

## First commands

```bash
prpr ping                          # -> {"connected": true, "version": "26.5.0", ...}
prpr project ensure MyShow         # open-or-create ~/Documents/prpr Projects/MyShow.prproj
prpr media import ~/footage/*.mp4 --bin Footage
prpr timeline ensure Edit_v1
prpr timeline append clip_a.mp4
prpr timeline mark --at 1.5 --name "start" --color-index 1
prpr timeline inspect | jq .tracks
prpr render presets                # discovers .epr presets on this machine
prpr render submit --target-dir ~/exports --preset "Match Source - Adaptive High Bitrate" --wait
```

Every command emits JSON when piped and a table on a TTY
(`--format json|table|yaml` or `PRPR_FORMAT` to override).

## Faster CLI: the daemon

Each CLI invocation hosts the bridge and waits ~1–2s for the panel to
reconnect. For agent workloads and scripts, run the daemon once and every
subsequent command reuses its live connection:

```bash
prpr serve start        # background daemon owns the bridge
prpr timeline inspect   # instant — forwarded over a Unix socket
prpr serve stop
```

## Where things live

| | |
|---|---|
| Projects created by name | `~/Documents/prpr Projects/` (`PRPR_PROJECTS_DIR` overrides) |
| Snapshots | `~/.prpr/snapshots/` |
| Daemon socket | `~/.cache/prpr/prpr.sock` |
| Bridge port | `8855` (then 8856/8857; `PRPR_PORT` pins one) |

## Troubleshooting

`prpr doctor` diagnoses the common failure modes: Premiere not installed /
not running, plugin not installed, panel not opened yet, port conflicts.
Every error `prpr` raises carries a `cause` and a `fix` — read the fix.
