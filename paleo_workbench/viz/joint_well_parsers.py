"""Parse well head and TD files for joint scene (thin host helpers)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path
from paleo_workbench.viz.joint_well_identity import (
    SourceWellRecord,
    WellIdentityRegistry,
)

ensure_geoviz_on_path()

from geoviz import JointWellId, TimeDepthTable, WellHead  # noqa: E402


@dataclass(frozen=True)
class ParsedWellHeads:
    wells: list[WellHead]
    identity_registry: WellIdentityRegistry


def parse_well_heads(
    path: Path | str,
    *,
    identity_registry: WellIdentityRegistry,
) -> ParsedWellHeads:
    """Parse SMI well heads and explicitly return the reconciled registry."""
    source_path = Path(path)
    records: list[tuple[str, float, float, float, float, float, float]] = []
    for line in source_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
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
        records.append((name, x, y, kb, td, bx, by))

    source_records = [
        SourceWellRecord(
            name=name,
            geometry=(x, y, kb, td, bx, by),
        )
        for name, x, y, kb, td, bx, by in records
    ]
    well_ids, updated_registry = identity_registry.reconcile(source_records)
    wells: list[WellHead] = []
    for record, well_id in zip(records, well_ids, strict=True):
        name, x, y, kb, td, bx, by = record
        wells.append(
            WellHead(
                name=name,
                x=x,
                y=y,
                bottom_x=bx,
                bottom_y=by,
                total_depth_m=td,
                kb_m=kb,
                id=JointWellId(well_id),
            )
        )
    return ParsedWellHeads(
        wells=wells,
        identity_registry=updated_registry,
    )


def parse_td_table(path: Path | str, well_name: str | None = None) -> TimeDepthTable | None:
    """Parse SMI TD dat (TIME, TVDSS, TVD, MD, ...)."""
    times: list[float] = []
    mds: list[float] = []
    name = well_name or Path(path).stem
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            if "Well :" in s or "Well:" in s:
                # # Well : A1 — the well name is the token right after the
                # colon attached to "Well". "# Well :" (unnamed) and label
                # comments like "# Well label: check" must not hijack the
                # well name (previously bits[-1] picked up "Well"/"check").
                left, sep, right = s.partition(":")
                if sep and left.strip().endswith("Well") and right.strip():
                    name = right.strip().split()[0]
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
    import warnings

    root = Path(td_dir)
    out: dict[str, TimeDepthTable] = {}
    sources: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.glob("*.dat")):
        tbl = parse_td_table(p)
        if tbl is None:
            continue
        for key in dict.fromkeys((tbl.well_name, p.stem)):
            if key in sources:
                # Duplicate key (stem == another table's well name, or two
                # files resolving to the same name): keep the first loaded
                # table instead of silently overwriting it.
                warnings.warn(
                    f"TD 时深表键 '{key}' 冲突：{p.name}（井名 {tbl.well_name}）与 "
                    f"{sources[key].name} 注册到同一键，保留先加载的 {sources[key].name}",
                    UserWarning,
                    stacklevel=2,
                )
                continue
            sources[key] = p
            out[key] = tbl
    return out
