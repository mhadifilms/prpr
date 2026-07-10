# Python library

```python
from pmr import Premiere

p = Premiere()          # hosts the bridge; launches Premiere if needed
```

The object model mirrors [`dvr`](https://github.com/mhadifilms/dvr)'s:
namespaces hang off the root handle, state is always read live, and
operations are idempotent where possible (`ensure` everywhere).

## Projects

```python
p.project.list()                  # projects open in Premiere
proj = p.project.ensure("MyShow") # open-or-create by name (or full path)
proj.inspect()                    # name, path, sequences, bin/item counts
proj.save(); proj.save_as("/path/copy.prproj"); proj.close()
```

## Timelines (sequences)

```python
tl = p.timeline.ensure("Edit_v1")
tl.inspect()                      # fps, frame size, tracks, items, markers, settings
tl.append("clip_a.mp4")           # by project-item name (or item_path=...)
tl.insert("clip_b.mp4", seconds=10.0, video_track=1)
tl.delete_clips(name_contains="temp", ripple=True)
tl.set_in_out(1.0, 5.0)
tl.insert_mogrt("/path/lower-third.mogrt", seconds=2.0)
tl.scene_edit_detection(operation="cut", clip_name="long_take.mp4")

tl.add_marker(1.0, name="start", note="first pass", color_index=1)
tl.markers(); tl.remove_marker(name="start")

short = tl.clips.where(lambda c: (c.duration or 0) < 0.5)   # query language
for clip in short:
    clip.disable()
```

## Media

```python
p.media.import_(["/footage/a.mp4"], bin="Footage/Day1")   # bins auto-created
p.media.find_or_import("/footage/a.mp4")                   # idempotent
p.media.inspect()                                          # full bin/clip tree
p.media.move("Selects", source_bin="Footage", name_contains="_ok")
p.media.attach_proxy("/proxies/a_proxy.mov", name="a.mp4")
p.media.create_subclip("a_sub", 1.0, 4.0, name="a.mp4")    # 26.3+
p.media.transcript_export(name="interview.mp4")            # 26.3+
pmr.scan_media_files("/footage")                           # no Premiere needed
```

## Effects, transitions, transforms

```python
p.effects.list("video")           # 111 effects with matchNames
p.effects.apply("PR.ADBE Gamma Correction", clip_name="a.mp4")
p.effects.add_transition("ADBE Film Dissolve", clip_name="a.mp4", duration_seconds=1.0)

# Transforms are Motion-component params:
p.effects.set_param("Motion", "Scale", 50, clip_name="a.mp4")
p.effects.set_param("Motion", "Position", [0.25, 0.5], clip_name="a.mp4")

# Keyframes: pass at_seconds
p.effects.set_param("Opacity", "Opacity", 100, clip_name="a.mp4", at_seconds=0)
p.effects.set_param("Opacity", "Opacity", 0, clip_name="a.mp4", at_seconds=2.0)

p.effects.components(clip_name="a.mp4", with_values=True)  # inspect the chain
```

## Render / export

```python
p.render.presets()                              # .epr discovery
job = p.render.submit(target_dir="/exports",
                      preset="ProRes 422",      # name or path to .epr
                      queue_to=None,            # None | "app" | "ame"
                      wait=True)
job.output_path

p.render.export_frame(2.0, "/stills/f.png", width=1920, height=1080)

from pmr import interchange
interchange.export_timeline(p, "/out/edit.xml")     # fcpxml by extension
interchange.export_timeline(p, "/out/edit.otio")
interchange.export_timeline(p, "/out/edit.aaf")
```

## Declarative workflows

```python
from pmr import spec, diff, snapshot, lint

s = spec.load_spec("show.yaml")
spec.plan(s, p)                    # what would change
spec.apply(s, p, verify=True)      # reconcile + read-back verification

d = diff.compare_timelines(p, "Edit_v1", "Edit_v2")
snap = snapshot.capture(p); snapshot.save(snap)
report = lint.lint(p)              # offline media, temp paths, empty sequences
```

## Escape hatch: raw JavaScript

The full `premierepro` UXP module is one call away — this is the same
mechanism every wrapper uses:

```python
p.eval_js("""
    const project = await ppro.Project.getActiveProject();
    return project.name;
""")
```

## Errors

Everything raises a `pmr.errors.PmrError` subclass with `message`,
`cause`, `fix`, and a `state` snapshot. Operations Premiere's API can't
perform raise `NotSupportedError` — see [parity](parity.md).
