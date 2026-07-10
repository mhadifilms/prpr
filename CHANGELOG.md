# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-07-10

First stable release.

### Added
- Plugin freshness check: on connect, pmr compares the running bridge to
  the version bundled in the pip package and (by default) UPIA-reinstalls
  the newer one so a `pip install -U pmr` refreshes the in-Premiere bridge
  on the next Premiere launch. Opt out with `PMR_PLUGIN_AUTOUPDATE=0`;
  surfaced in `pmr plugin check` and `pmr doctor --probe`.

### Changed
- Development status promoted to Production/Stable.
- Packaging hardened for distribution: the headless plugin ships inside
  the wheel (`pmr/plugin_assets/`); dev-tools session files are excluded.

## [0.3.0] - 2026-07-10

### Changed
- **The bridge plugin is now headless.** It's a `command`-entrypoint UXP
  plugin whose `main.js` opens the WebSocket connection at module load —
  no panel to dock, no menu to click. A UPIA-installed command plugin runs
  its code automatically at Premiere startup (verified on 26.5: connects
  with no panel and no developer tools). Setup is now just `pmr plugin
  install` + one Premiere restart; the bridge then starts with Premiere
  every launch and reconnects on its own.
- `pmr plugin autostart` → `pmr plugin check` (confirms the headless
  bridge is connected). Install/doctor/error messages updated accordingly.

### Added
- `plugin-panel/` — the previous status-panel variant, kept for anyone who
  wants a visible connection readout instead of the headless plugin.

## [0.2.0] - 2026-07-10

Live-validated against Adobe Premiere Pro 26.5. The full surface below was
driven end-to-end through the bridge (`scripts/smoke_live.py` + targeted
checks): transforms, keyframes, track mute/rename, marker move, keyframe
listing, sequence clone/settings-write, color labels, bin rename, scratch
disks, ingest, footage interpretation, selection read, still-frame and
sequence export, FCPXML export, snapshot, spec.

### Added
- **Transforms & keyframes**: `effects.set_param` writes any component
  parameter (Motion/Opacity/effect params) with `PointF`/`Color`
  coercion; pass `at_seconds` to write a keyframe. `timeline.keyframes`
  lists keyframe times for a parameter. (transforms + keyframes
  live-validated)
- **Timeline**: `track_update` (mute + rename), `clone`,
  `create_subsequence`, `set_in_out`, `work_area` (26.5+),
  `insert_mogrt`, `scene_edit_detection`, `move_marker`,
  `create_from_media`, `selection` (read + clear — `setSelection`
  crashes Premiere 26.5 beta and is refused rather than crashing the
  host).
- **Media**: `attach_proxy`, `create_subclip` (26.3+),
  `transcript_export`/`transcript_import` (26.3+),
  `footage_interpretation`, `color_label`, `bin_rename`, `smart_bin`,
  `purge_cache` (26.5+), `selection`.
- **Project**: `scratch_disks`, `ingest`, `color_settings`,
  `import_sequences`, `import_ae_comps`, sequence `set_settings`. **App**:
  `preference`.
- **Host events**: `p.events.subscribe`/`on`/`off` (EventManager —
  project/sequence/encoder/global events delivered to Python handlers on
  the bridge thread).
- **CLI/MCP** commands and tools for the above; `pmr/__main__.py`
  (`python -m pmr`).
- `scripts/smoke_live.py` full live E2E; `scripts/check_parity.py`
  cross-repo status/key-symmetry check. mypy (strict) added to CI.
- Parity matrix grown to 106 operations, synced with dvr.

### Changed
- Bridge object serialization depth 6 → 32 (nested inspect payloads).
- Manifest `network.domains` → `"all"` (UXP 26.5 rejects explicit
  `ws://` entries).
- Daemon: `--wait`/`watch` commands forward through the daemon instead
  of bypassing it (one-port-owner model), and the bypass parser no
  longer mistakes an option value for the command.

## [0.1.0] - 2026-07-10

Initial release. Structural sibling of [dvr](https://github.com/mhadifilms/dvr) for Adobe Premiere Pro.

### Added

- **Bridge architecture**: bundled UXP panel (`pmr bridge`) that dials into a
  local WebSocket server hosted by the Python side; generic RPC executor
  (`call`/`get`/`set`/`eval`/`transaction`/`subscribe`) with an object-handle
  registry, so the full `premierepro` API surface is reachable without plugin
  updates. Live-validated against Premiere Pro 26.5.
- **Python library** (`pmr.Premiere`) mirroring dvr's object model:
  - `project`: list open projects, `ensure`/`create`/`load`/`save`/`delete`
    (file-based, `PMR_PROJECTS_DIR` convention)
  - `timeline`: sequences with dvr's timeline routing — `list`/`current`/
    `ensure`/`create`/`switch`/`delete`/`rename`, full `inspect()` (fps, frame
    size, tracks, items, markers, settings), `append`/`insert`/`delete_clips`,
    markers (add/list/remove with colors, durations, types), clip queries
  - `media`: project-panel bins and clips — `inspect` tree, `import_` with
    bin targeting, `bin_ensure` (nested paths), `move`, `find_or_import`,
    plus Premiere-free `scan_media_files`
  - `render`: `.epr` preset discovery, `submit` (immediate / queue-to-app /
    queue-to-AME) with event-driven `wait`, still-frame export
  - `effects`: catalogs (111 video effects, 106 transitions, 81 audio effects),
    apply by matchName, transitions with duration/alignment, component-chain
    inspection, and `set_param` for transforms/keyframes (Motion, Opacity, any
    component parameter; PointF/Color coercion)
  - `interchange`: FCPXML / OTIO / AAF sequence export
  - XMP + project metadata read/write, source monitor control, per-project
    properties store
- **Declarative layer** mirroring dvr: `spec` (YAML/JSON apply with
  plan/verify, `from_live` export), `diff` (timelines/spec/snapshot),
  `snapshot` (capture/restore), `lint` (offline media, temp paths, empty
  sequences)
- **Daemon** (`pmr serve`): Unix-socket RPC holding the bridge across CLI
  invocations, dvr wire format, full-CLI forwarding
- **CLI** (`pmr`): dvr's command tree with identical output conventions
  (json/table/yaml, `PMR_FORMAT`, TTY auto-detection)
- **MCP server** (`pmr mcp serve`): dvr's tool names and registration
  pattern; typed tools for every library capability
- **Cross-app parity contract**: `pmr.errors.NotSupportedError` for
  operations Premiere's UXP API cannot perform (render queue enumeration,
  page switching, interchange import, ...), each with cause/fix pointing to
  the closest alternative; machine-readable matrix at `pmr schema show parity`
- **Diagnostics**: `pmr doctor [--probe]` (install/plugin/port checks),
  structured `PmrError` hierarchy with `cause`/`fix`/`state` on every failure
- **Plugin management**: `pmr plugin install|uninstall|status` via Adobe's
  UPIA installer with automatic `.ccx` packaging
- Test suite (MockBridge at the wire boundary, no Premiere required)

### Notes
- `timeline.work_area` (WorkAreaUtils) is feature-detected — it is absent
  on some Premiere 26.5 builds and fails with a clear version error rather
  than crashing.
- `Sequence.setSelection` crashes Premiere 26.5 beta, so `timeline.select`
  supports read + clear only and refuses filtered selection.

[1.0.0]: https://github.com/mhadifilms/pmr/releases/tag/v1.0.0
[0.3.0]: https://github.com/mhadifilms/pmr/releases/tag/v0.3.0
[0.2.0]: https://github.com/mhadifilms/pmr/releases/tag/v0.2.0
[0.1.0]: https://github.com/mhadifilms/pmr/releases/tag/v0.1.0
