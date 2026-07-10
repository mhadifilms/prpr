# Cookbook

Real workflows, all validated against live Premiere Pro.

## Assemble a rough cut from a folder

```python
from pmr import Premiere, scan_media_files

p = Premiere()
p.project.ensure("RoughCut")

files = scan_media_files("/footage/selects")           # no Premiere needed
p.media.import_([f["path"] for f in files], bin="Selects")

tl = p.timeline.ensure("Assembly")
for f in files:
    if f["kind"] == "video":
        tl.append(Path(f["path"]).name)                # end-to-end

p.render.submit(target_dir="/exports", preset="ProRes 422", wait=True)
```

## Batch-mark short clips for review

```python
tl = p.timeline.current
for clip in tl.clips.where(lambda c: (c.duration or 0) < 1.0):
    tl.add_marker(clip.start, name="short", note=f"{clip.name} < 1s", color_index=1)
```

## Reproducible project from a spec

```yaml
# show.yaml
project: NightlyBuild
bins: [Footage, Exports]
media:
  - {path: /footage/intro.mov, bin: Footage}
timelines:
  - name: Master
    active: true
    clips: [intro.mov]
    markers:
      - {seconds: 0, name: HEAD, color_index: 5}
```

```bash
pmr apply show.yaml --verify      # idempotent; safe to re-run
```

## Ken Burns (keyframed transform)

```python
tl = p.timeline.current
p.effects.set_param("Motion", "Scale", 100, clip_name="photo.jpg", at_seconds=0)
p.effects.set_param("Motion", "Scale", 130, clip_name="photo.jpg", at_seconds=5)
p.effects.set_param("Motion", "Position", [0.5, 0.5], clip_name="photo.jpg", at_seconds=0)
p.effects.set_param("Motion", "Position", [0.6, 0.4], clip_name="photo.jpg", at_seconds=5)
```

## Cross-fade every cut on V1

```python
tl = p.timeline.current
for clip in tl.items("video"):
    p.effects.add_transition("ADBE Cross Dissolve New", clip_name=clip.name,
                             duration_seconds=0.5)
```

## Snapshot before an experiment, diff after

```python
from pmr import snapshot, diff

snap = snapshot.capture(p); snapshot.save(snap)
# ... make changes ...
d = diff.compare_to_snapshot(p, snap.name)
print(d.to_dict())
```

## One editor, two NLEs

Because `pmr` and [`dvr`](https://github.com/mhadifilms/dvr) share routing,
the same driver code targets either app — swap the import and the ops that
exist in both Just Work; the ones that don't fail loudly:

```python
try:
    from pmr import Premiere as NLE          # or: from dvr import Resolve as NLE
except ImportError:
    from dvr import Resolve as NLE

app = NLE()
app.project.ensure("Show")
tl = app.timeline.ensure("Edit")
tl.add_marker(1.0, name="start")             # 'both' — works on either
# app.render.queue()                          # raises NotSupportedError on pmr
```
