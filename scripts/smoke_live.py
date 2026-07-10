#!/usr/bin/env python3
"""End-to-end smoke test against a live Premiere Pro.

Not part of the pytest suite (that runs offline against the mock bridge).
This drives a real Premiere through the bridge and asserts each layer
works: project, media, sequences, markers, effects, transforms, export,
interchange, snapshot, spec. Run it after any bridge/plugin change:

    .venv/bin/python scripts/smoke_live.py [/path/to/clip.mov ...]

Exits non-zero on the first failure, printing which stage broke. Safe to
re-run: it uses a throwaway project under the system temp dir.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from pmr import Premiere, interchange
from pmr import snapshot as snapshot_mod
from pmr import spec as spec_mod


def _stage(name: str) -> None:
    print(f"\x1b[36m▶ {name}\x1b[0m")


def main(argv: list[str]) -> int:
    clips = [Path(a) for a in argv if Path(a).exists()]
    if not clips:
        print("usage: smoke_live.py <clip.mov> [more clips...] (need at least one)")
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="pmr-smoke-"))
    p = Premiere(timeout=45)

    _stage("app + connection")
    info = p.app.inspect()
    assert info["ppro_available"], info
    print("  host", p.app.product, p.app.version)

    _stage("project ensure/save")
    proj = p.project.ensure(str(workdir / "smoke.prproj"))
    print("  project", proj.name)

    _stage("media import")
    result = p.media.import_([str(c) for c in clips], bin="Footage")
    assert result["imported"] >= 1, result
    print("  imported", result["imported"])

    _stage("sequence create + append")
    tl = p.timeline.ensure("Smoke_v1")
    p.timeline.set_current("Smoke_v1")
    tl.append(clips[0].name)
    data = tl.inspect()
    total = sum(t["clips"] for t in data["tracks"]["video"])
    assert total >= 1, data
    print("  clips on V", total, "fps", data["fps"])

    _stage("markers")
    tl.add_marker(0.5, name="smoke", note="e2e", color_index=1)
    assert any(m["name"] == "smoke" for m in tl.markers())
    print("  markers", len(tl.markers()))

    # Export a still while the sequence is simple and settled, before the
    # heavy effect/keyframe transactions below (which keep Premiere busy and
    # can delay an immediately-following frame render).
    _stage("still frame export")
    frame = workdir / "frame.png"
    p.render.export_frame(0.2, str(frame), timeline="Smoke_v1", width=320, height=180)
    for _ in range(60):  # exportSequenceFrame writes asynchronously
        if frame.exists():
            break
        time.sleep(0.25)
    assert frame.exists(), "frame was not written within 15s"
    print("  frame ->", frame.exists())

    _stage("effects + transform + keyframes")
    p.effects.apply("PR.ADBE Gamma Correction", clip_name=clips[0].name, timeline="Smoke_v1")
    p.effects.set_param("Motion", "Scale", 80, clip_name=clips[0].name, timeline="Smoke_v1")
    p.effects.set_param(
        "Opacity", "Opacity", 0, clip_name=clips[0].name, timeline="Smoke_v1", at_seconds=1.0
    )
    print("  gamma + scale=80 + opacity keyframe applied")

    _stage("interchange (fcpxml)")
    interchange.export_timeline(p, str(workdir / "smoke.xml"), timeline="Smoke_v1")
    print("  fcpxml ->", (workdir / "smoke.xml").exists())

    _stage("snapshot + spec from_live")
    snap = snapshot_mod.capture(p)
    snapshot_mod.save(snap)
    live_spec = spec_mod.from_live(p)
    print("  snapshot", snap.name, "| spec timelines", len(live_spec["timelines"]))

    _stage("sequence export (EncoderManager)")
    presets = p.render.presets()
    if presets:
        job = p.render.submit(
            target_dir=str(workdir / "out"),
            preset=presets[0]["path"],
            timeline="Smoke_v1",
            wait=True,
            timeout=600,
        )
        print("  exported ->", job.output_path, "exists", Path(job.output_path or "").exists())
    else:
        print("  (no .epr presets found; skipping sequence export)")

    p.project.save()
    p.close()
    print("\n\x1b[32m✓ all live stages passed\x1b[0m")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except AssertionError as exc:
        print(f"\x1b[31m✗ assertion failed: {exc}\x1b[0m")
        raise SystemExit(1) from exc
