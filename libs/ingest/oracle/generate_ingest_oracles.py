#!/usr/bin/env python3
"""CONV-19 oracle generator — freeze real-Python parse results for libs/ingest.

Every expected value in the emitted JSON comes from executing the REAL
implementation in this repository (no hand-written expectations). The geoviz
cascade (registry/well_log_parsers -> viz.__init__ -> PySide6) is bridged by
stand-in *parent* modules (decision D2 in docs/development/
cpp-conversion-swarm-20/ledgers/19-decisions.md): the real module source is
still what runs; the stand-ins only satisfy import-time symbols that the
ported code paths never call.

Run:  python3 libs/ingest/oracle/generate_ingest_oracles.py
Out:  libs/ingest/oracle/fixtures/ingest_oracle.json
"""
from __future__ import annotations

import base64
import importlib.util
import json
import shlex
import struct
import sys
import tempfile
import types
import warnings
import zipfile
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import sys as _sys  # archived-reference shim (legacy/python_reference)

from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'legacy' / 'python_reference' / 'product'))

import paleo_workbench  # noqa: E402

if not Path(paleo_workbench.__file__).resolve().is_relative_to(REPO):
    raise SystemExit(
        f"paleo_workbench resolved to {paleo_workbench.__file__}, not this worktree"
    )

# --- D2 stand-in parents for the geoviz cascade ----------------------------
_viz = types.ModuleType("paleo_workbench.viz")
_viz.__path__ = []  # namespace-package marker; real __init__ needs PySide6
sys.modules.setdefault("paleo_workbench.viz", _viz)
_wla = types.ModuleType("paleo_workbench.viz.well_log_api")


def _fast_las_parse_data(*_a, **_k):  # pragma: no cover - never called here
    raise RuntimeError("well_log native backend unavailable in oracle env")


_wla.fast_las_parse_data = _fast_las_parse_data
_wla.HAS_CPP_WELL_LOG = False
sys.modules.setdefault("paleo_workbench.viz.well_log_api", _wla)


def _load_real(module_name: str, file: Path):
    spec = importlib.util.spec_from_file_location(module_name, file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --- real modules -----------------------------------------------------------
from paleo_workbench.resources import classifier, io_registry  # noqa: E402
from paleo_workbench.resources.preview_parsers import (  # noqa: E402
    document_parsers as dp,
)
from paleo_workbench.resources.preview_parsers import (  # noqa: E402
    office_parsers as op,
)
from paleo_workbench.resources.preview_parsers import (  # noqa: E402
    table_parsers as tp,
)
from paleo_workbench.resources.preview_parsers.models import (  # noqa: E402
    PreviewResult,
)
from paleo_workbench.resources import preview_settings as ps_mod  # noqa: E402
from paleo_workbench.resources import well_location_xml as wlx  # noqa: E402
from paleo_workbench.resources import well_log_xml as wlxml  # noqa: E402
from paleo_workbench.resources import well_tops_parser as wtp  # noqa: E402

REG = _load_real(
    "paleo_workbench.resources.preview_parsers.registry",
    REPO / "paleo_workbench/resources/preview_parsers/registry.py",
)
WLP = _load_real(
    "paleo_workbench.resources.preview_parsers.well_log_parsers",
    REPO / "paleo_workbench/resources/preview_parsers/well_log_parsers.py",
)

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)

out: dict = {}


def f2s(value):
    """Floats travel as Python-repr strings so NaN/inf survive JSON (D14)."""
    if value is None:
        return None
    return repr(float(value))


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# constants group — frozen tables the C++ side embeds
# ---------------------------------------------------------------------------
MODELS = sys.modules["paleo_workbench.resources.preview_parsers.models"]
out["constants"] = {
    "text_formats": sorted(MODELS.TEXT_FORMATS),
    "table_formats": sorted(MODELS.TABLE_FORMATS),
    "excel_formats": sorted(MODELS.EXCEL_FORMATS),
    "image_formats": sorted(MODELS.IMAGE_FORMATS),
    "pdf_formats": sorted(MODELS.PDF_FORMATS),
    "las_formats": sorted(MODELS.LAS_FORMATS),
    "segy_formats": sorted(MODELS.SEGY_FORMATS),
    "markdown_formats": sorted(MODELS.MARKDOWN_FORMATS),
    "html_formats": sorted(MODELS.HTML_FORMATS),
    "json_formats": sorted(MODELS.JSON_FORMATS),
    "geotiff_formats": sorted(MODELS.GEOTIFF_FORMATS),
    "audio_formats": sorted(MODELS.AUDIO_FORMATS),
    "video_formats": sorted(MODELS.VIDEO_FORMATS),
    "max_text_preview_bytes": MODELS.MAX_TEXT_PREVIEW_BYTES,
    "max_table_rows": MODELS.MAX_TABLE_ROWS,
    "max_table_columns": MODELS.MAX_TABLE_COLUMNS,
    "max_json_parse_bytes": MODELS.MAX_JSON_PARSE_BYTES,
    "json_array_collapse_threshold": MODELS.JSON_ARRAY_COLLAPSE_THRESHOLD,
    "max_archive_names": op.MAX_ARCHIVE_NAMES,
    "max_embedded_image_bytes": op.MAX_EMBEDDED_IMAGE_BYTES,
    "max_central_directory_bytes": op.MAX_CENTRAL_DIRECTORY_BYTES,
    "max_central_entries": op.MAX_CENTRAL_ENTRIES,
    "max_central_name_bytes": op.MAX_CENTRAL_NAME_BYTES,
    "spreadsheetml_namespace": op._SPREADSHEETML_NAMESPACE,
    "geotiff_max_read_px": dp._GEOTIFF_MAX_READ_PX,
    "max_records_well_location": wlx._MAX_RECORDS,
    "max_elements_well_log_xml": wlxml._MAX_ELEMENTS,
    "spreadsheet_names_well_log": sorted(wlxml._SPREADSHEET_NAMES),
    "type_labels": io_registry.TYPE_LABELS,
    "preferred_import_extensions": sorted(io_registry.PREFERRED_IMPORT_EXTENSIONS),
    "role_by_type": io_registry.ROLE_BY_TYPE,
    "convert_label_ext": io_registry.CONVERT_LABEL_EXT,
    "preview_integer_ranges": {k: list(v) for k, v in ps_mod._INTEGER_RANGES.items()},
    "preview_boolean_fields": sorted(ps_mod._BOOLEAN_FIELDS),
}

# ---------------------------------------------------------------------------
# well_tops — synthetic + real repo fixtures
# ---------------------------------------------------------------------------
well_tops_cases = []


def tops_case(name: str, text: str):
    import paleo_workbench.resources.well_tops_parser as m

    # parse via the real function through a temp file (the public entry is
    # path-based; bytes come straight from the recorded text)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "case.dat"
        p.write_text(text, encoding="utf-8")
        rows = m.parse_well_tops(p)
    well_tops_cases.append(
        {
            "name": name,
            "text": text,
            "expected": [
                {
                    "well_name": r.well_name,
                    "top_name": r.top_name,
                    "md": f2s(r.md),
                    "tvd": f2s(r.tvd),
                }
                for r in rows
            ],
        }
    )


tops_case(
    "basic_smi",
    "#WellTops File From SMI\r\n"
    "#WellName    Name         MD           X            Y            Z            TVD          Time(ms)    \r\n"
    "A1           X            850.000      5288.670     8219.940     -850.000     850.000      -99999.000  \r\n"
    "A1           C1           1164.000     5288.670     8219.940     -1164.000    1164.000     -99999.000  \r\n"
    "A10          D21          1482.000     10499.930    11460.655    -1430.278    1430.278     -99999.000  \r\n",
)
tops_case(
    "garbage_rows",
    "# comment\n\nshort row\nA1 BAD_DEPTH notanumber 1 2 3 4 5\nA1 C1 1164.0 0 0 0 1164.0 0\n",
)
tops_case("missing_tvd", "A1 C1 1164.0\n")
tops_case("only_comments", "# only comments\n")
tops_case("empty", "")
tops_case("bad_tvd_value", "A1 C1 100 0 0 0 notafloat 0\nA1 D2 200 0 0 0 250.5 0\n")
tops_case("nan_md", "A1 X nan 0 0 0 1.5\nB2 Y inf 0 0 0\n")
tops_case("underscore_float", "A1 X 1_000.5 0 0 0 2_000\n")
tops_case("crlf_mixed", "A T1 1 0 0 0 10\rB T2 2 0 0 0 20\r\nC T3 3 0 0 0\n")
tops_case("two_token_row", "A1 T1\n")
# #1386: Unicode whitespace separators — str.split() treats U+3000
# (ideographic space, emitted by CJK editors/Excel) and U+00A0 (NBSP) as
# whitespace; an ASCII-only splitter silently drops these rows.
tops_case(
    "unicode_space_separators",
    "A1\u3000X\u3000850.0\u30000\u30000\u30000\u3000850.0\u30000\n"
    "B2\u00a0Y\u00a01164.5\u00a01\u00a02\u00a03\u00a01164.5\u00a00\n"
    "C3\u3000Z\u30002000.0\n",
)
tops_case("nbsp_separator", "A4\u00a0W\u00a0700.25\u00a00\u00a00\u00a00\u00a0700.25\u00a00\n")
for fixture in ("DC.dat", "ExportWellHead.dat", "A1_td.dat"):
    src = REPO / "tests/fixtures/realdata" / fixture
    rows = wtp.parse_well_tops(src)
    well_tops_cases.append(
        {
            "name": f"realdata_{fixture}",
            "text": src.read_text(encoding="utf-8", errors="replace"),
            "expected": [
                {
                    "well_name": r.well_name,
                    "top_name": r.top_name,
                    "md": f2s(r.md),
                    "tvd": f2s(r.tvd),
                }
                for r in rows
            ],
        }
    )
out["well_tops"] = well_tops_cases

# ---------------------------------------------------------------------------
# well_location_xml
# ---------------------------------------------------------------------------
wlx_cases = []


def wlx_case(name: str, xml: str):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "case.xml"
        p.write_text(xml, encoding="utf-8")
        records, warns = wlx.extract_well_locations_xml(p)
        claimed = wlx.is_well_location_xml(p)
    wlx_cases.append(
        {
            "name": name,
            "xml": xml,
            "expected": {
                "records": [
                    {
                        "name": r.name,
                        "x": f2s(r.x),
                        "y": f2s(r.y),
                        "z": f2s(r.z),
                        "uwi": r.uwi,
                        "source_crs": r.source_crs,
                    }
                    for r in records
                ],
                "warnings": warns,
                "is_well_location": claimed,
            },
        }
    )


wlx_case(
    "well_locations_root",
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<WellLocations crs="EPSG:4326">\n'
    "  <Well><WellName>REF-01</WellName><X>120.0</X><Y>30.0</Y></Well>\n"
    "  <Well><WellName>REF-02</WellName><X>121.0</X><Y>31.0</Y></Well>\n"
    "</WellLocations>\n",
)
wlx_case(
    "no_crs_untransformed",
    "<WellLocations><Well><WellName>UNKNOWN-CRS</WellName><X>120</X><Y>30</Y>"
    "</Well></WellLocations>",
)
wlx_case(
    "spreadsheetml_delivery",
    '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">\n'
    "  <Worksheet><Table>\n"
    "    <Row><Cell><Data>井号</Data></Cell><Cell><Data>X</Data></Cell>"
    "<Cell><Data>Y</Data></Cell></Row>\n"
    "    <Row><Cell><Data>REF-S</Data></Cell><Cell><Data>120.0</Data></Cell>"
    "<Cell><Data>30.0</Data></Cell></Row>\n"
    "  </Table></Worksheet>\n</Workbook>\n",
)
wlx_case(
    "spreadsheetml_with_z_uwi",
    '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
    "<Worksheet><Table>"
    "<Row><Cell><Data>井名</Data></Cell><Cell><Data>X坐标</Data></Cell>"
    "<Cell><Data>北坐标</Data></Cell><Cell><Data>井口高程</Data></Cell>"
    "<Cell><Data>坐标系</Data></Cell></Row>"
    "<Row><Cell><Data>W-1</Data></Cell><Cell><Data> 500000.25 </Data></Cell>"
    "<Cell><Data>3</Data></Cell><Cell><Data>12.5</Data></Cell>"
    "<Cell><Data>EPSG:4547</Data></Cell></Row>"
    "<Row><Cell><Data>W-2</Data></Cell><Cell><Data></Data></Cell>"
    "<Cell><Data>notfloat</Data></Cell></Row>"
    "</Table></Worksheet></Workbook>",
)
wlx_case(
    "generic_points_not_wells",
    '<root><point><name>Spring</name><x>1</x><y>2</y></point></root>',
)
wlx_case(
    "well_child_plain_name",
    '<data><well><name>P-1</name><x>5</x><y>6</y><z>7</z></well></data>',
)
wlx_case(
    "attrib_overrides_child_text",
    '<r><well x="9"><x>1</x><y>2</y></well></r>',
)
wlx_case(
    "dedup_same_name_xy",
    "<r><well><name>D</name><x>1</x><y>2</y></well>"
    "<well><name>D</name><x>1</x><y>2</y></well>"
    "<well><name>D</name><x>1</x><y>3</y></well></r>",
)
wlx_case(
    "root_crs_inherited",
    '<wells crs="EPSG:2343"><well><wellname>A</wellname><easting>1</easting>'
    "<northing>2</northing></well></wells>",
)
wlx_case(
    "lon_lat_keys_do_not_declare_crs",
    '<r><well><uwi>U-1</uwi><longitude>120.5</longitude><latitude>-30.25</latitude>'
    "</well></r>",
)
wlx_case(
    "namespaced_tags",
    '<ns:wells xmlns:ns="urn:x"><ns:well><ns:wellname>NS-1</ns:wellname>'
    "<ns:x>3</ns:x><ns:y>4</ns:y></ns:well></ns:wells>",
)
wlx_case(
    "empty_and_malformed",
    "<not xml at all",
)
wlx_case(
    "bom_prefixed_delivery",
    "\ufeff<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<WellLocations crs=\"EPSG:4326\">\n"
    "  <Well><WellName>B-1</WellName><X>1</X><Y>2</Y></Well>\n"
    "</WellLocations>\n",
)
out["well_location_xml"] = wlx_cases

# ---------------------------------------------------------------------------
# well_log_xml
# ---------------------------------------------------------------------------
wlog_cases = []


def wlog_case(name: str, xml: str):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "case.xml"
        p.write_text(xml, encoding="utf-8")
        result = wlxml.is_well_log_xml(p)
    wlog_cases.append({"name": name, "xml": xml, "expected": bool(result)})


WITSML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<WITSMLComposite xmlns="http://www.witsml.org/schemas/1series">\n'
    "  <log>\n    <nameWell>A11</nameWell>\n"
    "    <logCurveInfo><mnemonic>DEPT</mnemonic><unit>m</unit></logCurveInfo>\n"
    "    <logCurveInfo><mnemonic>GR</mnemonic><unit>gAPI</unit></logCurveInfo>\n"
    "    <logData><data>1000.0, 45.2</data><data>1000.125, 48.5</data></logData>\n"
    "  </log>\n</WITSMLComposite>\n"
)
wlog_case("witsml_composite", WITSML)
wlog_case(
    "log_only_missing_pieces",
    '<r><log><data>1</data></log></r>',
)
wlog_case(
    "spreadsheet_named_log_sheet",
    '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
    'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
    '<Worksheet ss:Name="测井曲线"><Table><Row><Cell><Data>x</Data></Cell></Row>'
    "</Table></Worksheet></Workbook>",
)
wlog_case(
    "ordinary_spreadsheet",
    '<Workbook><Worksheet Name="普通资料"><Table><Row><Cell><Data>a</Data></Cell>'
    "</Row></Table></Worksheet></Workbook>",
)
wlog_case("plain_xml", "<root><value>plain</value></root>")
wlog_case("bom_witsml", "\ufeff" + WITSML)
wlog_case("empty_file", "")
wlog_case("malformed", "<log><logCurveInfo><logData>")
wlog_case(
    "witsml_substring_root_only",
    '<witsmlLogin><logCurveInfo><x/></logCurveInfo><logData><d/></logData></witsmlLogin>',
)
out["well_log_xml"] = wlog_cases

# ---------------------------------------------------------------------------
# classifier (pure path) + classify_import_path (content)
# ---------------------------------------------------------------------------
cls_cases = []
_PATHS = [
    "well_a.las", "A1.Las", "line_01.sgy", "horizon.segy", "200P_seismic.SGY",
    "td/table.dat", "std/table.dat", "std.dat", "BitDepths/x.dat",
    "时深/table.dat", "层位/top.dat", "井分层/well.dat",
    "井位/ExportWellHead.dat", "wells/wellhead_x.dat", "misc/C6.dat", "x.dat",
    "book.xlsx", "old.xls", "well_log_A11.xml", "curves/测井/d.xml",
    "plain.xml", "list/井曲线/a.xml", "a.csv", "report.pdf", "deck.ppt",
    "a.docx", "legacy.doc", "image.tif", "p.jpg", "p.jpeg", "b.bmp", "r.png",
    "相图_reference.dfb", "相图.bin", "综合柱状图.WLP", "w.wlp", "bundle.zip",
    "notes.md", "n.markdown", "r.html", "r.htm", "clip.wav", "song.mp3",
    "clip.mp4", "v.mov", "looks-like-zip.bin", "noext", "config.json",
    "facies_map.json", "paleo.json", "geothing.json", "map.geojson",
    "井曲线/a.LAS", "v.webm", "v.mkv", "v.avi", "a.flac", "a.ogg", "a.m4a",
]
for rel in _PATHS:
    t, f, s = classifier.classify_path(Path(rel))
    cls_cases.append({"name": f"path:{rel}", "path": rel, "expected": [t, f, s]})
out["classify_path"] = cls_cases

cls_import_cases = []
_IMPORT_XMLS = {
    "regional_witsml": (
        "<WITSMLComposite><log><nameWell>REF-1</nameWell>\n"
        "<logCurveInfo><mnemonic>DEPT</mnemonic></logCurveInfo>\n"
        "<logCurveInfo><mnemonic>GR</mnemonic></logCurveInfo>\n"
        "<logData><data>1000,40</data><data>1001,41</data></logData>\n"
        "</log></WITSMLComposite>"
    ),
    "ordinary_spreadsheet_xml": (
        '<Workbook><Worksheet Name="普通资料"><Table>\n'
        "<Row><Cell><Data>名称</Data></Cell><Cell><Data>值</Data></Cell></Row>\n"
        "<Row><Cell><Data>A</Data></Cell><Cell><Data>1</Data></Cell></Row>\n"
        "</Table></Worksheet></Workbook>"
    ),
    "well_locations_xml": (
        '<WellLocations crs="EPSG:4326">\n'
        "  <Well><WellName>REF-01</WellName><X>120.0</X><Y>30.0</Y></Well>\n"
        "</WellLocations>"
    ),
    "broken_xml": "<a><b></a>",
    "plain_generic_xml": "<root><value>x</value></root>",
}
for cname, content in _IMPORT_XMLS.items():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "regional_delivery.xml"
        p.write_text(content, encoding="utf-8")
        t, f, s = classifier.classify_import_path(p)
    cls_import_cases.append(
        {"name": cname, "filename": "regional_delivery.xml",
         "content": content, "expected": [t, f, s]}
    )
with tempfile.TemporaryDirectory() as td:
    las = Path(td) / "w.las"
    las.write_text("~V\n", encoding="utf-8")
    t, f, s = classifier.classify_import_path(las)
cls_import_cases.append(
    {"name": "las_file", "filename": "w.las", "content": "~V\n",
     "expected": [t, f, s]}
)
out["classify_import"] = cls_import_cases

# ---------------------------------------------------------------------------
# project paths — traversal / relativize (machine paths via <TMP> marker)
# ---------------------------------------------------------------------------
pp_cases = []
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    proj = root / "demo.paleo.json"
    proj_dir = root / "demo.paleo.json.artifacts"
    proj_dir.mkdir()
    (proj_dir / "data").mkdir()
    inside = proj_dir / "data" / "a.las"
    inside.write_text("~V\n", encoding="utf-8")
    outside_dir = root / "outside"
    outside_dir.mkdir()
    outside = outside_dir / "secret.txt"
    outside.write_text("x", encoding="utf-8")

    def mark(value: str) -> str:
        return value.replace(str(root), "<TMP>")

    from paleo_workbench.project.paths import (
        is_within_directory,
        relativize_path,
        resolve_project_path,
        safe_file_stat,
    )

    def rel_case(name, path, project):
        stored, external = relativize_path(path, Path(project))
        pp_cases.append(
            {"name": name, "op": "relativize", "path": mark(str(path)),
             "project": mark(str(project)), "expected": [mark(stored), external]}
        )

    def resolve_case(name, path, project, error_expected):
        try:
            got = resolve_project_path(path, Path(project))
            pp_cases.append(
                {"name": name, "op": "resolve", "path": mark(str(path)),
                 "project": mark(str(project)), "expected": [mark(got), None]}
            )
        except Exception as exc:  # noqa: BLE001 - the class name is the oracle
            pp_cases.append(
                {"name": name, "op": "resolve", "path": mark(str(path)),
                 "project": mark(str(project)),
                 "expected": [None, exc.__class__.__name__]}
            )

    rel_case("inside_relative", "data/a.las", proj)
    rel_case("dot_relative", "./data/a.las", proj)
    rel_case("absolute_inside", str(inside), proj)
    rel_case("absolute_outside", str(outside), proj)
    rel_case("escape_relative", "../outside/secret.txt", proj)
    resolve_case("resolve_inside", "data/a.las", proj, False)
    resolve_case("resolve_absolute", str(inside), proj, False)
    resolve_case("resolve_escape", "../outside/secret.txt", proj, True)
    resolve_case("resolve_empty", "   ", proj, True)
    for name, (path, directory), expected in [
        ("within_true", (inside, proj_dir), True),
        ("within_false", (outside, proj_dir), False),
        ("within_dir_itself", (proj_dir, proj_dir), True),
    ]:
        pp_cases.append(
            {"name": name, "op": "is_within", "path": mark(str(path)),
             "project": mark(str(directory)), "expected": [expected, None]}
        )
    st = safe_file_stat(inside)
    pp_cases.append(
        {"name": "safe_stat_size", "op": "stat",
         "path": mark(str(inside)), "project": mark(str(proj)),
         "expected": [st[0], None]}
    )
    pp_cases.append(
        {"name": "safe_stat_missing", "op": "stat", "path": "<TMP>/nope.txt",
         "project": "demo.paleo.json", "expected": [None, None]}
    )
out["project_paths"] = pp_cases

# ---------------------------------------------------------------------------
# text / dat / csv / markdown / json previews
# ---------------------------------------------------------------------------
prev_cases = {"text": [], "dat": [], "csv": [], "markdown": [], "json": []}


def mask_tmp(obj, td):
    """Replace the ephemeral tmp dir prefix with <TMP> so expectations are
    machine-independent; the C++ test substitutes its own tmp back."""
    marker = str(td) + "/"
    def _walk(o):
        if isinstance(o, str):
            return o.replace(marker, "<TMP>/")
        if isinstance(o, list):
            return [_walk(v) for v in o]
        if isinstance(o, dict):
            return {k: _walk(v) for k, v in o.items()}
        return o
    return _walk(obj)


def project_result(r: PreviewResult, include_bytes: bool = False):
    data = {
        "mode": r.mode,
        "title": r.title,
        "path": r.path,
        "format": r.format,
        "status": r.status,
        "type_label": r.type_label,
        "message": r.message,
        "warning": r.warning,
        "text": r.text,
        "truncated": r.truncated,
        "rich_html": r.rich_html,
        "media_path": r.media_path,
        "table_headers": list(r.table_headers),
        "table_rows": [list(row) for row in r.table_rows],
        "summary_rows": [list(row) for row in r.summary_rows],
        "sheets": list(r.sheets),
        "data_headers": list(r.data_headers),
        "data_rows": [list(row) for row in r.data_rows],
        "json_truncated": r.json_truncated,
        "json_ok": r.json_payload is not None,
        "estimated_bytes": r.estimated_bytes,
        "visualization_available": r.visualization_available,
        "image_bytes_b64": b64(r.image_bytes or b"") if include_bytes else None,
        "revision": _rev(r.revision),
    }
    return data


def _rev(rev):
    if rev is None:
        return None
    if isinstance(rev, tuple) and len(rev) == 2 and all(
            isinstance(v, int) for v in rev):
        # bare (size, mtime_ns) stat tuple: freeze the size only (D13)
        return [["stat", rev[0]]]
    proj = []
    for item in rev:
        if isinstance(item, tuple):
            proj.append(["stat", item[0]])  # size only; mtime not frozen (D13)
        else:
            proj.append(item)
    return proj


def preview_case(group, name, filename, raw, fmt, rtype="document",
                 status="parsed", **settings_kw):
    base = ps_mod.PreviewSettings.defaults()
    settings = replace(base, **settings_kw) if settings_kw else base
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / filename
        p.write_bytes(raw)
        res = _resource(str(p), filename, fmt, rtype, status)
        if group == "csv":
            result = tp.table_preview(res, "\t" if fmt == "tsv" else ",", settings)
        elif group == "text":
            result = tp.text_preview(res, settings)
        elif group == "dat":
            result = tp.dat_preview(res, settings)
        elif group == "markdown":
            result = dp.markdown_rich_preview(res, settings)
        elif group == "json":
            result = dp.json_preview(res, settings)
    prev_cases[group].append(
        {
            "name": name,
            "filename": filename,
            "bytes_b64": b64(raw),
            "format": fmt,
            "type": rtype,
            "status": status,
            "settings": {k: getattr(settings, k) for k in
                         ("text_limit_kib", "table_max_rows", "table_max_columns",
                          "json_limit_mib")},
            "expected": mask_tmp(project_result(result), td),
        }
    )


def _resource(path, name, fmt, rtype, status, resource_id=None):
    from paleo_workbench.project.models import ResourceItem

    return ResourceItem(name=name, path=path, type=rtype, format=fmt,
                        status=status, id=resource_id or "res-oracle")


preview_case("text", "plain_txt", "a.txt", "hello world\nsecond line".encode(), "txt", "document")
preview_case("text", "bom_txt", "bom.txt", b"\xef\xbb\xbfhello world\nsecond line", "txt", "text", "ready",
             text_limit_kib=16)
preview_case("text", "ascii_hi_pb", "hi.bin", b"x" * 300, "log", "document",
             text_limit_kib=16)
preview_case("csv", "simple_csv", "t.csv", "Name,X\nalpha,1\nbeta,2\n".encode(), "csv", "tabular")
preview_case("csv", "bom_csv", "bom.csv", "﻿Name,X\nalpha,1\nbeta,2\n".encode("utf-8"), "csv", "tabular")
preview_case("csv", "bom_tsv", "bom.tsv", "﻿Name\tX\nalpha\t1\nbeta\t2\n".encode("utf-8"), "tsv", "tabular")
preview_case("csv", "quoted_newlines", "qn.csv",
             b'name,note\nalpha,"line one\nline two"\nbeta,plain', "csv", "tabular")
preview_case("csv", "escaped_quotes", "eq.csv",
             b'h1,h2\n"a","b""c"\n', "csv", "tabular")
preview_case("csv", "quote_then_junk", "qj.csv",
             b'h1,h2\n"a"b,c\n', "csv", "tabular")
preview_case("csv", "blank_lines", "blank.csv",
             b"a,b\n\nc,d\n", "csv", "tabular")
preview_case("csv", "eof_open_quote", "eofq.csv",
             b'a,"b', "csv", "tabular")
preview_case("csv", "leading_blanks", "lb.csv",
             b"\n\na\n", "csv", "tabular")
preview_case("csv", "big_field", "big.csv",
             b"h1,h2\nalpha,\"" + b"x" * 200_000 + b"\"\n", "csv", "tabular")
preview_case("csv", "too_many_cols_rows", "wide.csv",
             ("\n".join([",".join(f"c{i}" for i in range(43))] +
                        [",".join(str(c) for c in range(43)) for _ in range(205)])).encode(),
             "csv", "tabular")
preview_case("csv", "row_budget_break", "rows.csv",
             ("\n".join(f"r{i}" for i in range(210)) + "\n").encode(), "csv",
             "tabular", table_max_rows=20)
preview_case("dat", "structured_dat", "wells.dat",
             "\ufeff#WellHead File From SMI\n#Name X Y\n\"Alpha One\" 100.0 500.0\nBeta 130.0 480.0\n".encode("utf-8"),
             "dat", "well_head")
preview_case("dat", "unstructured_dat", "notes.dat",
             "free form note\nsecond line has different width\n".encode(), "dat", "document")
preview_case("dat", "smi_header_excluded", "dc.dat",
             (Path("tests/fixtures/realdata/DC.dat").read_bytes()
              if (REPO / "tests/fixtures/realdata/DC.dat").exists()
              else b"#WellTops File From SMI\n#WellName Name MD\nA1 T 100 1 2 3 4\n"),
             "dat", "well_stratification")
big_rows = b"1 2            \n" * 1000
preview_case("dat", "byte_truncated_partial_row", "bounded.dat",
             big_rows + b"\n" * (16 * 1024 - len(big_rows) - 4) + b"999 8\n3 4\n",
             "dat", "well_head", text_limit_kib=16, table_max_rows=2000)
preview_case("dat", "limit_ends_on_newline", "newline.dat",
             (b"1 2            \n" * 1024) + b"3 4\n",
             "dat", "well_head", text_limit_kib=16, table_max_rows=2000)
preview_case("dat", "only_hash_line", "hash.dat",
             b"# H1 H2\n####\n1 2\n3 4\n", "dat", "tabular")
preview_case("dat", "lone_cr_lines", "cr.dat",
             b"a b\rc d\re f\r", "dat", "tabular")
preview_case("dat", "quoted_shlex", "q.dat",
             b"# H1 H2\na 'b c' \"d\\\"e\" f\n", "dat", "tabular")
preview_case("dat", "unterminated_quote_falls_back", "uq.dat",
             b'a "unterminated\nb c\n', "dat", "tabular")
preview_case("dat", "ragged_falls_back", "ragged.dat",
             b"a b c\n1 2\n", "dat", "tabular")
preview_case("markdown", "headings_lists", "notes.md",
             "# Title\n\n- one\n- two\n\n1. first\n2. second\n\nSome **bold** text.".encode(),
             "md", "document")
preview_case("markdown", "bom_heading", "bom.md",
             "﻿# Title\n\nbody text".encode("utf-8"), "md", "document")
preview_case("markdown", "escape_and_code", "esc.md",
             "# T\n\n<script>x</script> & <b>\n\n```\ncode <line>\n```".encode(),
             "md", "document")
preview_case("markdown", "unclosed_fence", "uc.md",
             "a\n\n```\nunclosed".encode(), "markdown", "document")
preview_case("markdown", "list_type_switch", "ls.md",
             "- a\n1. b\n- c\n".encode(), "md", "document")
preview_case("markdown", "truncated", "large.md",
             ("# Title\n\n- one\n\n<script>x</script>\n" * 10000).encode(),
             "md", "document")
preview_case("json", "object", "c.json", b'{"a": 1, "b": [1,2,3]}', "json", "document")
preview_case("json", "bom_json", "bom.json",
             "﻿{\"a\": 1, \"b\": [1, 2]}".encode("utf-8"), "json", "document")
preview_case("json", "geojson", "f.geojson", b'{"type":"FeatureCollection","features":[]}',
             "geojson", "document")
preview_case("json", "nan_infinity", "nan.json",
             b'{"a": NaN, "b": [Infinity, -Infinity]}', "json", "document")
preview_case("json", "corrupt", "bad.json", b"{ not json", "json", "document")
preview_case("json", "truncated_prefix_parses", "big.json",
             b'{"a": 1, "b": [1, 2, 3]}\n' + b" " * (1024 * 1024 + 2),
             "json", "document", json_limit_mib=1)
preview_case("json", "truncated_prefix_unparsable", "bad.json",
             b'{"a": ' + b"1" * (1024 * 1024 + 2), "json", "document",
             json_limit_mib=1)
preview_case("json", "empty", "e.json", b"", "json", "document")
preview_case("json", "replacement_decode", "rep.json",
             b'{"a": "\xe4\xbd"}', "json", "document")
out["previews"] = prev_cases

# ---------------------------------------------------------------------------
# spreadsheetml_preview
# ---------------------------------------------------------------------------
ss_cases = []


def ss_case(name: str, raw: bytes, **limits):
    kwargs = {
        "max_text_bytes": limits.get("max_text_bytes", 256 * 1024),
        "max_rows": limits.get("max_rows", 200),
        "max_columns": limits.get("max_columns", 40),
    }
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "case.xml"
        p.write_bytes(raw)
        res = _resource(str(p), p.name, "xml", "spreadsheet", "indexed")
        result = op.spreadsheetml_preview(res, **kwargs)
    ss_cases.append(
        {
            "name": name,
            "bytes_b64": b64(raw),
            "limits": kwargs,
            "expected": None if result is None else mask_tmp(project_result(result), td),
        }
    )


def ssml_rows(rows: int, columns: int, second_sheet: bool = False) -> bytes:
    cells = "".join(f"<Cell><Data>{c % 10}</Data></Cell>" for c in range(columns))
    worksheet = "".join(f"<Row>{cells}</Row>" for _ in range(rows))
    extra = (
        '<Worksheet ss:Name="Ignored"><Table><Row><Cell><Data ss:Type="String">'
        "do-not-read</Data></Cell></Row></Table></Worksheet>"
        if second_sheet
        else ""
    )
    return (
        '<?xml version="1.0"?><Workbook '
        'xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        f'<Worksheet ss:Name="First"><Table>{worksheet}</Table></Worksheet>{extra}'
        "</Workbook>"
    ).encode()


ss_case("bounded_first_sheet", ssml_rows(250, 45, second_sheet=True))
ss_case("small_exact", ssml_rows(3, 2))
ss_case("sparse_indexes",
        b'<?xml version="1.0"?><Workbook '
        b'xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        b'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        b'<Worksheet ss:Name="Sparse"><Table><Row>'
        b'<Cell ss:Index="40"><Data ss:Type="String">last</Data></Cell>'
        b'<Cell ss:Index="1000000"><Data ss:Type="String">outside</Data></Cell>'
        b"</Row></Table></Worksheet></Workbook>")
ss_case("malformed_real",
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
        b"<Worksheet><Table><Row><Cell><Data>broken</Cell></Row>")
_boundary = ssml_rows(5, 2).replace(
    b"</Table></Worksheet></Workbook>", b"<Row><Cell><Data>boundary"
)
ss_case("boundary_truncation_keeps_rows",
        _boundary + b" " * (256 * 1024))
_mal_near = (
    b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
    b"<Worksheet><Table><Row><Cell><Data>"
)
_mal_near = _mal_near + b"x" * (250 * 1024 - len(_mal_near)) + b"</Cell>"
ss_case("malformed_inside_budget_not_truncation",
        _mal_near + b"x" * (256 * 1024 - len(_mal_near) + 4096))
ss_case("foreign_namespace",
        ('<?xml version="1.0"?>'
         '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
         'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet" '
         'xmlns:ext="urn:vendor-extension">'
         "<ext:Worksheet><ext:Table><ext:Row><ext:Cell><ext:Data>evil</ext:Data>"
         "</ext:Cell></ext:Row></ext:Table></ext:Worksheet>"
         '<Worksheet ss:Name="Real"><Table><Row>'
         "<ext:Cell><ext:Data>ignored</ext:Data></ext:Cell>"
         "<Cell><Data>good</Data></Cell>"
         "</Row></Table></Worksheet></Workbook>").encode())
ss_case("empty_file", b"")
ss_case("not_workbook", b"<root><value>text</value></root>")
ss_case("bad_index_value",
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
        b'<Worksheet ss:Name="B"><Table><Row ss:Index="4.5">'
        b"<Cell><Data>x</Data></Cell></Row></Table></Worksheet></Workbook>")
ss_case("row_gap_padding",
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
        b'<Worksheet ss:Name="G"><Table>'
        b'<Row ss:Index="3"><Cell><Data>a</Data></Cell></Row>'
        b"</Table></Worksheet></Workbook>")
ss_case("empty_workbook_no_worksheet",
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"/>')
out["spreadsheetml"] = ss_cases

# ---------------------------------------------------------------------------
# xml_well_log_preview
# ---------------------------------------------------------------------------
xwl_cases = []


def xwl_case(name: str, raw: bytes, table_max_rows: int = 200):
    settings = replace(ps_mod.PreviewSettings.defaults(),
                       table_max_rows=table_max_rows)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "case.xml"
        p.write_bytes(raw)
        res = _resource(str(p), p.name, "xml", "well_log", "indexed")
        result = WLP.xml_well_log_preview(res, settings)
    xwl_cases.append(
        {
            "name": name,
            "bytes_b64": b64(raw),
            "table_max_rows": table_max_rows,
            "expected": None if result is None else mask_tmp(project_result(result), td),
        }
    )


xwl_case("witsml_log", WITSML.encode())
xwl_case(
    "spreadsheetml_log_sheet",
    ('<?xml version="1.0" encoding="UTF-8"?>\n'
     '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
     'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">\n'
     '  <Worksheet ss:Name="测井曲线">\n    <Table>\n      <Row>\n'
     '        <Cell><Data ss:Type="String">井号</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">深度</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">GR</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">DT</Data></Cell>\n      </Row>\n'
     "      <Row>\n"
     '        <Cell><Data ss:Type="String">HZ19-1-1A</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">99.25</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">45.2</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">120.5</Data></Cell>\n      </Row>\n'
     "      <Row>\n"
     '        <Cell><Data ss:Type="String">HZ19-1-1A</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">99.375</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">48.1</Data></Cell>\n'
     '        <Cell><Data ss:Type="String">121.2</Data></Cell>\n      </Row>\n'
     "    </Table></Worksheet>\n</Workbook>\n").encode(),
)
_rows = "".join(
    '<Row><Cell><Data ss:Type="Number">%d</Data></Cell>'
    "<Cell><Data ss:Type=\"Number\">%d</Data></Cell></Row>" % (i, i * 10)
    for i in range(22)
)
xwl_case(
    "sheet_row_budget",
    ('<?xml version="1.0"?>'
     '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
     'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
     "<Worksheet ss:Name=\"Sheet1\"><Table>"
     "<Row><Cell><Data ss:Type=\"String\">MD</Data></Cell>"
     "<Cell><Data ss:Type=\"String\">GR</Data></Cell></Row>"
     + _rows + "</Table></Worksheet></Workbook>").encode(),
    table_max_rows=20,
)
xwl_case(
    "witsml_curve_info_units",
    (b'<?xml version="1.0"?><root xmlns="http://www.witsml.org/schemas/1series">'
     b"<log><nameWell>W-9</nameWell>"
     b"<logCurveInfo><mnemonic>DEPT</mnemonic><unit>m</unit>"
     b"<curveDescription>DEPTH</curveDescription></logCurveInfo>"
     b"<logCurveInfo><mnemonic>GR</mnemonic><unit>gAPI</unit>"
     b"<curveDescription>Gamma</curveDescription></logCurveInfo>"
     b"<logData><data>1000.0, 45.2</data>"
     b"<data>1000.125, 48.5</data><data># commented</data>"
     b"<data>1000.25, 52.1</data></logData></log></root>")
)
xwl_case("not_a_log", b"<root><value>plain</value></root>")
xwl_case(
    "record_points",
    b'<logs><record><DEPTH>100</DEPTH><GR>45</GR></record>'
    b"<record><DEPTH>101</DEPTH><GR>46</GR></record></logs>",
)
xwl_case(
    "well_name_via_namewell",
    b"<log><nameWell>LONG-NAME-WELL</nameWell>"
    b"<logCurveInfo><mnemonic>DEPT</mnemonic></logCurveInfo>"
    b"<logData><data>1</data></logData></log>",
)
out["xml_well_log"] = xwl_cases

# ---------------------------------------------------------------------------
# office: zip / pptx / dfb
# ---------------------------------------------------------------------------
office_cases = {"zip": [], "pptx": [], "dfb": []}


def office_case(group, name, files, fmt, rtype, runner, extra_files=None,
                raw=None):
    """files: arcname -> bytes (zip members); raw: literal file bytes."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / f"case.{fmt}"
        if files is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with zipfile.ZipFile(p, "w") as zf:
                    for arc, content in files.items():
                        zf.writestr(arc, content)
        elif raw is not None:
            p.write_bytes(raw)
        for extra_name, extra_bytes in (extra_files or {}).items():
            ep = Path(td) / extra_name
            ep.write_bytes(extra_bytes)
        res = _resource(str(p), p.name, fmt, rtype, "indexed")
        result = runner(res)
        raw_bytes = p.read_bytes()
    office_cases[group].append(
        {
            "name": name,
            "fmt": fmt,
            "bytes_b64": b64(raw_bytes),
            "extra_files": {k: b64(v) for k, v in (extra_files or {}).items()},
            "expected": mask_tmp(project_result(result, include_bytes=True), td),
        }
    )


def _zip_members(n=6, stem="item"):
    return {f"{stem}-{i:03}.txt": b"payload" for i in reversed(range(n))}


office_case("zip", "sorted_cap", _zip_members(6), "zip", "archive",
            lambda r: op.zip_preview(r, max_rows=4))
office_cases["zip"][-1]["max_rows"] = 4
office_case("zip", "default_limit", _zip_members(6), "zip", "archive",
            lambda r: op.zip_preview(r))
office_case("zip", "bad_zip", None, "zip", "archive",
            lambda r: op.zip_preview(r), raw=b"not zip")
office_case("zip", "wlp_passthrough", None, "wlp", "well_reference",
            lambda r: op.wlp_preview(r), raw=b"vendor bytes")


def _patched_eocd_zip(field_offset, format_code, value, members):
    import io as _io

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for arc, content in members.items():
            zf.writestr(arc, content)
    payload = bytearray(buf.getvalue())
    eocd = payload.rfind(b"PK\x05\x06")
    struct.pack_into(format_code, payload, eocd + field_offset, value)
    return bytes(payload)


office_case("zip", "eocd_multidisk", None, "zip", "archive",
            lambda r: op.zip_preview(r),
            raw=_patched_eocd_zip(8, "<H", 10_001, _zip_members(3)))
office_case("zip", "eocd_too_many_entries", None, "zip", "archive",
            lambda r: op.zip_preview(r),
            raw=_patched_eocd_zip(10, "<H", 10_001, _zip_members(3)))
office_case("zip", "eocd_zip64_size", None, "zip", "archive",
            lambda r: op.zip_preview(r),
            raw=_patched_eocd_zip(12, "<L", 4 * 1024 * 1024 + 1, _zip_members(3)))
office_case("zip", "eocd_missing", None, "zip", "archive",
            lambda r: op.zip_preview(r), raw=b"")


def _truncated_zip_bytes():
    import io as _io

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.txt", "payload")
    return buf.getvalue()[:-1]


office_case("zip", "eocd_byte_cut", None, "zip", "archive",
            lambda r: op.zip_preview(r), raw=_truncated_zip_bytes())

office_case("pptx", "thumbnail_and_slides",
            {"docProps/thumbnail.jpeg": PNG_1X1,
             "ppt/slides/_rels/slide1.xml.rels": b"not a slide",
             **{f"ppt/slides/slide{i}.xml": b"<slide />" for i in (1, 2, 3)}},
            "pptx", "document", lambda r: op.pptx_preview(r))
office_case("pptx", "bad_zip", None, "pptx", "document",
            lambda r: op.pptx_preview(r), raw=b"not zip")
office_case("pptx", "no_thumbnail",
            {"ppt/slides/slide1.xml": b"<slide />"}, "pptx", "document",
            lambda r: op.pptx_preview(r))
office_case("pptx", "directory_named_thumbnail",
            {"docProps/thumbnail.png/": b""}, "pptx", "document",
            lambda r: op.pptx_preview(r))
def _duplicate_thumbnail_zip():
    import io as _io

    buf = _io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("docProps/thumbnail.jpeg", PNG_1X1)
            zf.writestr("docProps/thumbnail.jpeg", PNG_1X1)
    return buf.getvalue()


office_case("pptx", "duplicate_thumbnail", None, "pptx", "document",
            lambda r: op.pptx_preview(r), raw=_duplicate_thumbnail_zip())

# hand-built structurally valid JPEG (PIL unavailable in oracle env)
_JPEG_BYTES = (
    b"\xff\xd8"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
    b"\x12\x34\x56"
    b"\xff\xd9"
)


# freeze the validators directly on synthetic buffers
validator_cases = []
for vname, buf in [
    ("png_valid", b"noise" + PNG_1X1 + b"tail"),
    ("png_no_iend", b"prefix" + PNG_1X1[:-12]),
    ("png_bad_crc", (lambda a: (a.__setitem__(20, a[20] ^ 1), bytes(a))[1])(
        bytearray(PNG_1X1))),
    ("jpeg_valid", b"prefix" + _JPEG_BYTES + b"suffix"),
    ("jpeg_header_only",
     b"prefix"
     b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
     b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xff\xd9suffix"),
    ("jpeg_no_eoi", b"prefix\xff\xd8\xff\xe0\x00\x02"),
    ("jpeg_fake_markers",
     b"prefix\xff\xd8\xff\xc0\x00\x02\xff\xda\x00\x02\xff\xd9"),
]:
    kind = "png" if buf.find(PNG_1X1) >= 0 or vname.startswith("png") else "jpeg"
    if kind == "png":
        start = buf.find(b"\x89PNG\r\n\x1a\n")
        end = op._validated_png_range(buf, start) if start >= 0 else None
    else:
        start = buf.find(b"\xff\xd8")
        end = op._validated_jpeg_range(buf, start) if start >= 0 else None
    validator_cases.append(
        {
            "name": vname,
            "kind": kind,
            "bytes_b64": b64(buf),
            "expected_range": None if end is None else [start, end],
            "expected_bytes": b64(buf[start:end]) if end is not None else None,
        }
    )
out["image_validators"] = validator_cases

office_case("dfb", "embedded_png", None, "dfb", "reference_map",
            lambda r: op.dfb_preview(r),
            raw=b"vendor-prefix" + PNG_1X1 + b"vendor-suffix")
office_case("dfb", "sibling_png", None, "dfb", "reference_map",
            lambda r: op.dfb_preview(r), raw=b"vendor",
            extra_files={"case.png": b"png-preview"})
office_case("dfb", "embedded_jpeg", None, "dfb", "reference_map",
            lambda r: op.dfb_preview(r), raw=b"prefix" + _JPEG_BYTES + b"suffix")
office_case("dfb", "empty_file", None, "dfb", "reference_map",
            lambda r: op.dfb_preview(r), raw=b"")
office_case("dfb", "no_valid_image", None, "dfb", "reference_map",
            lambda r: op.dfb_preview(r), raw=b"garbage bytes only")
out["office"] = office_cases

# ---------------------------------------------------------------------------
# registry.build_preview dispatch
# ---------------------------------------------------------------------------
reg_cases = []


def reg_case(name, filename, raw, fmt, rtype, status="indexed",
             checksum=None, project_root=None, project_files=None,
             resource_path=None):
    settings = ps_mod.PreviewSettings.defaults()
    with tempfile.TemporaryDirectory() as td:
        path_value = resource_path or str(Path(td) / filename)
        if raw is not None:
            p = Path(td) / filename
            p.write_bytes(raw)
            path_value = str(p)
        res = _resource(path_value, filename, fmt, rtype, status,
                        resource_id="res-oracle")
        res.checksum = checksum
        kwargs = {}
        if project_root is not None:
            pr = Path(td) / "projroot"
            pr.mkdir()
            for rel, content in (project_files or {}).items():
                dest = pr / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            kwargs["project_root"] = str(pr)
        result = REG.PreviewRegistry().build_preview(res, settings, **kwargs)
    reg_cases.append(
        {
            "name": name,
            "filename": filename,
            "resource_path": resource_path,
            "bytes_b64": None if raw is None else b64(raw),
            "format": fmt,
            "type": rtype,
            "status": status,
            "checksum": checksum,
            "project_root": project_root is not None,
            "project_files": {k: b64(v) for k, v in (project_files or {}).items()},
            "expected": mask_tmp(project_result(result, include_bytes=True), td),
        }
    )


reg_case("missing_file", "missing.txt", None, "txt", "document")
reg_case("plain_text", "sample.txt", b"first", "txt", "document")
reg_case("markdown_route", "notes.md", b"# Title\n\nbody", "md", "document")
reg_case("html_route", "doc.html", b"<h1>Hello</h1>", "html", "document")
reg_case("csv_route", "t.csv", b"a,b\n1,2\n", "csv", "tabular")
reg_case("dat_route", "w.dat", b"#Name X Y\nA 1 2\n", "dat", "well_head")
reg_case("json_route", "c.json", b"{}", "json", "document")
reg_case("audio_route", "clip.wav", b"\x00" * 64, "wav", "unknown", "parsed")
reg_case("video_route", "clip.mp4", b"\x00" * 64, "mp4", "video", "parsed")
reg_case("doc_route", "legacy.doc", b"\xd0\xcf\x11\xe0", "doc", "document", "parsed")
reg_case("docx_dep_missing", "s.docx", b"PK\x03\x04", "docx", "document", "parsed")
reg_case("excel_dep_missing", "w.xlsx", b"PK\x03\x04", "xlsx", "spreadsheet")
reg_case("las_dep_missing", "well.las", b"~V\n", "las", "well_log")
reg_case("geotiff_dep_missing", "fake.tif", b"\x00" * 64, "tif",
         "image_reference", "parsed")
reg_case("image_route", "map.png", b"first-image", "png", "image_reference",
         "indexed", checksum="checksum-1")
reg_case("image_by_type", "blob.xyz", b"\x00" * 16, "xyz", "image_reference")
reg_case("segy_dep_missing", "cube.sgy", b"not-a-real-segy", "sgy", "seismic")
reg_case("segy_by_type", "vol.bin", b"\x00" * 32, "bin", "seismic")
reg_case("pptx_route", "deck.pptx", b"vendor bytes", "pptx", "document")
reg_case("dfb_route", "phase.dfb", b"vendor bytes", "dfb", "reference_map")
reg_case("zip_route", "bundle.zip", b"vendor bytes", "zip", "archive")
reg_case("wlp_route", "well.wlp", b"vendor bytes", "wlp", "well_reference")
reg_case("pdf_route", "r.pdf", b"%PDF-1.4\n", "pdf", "document")
reg_case("xml_well_log_type", "A11_well_log.xml", WITSML.encode(), "xml", "well_log")
reg_case("xml_ordinary", "ordinary.xml", b"<root><value>plain</value></root>",
         "xml", "spreadsheet")
reg_case("xml_falls_to_text", "thing.xml", b"<root><value>plain</value></root>",
         "xml", "document")
reg_case("unknown_fallback", "blob.qqq", b"\x00", "qqq", "unknown")
reg_case("artifact_revision_pin", "map.png", b"second-image-with-new-bytes",
         "png", "image_reference", "indexed", checksum="checksum-2")
reg_case(
    "project_root_inside",
    "a.las",
    None,
    "las",
    "well_log",
    project_root=True,
    resource_path="data/well.las",
    project_files={"data/well.las": b"~Version\n"},
)
reg_case(
    "project_root_escape_rejected",
    "secret.txt",
    None,
    "txt",
    "document",
    project_root=True,
    resource_path="../outside/secret.txt",
    project_files={"keep.txt": b"root file"},
)
# BEGIN VIZ-A adjudication: the C++ registry LAS branch (no WLE provider
# installed) reports the honest capability message "LAS 预览不可用：WLE LAS
# 解析内核未接入" instead of the Python geoviz-absent parity message
# "LAS 预览失败: ModuleNotFoundError" — the fabricated Python dependency
# error is exactly what the VIZ-A line removes (the real preview lands with
# the provider installed; see docs/development/cpp-viz-a/reconciliation.md).
# The frozen expectation is patched to the C++ contract and flagged.
_CPP_LAS_UNAVAILABLE = "LAS 预览不可用：WLE LAS 解析内核未接入"
for case in reg_cases:
    if case["format"] == "las" and isinstance(case["expected"], dict):
        if case["expected"].get("message") == "LAS 预览失败: ModuleNotFoundError":
            case["expected"]["message"] = _CPP_LAS_UNAVAILABLE
            case["expected"]["warning"] = _CPP_LAS_UNAVAILABLE
            case["cpp_adjudication"] = "VIZ-A: honest capability message replaces the fabricated ModuleNotFoundError"
out["registry"] = reg_cases

# ---------------------------------------------------------------------------
# export artifact preview + resource revision token
# ---------------------------------------------------------------------------
from paleo_workbench.project.models import ExportArtifact  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    out_path = Path(td) / "map.png"
    art = ExportArtifact(linked_id="map_1", format="png", output_path=str(out_path))
    result = REG.artifact_preview(art)
    out["artifact_preview"] = mask_tmp(project_result(result, include_bytes=True), td)

with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "f.txt"
    p.write_text("x", encoding="utf-8")
    res = _resource(str(p), "f.txt", "txt", "document", "indexed")
    res.id = "res-fixed"
    res.checksum = "ck"
    token = dp.resource_revision_token(res, safe_stat_fn=lambda _p: (12, 100))
    out["revision_token"] = {
        "resource": {"id": res.id, "path": res.path, "type": res.type,
                     "format": res.format, "status": res.status,
                     "checksum": res.checksum},
        "stat": [12, 100],
        "expected_head": [
            str(x).replace(str(td) + "/", "<TMP>/") for x in token[:7]
        ],
    }

# ---------------------------------------------------------------------------
# preview settings
# ---------------------------------------------------------------------------
settings_cases = []
settings_cases.append({"values": {}, "expect_error": None,
                       "fingerprint": ps_mod.PreviewSettings.defaults().fingerprint()})
for values, err in [
    ({"table_max_rows": 100}, None),
    ({"text_limit_kib": 16, "table_max_columns": 5}, None),
    ({"density": "compact", "theme_mode": "system"}, None),
    ({"pdf_fit_mode": "custom", "pdf_zoom_percent": 200}, None),
    ({"show_metadata": False, "media_volume": 0}, None),
    ({"geoviz_max_points": 1_000_000}, None),
    ({"table_max_rows": 19}, "ValueError"),
    ({"table_max_rows": 2001}, "ValueError"),
    ({"density": "cozy"}, "ValueError"),
    ({"pdf_fit_mode": "diagonal"}, "ValueError"),
    ({"media_volume": True}, "TypeError"),
    ({"media_volume": 3.5}, "TypeError"),
    ({"show_metadata": 1}, "TypeError"),
]:
    try:
        settings = ps_mod.PreviewSettings(**values)
        settings_cases.append(
            {"values": values, "expect_error": None,
             "fingerprint": settings.fingerprint()}
        )
    except Exception as exc:  # noqa: BLE001
        settings_cases.append(
            {"values": values, "expect_error": exc.__class__.__name__,
             "fingerprint": None}
        )
    assert err is None or settings_cases[-1]["expect_error"] == err
from_mapping_settings = ps_mod.PreviewSettings.from_mapping(
    {"font_size": 14, "bogus_key": 1, "table_max_rows": 77}
)
settings_cases.append(
    {"values": {"font_size": 14, "bogus_key": 1, "table_max_rows": 77},
     "expect_error": None,
     "fingerprint": from_mapping_settings.fingerprint(),
     "from_mapping_font_size": from_mapping_settings.font_size,
     "from_mapping_table_max_rows": from_mapping_settings.table_max_rows}
)
out["preview_settings"] = {
    "defaults_fingerprint": ps_mod.PreviewSettings.defaults().fingerprint(),
    "defaults_mapping": ps_mod.PreviewSettings.defaults().to_mapping(),
    "cases": settings_cases,
}

# ---------------------------------------------------------------------------
# shlex (dat_preview tokenizer) direct pin
# ---------------------------------------------------------------------------
shlex_cases = []
for text in [
    "a b c", "  a   b  ", "'a b' c", '"a b" c', "a 'b c' \"d\\\"e\" f",
    '"a\\nb"', "a\\ b", "a\\\\b", '""', "''", "a'b'c", '"unterminated',
    "'unterminated", "back\\", "a#b", '"a#b"', "x 'y", '"a', "\\",
    "a \"b\" 'c'", "tab\tsep", "multi\nline tokens",
]:
    try:
        shlex_cases.append({"input": text, "expected": shlex.split(text),
                            "error": None})
    except ValueError as exc:
        shlex_cases.append({"input": text, "expected": None,
                            "error": str(exc)})
out["shlex"] = shlex_cases

# ---------------------------------------------------------------------------
# markdown_to_html direct pin (string -> string)
# ---------------------------------------------------------------------------
md_cases = []
for text in [
    "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6\n####### Not-H7\n",
    "para one\npara two\n\npara three\n",
    "- a\n- b\n\n1. c\n2. d\n",
    "```\ncode\nlines\n```\nafter\n",
    "unclosed:\n```\ncode\n",
    "escape < & > \" ' here\n",
    "- mixed\n1. switch\n- back\n",
    "text\n```\ninline after\n```\nmore text\n",
]:
    md_cases.append({"input": text, "expected": dp.markdown_to_html(text)})
out["markdown_direct"] = md_cases

# ---------------------------------------------------------------------------
# format_size direct pin
# ---------------------------------------------------------------------------
out["format_size"] = [
    [None if v == "none" else v, __import__("paleo_workbench.tokens", fromlist=["x"]).format_size(v)]
    for v in (None, 0, 1023, 1024, 1536, 2048, 1024 * 1024, 3 * 1024 * 1024,
              1024 * 1024 * 10)
]

# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------
fixture_path = REPO / "libs/ingest/oracle/fixtures/ingest_oracle.json"
fixture_path.parent.mkdir(parents=True, exist_ok=True)
total = sum(len(v) for v in out.values() if isinstance(v, list)) + sum(
    len(v) for v in out.get("previews", {}).values()
)
fixture_path.write_text(
    json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)
print(f"frozen {total} cases -> {fixture_path}")
print("groups:", {
    k: (len(v) if isinstance(v, list)
        else sum(len(x) if isinstance(x, (list, dict, str)) else 1
                 for x in v.values()) if isinstance(v, dict) else 1)
    for k, v in out.items()
})
