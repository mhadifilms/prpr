# Daemon mode

Every `pmr` CLI invocation must host the bridge server and wait for the
panel inside Premiere to (re)connect — a ~1–2s handshake. The daemon
removes that cost: it runs once, owns the bridge, and serves subsequent
CLI/library calls over a Unix-domain socket.

```bash
pmr serve start          # background daemon
pmr serve status         # {"running": true, "pid": ..., "socket": ...}
pmr serve methods        # RPC allow-list
pmr serve stop
```

While the daemon runs, `pmr` commands detect its socket and forward the
whole invocation to it (`PMR_NO_DAEMON=1` opts out). Because the daemon
keeps the WebSocket endpoint alive, the panel connection also survives
across commands — and across Premiere restarts (the panel auto-reconnects
to the daemon's port).

## Wire format

Identical to dvr's daemon — newline-delimited JSON on
`~/.cache/pmr/pmr.sock` (mode 0600):

```
{"id": "1", "method": "timeline.inspect", "params": {}}
-> {"id": "1", "ok": true, "result": {...}}
-> {"id": "1", "ok": false, "error": {"type": "...", "message": "...", "cause": "...", "fix": "..."}}
```

Methods are dotted paths validated against an allow-list
(`pmr serve methods`), plus `cli` which runs any pmr command in-process:

```python
from pmr.daemon import Client

client = Client()
client.call("timeline.inspect")
client.call("cli", {"argv": ["render", "submit", "--target-dir", "/x"]})
```

## One port, one owner

Only one process can own the bridge port at a time. The rule: if a daemon
is running, everything routes through it; otherwise the first CLI/MCP
process binds the port directly and the panel connects to that. Port
conflicts fail loudly with the owning process named in the error.
