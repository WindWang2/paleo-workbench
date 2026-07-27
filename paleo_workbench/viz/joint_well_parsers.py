"""Parse well head and TD files for joint scene (thin host helpers)."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path

import numpy as np

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz import JointWellId, TimeDepthTable, WellHead  # noqa: E402


def parse_well_heads(
    path: Path | str,
    *,
    identity_map: dict[str, str] | None = None,
) -> list[WellHead]:
    """Parse SMI well heads while reusing persisted source-record identities."""
    source_path = Path(path)
    asset_key = sha256(
        source_path.name.casefold().encode("utf-8")
    ).hexdigest()[:20]
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

    record_bases = [
        _joint_source_record_base(asset_key, record) for record in records
    ]
    base_counts = Counter(record_bases)
    occurrences: Counter[str] = Counter()
    previous = dict(identity_map or {})
    source_keys: list[str] = []
    for base in record_bases:
        occurrences[base] += 1
        source_key = base
        if base_counts[base] > 1:
            source_key = f"{base}|duplicate:{occurrences[base]}"
        source_keys.append(source_key)

    active = {
        source_key: previous[source_key]
        for source_key in source_keys
        if source_key in previous
    }
    unmatched_current: dict[str, list[str]] = {}
    for source_key in source_keys:
        if source_key not in active:
            unmatched_current.setdefault(
                _joint_source_lineage(source_key), []
            ).append(source_key)
    unmatched_previous: dict[str, list[str]] = {}
    for source_key in previous:
        if source_key not in active:
            unmatched_previous.setdefault(
                _joint_source_lineage(source_key), []
            ).append(source_key)
    for lineage, current_keys in unmatched_current.items():
        previous_keys = unmatched_previous.get(lineage, [])
        if len(current_keys) == 1 and len(previous_keys) == 1:
            active[current_keys[0]] = previous[previous_keys[0]]

    wells: list[WellHead] = []
    for record, source_key in zip(records, source_keys, strict=True):
        name, x, y, kb, td, bx, by = record
        well_id = active.get(source_key)
        if well_id is None:
            digest = sha256(source_key.encode("utf-8")).hexdigest()[:24]
            well_id = f"well-head:{digest}"
        active[source_key] = well_id
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
    if identity_map is not None:
        identity_map.clear()
        identity_map.update(active)
    return wells


def _joint_source_record_base(
    asset_key: str,
    record: tuple[str, float, float, float, float, float, float],
) -> str:
    """Build a reorder-safe key whose lineage survives geometry corrections."""
    name, x, y, kb, td, bx, by = record
    geometry = "|".join(
        f"{value:.17g}" for value in (x, y, kb, td, bx, by)
    )
    digest = sha256(geometry.encode("utf-8")).hexdigest()[:20]
    return f"asset:{asset_key}|name:{name}|geometry:{digest}"


def _joint_source_lineage(source_key: str) -> str:
    """Return the asset/name portion used to reconcile a corrected record."""
    return source_key.split("|geometry:", 1)[0]


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
