# Declarative specs

`prpr apply` reconciles a YAML/JSON description of desired project state
against the live project, terraform-style: compute a plan, execute only
what's missing, optionally verify by re-planning. Same format family as
`dvr`'s specs.

## Format

```yaml
project: MyShow            # opened-or-created (name or .prproj path)

bins:                      # created if missing (nested paths ok)
  - Footage
  - Footage/Day1
  - Exports

media:                     # imported if no clip references the path yet
  - path: /footage/a.mp4
    bin: Footage/Day1
  - path: /footage/b.mp4
    bin: Footage

timelines:
  - name: Edit_v1
    active: true           # becomes the active sequence
    clips:                 # appended in order when missing (by name)
      - a.mp4
      - b.mp4
    markers:               # added when no marker matches (name, seconds)
      - seconds: 1.0
        name: start
        note: first pass
        color_index: 1
      - seconds: 30.0
        name: review
        duration_seconds: 5.0
```

## Commands

```bash
prpr apply plan show.yaml       # print the plan, change nothing
prpr apply show.yaml            # reconcile
prpr apply show.yaml --verify   # reconcile, then re-plan; fail if anything remains
prpr spec export -o show.yaml   # reverse-engineer a spec from live state
prpr diff spec show.yaml        # structural diff: live vs spec
```

## Semantics

- **Idempotent**: applying twice is a no-op (the second plan is empty).
- **Additive**: apply never deletes clips, bins, or markers — it converges
  *toward* the spec by creating what's missing. Removal stays a manual or
  imperative-CLI operation by design.
- **Verified**: `--verify` catches Premiere's silent rejections by
  re-reading state after the apply.

## Library

```python
from prpr import spec

s = spec.load_spec("show.yaml")
actions = spec.plan(s, p)          # list of {op, target, detail}
spec.apply(s, p, verify=True)
live = spec.from_live(p)           # dict, ready to yaml.dump
```
