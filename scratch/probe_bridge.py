"""Can the prebuilt QGIS bridge actually load in THIS venv?

Sources considered, in order of plausibility:
  1. .venv/Lib/site-packages                       (editable install target)
  2. <worktree>/native/qgis_render_bridge          (stray build output)
  3. PALEO_QGIS_BRIDGE_DIR (explicit override)

Loading a QGIS-linked extension needs a large DLL closure (Qt6, GDAL, PROJ,
GEOS, QGIS itself). A bare .pyd on sys.path is NOT enough, so chain-import
failures are expected and reported verbatim.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / ".workbuddy" / "bridge_probe.txt"

# Minimal closure we need: mapstack is what QgisCanvasShim imports.
TARGETS = [
    "qgis_render_bridge",
    "qgis_render_bridge.mapstack",
]


def main() -> None:
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)

    say(f"python      = {sys.version.split()[0]}")
    say(f"executable  = {sys.executable}")
    say(f"cwd         = {os.getcwd()}")

    # ---- 1. where does the venv think the bridge is? ----------------------
    try:
        import importlib.util

        spec = importlib.util.find_spec("qgis_render_bridge")
        say(f"find_spec   = {spec.origin if spec else None}")
        say(f"sub_locs    = {list(getattr(spec, 'submodule_search_locations', []) or [])}")
    except Exception as exc:  # noqa: BLE001
        say(f"find_spec raised {type(exc).__name__}: {exc}")

    # ---- 2. what does the editable finder map to? -------------------------
    try:
        from qgis_render_bridge import __file__ as bf  # type: ignore

        say(f"imported    = {bf}")
    except Exception as exc:  # noqa: BLE001
        say(f"import raised {type(exc).__name__}: {exc}")

    # ---- 3. collect candidate .pyd locations ------------------------------
    candidates: list[Path] = []
    env = os.environ.get("PALEO_QGIS_BRIDGE_DIR", "").strip()
    if env:
        candidates.append(Path(env))
    sp = Path(sys.prefix) / "Lib" / "site-packages"
    candidates.append(sp)
    projects = REPO_ROOT.parent
    for d in sorted(projects.glob("paleo-workbench*/native/qgis_render_bridge")):
        candidates.append(d)

    say("")
    say("=== candidate dirs ===")
    found_dirs: list[Path] = []
    for d in candidates:
        pyds = list(d.glob("qgis_render_bridge*.pyd")) if d.is_dir() else []
        mark = "PYD" if pyds else ("dir" if d.is_dir() else "MISSING")
        say(f"[{mark:7}] {d}")
        for p in pyds:
            say(f"            {p.name}  {p.stat().st_size / 1e6:.2f} MB")
        if pyds:
            found_dirs.append(d)

    # ---- 4. try loading the best candidate in a clean interpreter ----------
    say("")
    say("=== load attempts (subprocess, fresh sys.path) ===")
    import subprocess

    for d in found_dirs:
        for target in TARGETS:
            code = (
                "import sys;"
                f"sys.path.insert(0, r'{d}');"
                f"import {target} as m;"
                f"print('OK', getattr(m, '__file__', '?'))"
            )
            try:
                r = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=180,
                    cwd=str(REPO_ROOT),
                )
            except subprocess.TimeoutExpired:
                say(f"[timeout ] {d.name} :: {target}")
                continue
            rc = r.returncode
            first_err = ""
            for line in (r.stderr or "").splitlines():
                if "Error" in line or "error" in line or "DLL" in line:
                    first_err = line.strip()
                    break
            if not first_err:
                first_err = ((r.stderr or "").strip().splitlines() or [""])[-1]
            verdict = "OK" if rc == 0 else f"rc={rc}"
            say(f"[{verdict:7}] {d.name} :: {target}")
            if rc != 0:
                say(f"            {first_err[:200]}")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", errors="replace")


if __name__ == "__main__":
    main()
