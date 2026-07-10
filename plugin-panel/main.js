/* pmr bridge — generic RPC executor for Premiere Pro's UXP API.
 *
 * The plugin is intentionally thin and generic: it connects OUT to a local
 * WebSocket server hosted by the `pmr` Python daemon (UXP panels cannot
 * listen on sockets) and executes structured RPC requests against the
 * `premierepro` module. All semantics — naming, validation, error decoding —
 * live on the Python side, so this plugin rarely needs updating.
 *
 * Wire protocol (JSON text frames):
 *   server -> plugin: {id, op, ...}
 *   plugin -> server: {id, ok: true, result} | {id, ok: false, error: {name, message, stack}}
 *   plugin -> server (unsolicited): {event: "hello", ...} | {event: "host-event", ...}
 *
 * Ops:
 *   ping         -> {pong: true}
 *   eval         {code, args}                 run async JS with (ppro, uxp, H, args) in scope
 *   call         {target, path, args}         invoke a method (dotted path, correct thisArg)
 *   get          {target, path}               read a property
 *   set          {target, path, value}        write a property
 *   release      {handles: [id]}              drop object handles
 *   transaction  {project, label, steps}      create actions inside lockedAccess + executeTransaction
 *   subscribe    {target, event}              EventManager listener -> "host-event" frames
 *   unsubscribe  {subscription}
 *
 * Object handles: host objects serialize as {"$h": id, "$type": ctorName}.
 * Requests reference them the same way. Plain objects/arrays/primitives
 * pass through by value.
 */

/* global document, WebSocket */

let ppro = null;
let uxp = null;
try {
  ppro = require("premierepro");
} catch (e) {
  /* not running inside Premiere */
}
try {
  uxp = require("uxp");
} catch (e) {
  /* no uxp module */
}

const PLUGIN_VERSION = "0.3.0";
const PORTS = [8855, 8856, 8857];
const RECONNECT_MS = 1500;

// ---------------------------------------------------------------------------
// Handle registry
// ---------------------------------------------------------------------------

const handles = new Map(); // id -> object
const reverse = new WeakMap(); // object -> id
let nextHandle = 1;

function putHandle(obj) {
  const existing = reverse.get(obj);
  if (existing !== undefined && handles.has(existing)) return existing;
  const id = String(nextHandle++);
  handles.set(id, obj);
  try {
    reverse.set(obj, id);
  } catch (e) {
    /* non-extensible object; registry map still holds it */
  }
  return id;
}

function getHandle(id) {
  if (!handles.has(id)) {
    throw new Error(`Unknown handle ${id} (released or from a previous session)`);
  }
  return handles.get(id);
}

const H = {
  get: getHandle,
  put: putHandle,
  ref: (obj) => ({ $h: putHandle(obj), $type: typeName(obj) }),
};

function typeName(obj) {
  try {
    if (obj && obj.constructor && obj.constructor.name) return obj.constructor.name;
  } catch (e) {
    /* ignore */
  }
  return typeof obj;
}

// ---------------------------------------------------------------------------
// Serialization
// ---------------------------------------------------------------------------

const MAX_DEPTH = 32;

// Cheap synchronous properties inlined onto handle refs so the Python side
// avoids extra round-trips for common value reads. Keyed by constructor name;
// every read is guarded — a missing/throwing getter just omits the field.
const SNAPSHOT_PROPS = {
  TickTime: ["seconds", "ticks", "ticksNumber"],
  FrameRate: ["value", "ticksPerFrame"],
  Color: ["red", "green", "blue", "alpha"],
  PointF: ["x", "y"],
  RectF: ["width", "height"],
  TimeDisplay: ["type"],
  Project: ["name", "path"],
  Sequence: ["name"],
  ProjectItem: ["name", "type"],
  ClipProjectItem: ["name", "type"],
  FolderItem: ["name", "type"],
  VideoTrack: ["name", "id"],
  AudioTrack: ["name", "id"],
  CaptionTrack: ["name", "id"],
  Media: [],
  ComponentParam: ["displayName"],
  CompoundAction: ["empty"],
};

function snapshotOf(obj, name) {
  const props = SNAPSHOT_PROPS[name];
  const snap = {};
  if (props) {
    for (const prop of props) {
      try {
        const v = obj[prop];
        const t = typeof v;
        if (v === null || t === "string" || t === "boolean") snap[prop] = v;
        else if (t === "number" && Number.isFinite(v)) snap[prop] = v;
      } catch (e) {
        /* getter threw; omit */
      }
    }
  }
  // GUIDs stringify usefully; capture when present.
  try {
    if (obj.guid && typeof obj.guid.toString === "function") {
      const s = obj.guid.toString();
      if (typeof s === "string" && s !== "[object Object]") snap.guid = s;
    }
  } catch (e) {
    /* ignore */
  }
  try {
    if (name === "Guid" && typeof obj.toString === "function") {
      snap.str = obj.toString();
    }
  } catch (e) {
    /* ignore */
  }
  return snap;
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function serialize(value, depth) {
  depth = depth || 0;
  if (value === undefined) return null;
  if (value === null) return null;
  const t = typeof value;
  if (t === "string" || t === "boolean") return value;
  if (t === "number") return Number.isFinite(value) ? value : String(value);
  if (t === "bigint") return String(value);
  if (t === "function") return { $fn: value.name || "anonymous" };
  if (Array.isArray(value)) {
    if (depth >= MAX_DEPTH) return { $truncated: true };
    return value.map((v) => serialize(v, depth + 1));
  }
  if (isPlainObject(value)) {
    if (depth >= MAX_DEPTH) return { $truncated: true };
    const out = {};
    for (const key of Object.keys(value)) out[key] = serialize(value[key], depth + 1);
    return out;
  }
  // Host object -> handle reference with a cheap value snapshot.
  const name = typeName(value);
  const ref = { $h: putHandle(value), $type: name };
  const snap = snapshotOf(value, name);
  if (Object.keys(snap).length) ref.$snap = snap;
  return ref;
}

function deserialize(value) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.map(deserialize);
  if (typeof value === "object") {
    if (typeof value.$h === "string" || typeof value.$h === "number") {
      return getHandle(String(value.$h));
    }
    const out = {};
    for (const key of Object.keys(value)) out[key] = deserialize(value[key]);
    return out;
  }
  return value;
}

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

function rootFor(target) {
  if (target === undefined || target === null || target === "ppro") return ppro;
  if (target === "uxp") return uxp;
  return deserialize(target);
}

function resolvePath(root, path) {
  if (!path) return { parent: null, value: root };
  const parts = String(path).split(".");
  let parent = null;
  let value = root;
  for (const part of parts) {
    if (value === null || value === undefined) {
      throw new Error(`Cannot resolve '${part}' of null while walking '${path}'`);
    }
    parent = value;
    value = value[part];
  }
  return { parent, value };
}

// ---------------------------------------------------------------------------
// Ops
// ---------------------------------------------------------------------------

const subscriptions = new Map(); // id -> {target, event, handler}
let nextSubscription = 1;

const OPS = {
  ping: async () => ({
    pong: true,
    plugin: PLUGIN_VERSION,
    host: uxp && uxp.host ? { name: uxp.host.name, version: uxp.host.version } : null,
    ppro: !!ppro,
  }),

  eval: async (req) => {
    // eslint-disable-next-line no-new-func
    const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    const fn = new AsyncFunction("ppro", "uxp", "H", "args", req.code);
    const result = await fn(ppro, uxp, H, deserialize(req.args));
    return serialize(result);
  },

  call: async (req) => {
    const root = rootFor(req.target);
    const { parent, value } = resolvePath(root, req.path);
    if (typeof value !== "function") {
      throw new Error(`'${req.path}' is not a function (got ${typeof value})`);
    }
    const args = (req.args || []).map(deserialize);
    const result = await value.apply(parent, args);
    return serialize(result);
  },

  get: async (req) => {
    const root = rootFor(req.target);
    const { value } = resolvePath(root, req.path);
    return serialize(value);
  },

  set: async (req) => {
    const root = rootFor(req.target);
    const parts = String(req.path).split(".");
    const last = parts.pop();
    const { value: parent } = resolvePath(root, parts.join("."));
    parent[last] = deserialize(req.value);
    return { set: req.path };
  },

  release: async (req) => {
    let dropped = 0;
    for (const id of req.handles || []) {
      if (handles.delete(String(id))) dropped += 1;
    }
    return { released: dropped };
  },

  // Create actions synchronously inside lockedAccess, then execute them in a
  // single undoable transaction. Steps: [{target, method, args}]. A step's
  // args may reference handles; each step's created Action is collected and
  // added to the compound action in order.
  transaction: async (req) => {
    const project = deserialize(req.project);
    if (!project || typeof project.lockedAccess !== "function") {
      throw new Error("transaction requires a project handle with lockedAccess()");
    }
    const steps = req.steps || [];
    let executed = false;
    let stepError = null;
    project.lockedAccess(() => {
      const actions = [];
      try {
        for (const step of steps) {
          const target = deserialize(step.target);
          const method = target[step.method];
          if (typeof method !== "function") {
            throw new Error(`'${step.method}' is not a function on ${typeName(target)}`);
          }
          const action = method.apply(target, (step.args || []).map(deserialize));
          if (!action) throw new Error(`'${step.method}' returned no action`);
          actions.push(action);
        }
      } catch (err) {
        stepError = err;
        return;
      }
      executed = project.executeTransaction((compound) => {
        for (const action of actions) compound.addAction(action);
      }, req.label || "pmr");
    });
    if (stepError) throw stepError;
    return { executed: executed !== false, steps: steps.length };
  },

  subscribe: async (req) => {
    if (!ppro || !ppro.EventManager) throw new Error("EventManager unavailable");
    const id = String(nextSubscription++);
    const handler = (event) => {
      send({
        event: "host-event",
        subscription: id,
        name: req.event,
        payload: serialize(event, 2),
      });
    };
    if (req.target === "global" || req.target === undefined || req.target === null) {
      ppro.EventManager.addGlobalEventListener(req.event, handler);
      subscriptions.set(id, { target: null, event: req.event, handler });
    } else {
      const target = deserialize(req.target);
      ppro.EventManager.addEventListener(target, req.event, handler);
      subscriptions.set(id, { target, event: req.event, handler });
    }
    return { subscription: id };
  },

  unsubscribe: async (req) => {
    const sub = subscriptions.get(String(req.subscription));
    if (!sub) return { unsubscribed: false };
    if (sub.target === null) {
      ppro.EventManager.removeGlobalEventListener(sub.event, sub.handler);
    } else {
      ppro.EventManager.removeEventListener(sub.target, sub.event, sub.handler);
    }
    subscriptions.delete(String(req.subscription));
    return { unsubscribed: true };
  },
};

// ---------------------------------------------------------------------------
// WebSocket client with reconnect
// ---------------------------------------------------------------------------

let ws = null;
let portIndex = 0;
let connected = false;
let requestCount = 0;

function send(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
  }
}

async function handleMessage(raw) {
  let req = null;
  try {
    req = JSON.parse(raw);
  } catch (e) {
    send({ id: null, ok: false, error: { name: "ParseError", message: String(e) } });
    return;
  }
  const op = OPS[req.op];
  requestCount += 1;
  updateStatus();
  if (!op) {
    send({ id: req.id, ok: false, error: { name: "UnknownOp", message: `Unknown op '${req.op}'` } });
    return;
  }
  try {
    const result = await op(req);
    send({ id: req.id, ok: true, result });
  } catch (err) {
    send({
      id: req.id,
      ok: false,
      error: {
        name: (err && err.name) || "Error",
        message: (err && err.message) || String(err),
        stack: err && err.stack ? String(err.stack).slice(0, 2000) : null,
      },
    });
  }
}

function connect() {
  const port = PORTS[portIndex % PORTS.length];
  const url = `ws://127.0.0.1:${port}/`;
  try {
    ws = new WebSocket(url);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    connected = true;
    updateStatus(url);
    send({
      event: "hello",
      plugin: PLUGIN_VERSION,
      host: uxp && uxp.host ? { name: uxp.host.name, version: uxp.host.version } : null,
      ppro: !!ppro,
    });
  };
  ws.onmessage = (msg) => handleMessage(msg.data);
  ws.onerror = () => {
    /* onclose fires next */
  };
  ws.onclose = () => {
    connected = false;
    portIndex += 1;
    updateStatus();
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  setTimeout(connect, RECONNECT_MS);
}

// ---------------------------------------------------------------------------
// Panel UI
// ---------------------------------------------------------------------------

function updateStatus(url) {
  const el = document.getElementById("status");
  const detail = document.getElementById("detail");
  if (!el) return;
  if (connected) {
    el.textContent = "connected";
    el.className = "ok";
    if (detail) detail.textContent = `${url || ""}  ·  ${requestCount} requests served`;
  } else {
    el.textContent = "waiting for pmr daemon…";
    el.className = "waiting";
    if (detail) detail.textContent = "run `pmr serve start` (or any pmr command) to connect";
  }
}

connect();
updateStatus();
