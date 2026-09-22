"""What does the sample project actually contain, layer-wise?

The composite's layer context menu only offers 「复制为草稿…」 on
raw_protected layers and 「开始编辑」 on editable ones. If the project
carries no map layers, the user will find neither — so check before
telling them to look for it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT = Path(r"C:\Users\wangj.KEVIN\projects\data\project_area\project_area.paleo.json")

OUT = ROOT / ".workbuddy" / "project_layers_probe.txt"
_fh = OUT.open("w", encoding="utf-8")


def out(line: str = "") -> None:
    _fh.write(line + "\n")
    _fh.flush()


raw = json.loads(PROJECT.read_text(encoding="utf-8"))
out("=== top-level sections in the .paleo.json ===")
for k, v in raw.items():
    if isinstance(v, list):
        out(f"  {k:28s} list[{len(v)}]")
    elif isinstance(v, dict):
        out(f"  {k:28s} dict  keys={list(v)[:10]}")
    else:
        out(f"  {k:28s} {type(v).__name__}")

# mapping_workspace detail
mw = raw.get("mapping_workspace") or {}
out()
out("=== mapping_workspace ===")
out(f"  current_stage = {mw.get('current_stage')!r}")
members = mw.get("memberships") or []
out(f"  memberships   = {len(members)}")
for m in members[:40]:
    out(f"    - {m}")
maturity = mw.get("artifact_maturity") or {}
out(f"  artifact_maturity keys = {list(maturity)[:20]}")

# any section that looks like a layer collection
out()
out("=== sections that may hold layers ===")
for k, v in raw.items():
    if isinstance(v, list) and v and isinstance(v[0], dict):
        sample = {kk: v[0].get(kk) for kk in list(v[0])[:8]}
        out(f"  {k}: first item keys = {list(v[0])[:12]}")
        out(f"      sample = {sample}")

_fh.close()
print("done")
