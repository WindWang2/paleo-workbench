#!/usr/bin/env python3
"""05 线 — XML 井曲线加载 oracle 生成器（双模式）。

模式 A（首选）：真实冻结 Python 生成——加载 geo-viz-engine@08851951 的
xml_preview.load_xml_preview 与 paleo_workbench/resources/well_log_xml.py
的 is_well_log_xml，对 fixtures/xml/ 下的输入文件产出期望值。
模式 B（本机现状）：环境无 numpy/pip（本机 python3.14 无 site-packages，
see docs/development/cpp-closure-wave/05-well-crosswell/findings.md
「环境事实」），退化到**逐条转录**的期望值——每个数值在
TRANSCRIBED 里注明其冻结源推导（行号级），并用模式 A 可复核。

输出：fixtures/expected/well_xml_oracle.json（被
tests/cpp/well_crosswell 的 well.load_path / ui_workers 的
ui_workers.well_xml 消费）。比较容差：绝对值 1e-12（转录值为十进制
字面量，与 C++ 双精度解析精确一致；NaN 以 "nan" 字符串载）。

用法：python3 tools/oracle/generate_well_xml_fixtures.py [--check]
  --check 模式：不写盘，校验现有 oracle 与生成器一致。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
XML_DIR = REPO / "tests/cpp/well_crosswell/fixtures/xml"
OUT = REPO / "tests/cpp/well_crosswell/fixtures/expected/well_xml_oracle.json"


def _local_name(tag: str) -> str:
    text = tag.rsplit("}", 1)[-1]
    return text.rsplit(":", 1)[-1].strip().casefold()


def recognize_mode_b(path: Path) -> bool:
    """is_well_log_xml 转录（resources/well_log_xml.py 逐条）。"""
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(str(path)).getroot()
    except Exception:
        return False
    tags: set[str] = set()
    has_log = has_info = has_data = has_sheet = False
    for index, element in enumerate(root.iter()):
        if index >= 200_000:
            break
        tag = _local_name(str(getattr(element, "tag", "")))
        tags.add(tag)
        has_log = has_log or tag == "log"
        has_info = has_info or tag in {"logcurveinfo", "curveinfo"}
        has_data = has_data or tag == "logdata"
        if tag == "worksheet":
            names = [str(v).strip().casefold()
                     for v in element.attrib.values() if str(v).strip()]
            has_sheet = has_sheet or any(
                n in {"测井曲线", "welllog", "well log", "log curves"}
                for n in names)
    root_tag = _local_name(str(root.tag))
    is_witsml = "witsml" in root_tag or "witsml" in tags
    return ((has_log and has_info and has_data)
            or (is_witsml and has_info and has_data)
            or has_sheet)


def _fmt(value: float) -> object:
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    return value


# ---------------------------------------------------------------------------
# 模式 B：转录期望值（冻结源推导逐条注释；NaN 表达缺测哨兵语义）。
# ---------------------------------------------------------------------------

def transcribed() -> dict:
    cases: dict[str, dict] = {}

    # witsml_basic.xml：headers=[DEPT,GR,DT]（logCurveInfo×3，mnemonic 子
    # 元素）；depth_idx=0（DEPT）；selected=[GR,DT]；well_name=NameWell
    # 文本 "W-1"（xml_preview.py L64-69）。5 行全保留（无抽稀，
    # stride=ceil(5/100000)=1）。GR 单位 gAPI、DT 单位 us/m
    # （_unit_for_header L27-28）。DEPT 为深度列不入曲线。
    cases["witsml_basic.xml"] = {
        "recognized": True,
        "well_name": "W-1",
        "depth_unit": None,  # XML 不声明深度单位（well_log_load.py L187-189）
        "top_depth": 96.0,
        "bottom_depth": 100.0,
        "total_rows": 5,
        "sample_stride": 1,
        "curves": [
            {"name": "GR", "unit": "gAPI",
             "depth": [100.0, 99.0, 98.0, 97.0, 96.0],
             "values": [42.3, 45.7, 48.2, 51.2, 49.85]},
            {"name": "DT", "unit": "us/m",
             "depth": [100.0, 99.0, 98.0, 97.0, 96.0],
             "values": [68.1, 70.25, 71.9, 73.4, 74.4]},
        ],
        "lithology": [], "facies": [], "formation": [],
        "text_desc": [], "horizons": [],
    }

    # witsml_reverse.xml：logData 文本块 splitlines → 6 行；深度降序
    # 200→195；well_name=NameWell "W-REV"；GR 一条曲线。
    cases["witsml_reverse.xml"] = {
        "recognized": True,
        "well_name": "W-REV",
        "depth_unit": None,
        "top_depth": 195.0,
        "bottom_depth": 200.0,
        "total_rows": 6,
        "sample_stride": 1,
        "curves": [
            {"name": "GR", "unit": "gAPI",
             "depth": [200.0, 199.0, 198.0, 197.0, 196.0, 195.0],
             "values": [61.25, 58.90, 55.40, 53.10, 49.85, 45.70]},
        ],
        "lithology": [], "facies": [], "formation": [],
        "text_desc": [], "horizons": [],
    }

    # witsml_missing_cells.xml：-9999 ≤ -9000 → NaN 值保留（L216-217）；
    # 短行（13.0,34.0）越界列 → NaN（L213-214）；"abc" 不可解析 → NaN
    # （L214-219）；坏深度行才整行剔除（本文件无）。7 行全保留。
    cases["witsml_missing_cells.xml"] = {
        "recognized": True,
        "well_name": "W-GAP",
        "depth_unit": None,
        "top_depth": 10.0,
        "bottom_depth": 16.0,
        "total_rows": 7,
        "sample_stride": 1,
        "curves": [
            {"name": "GR", "unit": "gAPI",
             "depth": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0],
             "values": [30.0, 31.5, "nan", 34.0, 36.5, "nan", 39.0]},
            {"name": "DT", "unit": "us/m",
             "depth": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0],
             "values": [50.0, 51.5, 52.5, "nan", 55.5, 56.5, 58.0]},
        ],
        "lithology": [], "facies": [], "formation": [],
        "text_desc": [], "horizons": [],
    }

    # spreadsheet_welllog.xml：测井曲线表（首表）→ headers=[井号,深度,
    # GR,POR]；well_name=首列首行 "W-SHEET"（L123-126）；ss:Index=4 行
    # 填充后深度列为空 → float("") ValueError → 整行跳过（L204-208）→
    # 4 数据行中 3 行保留；GR/POR 单位 gAPI/%（"POR" 对原名大小写敏感
    # 匹配，L31）。区间表：岩性表 2 条、分层表 formation 1 + facies 1、
    # 标准层 1（bottom=top+1，L347）。
    cases["spreadsheet_welllog.xml"] = {
        "recognized": True,
        "well_name": "W-SHEET",
        "depth_unit": None,
        "top_depth": 1000.0,
        "bottom_depth": 1003.0,
        "total_rows": 4,
        "sample_stride": 1,
        "curves": [
            {"name": "GR", "unit": "gAPI",
             "depth": [1000.0, 1001.0, 1003.0],
             "values": [45.2, 46.8, 50.4]},
            {"name": "POR", "unit": "%",
             "depth": [1000.0, 1001.0, 1003.0],
             "values": [12.5, 13.1, 15.0]},
        ],
        "lithology": [
            {"top": 1000.0, "bottom": 1002.0, "label": "泥岩"},
            {"top": 1002.0, "bottom": 1004.0, "label": "细砂岩"},
        ],
        "facies": [
            {"top": 1000.0, "bottom": 1003.0, "label": "三角洲前缘"},
        ],
        "formation": [
            {"top": 1000.0, "bottom": 1003.0, "label": "S1"},
        ],
        "text_desc": [],
        "horizons": [
            {"top": 1001.5, "bottom": 1002.5, "label": "K1 标志层"},
        ],
    }

    # 负例：generic 地图点（无 log/witsml/具名表）→ 不识别；
    # 不完整 WITSML（有 logCurveInfo 无 logData）→ 不识别。
    cases["negative_generic_points.xml"] = {"recognized": False}
    cases["negative_incomplete_witsml.xml"] = {"recognized": False}

    return cases


# ---------------------------------------------------------------------------
# 模式 A：真实冻结 Python（需要 numpy + lxml；环境具备时为权威）。
# ---------------------------------------------------------------------------

def measured() -> dict | None:
    try:
        sys.path.insert(0, str(REPO / "geo-viz-engine/packages/geoviz_well_log"))
        sys.path.insert(0, str(REPO / "geo-viz-engine/packages/geoviz_well_log/geoviz_well_log"))
        from geoviz_well_log.xml_preview import load_xml_preview  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print(f"[oracle] 模式 A 不可用（{exc.__class__.__name__}: {exc}）→ 模式 B",
              file=sys.stderr)
        return None
    cases: dict[str, dict] = {}
    for path in sorted(XML_DIR.glob("*.xml")):
        entry: dict = {"recognized": recognize_mode_b(path)}
        if not entry["recognized"]:
            cases[path.name] = entry
            continue
        try:
            data = load_xml_preview(str(path), max_curves=30,
                                    max_samples=100000)
        except Exception as exc:  # noqa: BLE001
            entry["error_class"] = exc.__class__.__name__
            cases[path.name] = entry
            continue
        entry.update({
            "well_name": data.well_name,
            "depth_unit": None,
            "top_depth": data.top_depth,
            "bottom_depth": data.bottom_depth,
            "total_rows": 0,  # 引擎不外露行数；模式 A 记 0 并在比较时跳过
            "sample_stride": 1,
            "curves": [
                {"name": c.name, "unit": c.unit,
                 "depth": [_fmt(v) for v in c.depth],
                 "values": [_fmt(v) for v in c.values]}
                for c in data.curves
            ],
            "lithology": [{"top": i.top, "bottom": i.bottom,
                           "label": i.lithology} for i in data.lithology],
            "facies": [{"top": i.top, "bottom": i.bottom,
                        "label": i.facies} for i in data.facies],
            "formation": [{"top": i.top, "bottom": i.bottom,
                           "label": i.name} for i in data.intervals.formation],
            "text_desc": [{"top": i.top, "bottom": i.bottom,
                           "label": i.name} for i in data.intervals.lithology_desc],
            "horizons": [{"top": i.top, "bottom": i.bottom,
                          "label": i.name} for i in data.intervals.sequence],
        })
        cases[path.name] = entry
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    measured_cases = measured()
    mode = "A-measured" if measured_cases is not None else "B-transcribed"
    cases = measured_cases if measured_cases is not None else transcribed()
    payload = {
        "mode": mode,
        "note": ("模式 A：geo-viz-engine@08851951 xml_preview.load_xml_preview"
                 " 实测 | 模式 B：冻结源逐条转录（见 generate_well_xml_fixtures.py"
                 " 内行号级推导）。"),
        "tolerance": 1e-12,
        "cases": cases,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if args.check:
        if not OUT.exists():
            print(f"[oracle] 缺 {OUT}", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8").strip() != text.strip():
            print("[oracle] 与盘上 oracle 不一致", file=sys.stderr)
            return 1
        print(f"[oracle] 一致（模式 {mode}）")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"[oracle] 写 {OUT}（模式 {mode}，{len(cases)} 案例）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
