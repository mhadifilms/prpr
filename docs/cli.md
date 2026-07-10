# CLI reference

`prpr` mirrors [`dvr`](https://github.com/mhadifilms/dvr)'s command tree.
Global options come before the subcommand:

```
prpr [--format json|table|yaml] [--no-launch] [--timeout SECONDS] <command> ...
```

Output is a table on a TTY, JSON when piped (`PRPR_FORMAT` overrides).
Every command exits non-zero and prints a structured error (JSON on
stderr when piped) on failure.

## Top level

| command | description |
|---|---|
| `prpr ping` | verify the Premiere connection; print version |
| `prpr inspect` | one-call snapshot: app + project + active sequence |
| `prpr doctor [--probe]` | diagnose install / plugin / ports / connectivity |
| `prpr lint` | pre-flight checks (offline media, temp paths, empty sequences) |
| `prpr plan SPEC` / `prpr apply SPEC [-n] [--verify]` | declarative reconcile |
| `prpr eval "EXPR"` | run a JavaScript expression inside Premiere |
| `prpr exec FILE.js` | run a JS file body inside Premiere |
| `prpr repl` | Python REPL with `p` bound to a live Premiere |
| `prpr page [NAME]` | dvr parity — fails with `NotSupportedError` |

## Namespaces

### `prpr project`
`list` · `current` · `ensure NAME` · `create NAME` · `load NAME` ·
`delete NAME` · `save`

### `prpr timeline`
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

### `prpr clip`
`ls [--name-contains] [--track] [--track-index] [--duration-lt] [--duration-gt]` ·
`rename NAME NEW` · `enable NAME` · `disable NAME` ·
`move NAME [--shift | --to]`

### `prpr media`
`inspect` · `bins` · `ls [BIN]` · `scan PATH` · `mkbin NAME` · `rmbin NAME` ·
`import PATHS... [--bin]` · `move TARGET [--source-bin] [--name-contains] [--name]`

### `prpr render`
`presets` · `submit [-o] [--name] [--preset] [--timeline] [--queue-to ame|app] [--wait]` ·
`watch [--timeout]` · `frame SECONDS FILE [--width] [--height]` ·
`status` / `queue` / `formats` / `codecs` / `stop` / `clear` (dvr parity — `NotSupportedError`)

### `prpr effects` (prpr-only)
`list [--kind video|audio|transition]` ·
`apply NAME [--clip] [--track-index] [--kind]` ·
`transition [MATCH] [--clip] [--duration] [--start/--end]` ·
`param COMPONENT PARAM VALUE [--clip] [--at]` ·
`components [--clip] [--with-values] [--at]`

### `prpr metadata` / `prpr monitor` / `prpr plugin` (prpr-only)
`metadata get NAME [--kind xmp|project]` · `metadata set-xmp NAME (--file|--value)`
`monitor open PATH|--item NAME` · `close` · `close-all` · `play [--speed]` · `position [SECONDS]`
`plugin install` · `plugin uninstall` · `plugin status`

### Declarative / infra
`prpr diff timelines A B | spec FILE | snapshot NAME` ·
`prpr snapshot save|list|show|restore|delete` · `prpr spec export [--out]` ·
`prpr schema topics|show TOPIC` ·
`prpr serve start|stop|status|methods` ·
`prpr mcp serve|tools|install-claude|install-cursor|uninstall` ·
`prpr completion show|install`
