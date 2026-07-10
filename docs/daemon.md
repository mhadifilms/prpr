# Daemon mode

Every `prpr` CLI invocation must host the bridge server and wait for the
panel inside Premiere to (re)connect — a ~1–2s handshake. The daemon
removes that cost: it runs once, owns the bridge, and serves subsequent
CLI/library calls over a Unix-domain socket.

```bash
prpr serve start          # background daemon
prpr serve status         # {"running": true, "pid": ..., "socket": ...}
prpr serve methods        # RPC allow-list
prpr serve stop
```

While the daemon runs, `prpr` commands detect its socket and forward the
whole invocation to it (`PRPR_NO_DAEMON=1` opts out). Because the daemon
keeps the WebSocket endpoint alive, the panel connection also survives
across commands — and across Premiere restarts (the panel auto-reconnects
to the daemon's port).

## Wire format

Identical to dvr's daemon — newline-delimited JSON on
`~/.cache/prpr/prpr.sock` (mode 0600):

```
{"id": "1", "method": "timeline.inspect", "params": {}}
-> {"id": "1", "ok": true, "result": {...}}
-> {"id": "1", "ok": false, "error": {"type": "...", "message": "...", "cause": "...", "fix": "..."}}
```

Methods are dotted paths validated against an allow-list
(`prpr serve methods`), plus `cli` which runs any prpr command in-process:

```python
from prpr.daemon import Client

client = Client()
client.call("timeline.inspect")
client.call("cli", {"argv": ["render", "submit", "--target-dir", "/x"]})
```

## One port, one owner

Only one process can own the bridge port at a time. The rule: if a daemon
is running, everything routes through it; otherwise the first CLI/MCP
process binds the port directly and the panel connects to that. Port
conflicts fail loudly with the owning process named in the error.
