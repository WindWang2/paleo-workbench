"""V8 worktree QGIS test/verification launcher.

Windows runtime recipe (reproduces the V7 authoring combo bit-for-bit):

* PySide6 pinned 6.8.3 (process Qt — same minor as the vendored QGIS build),
* vendor bin first (qgis_*.dll + self-contained third-party runtimes,
  including Qt6Core5Compat which PySide6 does not ship),
* PySide6 dir second (the single process Qt).

The conda deps env (qt6-main 6.11.2) is deliberately NOT on the loader path:
its satellite Qt DLLs would shadow PySide6's and break the load with
WinError 127 (mixed-minor Qt).  It remains a build-time prefix only.

Usage:
    python scripts/run_qgis_env.py <pytest args...>   # runs pytest with env set
    python scripts/run_qgis_env.py --probe            # verifies bridge import
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# V10 review follow-up（#1263）：不再硬编码作者机器的 worktree 绝对路径——
# 那让"默认可用"只在作者机器上成立。改为本仓库的相对约定位置；跨 worktree
# 复用请显式设 PALEO_QGIS_BUILD_DIR。
_VENDOR_SUBDIR = ("native", "qgis_render_bridge", "build", "qgis-vendor")

VENDOR_BIN = Path(os.environ.get(
    "PALEO_QGIS_BUILD_DIR",
    str(REPO.joinpath(*_VENDOR_SUBDIR)),
)) / "output" / "bin"


def _pyside_dir() -> Path | None:
    try:
        import importlib.util

        spec = importlib.util.find_spec("PySide6")
        locations = list(getattr(spec, "submodule_search_locations", None) or [])
        return Path(locations[0]) if locations else None
    except Exception:
        return None


def prepare(*, quiet: bool = False) -> list[Path]:
    """Idempotent environment preparation; returns dirs added in order.

    Fails loudly (exit) when the vendor dir is missing and no
    ``PALEO_QGIS_BUILD_DIR`` override is set — a silent no-op here makes
    every qgis-marked test skip with no pointer to the cause.
    """
    if not VENDOR_BIN.is_dir() and not os.environ.get("PALEO_QGIS_BUILD_DIR"):
        if not quiet:
            sys.exit(
                f"run_qgis_env: vendor bin not found: {VENDOR_BIN}\n"
                "Set PALEO_QGIS_BUILD_DIR to a completed vendored-QGIS build "
                "(see docs/development/qgis-spatial-authoring-v8/03-decisions.md D6)."
            )
    dirs: list[Path] = []
    for candidate in (VENDOR_BIN, _pyside_dir()):
        if candidate is None or not candidate.is_dir():
            continue
        dirs.append(candidate)
        try:
            os.add_dll_directory(str(candidate))
        except OSError:
            continue
    # PATH order mirrors add order: vendor → PySide6 (single-Qt rule).
    if dirs:
        os.environ["PATH"] = (
            os.pathsep.join(str(d) for d in dirs)
            + os.pathsep
            + os.environ.get("PATH", "")
        )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("PALEO_QGIS_BUILD_DIR", str(VENDOR_BIN.parent.parent))
    return dirs


def main() -> int:
    prepare()
    bootstrap = Path(__file__).resolve().parent / "qgis_env_bootstrap"
    if len(sys.argv) >= 2 and sys.argv[1] == "--probe":
        import qgis_render_bridge
        import qgis_render_bridge.mapstack  # noqa: F401

        print("bridge", qgis_render_bridge.__version__, "OK")
        from PySide6 import QtCore, QtWidgets

        print("QtCore", QtCore.qVersion(), "OK")
        return 0
    env = dict(os.environ)
    # sitecustomize carries the MSVCP pre-pin + loader dirs into every child
    # interpreter (pytest and its subprocesses) BEFORE numpy can squat the
    # CRT slot — PATH inheritance alone is not enough for that race.
    env["PYTHONPATH"] = os.pathsep.join(
        [str(bootstrap)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    return subprocess.call([sys.executable, "-m", "pytest", *sys.argv[1:]], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
