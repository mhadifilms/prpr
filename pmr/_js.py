"""Host-side JavaScript snippets executed inside Premiere via the bridge.

Each snippet is the body of ``async (ppro, uxp, H, args) => { ... }``. A
shared prelude provides helpers (sequence lookup, TickTime conversion,
transaction wrapper) so the Python modules stay thin and every operation
costs exactly one bridge round-trip.

Conventions:
- ``args`` is a plain object from Python (handles already resolved).
- Return plain JSON-able data; host objects are auto-wrapped as handles.
- Synchronous DOM reads (``getTrackItems``, ``markers.getMarkers``) run
  inside ``project.lockedAccess``; mutations run inside
  ``executeTransaction`` so they land as single undo steps.
"""

from __future__ import annotations

PRELUDE = r"""
const C = ppro.Constants;
const TICKS_PER_SECOND = 254016000000;

function tt(t) {
  if (!t) return null;
  try { return { seconds: t.seconds, ticks: t.ticks }; } catch (e) { return null; }
}

function secondsToTick(seconds) {
  return ppro.TickTime.createWithSeconds(Number(seconds || 0));
}

async function activeProject() {
  const p = await ppro.Project.getActiveProject();
  if (!p || !p.name) throw new Error("No active project is open in Premiere");
  return p;
}

async function resolveSequence(project, ref) {
  if (ref === undefined || ref === null || ref === "") {
    const s = await project.getActiveSequence();
    if (!s) throw new Error("No active sequence");
    return s;
  }
  if (typeof ref === "object") return ref; // already a Sequence handle
  const seqs = await project.getSequences();
  for (const s of seqs) {
    if (s.name === ref) return s;
    try { if (s.guid && s.guid.toString() === ref) return s; } catch (e) {}
  }
  throw new Error(`Sequence not found: ${ref}`);
}

function fpsFromTimebase(tb) {
  const n = Number(tb);
  return n > 0 ? TICKS_PER_SECOND / n : null;
}

function runTransaction(project, label, build) {
  // build(addAction) is called inside lockedAccess; collect actions then
  // execute them as one undoable step. Returns executeTransaction result.
  let result = false;
  let failure = null;
  project.lockedAccess(() => {
    const actions = [];
    try {
      build((action) => { if (action) actions.push(action); });
    } catch (err) {
      failure = err;
      return;
    }
    if (!actions.length) { result = true; return; }
    result = project.executeTransaction((compound) => {
      for (const a of actions) compound.addAction(a);
    }, label || "pmr");
  });
  if (failure) throw failure;
  return result;
}

function trackItemsSync(project, tracks, includeEmpty) {
  // Must run under lockedAccess; returns raw arrays per track.
  const out = [];
  project.lockedAccess(() => {
    for (const track of tracks) {
      let items = [];
      try {
        items = track.getTrackItems(C.TrackItemType.CLIP, !!includeEmpty) || [];
      } catch (e) { items = []; }
      out.push(items);
    }
  });
  return out;
}

async function itemDetail(item) {
  const detail = {};
  const grab = async (key, fn) => {
    try { detail[key] = await fn(); } catch (e) { detail[key] = null; }
  };
  await grab("name", () => item.getName());
  await grab("start", async () => tt(await item.getStartTime()));
  await grab("end", async () => tt(await item.getEndTime()));
  await grab("duration", async () => tt(await item.getDuration()));
  await grab("in_point", async () => tt(await item.getInPoint()));
  await grab("out_point", async () => tt(await item.getOutPoint()));
  await grab("enabled", async () => !(await item.isDisabled()));
  await grab("selected", () => item.getIsSelected());
  await grab("speed", () => item.getSpeed());
  await grab("track_index", () => item.getTrackIndex());
  await grab("type", () => item.getType());
  await grab("adjustment_layer", () => item.isAdjustmentLayer());
  return detail;
}

async function gatherTracks(project, seq, kind) {
  const counts = {
    video: () => seq.getVideoTrackCount(),
    audio: () => seq.getAudioTrackCount(),
    caption: () => seq.getCaptionTrackCount(),
  };
  const getters = {
    video: (i) => seq.getVideoTrack(i),
    audio: (i) => seq.getAudioTrack(i),
    caption: (i) => seq.getCaptionTrack(i),
  };
  const count = await counts[kind]();
  const tracks = [];
  for (let i = 0; i < count; i++) tracks.push(await getters[kind](i));
  return tracks;
}

async function markerList(ownerMarkers) {
  // markers.getMarkers() is sync; caller wraps in lockedAccess when needed.
  const out = [];
  const raw = ownerMarkers.getMarkers() || [];
  for (const m of raw) {
    const entry = {};
    const grab = (key, fn) => { try { entry[key] = fn(); } catch (e) { entry[key] = null; } };
    grab("name", () => m.getName());
    grab("comments", () => m.getComments());
    grab("type", () => m.getType());
    grab("start", () => tt(m.getStart()));
    grab("duration", () => tt(m.getDuration()));
    grab("color_index", () => m.getColorIndex());
    grab("url", () => m.getUrl());
    out.push(entry);
  }
  return out;
}

async function findBin(project, path, create) {
  // path: "A/B/C" relative to root; returns FolderItem.
  const root = await project.getRootItem();
  if (!path) return root;
  const parts = String(path).split("/").filter(Boolean);
  let current = root;
  for (const part of parts) {
    const items = await current.getItems();
    let next = null;
    for (const item of items) {
      if (item.name === part && item.type === ppro.ProjectItem.TYPE_BIN) {
        next = ppro.FolderItem.cast(item);
        break;
      }
    }
    if (!next) {
      if (!create) throw new Error(`Bin not found: ${path}`);
      runTransaction(project, `pmr: create bin ${part}`, (add) => {
        add(current.createBinAction(part, false));
      });
      const refreshed = await current.getItems();
      for (const item of refreshed) {
        if (item.name === part && item.type === ppro.ProjectItem.TYPE_BIN) {
          next = ppro.FolderItem.cast(item);
          break;
        }
      }
      if (!next) throw new Error(`Failed to create bin: ${part}`);
    }
    current = next;
  }
  return current;
}

async function findProjectItem(project, ref) {
  // ref: {name} or {path} or {binPath, name} — depth-first search.
  const root = await project.getRootItem();
  const wantName = ref && ref.name;
  const wantPath = ref && ref.path;
  const stack = [root];
  while (stack.length) {
    const folder = stack.pop();
    const items = await folder.getItems();
    for (const item of items) {
      if (item.type === ppro.ProjectItem.TYPE_BIN) {
        stack.push(ppro.FolderItem.cast(item));
        continue;
      }
      if (wantName && item.name === wantName) return item;
      if (wantPath) {
        try {
          const clip = ppro.ClipProjectItem.cast(item);
          const mediaPath = await clip.getMediaFilePath();
          if (mediaPath === wantPath) return item;
        } catch (e) {}
      }
    }
  }
  return null;
}
"""


def _s(body: str) -> str:
    """Attach the shared prelude to a snippet body."""
    return PRELUDE + "\n" + body


SNIPPETS: dict[str, str] = {
    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    "app_info": _s("""
        const host = uxp && uxp.host ? { name: uxp.host.name, version: uxp.host.version } : null;
        let projectName = null;
        try { const p = await ppro.Project.getActiveProject(); projectName = p ? p.name : null; } catch (e) {}
        return {
          host,
          ppro_available: !!ppro,
          active_project: projectName,
          capabilities: {
            work_area: typeof ppro.WorkAreaUtils !== "undefined",
            project_converter: typeof ppro.ProjectConverter !== "undefined",
            media_manager: typeof ppro.MediaManager !== "undefined",
            transcript: typeof ppro.Transcript !== "undefined",
            object_mask: typeof ppro.ObjectMaskUtils !== "undefined",
          },
        };
    """),
    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------
    "project_list_open": _s("""
        const out = [];
        try {
          const ids = await ppro.ProjectUtils.getProjectViewIds();
          const seen = new Set();
          for (const id of ids) {
            try {
              const p = await ppro.ProjectUtils.getProjectFromViewId(id);
              if (p && p.name && !seen.has(p.path)) {
                seen.add(p.path);
                out.push({ name: p.name, path: p.path, guid: p.guid ? p.guid.toString() : null });
              }
            } catch (e) {}
          }
        } catch (e) {}
        if (!out.length) {
          try {
            const p = await ppro.Project.getActiveProject();
            if (p && p.name) out.push({ name: p.name, path: p.path, guid: p.guid ? p.guid.toString() : null });
          } catch (e) {}
        }
        return out;
    """),
    "project_inspect": _s("""
        const project = await activeProject();
        let active = null;
        try {
          const seq = await project.getActiveSequence();
          if (seq) active = { name: seq.name, guid: seq.guid ? seq.guid.toString() : null };
        } catch (e) {}
        const sequences = [];
        try {
          for (const s of await project.getSequences()) {
            sequences.push({ name: s.name, guid: s.guid ? s.guid.toString() : null });
          }
        } catch (e) {}
        let bins = 0, clips = 0;
        try {
          const root = await project.getRootItem();
          const stack = [root];
          while (stack.length) {
            const folder = stack.pop();
            for (const item of await folder.getItems()) {
              if (item.type === ppro.ProjectItem.TYPE_BIN) { bins += 1; stack.push(ppro.FolderItem.cast(item)); }
              else clips += 1;
            }
          }
        } catch (e) {}
        return {
          name: project.name,
          path: project.path,
          guid: project.guid ? project.guid.toString() : null,
          active_sequence: active,
          sequences,
          bin_count: bins,
          item_count: clips,
        };
    """),
    "project_open": _s("""
        const project = await ppro.Project.open(args.path);
        if (!project) throw new Error(`Could not open project: ${args.path}`);
        return { name: project.name, path: project.path };
    """),
    "project_create": _s("""
        const project = await ppro.Project.createProject(args.path);
        if (!project) throw new Error(`Could not create project at: ${args.path}`);
        return { name: project.name, path: project.path };
    """),
    "project_save": _s("""
        const project = await activeProject();
        await project.save();
        return { saved: project.name, path: project.path };
    """),
    "project_save_as": _s("""
        const project = await activeProject();
        const ok = await project.saveAs(args.path);
        if (!ok) throw new Error(`saveAs failed for: ${args.path}`);
        return { saved: project.name, path: args.path };
    """),
    "project_close": _s("""
        const project = await activeProject();
        const name = project.name;
        const options = new ppro.CloseProjectOptions();
        try { options.setPromptIfDirty(!!args.prompt_if_dirty); } catch (e) {}
        try { options.setShowCancelButton(false); } catch (e) {}
        const ok = await project.close(options);
        return { closed: name, ok: !!ok };
    """),
    # ------------------------------------------------------------------
    # Sequences (timelines)
    # ------------------------------------------------------------------
    "sequence_list": _s("""
        const project = await activeProject();
        const active = await project.getActiveSequence();
        const activeGuid = active && active.guid ? active.guid.toString() : null;
        const out = [];
        for (const s of await project.getSequences()) {
          const guid = s.guid ? s.guid.toString() : null;
          let fps = null;
          try { fps = fpsFromTimebase(await s.getTimebase()); } catch (e) {}
          let end = null;
          try { end = tt(await s.getEndTime()); } catch (e) {}
          out.push({ name: s.name, guid, fps, end, is_active: guid !== null && guid === activeGuid });
        }
        return out;
    """),
    "sequence_create": _s("""
        const project = await activeProject();
        let seq;
        if (args.preset_path && typeof project.createSequenceWithPresetPath === "function") {
          seq = await project.createSequenceWithPresetPath(args.name, args.preset_path);
        } else {
          seq = await project.createSequence(args.name);
        }
        if (!seq) throw new Error(`Could not create sequence: ${args.name}`);
        if (args.set_active !== false) { try { await project.setActiveSequence(seq); } catch (e) {} }
        return { name: seq.name, guid: seq.guid ? seq.guid.toString() : null };
    """),
    "sequence_delete": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const name = seq.name;
        const ok = await project.deleteSequence(seq);
        if (!ok) throw new Error(`Could not delete sequence: ${name}`);
        return { deleted: name };
    """),
    "sequence_set_active": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const ok = await project.setActiveSequence(seq);
        if (!ok) throw new Error(`Could not activate sequence: ${seq.name}`);
        try { await project.openSequence(seq); } catch (e) {}
        return { current: seq.name };
    """),
    "sequence_rename": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const item = await seq.getProjectItem();
        if (!item) throw new Error("Sequence has no project item");
        const oldName = seq.name;
        runTransaction(project, `pmr: rename sequence`, (add) => {
          add(item.createSetNameAction(args.new_name));
        });
        return { renamed: oldName, name: args.new_name };
    """),
    "sequence_inspect": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const result = {
          name: seq.name,
          guid: seq.guid ? seq.guid.toString() : null,
          project: project.name,
        };
        try { result.fps = fpsFromTimebase(await seq.getTimebase()); } catch (e) { result.fps = null; }
        try {
          const rect = await seq.getFrameSize();
          result.frame_size = { width: rect.width, height: rect.height };
        } catch (e) { result.frame_size = null; }
        try { result.zero_point = tt(await seq.getZeroPoint()); } catch (e) {}
        try { result.end = tt(await seq.getEndTime()); } catch (e) {}
        try { result.in_point = tt(await seq.getInPoint()); } catch (e) {}
        try { result.out_point = tt(await seq.getOutPoint()); } catch (e) {}
        try { result.player_position = tt(await seq.getPlayerPosition()); } catch (e) {}

        const tracks = { video: [], audio: [], caption: [] };
        for (const kind of ["video", "audio", "caption"]) {
          let list = [];
          try { list = await gatherTracks(project, seq, kind); } catch (e) { list = []; }
          const perTrack = trackItemsSync(project, list, false);
          for (let i = 0; i < list.length; i++) {
            const track = list[i];
            const items = perTrack[i] || [];
            let muted = null;
            try { muted = await track.isMuted(); } catch (e) {}
            const details = [];
            if (!args.names_only) {
              for (const item of items) details.push(await itemDetail(item));
            }
            tracks[kind].push({
              index: i,
              name: track.name,
              id: track.id,
              muted,
              clips: items.length,
              items: details,
            });
          }
        }
        result.tracks = tracks;

        try {
          const markers = await ppro.Markers.getMarkers(seq);
          let list = [];
          project.lockedAccess(() => { list = markers.getMarkers() || []; });
          const out = [];
          for (const m of list) {
            const entry = {};
            const grab = (key, fn) => { try { entry[key] = fn(); } catch (e) { entry[key] = null; } };
            grab("name", () => m.getName());
            grab("comments", () => m.getComments());
            grab("type", () => m.getType());
            grab("start", () => tt(m.getStart()));
            grab("duration", () => tt(m.getDuration()));
            grab("color_index", () => m.getColorIndex());
            out.push(entry);
          }
          result.markers = out;
        } catch (e) { result.markers = []; }

        try {
          const settings = await seq.getSettings();
          result.settings = {};
          const grab = async (key, fn) => { try { result.settings[key] = await fn(); } catch (e) {} };
          await grab("audio_channel_count", () => settings.getAudioChannelCount());
          await grab("audio_channel_type", () => settings.getAudioChannelType());
          await grab("editing_mode", () => settings.getEditingMode());
          await grab("video_pixel_aspect_ratio", () => settings.getVideoPixelAspectRatio());
          await grab("max_bit_depth", () => settings.getMaximumBitDepth());
          await grab("max_render_quality", () => settings.getMaxRenderQuality());
        } catch (e) { result.settings = {}; }
        return result;
    """),
    "sequence_player_position": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        if (args.seconds !== undefined && args.seconds !== null) {
          await seq.setPlayerPosition(secondsToTick(args.seconds));
        }
        return { position: tt(await seq.getPlayerPosition()) };
    """),
    # ------------------------------------------------------------------
    # Markers
    # ------------------------------------------------------------------
    "marker_list": _s("""
        const project = await activeProject();
        let owner;
        if (args.clip_name || args.clip_path) {
          const item = await findProjectItem(project, { name: args.clip_name, path: args.clip_path });
          if (!item) throw new Error("Clip not found for marker listing");
          owner = ppro.ClipProjectItem.cast(item);
        } else {
          owner = await resolveSequence(project, args.sequence);
        }
        const markers = await ppro.Markers.getMarkers(owner);
        let out = [];
        project.lockedAccess(() => { out = markers; });
        let list = [];
        project.lockedAccess(() => { list = markers.getMarkers() || []; });
        const result = [];
        for (const m of list) {
          const entry = {};
          const grab = (key, fn) => { try { entry[key] = fn(); } catch (e) { entry[key] = null; } };
          grab("name", () => m.getName());
          grab("comments", () => m.getComments());
          grab("type", () => m.getType());
          grab("start", () => tt(m.getStart()));
          grab("duration", () => tt(m.getDuration()));
          grab("color_index", () => m.getColorIndex());
          grab("url", () => m.getUrl());
          result.push(entry);
        }
        return result;
    """),
    "marker_add": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const markers = await ppro.Markers.getMarkers(seq);
        const start = secondsToTick(args.seconds || 0);
        const duration = secondsToTick(args.duration_seconds || 0);
        const type = args.marker_type || "Comment";
        runTransaction(project, "pmr: add marker", (add) => {
          add(markers.createAddMarkerAction(args.name || "marker", type, start, duration, args.comments || ""));
        });
        if (args.color_index !== undefined && args.color_index !== null) {
          let created = null;
          project.lockedAccess(() => {
            const list = markers.getMarkers() || [];
            for (const m of list) {
              try {
                if (m.getStart().seconds === start.seconds && m.getName() === (args.name || "marker")) { created = m; }
              } catch (e) {}
            }
          });
          if (created) {
            runTransaction(project, "pmr: marker color", (add) => {
              add(created.createSetColorByIndexAction(args.color_index));
            });
          }
        }
        return { added: args.name || "marker", seconds: Number(args.seconds || 0), sequence: seq.name };
    """),
    "marker_remove": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const markers = await ppro.Markers.getMarkers(seq);
        let target = null;
        project.lockedAccess(() => {
          const list = markers.getMarkers() || [];
          for (const m of list) {
            try {
              const matchName = args.name ? m.getName() === args.name : true;
              const matchTime = args.seconds !== undefined && args.seconds !== null
                ? Math.abs(m.getStart().seconds - Number(args.seconds)) < 0.001
                : true;
              if (matchName && matchTime) { target = m; break; }
            } catch (e) {}
          }
        });
        if (!target) throw new Error("No matching marker found");
        runTransaction(project, "pmr: remove marker", (add) => {
          add(markers.createRemoveMarkerAction(target));
        });
        return { removed: true };
    """),
    # ------------------------------------------------------------------
    # Media / bins
    # ------------------------------------------------------------------
    "media_tree": _s("""
        const project = await activeProject();
        const root = await project.getRootItem();
        const withPaths = !!args.with_paths;
        async function walk(folder, depth) {
          const out = [];
          if (depth > 12) return out;
          for (const item of await folder.getItems()) {
            if (item.type === ppro.ProjectItem.TYPE_BIN) {
              out.push({
                kind: "bin",
                name: item.name,
                children: await walk(ppro.FolderItem.cast(item), depth + 1),
              });
            } else {
              const entry = { kind: "clip", name: item.name, type: item.type };
              if (withPaths) {
                try {
                  const clip = ppro.ClipProjectItem.cast(item);
                  entry.is_sequence = await clip.isSequence();
                  if (!entry.is_sequence) {
                    entry.path = await clip.getMediaFilePath();
                    entry.offline = await clip.isOffline();
                  }
                } catch (e) {}
              }
              out.push(entry);
            }
          }
          return out;
        }
        return { project: project.name, items: await walk(root, 0) };
    """),
    "media_import": _s("""
        const project = await activeProject();
        let targetBin;
        if (args.bin) {
          const folder = await findBin(project, args.bin, true);
          targetBin = ppro.ProjectItem.cast(folder);
        }
        const ok = await project.importFiles(args.paths, true, targetBin, !!args.as_numbered_stills);
        if (!ok) throw new Error("importFiles returned false");
        // Read back names for confirmation.
        const found = [];
        for (const p of args.paths) {
          const item = await findProjectItem(project, { path: p });
          found.push({ path: p, imported: !!item, name: item ? item.name : null });
        }
        return { imported: found.filter((f) => f.imported).length, requested: args.paths.length, items: found };
    """),
    "bin_ensure": _s("""
        const project = await activeProject();
        const folder = await findBin(project, args.path, true);
        return { name: folder.name, path: args.path };
    """),
    "bin_delete": _s("""
        const project = await activeProject();
        const parts = String(args.path).split("/").filter(Boolean);
        const name = parts.pop();
        const parent = await findBin(project, parts.join("/"), false);
        const items = await parent.getItems();
        let target = null;
        for (const item of items) {
          if (item.name === name && item.type === ppro.ProjectItem.TYPE_BIN) { target = item; break; }
        }
        if (!target) throw new Error(`Bin not found: ${args.path}`);
        runTransaction(project, "pmr: delete bin", (add) => {
          add(parent.createRemoveItemAction(target));
        });
        return { deleted: args.path };
    """),
    "media_move": _s("""
        const project = await activeProject();
        const source = await findBin(project, args.source_bin || "", false);
        const target = await findBin(project, args.target_bin, true);
        const items = await source.getItems();
        const moved = [];
        runTransaction(project, "pmr: move items", (add) => {
          for (const item of items) {
            if (item.type === ppro.ProjectItem.TYPE_BIN) continue;
            if (args.name_contains && !item.name.includes(args.name_contains)) continue;
            if (args.names && !args.names.includes(item.name)) continue;
            add(source.createMoveItemAction(item, target));
            moved.push(item.name);
          }
        });
        return { moved, target_bin: args.target_bin };
    """),
    "media_inspect_item": _s("""
        const project = await activeProject();
        const item = await findProjectItem(project, { name: args.name, path: args.path });
        if (!item) throw new Error(`Project item not found: ${args.name || args.path}`);
        const clip = ppro.ClipProjectItem.cast(item);
        const result = { name: item.name };
        const grab = async (key, fn) => { try { result[key] = await fn(); } catch (e) { result[key] = null; } };
        await grab("is_sequence", () => clip.isSequence());
        await grab("media_path", () => clip.getMediaFilePath());
        await grab("offline", () => clip.isOffline());
        await grab("has_proxy", () => clip.hasProxy());
        await grab("proxy_path", () => clip.getProxyPath());
        await grab("can_proxy", () => clip.canProxy());
        await grab("content_type", () => clip.getContentType());
        await grab("color_label", () => item.getColorLabelIndex());
        return result;
    """),
    # ------------------------------------------------------------------
    # Timeline editing
    # ------------------------------------------------------------------
    "timeline_insert": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const item = await findProjectItem(project, { name: args.item_name, path: args.item_path });
        if (!item) throw new Error(`Project item not found: ${args.item_name || args.item_path}`);
        const editor = ppro.SequenceEditor.getEditor(seq);
        let atSeconds = args.seconds;
        if (atSeconds === undefined || atSeconds === null) {
          const end = await seq.getEndTime();
          atSeconds = end ? end.seconds : 0;
        }
        const time = secondsToTick(atSeconds);
        const vTrack = args.video_track ?? 0;
        const aTrack = args.audio_track ?? 0;
        runTransaction(project, "pmr: insert clip", (add) => {
          if (args.overwrite) {
            add(editor.createOverwriteItemAction(item, time, vTrack, aTrack));
          } else {
            add(editor.createInsertProjectItemAction(item, time, vTrack, aTrack, !!args.limit_shift));
          }
        });
        return { inserted: item.name, at_seconds: Number(atSeconds), video_track: vTrack, audio_track: aTrack, overwrite: !!args.overwrite };
    """),
    "timeline_remove_items": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const tracks = await gatherTracks(project, seq, args.track_type || "video");
        const filterIdx = args.track_indexes;
        const perTrack = trackItemsSync(project, tracks, false);
        const matched = [];
        for (let i = 0; i < perTrack.length; i++) {
          if (filterIdx && !filterIdx.includes(i)) continue;
          for (const item of perTrack[i]) {
            let name = null;
            try { name = await item.getName(); } catch (e) {}
            if (args.name_contains && (!name || !name.includes(args.name_contains))) continue;
            matched.push(item);
          }
        }
        if (!matched.length) return { removed: 0 };
        let selection = null;
        ppro.TrackItemSelection.createEmptySelection((sel) => { selection = sel; });
        if (!selection) throw new Error("Could not create selection");
        for (const item of matched) selection.addItem(item, true);
        const editor = ppro.SequenceEditor.getEditor(seq);
        const mediaType = (args.track_type || "video") === "audio" ? C.MediaType.AUDIO : C.MediaType.VIDEO;
        runTransaction(project, "pmr: remove items", (add) => {
          add(editor.createRemoveItemsAction(selection, !!args.ripple, mediaType));
        });
        return { removed: matched.length, ripple: !!args.ripple };
    """),
    "clip_update": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const tracks = await gatherTracks(project, seq, args.track_type || "video");
        const perTrack = trackItemsSync(project, tracks, false);
        const updates = [];
        for (let i = 0; i < perTrack.length; i++) {
          if (args.track_index !== undefined && args.track_index !== null && i !== args.track_index) continue;
          for (const item of perTrack[i]) {
            let name = null;
            try { name = await item.getName(); } catch (e) {}
            if (args.name && name !== args.name) continue;
            if (args.name_contains && (!name || !name.includes(args.name_contains))) continue;
            updates.push({ item, name });
          }
        }
        if (!updates.length) return { updated: 0 };
        runTransaction(project, "pmr: update clips", (add) => {
          for (const u of updates) {
            if (args.set_name !== undefined) add(u.item.createSetNameAction(args.set_name));
            if (args.set_disabled !== undefined) add(u.item.createSetDisabledAction(!!args.set_disabled));
            if (args.shift_seconds) add(u.item.createMoveAction(secondsToTick(args.shift_seconds)));
            if (args.set_start_seconds !== undefined && args.set_start_seconds !== null)
              add(u.item.createSetStartAction(secondsToTick(args.set_start_seconds)));
            if (args.set_end_seconds !== undefined && args.set_end_seconds !== null)
              add(u.item.createSetEndAction(secondsToTick(args.set_end_seconds)));
          }
        });
        return { updated: updates.length, names: updates.map((u) => u.name) };
    """),
    # ------------------------------------------------------------------
    # Effects & transitions
    # ------------------------------------------------------------------
    "effects_list": _s("""
        const kind = args.kind || "video";
        if (kind === "video") {
          const matchNames = await ppro.VideoFilterFactory.getMatchNames();
          let displayNames = [];
          try { displayNames = await ppro.VideoFilterFactory.getDisplayNames(); } catch (e) {}
          return { kind, match_names: matchNames, display_names: displayNames };
        }
        if (kind === "audio") {
          const displayNames = await ppro.AudioFilterFactory.getDisplayNames();
          return { kind, display_names: displayNames };
        }
        if (kind === "transition") {
          const matchNames = await ppro.TransitionFactory.getVideoTransitionMatchNames();
          return { kind, match_names: matchNames };
        }
        throw new Error(`Unknown effects kind: ${kind}`);
    """),
    "transition_add": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const tracks = await gatherTracks(project, seq, "video");
        const perTrack = trackItemsSync(project, tracks, false);
        const targets = [];
        for (let i = 0; i < perTrack.length; i++) {
          if (args.track_index !== undefined && args.track_index !== null && i !== args.track_index) continue;
          for (const item of perTrack[i]) {
            let name = null;
            try { name = await item.getName(); } catch (e) {}
            if (args.clip_name && name !== args.clip_name) continue;
            targets.push(item);
          }
        }
        if (!targets.length) throw new Error("No matching clips for transition");
        const transition = ppro.TransitionFactory.createVideoTransition(args.match_name || "AE.ADBE Cross Dissolve New");
        let options;
        if (args.duration_seconds || args.apply_to_start !== undefined) {
          options = new ppro.AddTransitionOptions();
          if (args.duration_seconds) options.setDuration(secondsToTick(args.duration_seconds));
          if (args.apply_to_start !== undefined) options.setApplyToStart(!!args.apply_to_start);
        }
        runTransaction(project, "pmr: add transition", (add) => {
          for (const item of targets) {
            add(item.createAddVideoTransitionAction(transition, options));
          }
        });
        return { applied: targets.length, transition: args.match_name || "AE.ADBE Cross Dissolve New" };
    """),
    "effect_add": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const kind = args.kind || "video";
        const tracks = await gatherTracks(project, seq, kind === "audio" ? "audio" : "video");
        const perTrack = trackItemsSync(project, tracks, false);
        const targets = [];
        for (let i = 0; i < perTrack.length; i++) {
          if (args.track_index !== undefined && args.track_index !== null && i !== args.track_index) continue;
          for (const item of perTrack[i]) {
            let name = null;
            try { name = await item.getName(); } catch (e) {}
            if (args.clip_name && name !== args.clip_name) continue;
            targets.push(item);
          }
        }
        if (!targets.length) throw new Error("No matching clips for effect");
        let applied = 0;
        for (const item of targets) {
          const chain = await item.getComponentChain();
          let component;
          if (kind === "audio") {
            component = await ppro.AudioFilterFactory.createComponentByDisplayName(args.name, item);
          } else {
            component = await ppro.VideoFilterFactory.createComponent(args.name);
          }
          if (!component) throw new Error(`Could not create effect: ${args.name}`);
          runTransaction(project, "pmr: add effect", (add) => {
            add(chain.createAppendComponentAction(component));
          });
          applied += 1;
        }
        return { applied, effect: args.name };
    """),
    "clip_components": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const kind = args.kind || "video";
        const tracks = await gatherTracks(project, seq, kind === "audio" ? "audio" : "video");
        const perTrack = trackItemsSync(project, tracks, false);
        let target = null;
        for (let i = 0; i < perTrack.length; i++) {
          if (args.track_index !== undefined && args.track_index !== null && i !== args.track_index) continue;
          for (const item of perTrack[i]) {
            let name = null;
            try { name = await item.getName(); } catch (e) {}
            if (args.clip_name && name !== args.clip_name) continue;
            target = item;
            break;
          }
          if (target) break;
        }
        if (!target) throw new Error("Clip not found");
        const chain = await target.getComponentChain();
        const out = [];
        let count = 0;
        project.lockedAccess(() => { count = chain.getComponentCount(); });
        for (let i = 0; i < count; i++) {
          let component = null;
          project.lockedAccess(() => { component = chain.getComponentAtIndex(i); });
          const entry = { index: i, params: [] };
          try { entry.display_name = await component.getDisplayName(); } catch (e) {}
          try { entry.match_name = await component.getMatchName(); } catch (e) {}
          let paramCount = 0;
          project.lockedAccess(() => { try { paramCount = component.getParamCount(); } catch (e) {} });
          for (let j = 0; j < paramCount; j++) {
            let param = null;
            project.lockedAccess(() => { try { param = component.getParam(j); } catch (e) {} });
            if (!param) continue;
            const p = { index: j };
            try { p.display_name = param.displayName; } catch (e) {}
            try { p.time_varying = param.isTimeVarying(); } catch (e) {}
            if (args.with_values) {
              try {
                const v = await param.getValueAtTime(secondsToTick(args.at_seconds || 0));
                p.value = (v && typeof v === "object") ? JSON.parse(JSON.stringify(v)) : v;
              } catch (e) {}
            }
            entry.params.push(p);
          }
          out.push(entry);
        }
        return { clip: args.clip_name || null, components: out };
    """),
    "param_set": _s("""
        // Set a component parameter value (optionally keyframed at a time).
        // args: sequence, clip_name, track_index, kind, component (match or display name),
        //       param (display name or index), value (number|bool|string|[x,y]|{r,g,b,a}),
        //       at_seconds (optional -> keyframe), interpolation (optional)
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const kind = args.kind || "video";
        const tracks = await gatherTracks(project, seq, kind === "audio" ? "audio" : "video");
        const perTrack = trackItemsSync(project, tracks, false);
        let target = null;
        for (let i = 0; i < perTrack.length; i++) {
          if (args.track_index !== undefined && args.track_index !== null && i !== args.track_index) continue;
          for (const item of perTrack[i]) {
            let name = null;
            try { name = await item.getName(); } catch (e) {}
            if (args.clip_name && name !== args.clip_name) continue;
            target = item;
            break;
          }
          if (target) break;
        }
        if (!target) throw new Error("Clip not found");
        const chain = await target.getComponentChain();
        let count = 0;
        project.lockedAccess(() => { count = chain.getComponentCount(); });
        let component = null;
        for (let i = 0; i < count; i++) {
          let candidate = null;
          project.lockedAccess(() => { candidate = chain.getComponentAtIndex(i); });
          let dn = null, mn = null;
          try { dn = await candidate.getDisplayName(); } catch (e) {}
          try { mn = await candidate.getMatchName(); } catch (e) {}
          if (dn === args.component || mn === args.component) { component = candidate; break; }
        }
        if (!component) throw new Error(`Component not found: ${args.component}`);
        let param = null;
        project.lockedAccess(() => {
          const paramCount = component.getParamCount();
          for (let j = 0; j < paramCount; j++) {
            const candidate = component.getParam(j);
            if (typeof args.param === "number" ? j === args.param : candidate.displayName === args.param) {
              param = candidate;
              break;
            }
          }
        });
        if (!param) throw new Error(`Param not found: ${args.param}`);
        let value = args.value;
        if (Array.isArray(value) && value.length === 2) {
          value = new ppro.PointF(Number(value[0]), Number(value[1]));
        } else if (value && typeof value === "object" && "r" in value) {
          value = new ppro.Color(value.r, value.g, value.b, value.a === undefined ? 255 : value.a);
        }
        const keyframe = param.createKeyframe(value);
        runTransaction(project, "pmr: set param", (add) => {
          if (args.at_seconds !== undefined && args.at_seconds !== null) {
            add(param.createSetTimeVaryingAction(true));
            keyframe.position = secondsToTick(args.at_seconds);
            add(param.createAddKeyframeAction(keyframe));
          } else {
            add(param.createSetValueAction(keyframe, true));
          }
        });
        return { set: args.param, component: args.component, value: args.value,
                 keyframed: args.at_seconds !== undefined && args.at_seconds !== null };
    """),
    # ------------------------------------------------------------------
    # Export / render
    # ------------------------------------------------------------------
    "export_sequence": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const manager = ppro.EncoderManager.getManager();
        const typeMap = {
          immediately: C.ExportType.IMMEDIATELY,
          queue_to_ame: C.ExportType.QUEUE_TO_AME,
          queue_to_app: C.ExportType.QUEUE_TO_APP,
        };
        const exportType = typeMap[args.export_type || "immediately"];
        if (exportType === undefined) throw new Error(`Unknown export_type: ${args.export_type}`);
        const ok = await manager.exportSequence(
          seq, exportType, args.output_file, args.preset_file, args.export_full !== false
        );
        if (!ok) throw new Error("exportSequence returned false");
        return {
          submitted: true,
          sequence: seq.name,
          output_file: args.output_file || null,
          preset_file: args.preset_file || null,
          export_type: args.export_type || "immediately",
        };
    """),
    "export_frame": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const time = secondsToTick(args.seconds || 0);
        const ok = await ppro.Exporter.exportSequenceFrame(
          seq, time, args.filename, args.dir, args.width || 0, args.height || 0
        );
        if (!ok) throw new Error("exportSequenceFrame returned false");
        return { exported: `${args.dir}/${args.filename}`, seconds: Number(args.seconds || 0) };
    """),
    "export_file_extension": _s("""
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const ext = await ppro.EncoderManager.getExportFileExtension(seq, args.preset_file);
        return { extension: ext };
    """),
    "ame_status": _s("""
        const manager = ppro.EncoderManager.getManager();
        return { ame_installed: !!manager.isAMEInstalled };
    """),
    # ------------------------------------------------------------------
    # Interchange
    # ------------------------------------------------------------------
    "interchange_export": _s("""
        if (typeof ppro.ProjectConverter === "undefined") {
          throw new Error("ProjectConverter is unavailable in this Premiere version (needs 26.3+)");
        }
        const project = await activeProject();
        const seq = await resolveSequence(project, args.sequence);
        const format = args.format;
        if (format === "fcpxml") {
          await ppro.ProjectConverter.exportAsFinalCutProXML(seq, args.path, true);
        } else if (format === "otio") {
          await ppro.ProjectConverter.exportAsOpenTimelineIO(seq, args.path, true);
        } else if (format === "aaf") {
          await ppro.ProjectConverter.exportAAF(seq, args.path);
        } else {
          throw new Error(`Unknown interchange format: ${format} (expected fcpxml|otio|aaf)`);
        }
        return { exported: args.path, format, sequence: seq.name };
    """),
    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    "metadata_get": _s("""
        const project = await activeProject();
        const item = await findProjectItem(project, { name: args.name, path: args.path });
        if (!item) throw new Error(`Project item not found: ${args.name || args.path}`);
        const result = { name: item.name };
        if (args.kind === "xmp" || !args.kind) {
          try { result.xmp = await ppro.Metadata.getXMPMetadata(item); } catch (e) { result.xmp = null; }
        }
        if (args.kind === "project" || !args.kind) {
          try { result.project_metadata = await ppro.Metadata.getProjectMetadata(item); } catch (e) { result.project_metadata = null; }
        }
        return result;
    """),
    "metadata_set_xmp": _s("""
        const project = await activeProject();
        const item = await findProjectItem(project, { name: args.name, path: args.path });
        if (!item) throw new Error(`Project item not found: ${args.name || args.path}`);
        runTransaction(project, "pmr: set XMP metadata", (add) => {
          add(ppro.Metadata.createSetXMPMetadataAction(item, args.xmp));
        });
        return { updated: item.name };
    """),
    # ------------------------------------------------------------------
    # Source monitor
    # ------------------------------------------------------------------
    "source_monitor": _s("""
        const op = args.op;
        if (op === "open_path") { await ppro.SourceMonitor.openFilePath(args.path); return { opened: args.path }; }
        if (op === "open_item") {
          const project = await activeProject();
          const item = await findProjectItem(project, { name: args.name, path: args.path });
          if (!item) throw new Error("Project item not found");
          await ppro.SourceMonitor.openProjectItem(item);
          return { opened: item.name };
        }
        if (op === "close") { await ppro.SourceMonitor.closeClip(); return { closed: true }; }
        if (op === "close_all") { await ppro.SourceMonitor.closeAllClips(); return { closed: "all" }; }
        if (op === "play") { await ppro.SourceMonitor.play(args.speed || 1.0); return { playing: true }; }
        if (op === "position") {
          if (args.seconds !== undefined && typeof ppro.SourceMonitor.setPosition === "function") {
            await ppro.SourceMonitor.setPosition(secondsToTick(args.seconds));
          }
          return { position: tt(await ppro.SourceMonitor.getPosition()) };
        }
        throw new Error(`Unknown source monitor op: ${op}`);
    """),
    # ------------------------------------------------------------------
    # Properties (per-project/sequence key-value store)
    # ------------------------------------------------------------------
    "properties_get": _s("""
        const project = await activeProject();
        const owner = args.sequence ? await resolveSequence(project, args.sequence) : project;
        const props = await ppro.Properties.getProperties(owner);
        if (!props.hasValue(args.key)) return { key: args.key, exists: false, value: null };
        return { key: args.key, exists: true, value: props.getValue(args.key) };
    """),
    "properties_set": _s("""
        const project = await activeProject();
        const owner = args.sequence ? await resolveSequence(project, args.sequence) : project;
        const props = await ppro.Properties.getProperties(owner);
        const flag = args.persistent === false ? ppro.Properties.PROPERTY_NON_PERSISTENT : ppro.Properties.PROPERTY_PERSISTENT;
        runTransaction(project, "pmr: set property", (add) => {
          add(props.createSetValueAction(args.key, args.value, flag));
        });
        return { set: args.key };
    """),
}


def snippet(name: str) -> str:
    """Return the full JS source for a named snippet."""
    return SNIPPETS[name]


__all__ = ["PRELUDE", "SNIPPETS", "snippet"]
