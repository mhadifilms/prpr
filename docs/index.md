<p align="center">
  <img src="https://raw.githubusercontent.com/mhadifilms/pmr/main/assets/logo.svg" alt="pmr logo" width="140">
</p>

# pmr

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**The missing CLI, Python library, and MCP server for Adobe Premiere Pro.**

Declarative. Scriptable. LLM-friendly. Structural sibling of [`dvr`](https://github.com/mhadifilms/dvr) (the same project for DaVinci Resolve) — same namespaces, same routing, same error model.

`pmr` is a command-line tool, a typed Python library, and a [Model Context Protocol (MCP)](mcp.md) server for automating **Adobe Premiere Pro** — editing, sequencing, effects, and export. It drives Premiere's UXP API through a bundled bridge plugin, wraps it in clean idempotent operations with structured JSON output, and makes it usable by humans, scripts, and AI agents (Claude, Cursor, and any MCP-compatible client).

```bash
pip install pmr
```

```bash
$ pmr timeline inspect
{
  "name": "Edit_v1",
  "fps": 23.976,
  "duration_frames": 4274,
  "frame_size": {"width": 1920, "height": 1080},
  "tracks": {
    "video": [{"index": 0, "name": "Video 1", "clips": 2, "items": [...]}],
    "audio": [{"index": 0, "name": "Audio 1", "clips": 2, "items": [...]}]
  },
  "markers": [{"name": "start", "start": {"seconds": 1.0}, ...}]
}
```

---

## How it connects

Premiere has no external scripting socket — its UXP API runs *inside* the app, and UXP plugins can only dial **out**. So `pmr` inverts the connection:

```
pmr CLI / library / MCP  ──hosts──▶  ws://127.0.0.1:8855  ◀──dials in──  pmr bridge panel (UXP, inside Premiere)
```

One-time setup:

```bash
pmr plugin install     # packages + installs the bridge panel via Adobe's installer
# then in Premiere: Window > UXP Plugins > pmr bridge (dock it once, it reconnects forever)
pmr doctor --probe     # verify the whole chain
```

## Why pmr exists

Premiere's UXP API is powerful but locked inside the app:

- **No external process access.** Resolve ships a Python API; Premiere gives you a JavaScript sandbox in a panel.
- **Action/transaction ceremony.** Every mutation needs `lockedAccess` + `executeTransaction` + action objects.
- **Ticks.** Time is measured in 254,016,000,000ths of a second.
- **Silent failures.** `importFiles()` returns `false` and moves on with its day.
- **No batch operators, no inspection.** You loop `getVideoTrack(i)` → `getTrackItems(...)` → six async getters per clip.

`pmr` wraps all of it: one `inspect()` call returns full structured state, mutations are single undoable transactions, every failure decodes into an error with a `cause`, a `fix`, and a `state` snapshot.

## Three ways to use it

### 1. Python library

```python
from pmr import Premiere

p = Premiere()                        # hosts the bridge, launches Premiere if needed

p.project.ensure("MyShow")            # open-or-create ~/Documents/pmr Projects/MyShow.prproj
p.media.import_(["/footage/a.mp4"], bin="Footage")

tl = p.timeline.ensure("Edit_v1")
tl.append("a.mp4")
tl.add_marker(1.0, name="start", note="first pass", color_index=1)

p.effects.set_param("Motion", "Scale", 50, clip_name="a.mp4")     # transforms
p.effects.add_transition("ADBE Film Dissolve", clip_name="a.mp4")

job = p.render.submit(target_dir="/exports", preset="prores-422", wait=True)
print(job.output_path)
```

### 2. CLI

```bash
$ pmr project ensure MyShow
$ pmr media import /footage/*.mp4 --bin Footage
$ pmr timeline inspect | jq '.tracks.video[].items'
$ pmr render submit --target-dir /exports --preset prores-422 --wait
$ pmr apply spec.yaml            # terraform-style declarative reconcile
```

### 3. MCP server (for LLM agents)

```bash
$ pmr mcp install-claude     # one-shot Claude Desktop setup
$ pmr mcp serve              # or run the stdio server yourself
$ pmr mcp tools              # introspect the typed tools
```

## dvr ↔ pmr: one convention, two apps

`pmr` and [`dvr`](https://github.com/mhadifilms/dvr) share naming, routing, output envelopes, and the error model. An agent (or human) that knows one knows the other:

| | dvr (Resolve) | pmr (Premiere) |
|---|---|---|
| `timeline inspect` | ✅ | ✅ |
| `media import --bin` | ✅ | ✅ |
| `render submit --preset` | render presets | `.epr` presets |
| `render queue` | ✅ | ❌ fails: `NotSupportedError` + fix |
| `page edit` | ✅ | ❌ fails: `NotSupportedError` + fix |
| `effects apply` | ❌ fails with pointer to Resolve alternative | ✅ |

Operations one app can't perform **fail loudly** with a structured `NotSupportedError` explaining why and what to use instead — never silent degradation. The machine-readable support matrix ships in both packages:

```bash
$ pmr schema show parity | jq '.operations["render.queue"]'
{"status": "dvr-only", "reason": "no enumerable render queue in UXP"}
```

## Requirements

- Adobe Premiere Pro **25.6+** (26.x recommended; built and tested against 26.5)
- Python 3.10+
- macOS or Windows (daemon mode is macOS/Linux-style Unix sockets; Windows uses direct mode)

## Documentation

- [Getting started](getting-started.md)
- [Library guide](library.md) · [CLI reference](cli.md) · [MCP server](mcp.md)
- [Declarative specs](spec.md) · [Daemon mode](daemon.md)
- [dvr ↔ pmr parity](parity.md)

## License

MIT © M Hadi
