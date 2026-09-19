#!/usr/bin/env python3
"""Generate the C++ well-log adapter oracle fixture.

Runs the REAL production adapter (paleo_workbench/viz/welllog_engine_adapter.py)
on a set of frozen synthetic cases and writes its ``parity_snapshot`` output to
welllog_adapter_oracle.json. The C++ port (libs/visualization
well_log_document_plan) must reproduce these snapshots exactly — this is the
Python→C++ replay contract for the well-log host migration.

The adapter module imports only stdlib + numpy, so the fixture regenerates in
a bare environment:

    python3 -m venv /tmp/pwb-oracle-venv
    /tmp/pwb-oracle-venv/bin/pip install numpy
    /tmp/pwb-oracle-venv/bin/python generate_oracle.py

The script self-checks: it re-reads the written file, verifies the schema and
UUID formatting, and asserts that a deliberately name-mangled entity id does
NOT collide with the real one (negative self-check proves the comparator can
fail).
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
import types
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
ADAPTER_PATH = REPO_ROOT / "paleo_workbench" / "viz" / "welllog_engine_adapter.py"

NAN = float("nan")
INF = float("inf")


def f64_encode(value):
    """JSON has no NaN/Inf: encode non-finite doubles as tagged strings."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return value


def encode_array(values):
    return [f64_encode(v) for v in values]


def load_adapter():
    # The adapter lazily imports paleo_workbench.workflow.well_science (pure
    # stdlib) for classify_depth_unit. The paleo_workbench package __init__
    # pulls PySide6, so register minimal import trampolines and load BOTH real
    # modules from their files — nothing under test is stubbed.
    pkg = types.ModuleType("paleo_workbench")
    workflow = types.ModuleType("paleo_workbench.workflow")
    pkg.workflow = workflow
    sys.modules.setdefault("paleo_workbench", pkg)
    sys.modules.setdefault("paleo_workbench.workflow", workflow)

    science_spec = importlib.util.spec_from_file_location(
        "paleo_workbench.workflow.well_science",
        REPO_ROOT / "paleo_workbench" / "workflow" / "well_science.py")
    science = importlib.util.module_from_spec(science_spec)
    sys.modules[science_spec.name] = science
    science_spec.loader.exec_module(science)
    workflow.well_science = science

    spec = importlib.util.spec_from_file_location(
        "pwb_welllog_adapter_oracle", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["pwb_welllog_adapter_oracle"] = module
    spec.loader.exec_module(module)
    return module


class Curve:
    def __init__(self, name, unit, depth, values, display_range=None, color=""):
        self.name = name
        self.unit = unit
        self.depth = depth
        self.values = values
        self.display_range = display_range
        self.color = color


class Data:
    def __init__(self, **kwargs):
        self.well_name = ""
        self.top_depth = 0.0
        self.bottom_depth = 0.0
        self.depth_unit = None
        self.curves = []
        self.lithology = []
        self.facies = []
        self.intervals = None
        self.markers = []
        self.__dict__.update(kwargs)


class Interval:
    def __init__(self, top, bottom, **attrs):
        self.top = top
        self.bottom = bottom
        self.__dict__.update(attrs)


class Marker:
    def __init__(self, depth, label="", semantic="formation_top", id=""):
        self.depth = depth
        self.label = label
        self.semantic = semantic
        self.id = id


class FaciesData:
    """Mirrors paleo_workbench FaciesData: grouped facies interval buckets."""

    def __init__(self, phase=(), sub_phase=(), micro_phase=()):
        self.phase = list(phase)
        self.sub_phase = list(sub_phase)
        self.micro_phase = list(micro_phase)


class WellIntervals:
    """Mirrors paleo_workbench WellIntervals: .lithology + .facies buckets."""

    def __init__(self, lithology=(), facies=None):
        self.lithology = list(lithology)
        self.facies = facies


def curve_to_json(curve: Curve) -> dict:
    return {
        "mnemonic": curve.name,
        "unit": curve.unit,
        "depth": encode_array(curve.depth),
        "values": encode_array(curve.values),
        "display_range": (
            [f64_encode(curve.display_range[0]), f64_encode(curve.display_range[1])]
            if curve.display_range is not None
            else None
        ),
        "color": curve.color,
    }


def interval_to_json(item, label_attr: str) -> dict:
    return {
        "top": f64_encode(item.top),
        "bottom": f64_encode(item.bottom),
        "label": getattr(item, label_attr),
    }


def data_to_json(data: Data) -> dict:
    payload = {
        "well_name": data.well_name,
        "top_depth": f64_encode(data.top_depth),
        "bottom_depth": f64_encode(data.bottom_depth),
        "depth_unit": data.depth_unit,
        "curves": [curve_to_json(c) for c in data.curves],
        "lithology": [interval_to_json(i, "lithology") for i in data.lithology],
        "facies": [
            interval_to_json(i, "facies" if hasattr(i, "facies") else "name")
            for i in data.facies
        ],
        "markers": [
            {"depth": f64_encode(m.depth), "label": m.label,
             "semantic": m.semantic, "id": m.id}
            for m in data.markers
        ],
        "facies_groups": None,
    }
    if data.intervals is not None:
        payload["facies_groups"] = {
            "lithology": [interval_to_json(i, "lithology")
                          for i in data.intervals.lithology],
        }
        grouped_facies = data.intervals.facies
        if grouped_facies is not None:
            payload["facies_groups"].update({
                "phase": [interval_to_json(i, "facies") for i in grouped_facies.phase],
                "sub_phase": [
                    interval_to_json(i, "facies") for i in grouped_facies.sub_phase
                ],
                "micro_phase": [
                    interval_to_json(i, "facies") for i in grouped_facies.micro_phase
                ],
            })
    return payload


def build_cases():
    """The frozen case set — everything the C++ port must survive."""
    cases = []

    # 1. basic production shape: GR primary, NaN value gap, log-scale RT with a
    #    positive sample, tops, Chinese labels.
    cases.append((
        "basic_production",
        Data(
            well_name="W1",
            top_depth=1000.0,
            bottom_depth=1100.5,
            depth_unit="m",
            curves=[
                Curve("GR", "API", [1000.0, 1001.0, 1002.0, 1003.0],
                      [42.0, NAN, 55.5, 61.0], (0.0, 150.0)),
                Curve("RT", "ohmm", [1000.0, 1000.5, 1001.0],
                      [2.0, 0.5, 20.0]),
                Curve("AC", "us/ft", [1000.0, 1002.0], [70.0, 88.0]),
            ],
            markers=[Marker(1010.0, "长2"), Marker(1080.0, "长1")],
        ),
    ))

    # 2. unknown depth unit stays honest: label "m", declared False.
    cases.append((
        "unknown_depth_unit",
        Data(
            well_name="W2",
            top_depth=10.0,
            bottom_depth=20.0,
            depth_unit="furlongs",
            curves=[Curve("GR", "API", [10.0, 11.0], [1.0, 2.0])],
        ),
    ))

    # 3. no curves at all.
    cases.append(("empty_well", Data(well_name="W3")))

    # 4. every value non-finite → curve_empty + all_curves_empty.
    cases.append((
        "all_nan_values",
        Data(
            well_name="W4",
            top_depth=0.0,
            bottom_depth=10.0,
            depth_unit="ft",
            curves=[Curve("SON", "us/ft", [0.0, 1.0, 2.0], [NAN, NAN, NAN])],
        ),
    ))

    # 5. non-finite DEPTHS are dropped, finite-depth NaN values stay.
    cases.append((
        "depth_gaps",
        Data(
            well_name="W5",
            top_depth=100.0,
            bottom_depth=200.0,
            depth_unit="m",
            curves=[
                Curve("GR", "API",
                      [100.0, NAN, 102.0, 103.0, INF, 105.0],
                      [10.0, 20.0, NAN, 30.0, 40.0, 50.0]),
            ],
        ),
    ))

    # 6. duplicate depths stay (index-based identity, engine-order semantics).
    cases.append((
        "duplicate_depth",
        Data(
            well_name="W6",
            top_depth=5.0,
            bottom_depth=5.0,
            curves=[Curve("GR", "API", [5.0, 5.0, 6.0], [1.0, 2.0, 3.0])],
        ),
    ))

    # 7. descending depth order is preserved (envelope normalizes).
    cases.append((
        "descending_depth",
        Data(
            well_name="W7",
            top_depth=0.0,
            bottom_depth=0.0,
            curves=[Curve("GR", "API", [300.0, 200.0, 100.0], [3.0, 2.0, 1.0])],
        ),
    ))

    # 8. RT with no positive finite sample falls back to linear; display_range
    #    sanitization; non-finite display range.
    cases.append((
        "log_scale_fallback",
        Data(
            well_name="W8",
            top_depth=0.0,
            bottom_depth=10.0,
            depth_unit="m",
            curves=[
                Curve("RT", "ohmm", [0.0, 1.0], [-2.0, -1.0]),
                Curve("RXO", "ohmm", [0.0, 1.0], [5.0, 7.0], (0.0, 0.0)),
                Curve("DEN", "g/cm3", [0.0, 1.0], [2.0, 2.4], (2.0, NAN)),
            ],
            lithology=[Interval(0.0, 10.0, lithology="泥岩")],
            markers=[Marker(5.0, "K1")],
        ),
    ))

    # 9. invalid intervals/markers produce diagnostics, valid ones survive.
    cases.append((
        "invalid_interval_marker",
        Data(
            well_name="W9",
            top_depth=0.0,
            bottom_depth=100.0,
            depth_unit="m",
            curves=[Curve("GR", "API", [0.0, 100.0], [1.0, 2.0])],
            lithology=[
                Interval(0.0, 50.0, lithology="泥岩"),
                Interval(60.0, 40.0, lithology="砂岩"),  # bottom <= top
                Interval(70.0, NAN, lithology="灰岩"),   # non-finite
                # repr(edge) branch coverage inside interval ids.
                Interval(1e15, 2e15, lithology="极端"),
                Interval(1e-5, 2e-5, lithology="微观"),
            ],
            facies=[Interval(0.0, 30.0, name="浅湖")],
            markers=[
                Marker(10.0, "K1"),
                Marker(NAN, "bad"),
                Marker(20.0, "K2", "fault"),
                Marker(30.0, "K3", "formation_top", id="biz-marker-7"),
            ],
        ),
    ))

    # 10. unicode primary pick (预测概率), facies color substring mapping,
    #     curve color default by mnemonic and explicit override.
    cases.append((
        "unicode_and_colors",
        Data(
            well_name="井A-1",
            top_depth=1000.0,
            bottom_depth=1002.0,
            depth_unit="m",
            curves=[
                Curve("其他", "unit", [1000.0, 1001.0], [1.0, 2.0]),
                Curve("预测概率", "", [1000.0, 1001.0], [0.1, 0.9]),
                Curve("gr2", "API", [1000.0, 1001.0], [10.0, 20.0]),
                Curve("SP", "mV", [1000.0, 1001.0], [-20.0, -10.0],
                      None, "#123456"),
            ],
            lithology=[Interval(1000.0, 1002.0, lithology="泥岩夹砂岩")],
            facies=[Interval(1000.0, 1001.5, name="三角洲前缘"),
                    Interval(1001.5, 1002.0, name="未知相带")],
        ),
    ))

    # 11. grouped facies (phase/sub_phase/micro_phase) flatten in order.
    cases.append((
        "grouped_facies",
        Data(
            well_name="W11",
            top_depth=0.0,
            bottom_depth=90.0,
            depth_unit="m",
            curves=[Curve("GR", "API", [0.0, 90.0], [1.0, 2.0])],
            intervals=WellIntervals(
                lithology=[Interval(30.0, 45.0, lithology="灰岩")],
                facies=FaciesData(
                    phase=[Interval(0.0, 90.0, facies="湖")],
                    sub_phase=[Interval(0.0, 60.0, facies="浅湖"),
                               Interval(60.0, 90.0, facies="深湖")],
                    micro_phase=[Interval(10.0, 20.0, facies="湖底泥")],
                )
            ),
        ),
    ))

    return cases


def finalize(name: str, adapter, data: Data) -> dict:
    plan = adapter.adapt_well_log_data(data)
    entry = {
        "name": name,
        "input": data_to_json(data),
        "expected": adapter.parity_snapshot(data),
        "submit": None,
    }
    try:
        payload = adapter.plan_to_submit_payload(plan)
        entry["submit"] = {
            "top": f64_encode(payload["top"]),
            "bottom": f64_encode(payload["bottom"]),
            "tracks": payload["tracks"],
            "diagnostics": list(plan.diagnostics),
        }
    except ValueError:
        pass
    return entry


def main() -> int:
    adapter = load_adapter()
    cases = [finalize(name, adapter, data) for name, data in build_cases()]

    # Negative self-check material: an id derived from a *different* namespace
    # must never equal the real adapter namespace ids. The C++ test asserts
    # inequality; if the C++ encoder ever degraded to plain hashing of the
    # name, this guard has a real chance of catching it.
    probe_parts = ["document", "W1"]
    real_id = adapter.stable_entity_id(*probe_parts)
    wrong_namespace_id = str(uuid.uuid5(uuid.UUID(int=7), "|".join(probe_parts)))
    assert real_id != wrong_namespace_id
    cases.append({
        "name": "uuid_negative_self_check",
        "input": None,
        "expected": None,
        "submit": None,
        "negative": {
            "parts": probe_parts,
            "real_id": real_id,
            "must_not_equal": wrong_namespace_id,
        },
    })

    fixture = {
        "schema": "pwb.welllog.adapter_oracle/1",
        "generator": "tests/cpp/science/fixtures/welllog/generate_oracle.py",
        "source_of_truth": "paleo_workbench/viz/welllog_engine_adapter.py",
        "cases": cases,
    }

    out_path = HERE / "welllog_adapter_oracle.json"
    out_path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    # Self-check: re-read and validate.
    reloaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert reloaded["schema"] == fixture["schema"]
    uuid_ok = all(
        len(entry["expected"]["document_id"]) == 36
        for entry in reloaded["cases"]
        if entry.get("expected") and entry["expected"].get("document_id")
    )
    assert uuid_ok
    negative = [c for c in reloaded["cases"]
                if c["name"] == "uuid_negative_self_check"][0]
    assert negative["negative"]["real_id"] != negative["negative"]["must_not_equal"]
    print(f"wrote {out_path} ({len(reloaded['cases'])} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
