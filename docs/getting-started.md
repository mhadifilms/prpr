# Getting started

## Install

```bash
pip install pmr
```

Requirements: Adobe Premiere Pro **25.6+** (built and tested against 26.x)
and Python 3.10+.

## One-time setup: the bridge plugin

Premiere's UXP API lives inside the app, so `pmr` ships a tiny resident
panel that connects Premiere to the CLI/library/MCP server.

```bash
pmr plugin install
```

This packages the bundled plugin into a `.ccx` and installs it through
Adobe's own installer (UPIA, part of Creative Cloud). Then, **once**, in
Premiere:

> Window → UXP Plugins → **pmr bridge**

Dock the panel anywhere (it's small and quiet). It dials into the local
`pmr` server automatically and reconnects forever — including across
Premiere and daemon restarts. Panels that are part of a saved workspace
re-open with it, so add it to your workspace and forget about it.

Verify the whole chain:

```bash
pmr doctor --probe
```

## First commands

```bash
pmr ping                          # -> {"connected": true, "version": "26.5.0", ...}
pmr project ensure MyShow         # open-or-create ~/Documents/pmr Projects/MyShow.prproj
pmr media import ~/footage/*.mp4 --bin Footage
pmr timeline ensure Edit_v1
pmr timeline append clip_a.mp4
pmr timeline mark --at 1.5 --name "start" --color-index 1
pmr timeline inspect | jq .tracks
pmr render presets                # discovers .epr presets on this machine
pmr render submit --target-dir ~/exports --preset "Match Source - Adaptive High Bitrate" --wait
```

Every command emits JSON when piped and a table on a TTY
(`--format json|table|yaml` or `PMR_FORMAT` to override).

## Faster CLI: the daemon

Each CLI invocation hosts the bridge and waits ~1–2s for the panel to
reconnect. For agent workloads and scripts, run the daemon once and every
subsequent command reuses its live connection:

```bash
pmr serve start        # background daemon owns the bridge
pmr timeline inspect   # instant — forwarded over a Unix socket
pmr serve stop
```

## Where things live

| | |
|---|---|
| Projects created by name | `~/Documents/pmr Projects/` (`PMR_PROJECTS_DIR` overrides) |
| Snapshots | `~/.pmr/snapshots/` |
| Daemon socket | `~/.cache/pmr/pmr.sock` |
| Bridge port | `8855` (then 8856/8857; `PMR_PORT` pins one) |

## Troubleshooting

`pmr doctor` diagnoses the common failure modes: Premiere not installed /
not running, plugin not installed, panel not opened yet, port conflicts.
Every error `pmr` raises carries a `cause` and a `fix` — read the fix.
