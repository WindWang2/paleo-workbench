"""Focused: which provider DLL lacks which export?

Compares, for the few DLLs that matter, the import lists against the exports of
the DLL that actually wins on the app's search path.

Writes .workbuddy/pe_focus.txt
"""

from __future__ import annotations

import os
from pathlib import Path

import pefile

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "pe_focus.txt"
VENDOR_BIN = REPO / "native/qgis_render_bridge/build/qgis-vendor/output/bin"
PYSIDE = REPO / ".venv/Lib/site-packages/PySide6"
DEPS_QT = Path("C:/deps/Qt/6.8.0/msvc2022_64/bin")
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
PYD = REPO / "native/qgis_render_bridge/qgis_render_bridge.cp312-win_amd64.pyd"

SEARCH = [VENDOR_BIN, PYSIDE, SYSTEM32]


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def exports(path: Path) -> set[str]:
    pe = pefile.PE(str(path))          # full load — fast_load dropped the EAT
    names: set[str] = set()
    exp = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if exp is not None:
        for s in exp.symbols:
            if s.name:
                names.add(s.name.decode("ascii", "replace"))
            elif s.ordinal is not None:
                names.add(f"#{s.ordinal}")
    pe.close()
    return names


def imports(path: Path) -> dict[str, set[str]]:
    pe = pefile.PE(str(path))
    out: dict[str, set[str]] = {}
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
        dll = entry.dll.decode("ascii", "replace")
        syms: set[str] = set()
        for imp in entry.imports:
            if imp.name:
                syms.add(imp.name.decode("ascii", "replace"))
            elif imp.ordinal is not None:
                syms.add(f"#{imp.ordinal}")
        out[dll] = syms
    pe.close()
    return out


def find(name: str) -> Path | None:
    low = name.lower()
    for d in SEARCH:
        p = d / name
        if p.is_file():
            return p
        try:
            for e in d.iterdir():
                if e.name.lower() == low and e.is_file():
                    return e
        except OSError:
            pass
    return None


OUT.write_text("", encoding="utf-8")

# 0. sanity: can we even read Qt exports?
qg = PYSIDE / "Qt6Gui.dll"
log(f"sanity: PySide6 Qt6Gui.dll exports = {len(exports(qg))}")
log(f"sanity: does it export ?setPen@QPainter ? "
    f"{'?setPen@QPainter@@QEAAXAEBVQColor@@@Z' in exports(qg)}")
log(f"sanity: deps    Qt6Gui.dll exports = {len(exports(DEPS_QT / 'Qt6Gui.dll'))}")
log("")

# 1. exports diff for the Qt modules both sides ship
log("=== Qt6Core.dll export-set diff (PySide6 vs deps) ===")
a = exports(PYSIDE / "Qt6Core.dll")
b = exports(DEPS_QT / "Qt6Core.dll")
log(f"  PySide6 = {len(a)}   deps = {len(b)}   only-PySide6 = {len(a - b)}   only-deps = {len(b - a)}")
for s in sorted(list(b - a))[:15]:
    log(f"    only-deps     {s}")
for s in sorted(list(a - b))[:15]:
    log(f"    only-PySide6  {s}")
log("")

# 2. per-consumer: imports NOT exported by the winning provider
log("=== unresolved imports on the app search path ===")
consumers = [
    PYD,
    VENDOR_BIN / "qgis_core.dll",
    VENDOR_BIN / "qgis_gui.dll",
    VENDOR_BIN / "qgis_analysis.dll",
    VENDOR_BIN / "Qt6Core5Compat.dll",
    VENDOR_BIN / "qt6keychain.dll",
    VENDOR_BIN / "qca-qt6.dll",
]
for c in consumers:
    if not c.is_file():
        log(f"  SKIP absent {c.name}")
        continue
    bad: list[tuple[str, str]] = []
    for dll, syms in imports(c).items():
        if dll.lower().startswith(("api-ms-win-", "ext-ms-win-")) or dll.lower() in ("python312.dll", "python3.dll"):
            continue
        p = find(dll)
        if p is None:
            bad.append((dll, "<MODULE NOT FOUND>"))
            continue
        exp = exports(p)
        if not exp:
            continue
        for s in syms:
            if s not in exp:
                bad.append((dll, s))
    log(f"  {c.name}: {len(bad)} unresolved")
    for dll, s in bad[:20]:
        log(f"      -> {dll}   {s}")
log("")
log("=== END ===")
