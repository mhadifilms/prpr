# CLI reference

`pmr` mirrors [`dvr`](https://github.com/mhadifilms/dvr)'s command tree.
Global options come before the subcommand:

```
pmr [--format json|table|yaml] [--no-launch] [--timeout SECONDS] <command> ...
```

Output is a table on a TTY, JSON when piped (`PMR_FORMAT` overrides).
Every command exits non-zero and prints a structured error (JSON on
stderr when piped) on failure.

## Top level

| command | description |
|---|---|
| `pmr ping` | verify the Premiere connection; print version |
| `pmr inspect` | one-call snapshot: app + project + active sequence |
| `pmr doctor [--probe]` | diagnose install / plugin / ports / connectivity |
| `pmr lint` | pre-flight checks (offline media, temp paths, empty sequences) |
| `pmr plan SPEC` / `pmr apply SPEC [-n] [--verify]` | declarative reconcile |
| `pmr eval "EXPR"` | run a JavaScript expression inside Premiere |
| `pmr exec FILE.js` | run a JS file body inside Premiere |
| `pmr repl` | Python REPL with `p` bound to a live Premiere |
| `pmr page [NAME]` | dvr parity — fails with `NotSupportedError` |

## Namespaces

### `pmr project`
`list` · `current` · `ensure NAME` · `create NAME` · `load NAME` ·
`delete NAME` · `save`

### `pmr timeline`
`list` · `current` · `inspect [NAME]` · `ensure NAME` · `create NAME [--preset]` ·
`switch NAME` · `delete NAME` · `rename NEW [--timeline]` ·
`append ITEM [--path] [--at] [--video-track] [--audio-track] [--insert]` ·
`clear [--track-type] [--track-indexes] [--name-contains] [--ripple]` ·
`mark [--at] [--name] [--note] [--type] [--color-index] [--duration]` ·
`markers` · `unmark [--name] [--at]` ·
`track INDEX [--track-type] [--mute/--unmute] [--name]` ·
`clone` · `from-media NAME ITEMS...` · `selection [--clear]` ·
`in-out [--in] [--out]` · `mogrt PATH [--at]` ·
`scene-detect [-o cut|marker|subclip]` ·
`export FILE [--format fcpxml|otio|aaf]`

### `pmr clip`
`ls [--name-contains] [--track] [--track-index] [--duration-lt] [--duration-gt]` ·
`rename NAME NEW` · `enable NAME` · `disable NAME` ·
`move NAME [--shift | --to]`

### `pmr media`
`inspect` · `bins` · `ls [BIN]` · `scan PATH` · `mkbin NAME` · `rmbin NAME` ·
`import PATHS... [--bin]` · `move TARGET [--source-bin] [--name-contains] [--name]`

### `pmr render`
`presets` · `submit [-o] [--name] [--preset] [--timeline] [--queue-to ame|app] [--wait]` ·
`watch [--timeout]` · `frame SECONDS FILE [--width] [--height]` ·
`status` / `queue` / `formats` / `codecs` / `stop` / `clear` (dvr parity — `NotSupportedError`)

### `pmr effects` (pmr-only)
`list [--kind video|audio|transition]` ·
`apply NAME [--clip] [--track-index] [--kind]` ·
`transition [MATCH] [--clip] [--duration] [--start/--end]` ·
`param COMPONENT PARAM VALUE [--clip] [--at]` ·
`components [--clip] [--with-values] [--at]`

### `pmr metadata` / `pmr monitor` / `pmr plugin` (pmr-only)
`metadata get NAME [--kind xmp|project]` · `metadata set-xmp NAME (--file|--value)`
`monitor open PATH|--item NAME` · `close` · `close-all` · `play [--speed]` · `position [SECONDS]`
`plugin install` · `plugin uninstall` · `plugin status`

### Declarative / infra
`pmr diff timelines A B | spec FILE | snapshot NAME` ·
`pmr snapshot save|list|show|restore|delete` · `pmr spec export [--out]` ·
`pmr schema topics|show TOPIC` ·
`pmr serve start|stop|status|methods` ·
`pmr mcp serve|tools|install-claude|install-cursor|uninstall` ·
`pmr completion show|install`
