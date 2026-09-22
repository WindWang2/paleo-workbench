"""Verify the two ways to get real data into the app.

A) 打开样例工程  (open_sample_requested) -> resolve_sample_data_root()
B) 打开工程      (open_project_requested) -> ProjectManager(path).load()

Reports which one actually works on this machine, so the user is not told to
click a button that raises FileNotFoundError.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OUT = ROOT / ".workbuddy" / "open_paths_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()


CANDIDATE = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area")
PROJECT_FILE = CANDIDATE / "project_area.paleo.json"

# --- A) sample-data resolver -------------------------------------------
out("=== A) resolve_sample_data_root() ===")
from paleo_workbench.pipeline.bootstrap import resolve_sample_data_root  # noqa: E402

try:
    got = resolve_sample_data_root(cwd=ROOT)
    out(f"  no-env, cwd=repo        -> {got}")
except Exception as e:
    out(f"  no-env, cwd=repo        -> {type(e).__name__}: {e}")

os.environ["PALEO_SAMPLE_DATA"] = str(CANDIDATE)
try:
    got = resolve_sample_data_root()
    out(f"  PALEO_SAMPLE_DATA=...   -> {got}")
    out(f"  resolved == 井曲线 dir parent? {(got / '井曲线').is_dir()}")
except Exception as e:
    out(f"  PALEO_SAMPLE_DATA=...   -> {type(e).__name__}: {e}")

# --- B) open the existing project file ---------------------------------
out()
out("=== B) ProjectManager(<file>).load() ===")
out(f"  file exists = {PROJECT_FILE.is_file()}  size={PROJECT_FILE.stat().st_size if PROJECT_FILE.is_file() else 0}")

from paleo_workbench.project.manager import ProjectManager  # noqa: E402

try:
    mgr = ProjectManager(PROJECT_FILE)
    proj = mgr.load()
except Exception as e:
    out(f"  LOAD FAILED: {type(e).__name__}: {e}")
else:
    out("  LOAD OK")
    meta = proj.meta
    out(f"  name={meta.name!r} region={meta.region!r} version={meta.version!r}")
    out(f"  project_root={meta.project_root!r}")
    out(f"  project_crs={proj.coordinate.project_crs!r}")

    def count(attr: str) -> str:
        v = getattr(proj, attr, None)
        if v is None:
            return "<absent>"
        try:
            return str(len(v))
        except TypeError:
            return repr(v)

    for attr in (
        "wells",
        "well_curves",
        "well_picks",
        "horizon_interpretations",
        "seismic_surveys",
        "reference_layers",
        "factor_grids",
        "export_artifacts",
        "sequence_boundaries",
    ):
        out(f"  {attr:24s} = {count(attr)}")

    wp = getattr(proj, "mapping_workspace", None)
    out(f"  mapping_workspace        = {type(wp).__name__ if wp is not None else None}")

out()
out("DONE")
_fh.close()
print("done")
