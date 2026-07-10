# Architecture

`pmr` looks like a normal Python library, but under the hood it drives
JavaScript running inside Premiere Pro. Three ideas make that feel
seamless.

## 1. The connection is inverted

DaVinci Resolve exposes a scripting API an external process can import
directly. Premiere does not: its UXP API is JavaScript that runs inside a
plugin panel, and UXP plugins can only open **outgoing** network
connections. There is no socket to dial into.

So `pmr` turns the relationship around. The Python side (CLI, library, or
MCP server) **hosts** a WebSocket server on `127.0.0.1:8855`. The bundled
`pmr bridge` panel, running inside Premiere, **dials out** to it and waits
for work.

```
┌─────────────────────────┐         ws://127.0.0.1:8855         ┌────────────────────────┐
│ pmr (Python)            │ ◀───────── dials in ──────────────  │ pmr bridge panel (UXP) │
│  hosts the WS server    │ ───────── RPC requests ──────────▶  │  runs premierepro JS   │
└─────────────────────────┘                                     └────────────────────────┘
```

Consequences that shape everything else:

- **Premiere must be running with the panel open.** There is no headless
  mode. The panel auto-reconnects, so this is a one-time dock.
- **One port, one owner.** Only one Python process can host the bridge.
  When the daemon runs, every CLI command forwards to it rather than
  binding a second server (see [daemon](../daemon.md)).

## 2. The plugin is generic; semantics live in Python

The panel (`plugin/main.js`) is a thin, stable RPC executor. It knows how
to `call` a method, `get`/`set` a property, `eval` a function body,
`subscribe` to an event, and run a `transaction` — nothing about
projects or sequences specifically. Live host objects are kept in a
handle registry and referenced across the wire as `{"$h": id}`.

That means **adding a Premiere capability almost never requires touching
or reinstalling the plugin.** New behavior is a JavaScript snippet in
`pmr/_js.py` plus a typed Python wrapper. The snippet is the body of an
`async (ppro, uxp, H, args) => {...}` function; it runs against the real
`premierepro` module and returns JSON-able data.

## 3. Mutations are transactions; reads may need a lock

Premiere's write model is unusual. You don't set properties directly —
you build **Action** objects and commit them inside
`project.executeTransaction(...)`, which makes the whole batch a single
undoable step. Some synchronous DOM reads (`getTrackItems`,
`markers.getMarkers`, component parameters) must run inside
`project.lockedAccess(...)` to see a consistent state.

Every snippet uses a shared `runTransaction(project, label, build)` helper
that wraps both concerns. This is why a `pmr` mutation shows up as one
tidy entry in Premiere's Edit → Undo menu.

## Time

Premiere measures time in **ticks**: 254,016,000,000 per second. The
bridge protocol converts everything to **seconds** at the boundary, and
frame counts are derived from the sequence's `getTimebase()` fps. You
never deal with ticks in Python.

## Failure decoding

The raw API fails quietly: promises reject with one-line messages,
`importFiles()` returns a bare `false`, actions silently no-op. Each
wrapper decodes those into a `PmrError` subclass carrying a `cause`, a
`fix`, and a `state` snapshot — the same structured shape `dvr` uses, so
agents can branch on error type and humans can read the fix.

Operations Premiere's API simply cannot do (render-queue enumeration,
page switching, interchange import) raise `NotSupportedError` — they still
*exist* in the CLI/MCP surface for cross-app parity, but fail loudly with
a pointer to the closest alternative. See [parity](../parity.md).
