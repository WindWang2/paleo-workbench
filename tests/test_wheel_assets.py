"""Packaging smoke test: the built wheel must carry the runtime file-system assets.

The workbench loads icons / prototypes / docs from the file system at runtime
(paleo_workbench/ui/icon_rail.py, menu_bar.py, mapping docs, vendored
ATTRIBUTION.md). setuptools only packages .py files by default, so without
[tool.setuptools.package-data] a wheel silently ships without any of these 21
files and the installed UI degrades to plain-text navigation (packaging #439).
This test rebuilds the wheel and asserts the manifest, failing the gate if the
package-data config regresses.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import zipfile

from setuptools import build_meta

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SVG = 77
EXPECTED_HTML = 3
EXPECTED_MD = 2


def test_wheel_manifest_contains_all_non_py_assets(tmp_path) -> None:
    build_dir = REPO_ROOT / "build"
    egg_info = REPO_ROOT / "paleo_workbench.egg-info"
    for artifact in (build_dir, egg_info):
        if artifact.exists():
            shutil.rmtree(artifact, ignore_errors=True)
    try:
        wheel_name = build_meta.build_wheel(str(tmp_path))
        wheel_path = Path(tmp_path) / wheel_name
    finally:
        # Build artifacts are never committed; remove them so repeated local
        # runs start from a clean tree.
        for artifact in (build_dir, egg_info):
            shutil.rmtree(artifact, ignore_errors=True)

    with zipfile.ZipFile(wheel_path) as wheel:
        names = wheel.namelist()

    svg_assets = [
        name for name in names if name.startswith("paleo_workbench/ui/assets/icons/") and name.endswith(".svg")
    ]
    html_assets = [
        name for name in names if name.startswith("paleo_workbench/ui/pages/prototypes/") and name.endswith(".html")
    ]
    md_assets = [name for name in names if name.endswith(".md")]

    assert len(svg_assets) == EXPECTED_SVG, (
        f"wheel must carry all {EXPECTED_SVG} SVG icons, found {len(svg_assets)}: {sorted(svg_assets)}"
    )
    assert len(html_assets) == EXPECTED_HTML, (
        f"wheel must carry all {EXPECTED_HTML} HTML prototypes, found {len(html_assets)}"
    )
    assert len(md_assets) == EXPECTED_MD, (
        f"wheel must carry both package .md docs, found {len(md_assets)}: {sorted(md_assets)}"
    )
    # Spot-check the exact assets the UI loads (icon_rail / menu_bar).
    assert "paleo_workbench/ui/assets/icons/home.svg" in names
    assert "paleo_workbench/ui/assets/icons/mapping.svg" in names
    assert "paleo_workbench/mapping/CPP_EXTENSION.md" in names
    assert "paleo_workbench/_vendored/haiyou_constrained_idw/ATTRIBUTION.md" in names
