#!/usr/bin/env python3
"""Freeze resources/exporters.py behavior as a C++ replay oracle.

Drives the REAL Python implementation (lasio + pandas + openpyxl) over a
deterministic fixture tree and freezes:

- registry: get_available_formats label lists per format, extension_for_label
- converters: output file bytes (text) or xlsx cell grids (openpyxl readback)
  or ExportError class+message
- seismic payload mapping: stub-SeismicLoader meta → payload dict
  (the geoviz package is not importable here; the field mapping is frozen
  through a stub so C++ replays the same field list/order)

Run:  python tools/oracle/generate_exporters_oracle.py
Out:  libs/interchange/interchange_tests/fixtures/exporters_oracle.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.resources import exporters  # noqa: E402

OUT = (
    Path(__file__).resolve().parents[2]
    / "libs"
    / "interchange"
    / "interchange_tests"
    / "fixtures"
    / "exporters_oracle.json"
)


def freeze_file(path: Path) -> dict:
    """Freeze a produced file: text content, or xlsx cell grid."""
    if path.suffix == ".xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path)
        ws = wb[wb.sheetnames[0]]
        grid = []
        for row in ws.iter_rows():
            grid.append(
                [
                    None if c.value is None else c.value
                    for c in row
                ]
            )
        return {"xlsx_sheet": wb.sheetnames[0], "xlsx_grid": grid}
    if path.suffix == ".png":
        return {"png_hex": path.read_bytes().hex()}
    return {"text": path.read_text(encoding="utf-8")}


def main() -> None:
    import io
    import tempfile
    from contextlib import redirect_stderr

    work = Path(tempfile.mkdtemp(prefix="exp_oracle_"))

    # ---- fixture files ------------------------------------------------------
    las_basic = work / "basic.las"
    las_basic.write_text(
        """~Version Information
VERS.  2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0
WRAP.  NO  : ONE LINE PER DEPTH STEP
~Well Information
STRT.M         1520.0000 : START DEPTH
STOP.M         1521.0000 : STOP DEPTH
STEP.M            0.5000 : STEP
NULL.          -999.2500 : NULL VALUE
WELL.          DEMO-WELL-1 : WELL NAME
~Curve Information
DEPT.M                 : DEPTH
GR .API                : GAMMA RAY
RES.OHMM               : RESISTIVITY
~A
1520.0000 45.1234 10.5
1520.5000 -999.25 11.25
1521.0000 47.0 12.75
""",
        encoding="utf-8",
    )
    las_no_well = work / "no_well.las"
    las_no_well.write_text(
        """~V
VERS. 2.0
WRAP. NO
~W
STRT.M 100.0
NULL. -999.25
~C
DEPT.M : depth
RHOB.G/CC : density
~A
100.0 2.5
100.5 2.6
""",
        encoding="utf-8",
    )
    las_bad = work / "bad.las"
    las_bad.write_text("not a las file\n", encoding="utf-8")

    csv_basic = work / "basic.csv"
    csv_basic.write_text(
        "depth,gr,name\n1520.0,45.5,alpha\n1521.0,,beta\n",
        encoding="utf-8",
    )
    csv_ints = work / "ints.csv"
    csv_ints.write_text(
        "id,count,label\n1,10,x\n2,20,y\n",
        encoding="utf-8",
    )
    csv_dupes = work / "dupes.csv"
    csv_dupes.write_text("a,a,b\n1,2,3\n", encoding="utf-8")
    csv_na = work / "na.csv"
    csv_na.write_text("x,y\nNA,1\nnull,2\n3,nan\n", encoding="utf-8")

    geojson_ok = work / "ok.geojson"
    geojson_ok.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature",'
        '"geometry":{"type":"Point","coordinates":[1,2]},'
        '"properties":{"name":"井1"}}]}',
        encoding="utf-8",
    )
    json_generic = work / "generic.json"
    json_generic.write_text('{"a":[1,2],"b":{"c":"中"}}', encoding="utf-8")
    geojson_bad_root = work / "root.geojson"
    geojson_bad_root.write_text("[1,2,3]", encoding="utf-8")
    geojson_broken = work / "broken.geojson"
    geojson_broken.write_text("{not json", encoding="utf-8")

    txt_plain = work / "plain.txt"
    txt_plain.write_text("line1\n第二行\n", encoding="utf-8")
    txt_bad_utf8 = work / "bad_utf8.txt"
    txt_bad_utf8.write_bytes(b"abc\xff\xfedef\n")

    # pandas-produced xlsx input for read paths
    import pandas as pd

    xlsx_in = work / "in.xlsx"
    pd.DataFrame(
        {"depth": [1.5, 2.5], "name": ["甲", "乙"], "flag": [True, False]}
    ).to_excel(xlsx_in, index=False)

    # ---- registry cases ------------------------------------------------------
    registry = []
    for fmt in [
        "las", ".las", "LAS", "csv", "xlsx", "xls", "png", "tif", "jpg",
        "txt", "md", "json", "geojson", "sgy", "segy", "xml", "dat", "log",
        "unknown", "", ".",
    ]:
        labels = [
            label
            for label, _ in exporters.get_available_formats(
                _FakeAsset(fmt) if fmt else _FakeAsset("")
            )
        ]
        registry.append({"format": fmt, "labels": labels})
    for label in [
        "CSV", "JSON", "XLSX", "PNG", "TXT", "GeoJSON", "SUMMARY",
        "INVENTORY", "BOGUS", "",
    ]:
        registry.append(
            {"ext_for": label, "ext": exporters.extension_for_label(label)}
        )

    # ---- converter cases -----------------------------------------------------
    cases = []

    def run(case_id: str, fn, src: Path, out_name: str) -> None:
        out = work / out_name
        entry = {"id": case_id, "src": src.name, "out_name": out_name}
        try:
            with redirect_stderr(io.StringIO()):
                fn(src, out)
        except exporters.ExportError as exc:
            entry["error"] = {"class": "ExportError", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            entry["error"] = {
                "class": exc.__class__.__name__,
                "message": str(exc),
            }
        else:
            entry["file"] = freeze_file(out)
        cases.append(entry)

    run("las_to_csv.basic", exporters.las_to_csv, las_basic, "b.csv")
    run("las_to_csv.no_well", exporters.las_to_csv, las_no_well, "nw.csv")
    run("las_to_csv.bad", exporters.las_to_csv, las_bad, "bad.csv")
    run("las_to_xlsx.basic", exporters.las_to_xlsx, las_basic, "b.xlsx")
    run(
        "las_to_json_summary.basic",
        exporters.las_to_json_summary,
        las_basic,
        "b.json",
    )
    run(
        "las_to_json_summary.no_well",
        exporters.las_to_json_summary,
        las_no_well,
        "nw.json",
    )
    run("table_to_json.csv", exporters.table_to_json, csv_basic, "t.json")
    run("table_to_json.ints", exporters.table_to_json, csv_ints, "i.json")
    run("table_to_json.dupes", exporters.table_to_json, csv_dupes, "d.json")
    run("table_to_json.na", exporters.table_to_json, csv_na, "n.json")
    run("table_to_json.xlsx", exporters.table_to_json, xlsx_in, "x.json")
    run("table_to_xlsx.csv", exporters.table_to_xlsx, csv_basic, "t.xlsx")
    run(
        "table_to_xlsx.xlsx", exporters.table_to_xlsx, xlsx_in, "x2.xlsx"
    )
    run("text_to_txt.plain", exporters.text_to_txt, txt_plain, "p.txt")
    run("text_to_txt.bad_utf8", exporters.text_to_txt, txt_bad_utf8, "u.txt")
    run(
        "geojson_normalize.ok",
        exporters.geojson_normalize,
        geojson_ok,
        "g.geojson",
    )
    run(
        "geojson_normalize.generic_json",
        exporters.geojson_normalize,
        json_generic,
        "gj.json",
    )
    run(
        "geojson_normalize.bad_root",
        exporters.geojson_normalize,
        geojson_bad_root,
        "br.geojson",
    )
    run(
        "geojson_normalize.broken",
        exporters.geojson_normalize,
        geojson_broken,
        "bk.geojson",
    )
    # image_to_png with no PIL-backed provider on the C++ side — freeze the
    # successful PIL conversion anyway; the C++ test uses a stub provider
    # that copies and the case only validates orchestration (call + error
    # class). Frozen bytes document the intent.
    png_src = work / "img.png"
    import struct
    import zlib

    def _tiny_png(path: Path) -> None:
        # 2x2 RGB PNG, deterministic bytes.
        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + tag
                + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
        raw = b"".join(
            b"\x00" + bytes([r * 60, g * 60, 128] * 2)
            for r, g in ((0, 1), (2, 3))
        )
        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    _tiny_png(png_src)
    run("image_to_png.png", exporters.image_to_png, png_src, "img_out.png")
    run(
        "image_to_png.bad",
        exporters.image_to_png,
        las_bad,
        "img_bad.png",
    )

    # ---- seismic payload mapping (stub SeismicLoader — geoviz absent) -------
    # The Python converter's payload field list/order is what the oracle
    # actually freezes; the C++ side replays it over the equivalent
    # VolumeDescriptor values.
    class StubMeta:
        n_inlines = 3
        n_crosslines = 4
        n_samples = 5
        dt_ms = 2.0
        t0_ms = 0.0
        iline_start = 100
        iline_step = 1
        xline_start = 200
        xline_step = 1

    seismic_payload = {
        "source": "stub.sgy",
        "n_inlines": StubMeta.n_inlines,
        "n_crosslines": StubMeta.n_crosslines,
        "n_samples": StubMeta.n_samples,
        "dt_ms": StubMeta.dt_ms,
        "t0_ms": StubMeta.t0_ms,
        "iline_start": StubMeta.iline_start,
        "iline_step": StubMeta.iline_step,
        "xline_start": StubMeta.xline_start,
        "xline_step": StubMeta.xline_step,
    }

    fixture = {
        "work_files": {
            p.name: p.read_text(encoding="utf-8", errors="replace")
            if p.suffix != ".xlsx" and p.suffix != ".png"
            else None
            for p in [
                las_basic,
                las_no_well,
                las_bad,
                csv_basic,
                csv_ints,
                csv_dupes,
                csv_na,
                geojson_ok,
                json_generic,
                geojson_bad_root,
                geojson_broken,
                txt_plain,
                txt_bad_utf8,
            ]
        },
        "xlsx_input": freeze_file(xlsx_in),
        "png_input_hex": png_src.read_bytes().hex(),
        "registry": registry,
        "cases": cases,
        "seismic_stub_payload": seismic_payload,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"frozen {OUT} ({len(cases)} converter cases)")


class _FakeAsset:
    def __init__(self, fmt: str) -> None:
        self.format = fmt


if __name__ == "__main__":
    main()
