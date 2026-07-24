"""Parse well head and TD files for joint scene (thin host helpers)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz import TimeDepthTable, WellHead  # noqa: E402


def parse_well_heads(path: Path | str) -> list[WellHead]:
    """Parse SMI ExportWellHead.dat style file."""
    wells: list[WellHead] = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 7:
            continue
        name = parts[0]
        try:
            x, y = float(parts[1]), float(parts[2])
            kb = float(parts[3])
            td = float(parts[4])
            bx, by = float(parts[5]), float(parts[6])
        except ValueError:
            continue
        wells.append(
            WellHead(
                name=name,
                x=x,
                y=y,
                bottom_x=bx,
                bottom_y=by,
                total_depth_m=td,
                kb_m=kb,
            )
        )
    return wells


def parse_td_table(path: Path | str, well_name: str | None = None) -> TimeDepthTable | None:
    """Parse SMI TD dat (TIME, TVDSS, TVD, MD, ...)."""
    times: list[float] = []
    mds: list[float] = []
    name = well_name or Path(path).stem
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            if "Well :" in s or "Well:" in s:
                # # Well : A1
                bits = s.replace(":", " ").split()
                if bits:
                    name = bits[-1]
            continue
        parts = s.split()
        if len(parts) < 4:
            continue
        try:
            t = float(parts[0])
            md = float(parts[3])  # MD column
        except ValueError:
            continue
        times.append(t)
        mds.append(md)
    if len(times) < 2:
        return None
    return TimeDepthTable(
        well_name=name,
        time_ms=np.asarray(times, dtype=np.float64),
        md_m=np.asarray(mds, dtype=np.float64),
    )


def load_td_tables(td_dir: Path | str) -> dict[str, TimeDepthTable]:
    """Load all *.dat TD tables in a directory keyed by well name."""
    root = Path(td_dir)
    out: dict[str, TimeDepthTable] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.glob("*.dat")):
        tbl = parse_td_table(p)
        if tbl is not None:
            out[tbl.well_name] = tbl
            out[p.stem] = tbl
    return out
