# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[0.1.0]: https://github.com/mhadifilms/pmr/releases/tag/v0.1.0
