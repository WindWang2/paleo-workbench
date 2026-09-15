"""Resolve WHY the bridge fails with ERROR_PROC_NOT_FOUND.

Walks the PE dependency closure of qgis_render_bridge.pyd over the exact search
path the app provides ([vendor/output/bin, PySide6, System32]) and reports any
imported symbol that no provider DLL exports.

Writes .workbuddy/pe_audit.txt
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pefile

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / ".workbuddy" / "pe_audit.txt"
VENDOR_BIN = REPO / "native/qgis_render_bridge/build/qgis-vendor/output/bin"
PYSIDE = REPO / ".venv/Lib/site-packages/PySide6"
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
PYD = REPO / "native/qgis_render_bridge/qgis_render_bridge.cp312-win_amd64.pyd"

SEARCH = [VENDOR_BIN, PYSIDE, SYSTEM32]
# Resolved by the OS loader itself / by the interpreter, never by us.
SKIP = ("api-ms-win-", "ext-ms-win-", "python312.dll", "python3.dll")


def log(msg: str = "") -> None:
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")


def find(name: str) -> Path | None:
    low = name.lower()
    for d in SEARCH:
        cand = d / name
        if cand.is_file():
            return cand
        # case-insensitive fallback
        try:
            for entry in d.iterdir():
                if entry.name.lower() == low and entry.is_file():
                    return entry
        except OSError:
            continue
    return None


_exports_cache: dict[Path, set[str]] = {}


def exports_of(path: Path) -> set[str]:
    if path in _exports_cache:
        return _exports_cache[path]
    names: set[str] = set()
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]]
        )
        exp = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        if exp is not None:
            for sym in exp.symbols:
                if sym.name:
                    names.add(sym.name.decode("ascii", "replace"))
                elif sym.ordinal is not None:
                    names.add(f"#{sym.ordinal}")
        pe.close()
    except Exception as exc:  # noqa: BLE001
        log(f"    (pefile failed on {path.name}: {exc})")
    _exports_cache[path] = names
    return names


def imports_of(path: Path) -> list[tuple[str, set[str]]]:
    result: list[tuple[str, set[str]]] = []
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        )
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
            dll = entry.dll.decode("ascii", "replace")
            syms: set[str] = set()
            for imp in entry.imports:
                if imp.name:
                    syms.add(imp.name.decode("ascii", "replace"))
                elif imp.ordinal is not None:
                    syms.add(f"#{imp.ordinal}")
            result.append((dll, syms))
        pe.close()
    except Exception as exc:  # noqa: BLE001
        log(f"    (pefile failed on {path.name}: {exc})")
    return result


OUT.write_text("", encoding="utf-8")
log(f"search path: {[str(d) for d in SEARCH]}")
log(f"root       : {PYD.name}")
log("")

visited: set[str] = set()
queue: list[Path] = [PYD]
unresolved: list[tuple[str, str, str]] = []   # (consumer, dll, symbol)
missing_dlls: set[str] = set()
level = 0

while queue and level < 4:
    nxt: list[Path] = []
    for path in queue:
        key = path.name.lower()
        if key in visited:
            continue
        visited.add(key)
        for dll, syms in imports_of(path):
            if dll.lower().startswith(SKIP) or dll.lower() in SKIP:
                continue
            provider = find(dll)
            if provider is None:
                missing_dlls.add(dll)
                continue
            exp = exports_of(provider)
            if not exp:
                continue
            for s in syms:
                if s not in exp:
                    unresolved.append((path.name, dll, s))
            nxt.append(provider)
    queue = nxt
    level += 1

log(f"DLLs walked: {len(visited)}")
log("")
log(f"=== MISSING MODULES ({len(missing_dlls)}) ===")
for m in sorted(missing_dlls):
    log(f"  {m}")
log("")
log(f"=== UNRESOLVED IMPORTS ({len(unresolved)}) ===")
seen_pairs: set[tuple[str, str]] = set()
for consumer, dll, sym in unresolved:
    tag = (consumer, dll)
    if tag not in seen_pairs:
        seen_pairs.add(tag)
        log(f"  {consumer} -> {dll}")
    log(f"      {sym}")
log("")
log("=== END ===")
