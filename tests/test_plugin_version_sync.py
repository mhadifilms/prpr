"""Guard: the plugin's manifest version and its JS PLUGIN_VERSION must match.

The bridge reports PLUGIN_VERSION (from main.js) in its `hello`, while the
pip package compares against the manifest version. If these drift, the
auto-update check misfires. This test keeps them locked together for both
the headless and panel plugins.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PLUGIN_DIRS = [REPO / "plugin", REPO / "plugin-panel"]


@pytest.mark.parametrize("plugin_dir", PLUGIN_DIRS, ids=lambda p: p.name)
def test_manifest_and_js_version_match(plugin_dir: Path) -> None:
    manifest = json.loads((plugin_dir / "manifest.json").read_text())
    manifest_version = manifest["version"]

    js = (plugin_dir / "main.js").read_text()
    match = re.search(r'PLUGIN_VERSION\s*=\s*"([^"]+)"', js)
    assert match, f"PLUGIN_VERSION not found in {plugin_dir.name}/main.js"
    js_version = match.group(1)

    assert manifest_version == js_version, (
        f"{plugin_dir.name}: manifest.json version {manifest_version!r} != "
        f"main.js PLUGIN_VERSION {js_version!r}"
    )


def test_manifest_version_matches_bundled_helper() -> None:
    from prpr import connection

    # bundled_plugin_version() reads the default (headless) plugin manifest.
    manifest = json.loads((REPO / "plugin" / "manifest.json").read_text())
    assert connection.bundled_plugin_version() == manifest["version"]
