#!/usr/bin/env python3
"""Oracle for the VIZ-D xy_scatter well-head preview core (CONV-VIZ V5).

Imports the REAL frozen geoviz engine (geo-viz-engine@08851951,
geoviz.previews.dat._well_head_payload + XYScatterBackend.prepare warnings)
and freezes payloads for the C++ port in
libs/ui_pages_preview/src/well_head_scatter_core.cpp.

Run with a numpy/PySide6-capable interpreter (geoviz imports Qt at module
level; offscreen platform):

    QT_QPA_PLATFORM=offscreen /opt/miniconda3/bin/python3 \
        tools/oracle/generate_viz_d_wellhead_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "geo-viz-engine"))

from geoviz.previews import dat as dat_preview  # noqa: E402
from geoviz.previews.dat import _well_head_payload  # noqa: E402

OUT = REPO_ROOT / "tests" / "cpp" / "viz_d" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

MARKER = "#WellHead File From SMI"


def _num(value):
    if isinstance(value, bool):
        return value
    try:
        value = float(value)
    except (TypeError, ValueError):
        return value
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _payload_dict(payload) -> dict:
    d = asdict(payload) if is_dataclass(payload) else dict(payload)
    out = {}
    for key, value in d.items():
        if key in ("x", "y"):
            out[key] = [_num(v) for v in value]
        elif key in ("names", "uwis"):
            out[key] = list(value)
        elif key == "record_ids" or key == "source_rows":
            out[key] = [int(v) for v in value]
        elif key == "diagnostics":
            # asdict() already nested the dataclasses into dicts.
            get = lambda obj, k: obj[k] if isinstance(obj, dict) else getattr(obj, k)
            out[key] = {
                "total_records": int(get(value, "total_records")),
                "valid_records": int(get(value, "valid_records")),
                "omitted_issue_count": int(get(value, "omitted_issue_count")),
                "issues": [
                    {"source_row": int(get(i, "source_row")), "reason": get(i, "reason")}
                    for i in get(value, "issues")
                ],
            }
        elif key == "coordinate_status":
            get = lambda obj, k: obj[k] if isinstance(obj, dict) else getattr(obj, k)
            out[key] = {
                "source_crs_provenance": get(value, "source_crs_provenance"),
                "coordinate_units_provenance": get(value, "coordinate_units_provenance"),
                "comparison_crs": get(value, "comparison_crs"),
                "comparison_matches_source": get(value, "comparison_matches_source"),
            }
        else:
            out[key] = value
    return out


def case_text(body_lines, header_lines) -> str:
    return "\n".join(header_lines + body_lines) + "\n"


def cases() -> dict:
    out = {}

    def run(case_id, text, **kwargs):
        with tempfile.NamedTemporaryFile("w", suffix=".dat", encoding="utf-8",
                                         delete=False) as handle:
            handle.write(text)
            path = handle.name
        entry = {"text": text, "kwargs": kwargs}
        try:
            payload = _well_head_payload(path, None, **kwargs)
            entry["ok"] = True
            entry["payload"] = _payload_dict(payload)
            # XYScatterBackend.prepare warning list parity.
            warnings = []
            diagnostics = payload.diagnostics
            if diagnostics.skipped_count:
                warnings.append(
                    f"{diagnostics.skipped_count} 行已跳过；"
                    f"有效 {diagnostics.valid_records}/{diagnostics.total_records}"
                )
            if not payload.source_crs:
                warnings.append("SourceCRS 未声明")
            elif payload.coordinate_status.comparison_mismatch:
                warnings.append(
                    f"SourceCRS {payload.source_crs} 与参考 CRS "
                    f"{payload.coordinate_status.comparison_crs} 不同（未转换）"
                )
            if not payload.coordinate_units:
                warnings.append("坐标单位未知")
            entry["warnings"] = warnings
        except Exception as error:  # the C++ side must reproduce these errors
            entry["ok"] = False
            entry["error"] = f"{type(error).__name__}: {error}"
        finally:
            Path(path).unlink()
        out[case_id] = entry

    # 1. basic: marker + declared columns + rows.
    run("basic",
        case_text(['"Alpha One" 100.0 500.0', "Beta 130.0 480.0", "Gamma 120.0 470.0"],
                  [MARKER, "#Name X Y"]))
    # 2. aliases + extras + uwi column.
    run("alias_extras_uwi",
        case_text(["A 1 2 UWI-1 30.0", "B 3 4 UWI-2 31.0"],
                  [MARKER, "#Well BottomX BottomY UWI TD", "#WellName X Y"]))
    # 3. CRS + unit declarations + asset metadata merge.
    run("crs_units",
        case_text(["A 1.5 2.5", "B 3.5 4.5"],
                  [MARKER, "#Name X Y", "#SourceCRS: EPSG:32650", "#X .m", "#Y .m"]),
        source_crs="EPSG:4326", coordinate_units="m", comparison_crs="epsg:32650")
    # 4. bad rows (width mismatch, empty name, non-numeric x) + skipped count.
    run("bad_rows",
        case_text(["A 1 2", " 2 3", "C x 4", "D 5", "E 6 7"],
                  [MARKER, "#Name X Y"]))
    # 5. unit conflict in header -> schema error.
    run("unit_conflict",
        case_text(["A 1 2"], [MARKER, "#Name X Y", "#X .m", "#Y .ft"]))
    # 6. conflicting asset vs declared CRS.
    run("crs_conflict",
        case_text(["A 1 2"], [MARKER, "#Name X Y", "#SourceCRS: EPSG:32650"]),
        source_crs="EPSG:4326")
    # 7. no marker.
    run("no_marker", case_text(["A 1 2"], ["#Name X Y"]))
    # 8. no data rows.
    run("no_data_rows", case_text([], [MARKER, "#Name X Y"]))
    # 9. all rows invalid -> no renderable locations.
    run("all_invalid", case_text(["1 2", "3 4"], [MARKER, "#Name X Y"]))
    # 10. BOM + CRLF + quotes with spaces.
    run("bom_crlf",
        "\ufeff" + "\r\n".join([MARKER, "#Name X Y", '"Quoted Well" 10 20']) + "\r\n")
    # 11. uwi votes conflict -> no uwi (uwis empty).
    run("uwi_conflict",
        case_text(["A 1 2 x", "B 3 4 y"], [MARKER, "#Name X Y UWI", "#Name X Y Other"]))
    # 12. unclosed quote in header -> schema error.
    run("unclosed_quote", case_text(["A 1 2"], [MARKER, '#Name "X Y']))
    return out


def main() -> None:
    fixture = {
        "generator": "tools/oracle/generate_viz_d_wellhead_fixtures.py",
        "engine": "geo-viz-engine@08851951",
        "marker": MARKER,
        "cases": cases(),
    }
    path = OUT / "viz_d_wellhead_oracle.json"
    path.write_text(json.dumps(fixture, indent=1, ensure_ascii=False),
                    encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
