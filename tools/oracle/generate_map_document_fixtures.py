#!/usr/bin/env python3
"""Oracle fixture generator for the MapDocument / composition JSON kernel (CONV-02).

Imports the REAL Python product code (paleo_workbench.mapping.layers,
paleo_workbench.mapping.composer.*, paleo_workbench.mapping.geological_pipeline.*)
and freezes:

* map-document dicts produced by the product ``to_dict`` paths (layer default
  styles baked by real ``__post_init__`` code, pipeline documents built by the
  real ``build_factor_map_document``);
* composition dicts produced by the real ``to_dict``/``from_dict`` pair,
  including the forward-compat TEXT carrier and falsy/string coercion quirks;
* document-mutation expectations (add/remove/reorder/recompute/set_paper/
  add_element) applied by the real Python objects;
* ``composition_page_pixels`` outputs (banker's rounding incl. half-even tie).

Case kinds:
* ``expectation_source: "python-product"`` — expected value computed by running
  real product code; the C++ port must match it. Probes on these cases are
  read off the live Python objects, never hand-written.
* ``expectation_source: "identity-contract"`` — the case exercises the C++
  read/write losslessness contract itself (unknown-key extras); the expected
  value is the input carried through unchanged. No expected numbers are
  invented here.
* ``expectation_source: "cpp-read-contract"`` — the case pins a read-side
  behavior that Python product code does not define (MapDocument has no
  loader; missing element ids never reach Python's random generator). The
  expected value is derived programmatically from the documented kernel
  contract (decision D-03/D-04), not from product behavior.

Regenerate with the repo venv python (needs PySide6 for the mapping package
import chain):
    /home/kevin/projects/paleo_project/main/.venv/bin/python \
        tools/oracle/generate_map_document_fixtures.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.mapping.composer.models import (  # noqa: E402
    COMPOSITION_SCHEMA_VERSION,
    PAPER_SIZES_MM,
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.registry import get_spec  # noqa: E402
from paleo_workbench.mapping.composer.export import composition_page_pixels  # noqa: E402
from paleo_workbench.mapping.geological_pipeline.pipeline import (  # noqa: E402
    GeologicalFactor,
    GeologicalFactorDataset,
    GeologicalMappingPipeline,
)
from paleo_workbench.mapping.geological_pipeline.models import InterpolationOptions  # noqa: E402
from paleo_workbench.mapping.geological_pipeline.templates import (  # noqa: E402
    create_geological_factor_map_template,
)
from paleo_workbench.mapping.layers import (  # noqa: E402
    AnnotationMapLayer,
    ContourMapLayer,
    GridMapLayer,
    MapDocument,
    PolygonMapLayer,
    RasterMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult  # noqa: E402

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_document"
    / "mapping_document_tests"
    / "fixtures"
    / "map_document_oracle.json"
)


def _line_feature(fid: str, coords: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"name": fid},
    }


def _layer_ids(doc) -> list[str]:
    return [l.id for l in doc.layers]


def _doc_probes(doc: MapDocument) -> dict:
    """Probes computed from the live document object (never hand-written)."""
    probes: dict = {
        "layer_types": [l.layer_type for l in doc.layers],
        "input_version_ids": list(doc.input_version_ids),
        "extent": list(doc.extent),
        "active_layer_id": doc.active_layer_id,
    }
    if doc.metadata.get("run_id") is not None:
        probes["run_id"] = doc.metadata["run_id"]
    return probes


def _doc_case(cid: str, doc: MapDocument, *, expectation_source: str,
              ops: list[dict] | None = None, probes: dict | None = None) -> dict:
    doc_dict = doc.to_dict()
    return {
        "id": cid,
        "expectation_source": expectation_source,
        "input": doc_dict,
        "cpp_expected": doc_dict,
        "ops": ops or [],
        "probes": probes or {},
    }


def _small_grid_result() -> FactorGridResult:
    z = np.array(
        [[10.0, 12.0, 14.0], [12.0, 16.0, 18.0], [14.0, 18.0, 22.0]],
        dtype=np.float32,
    )
    return FactorGridResult(
        grid_z=z,
        grid_x=np.array([0.0, 5.0, 10.0], dtype=np.float64),
        grid_y=np.array([0.0, 5.0, 10.0], dtype=np.float64),
        factor_name="孔隙度",
        algorithm_id="idw",
        algorithm_parameters={"power": 2.0},
        crs="EPSG:4326",
        unit="%",
    )


def _well_dataset(n: int = 4) -> GeologicalFactorDataset:
    ds = GeologicalFactorDataset(
        factor_name="孔隙度", unit="%", target_horizon="T1", crs="EPSG:4326"
    )
    wells = [
        ("W1", "井-1", 114.10, 22.50, 18.5),
        ("W2", "井-2", 114.25, 22.52, 22.3),
        ("W3", "井-3", 114.38, 22.48, 15.2),
        ("W4", "井-4", 114.15, 22.65, 24.1),
        ("W5", "井-5", 114.30, 22.68, 19.8),
        ("W6", "井-6", 114.42, 22.62, 12.4),
    ][:n]
    for wid, wname, x, y, val in wells:
        ds.add_point(
            GeologicalFactor(
                name="孔隙度", value=val, unit="%", well_id=wid, well_name=wname,
                x=x, y=y, crs="EPSG:4326", formation="T1",
            )
        )
    return ds


def build_map_document_cases() -> list[dict]:
    cases: list[dict] = []

    # 1. empty document (all dataclass defaults; the deterministic uuid4 stub
    #    freezes the random default id)
    doc = MapDocument()
    cases.append(_doc_case(
        "empty_document", doc, expectation_source="python-product",
        ops=[],
        probes=_doc_probes(doc),
    ))

    # 2. titled document with metadata (run_id view)
    doc = MapDocument(
        id="map_t1", title="T1 沉积相图", crs="EPSG:3857",
        extent=(1.0, 2.0, 3.5, 4.25),
        metadata={"run_id": "run_9", "author": "测试"},
        active_layer_id=None,
    )
    cases.append(_doc_case(
        "titled_document", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 3. single vector layer: real default line style baked by __post_init__,
    #    extent recomputed from features (degenerate-pad contract).
    vec = VectorMapLayer(
        id="lyr_vec", name="断层", crs="EPSG:4326",
        features=(_line_feature("f_1", [[0.0, 0.0], [4.0, 3.0]]),),
    )
    doc = MapDocument(id="map_vec", title="矢量")
    doc.add_layer(vec)
    cases.append(_doc_case(
        "single_vector_layer", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 4. single grid layer: style baked by GridMapLayer.__post_init__ from a
    #    real FactorGridResult (statistics-driven value_range). to_dict keeps
    #    the base 13-key shape — grid arrays never enter JSON.
    grid = GridMapLayer(id="grid_孔隙度", name="孔隙度 连续分布栅格",
                        grid_result=_small_grid_result())
    doc = MapDocument(id="map_grid", title="网格")
    doc.add_layer(grid)
    cases.append(_doc_case(
        "single_grid_layer", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 5. grid layer without a result: explicit arrays drive extent/value_range.
    z = np.array([[1.0, np.nan], [3.0, 7.0]], dtype=np.float32)
    grid2 = GridMapLayer(
        id="grid_raw", name="raw",
        grid_z=z, grid_x=np.array([100.0, 110.0]), grid_y=np.array([30.0, 35.0]),
    )
    doc = MapDocument(id="map_grid_raw", title="raw grid")
    doc.add_layer(grid2)
    cases.append(_doc_case(
        "grid_layer_raw_arrays", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 6. contour + well + polygon via the REAL pipeline (idw, small grid).
    pipeline = GeologicalMappingPipeline()
    ds = _well_dataset(6)
    opts = InterpolationOptions(method="idw", grid_n=6, color_ramp="porosity")
    doc = pipeline.build_factor_map_document(
        ds, opts,
        include_grid=True, include_contours=True, include_wells=True,
        include_polygons=True, title="T1 孔隙度分布图",
        run_id="run_2026", input_version_ids=["ver_a", "ver_b"],
    )
    cases.append(_doc_case(
        "pipeline_full_document", doc, expectation_source="python-product",
probes=_doc_probes(doc),
    ))

    # 7. pipeline grid-only document.
    doc = pipeline.build_factor_map_document(
        _well_dataset(4), InterpolationOptions(method="idw", grid_n=5),
        include_grid=True, include_contours=False, include_wells=False,
    )
    cases.append(_doc_case(
        "pipeline_grid_only", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 8. pipeline with annotations.
    doc = pipeline.build_factor_map_document(
        _well_dataset(4), InterpolationOptions(method="idw", grid_n=5),
        include_grid=True, include_contours=False, include_wells=False,
        include_annotations=True,
        annotations=[
            {"text": "物源方向 →", "x": 114.2, "y": 22.6, "font_size": 10.0},
            {"text": "湖区", "x": 114.4, "y": 22.5, "rotation": 15.0},
        ],
    )
    cases.append(_doc_case(
        "pipeline_annotations", doc, expectation_source="python-product",
        probes={"layer_types": ["grid", "annotation"]},
    ))

    # 9. annotation layer with real add_annotation (ids frozen as produced).
    ann = AnnotationMapLayer(id="ann_1", name="标注", crs="EPSG:4326")
    ann.add_annotation("古隆起轴线", 108.0, 38.0, font_size=12.0,
                       color="#f1c40f", rotation=45.0)
    ann.add_annotation("Depocenter >4500m & <5000m", 112.0, 34.0)
    doc = MapDocument(id="map_ann", title="标注图")
    doc.add_layer(ann)
    cases.append(_doc_case(
        "annotation_layer_direct", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 10. raster layer: source_path must NOT appear in JSON (13-key contract).
    doc = MapDocument(id="map_raster", title="遥感底图")
    doc.add_layer(RasterMapLayer(
        id="rast_1", name="卫星影像", source_path="/tmp/fake_dem.tif",
        extent=(100.0, 30.0, 120.0, 50.0), crs="EPSG:4326",
        style={"opacity": 0.8},
    ))
    cases.append(_doc_case(
        "raster_layer_no_source_path", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 11. missing CRS everywhere (empty crs strings survive round-trip).
    doc = MapDocument(id="map_nocrs", title="无 CRS")
    doc.add_layer(VectorMapLayer(id="lyr_a", name="A",
                                 features=(_line_feature("fa", [[0.0, 0.0], [1.0, 1.0]]),)))
    cases.append(_doc_case(
        "missing_crs", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 12. scale_range set / None on two layers.
    doc = MapDocument(id="map_scale", title="比例尺范围")
    l1 = VectorMapLayer(id="lyr_s1", name="S1",
                        features=(_line_feature("fs", [[0.0, 0.0], [2.0, 2.0]]),))
    l1.scale_range = (500.0, 10000.0)
    doc.add_layer(l1)
    doc.add_layer(WellPointMapLayer(id="well_s2", name="S2", factor_name="孔隙度",
                                    unit="%",
                                    features=({
                                        "type": "Feature", "id": "wf",
                                        "geometry": {"type": "Point",
                                                     "coordinates": [3.0, 4.0]},
                                        "properties": {"name": "W1"},
                                    },)))
    cases.append(_doc_case(
        "scale_range", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 13. input_version_ids dedup probe (metadata list + layer sources).
    doc = MapDocument(id="map_ver", title="版本")
    doc.metadata["input_version_ids"] = ["ver_a", "ver_b"]
    for lid, vid in (("lyr_v1", "ver_b"), ("lyr_v2", "ver_c"), ("lyr_v3", "")):
        lyr = VectorMapLayer(id=lid, name=lid)
        lyr.source_version_id = vid
        doc.add_layer(lyr)
    cases.append(_doc_case(
        "input_version_ids_dedup", doc, expectation_source="python-product",
        probes=_doc_probes(doc),
    ))

    # 14/15. mutation ops frozen from the real Python objects.
    base = MapDocument(id="map_ops", title="操作", crs="EPSG:4326")
    la = VectorMapLayer(id="lyr_a", name="A",
                        features=(_line_feature("fa", [[0.0, 0.0], [1.0, 1.0]]),))
    lb = GridMapLayer(id="lyr_b", name="B", grid_result=_small_grid_result())
    lc = ContourMapLayer(id="lyr_c", name="C", levels=[10.0, 20.0],
                         features=(_line_feature("fc", [[2.0, 2.0], [3.0, 3.0]]),))
    base.add_layer(la)
    base.add_layer(lb)
    base.add_layer(lc)

    removed = copy.deepcopy(base)
    removed_layer = removed.remove_layer("lyr_a")
    assert removed_layer is not None and removed_layer.id == "lyr_a"
    op = {
        "op": "remove_layer", "args": ["lyr_a"],
        "expect": removed.to_dict(),
        "returns": removed_layer.to_dict(),
        "probes": {"active_layer_id": removed.active_layer_id},
    }
    cases.append(_doc_case(
        "op_remove_active_layer", base, expectation_source="python-product",
        ops=[op], probes={"active_layer_id": "lyr_a"},
    ))

    removed2 = copy.deepcopy(base)
    removed2_layer = removed2.remove_layer("lyr_b")
    assert removed2_layer is not None and removed2_layer.id == "lyr_b"
    op2 = {
        "op": "remove_layer", "args": ["lyr_b"],
        "expect": removed2.to_dict(),
        "returns": removed2_layer.to_dict(),
        "probes": {"active_layer_id": removed2.active_layer_id},
    }
    cases.append(_doc_case(
        "op_remove_other_layer", base, expectation_source="python-product",
        ops=[op2],
    ))

    unchanged = copy.deepcopy(base)
    assert unchanged.remove_layer("nope") is None
    cases.append(_doc_case(
        "op_remove_missing_layer", base, expectation_source="python-product",
        ops=[{"op": "remove_layer", "args": ["nope"], "expect": unchanged.to_dict(),
              "returns": None}],
    ))

    reordered = copy.deepcopy(base)
    reordered.reorder_layers(["lyr_c", "lyr_a"])
    cases.append(_doc_case(
        "op_reorder_layers", base, expectation_source="python-product",
        ops=[{
            "op": "reorder_layers", "args": [["lyr_c", "lyr_a"]],
            "expect": reordered.to_dict(),
            "probes": {"layer_ids": _layer_ids(reordered)},
        }],
    ))

    added = copy.deepcopy(base)
    new_layer = PolygonMapLayer(
        id="lyr_new", name="新增相带",
        features=({
            "type": "Feature", "id": "pf",
            "geometry": {"type": "Polygon",
                         "coordinates": [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]]},
            "properties": {"facies_name": "三角洲"},
        },),
    )
    added.add_layer(new_layer, position=0)
    cases.append(_doc_case(
        "op_add_layer_position0", base, expectation_source="python-product",
        ops=[{
            "op": "add_layer", "args": [new_layer.to_dict()], "position": 0,
            "expect": added.to_dict(),
            "probes": {"layer_ids": _layer_ids(added)},
        }],
    ))

    # 16. recompute_extent: hidden and sentinel layers excluded.
    ext_doc = MapDocument(id="map_ext", title="范围聚合",
                          extent=(0.0, 0.0, 1.0, 1.0))
    e1 = VectorMapLayer(id="lyr_e1", name="E1", extent=(10.0, 20.0, 30.0, 40.0))
    e2 = VectorMapLayer(id="lyr_e2", name="E2", extent=(-5.0, -6.0, 15.0, 25.0))
    e2.visible = False
    e3 = VectorMapLayer(id="lyr_e3", name="E3")  # sentinel extent stays
    ext_doc.add_layer(e1)
    ext_doc.add_layer(e2)
    ext_doc.add_layer(e3)
    recomputed = copy.deepcopy(ext_doc)
    recomputed.recompute_extent()
    cases.append(_doc_case(
        "op_recompute_extent", ext_doc, expectation_source="python-product",
        ops=[{
            "op": "recompute_extent", "args": [],
            "expect": recomputed.to_dict(),
        }],
        probes={"extent": list(recomputed.extent)},
    ))

    # 17. identity-contract: unknown keys anywhere survive the C++ round trip.
    extras_doc = {
        "id": "map_extras",
        "title": "多余字段",
        "crs": "EPSG:4326",
        "extent": [0.0, 0.0, 10.0, 10.0],
        "layers": [
            {
                "id": "lyr_x", "name": "X", "layer_type": "vector",
                "extent": [0.0, 0.0, 1.0, 1.0], "crs": "",
                "data_revision": 1, "style_revision": 1, "visible": True,
                "opacity": 1.0, "scale_range": None,
                "style": {}, "metadata": {}, "source_version_id": "",
                "features": [],
                "future_layer_field": {"keep": True},
            },
            {
                "id": "lyr_g", "name": "G", "layer_type": "grid",
                "extent": [0.0, 0.0, 1.0, 1.0], "crs": "",
                "data_revision": 1, "style_revision": 1, "visible": True,
                "opacity": 1.0, "scale_range": None,
                "style": {"color_ramp": "viridis", "value_range": None,
                          "unit": "", "opacity": 1.0},
                "metadata": {}, "source_version_id": "",
                # features on a base-family layer are unknown keys, not payload
                "features": [{"unexpected": True}],
            },
        ],
        "metadata": {},
        "active_layer_id": None,
        "future_doc_field": [1, 2, 3],
    }
    cases.append({
        "id": "extras_roundtrip",
        "expectation_source": "identity-contract",
        "input": extras_doc,
        "cpp_expected": extras_doc,
        "ops": [],
        "probes": {},
    })

    # 18. identity-contract: unknown layer_type keeps base shape verbatim.
    unknown_type_doc = {
        "id": "map_unknown", "title": "未知层型", "crs": "EPSG:4326",
        "extent": [0.0, 0.0, 1.0, 1.0],
        "layers": [
            {"id": "lyr_h", "name": "H", "layer_type": "hologram_layer",
             "extent": [0.0, 0.0, 1.0, 1.0], "crs": "", "data_revision": 2,
             "style_revision": 3, "visible": False, "opacity": 0.5,
             "scale_range": [1.0, 2.0], "style": {"custom": "yes"},
             "metadata": {"k": "v"}, "source_version_id": "ver_h"},
        ],
        "metadata": {}, "active_layer_id": "lyr_h",
    }
    cases.append({
        "id": "unknown_layer_type_roundtrip",
        "expectation_source": "identity-contract",
        "input": unknown_type_doc,
        "cpp_expected": unknown_type_doc,
        "ops": [],
        "probes": {},
    })

    # 19. identity-contract: trimmed layer dict → scalar defaults filled,
    #     style stays {} (C++ read contract; Python construction would bake a
    #     default style, which is a DIFFERENT operation — see D-03/D-13).
    trimmed_doc = {
        "id": "map_trim", "title": "精简", "crs": "EPSG:4326",
        "extent": [0.0, 0.0, 1.0, 1.0],
        "layers": [{"id": "lyr_t", "layer_type": "vector"}],
        "metadata": {},
    }
    trimmed_expected = {
        "id": "map_trim", "title": "精简", "crs": "EPSG:4326",
        "extent": [0.0, 0.0, 1.0, 1.0],
        "layers": [{
            "id": "lyr_t", "name": "Untitled Layer", "layer_type": "vector",
            "extent": [0.0, 0.0, 1.0, 1.0], "crs": "",
            "data_revision": 1, "style_revision": 1, "visible": True,
            "opacity": 1.0, "scale_range": None,
            "style": {}, "metadata": {}, "source_version_id": "",
            "features": [],
        }],
        "metadata": {},
        "active_layer_id": None,
    }
    cases.append({
        "id": "trimmed_document_defaults",
        # C++ read contract only: Python has no MapDocument loader, so the
        # scalar-default fill is defined by this kernel (D-03), not by any
        # Python product path.
        "expectation_source": "cpp-read-contract",
        "input": trimmed_doc,
        "cpp_expected": trimmed_expected,
        "ops": [],
        "probes": {},
    })

    return cases


def _comp_case(cid: str, comp: MapCompositionDocument, *, expectation_source: str,
               ops: list[dict] | None = None, probes: dict | None = None) -> dict:
    doc_dict = comp.to_dict()
    # Product idempotency guard: from_dict(to_dict(x)) serializes to the same
    # dict for in-process documents (asserted by the pytest suite, re-asserted
    # here so a fixture can never freeze a non-idempotent shape).
    restored = MapCompositionDocument.from_dict(doc_dict).to_dict()
    if expectation_source == "python-product":
        assert restored == doc_dict, f"{cid}: composition to_dict not idempotent"
    return {
        "id": cid,
        "expectation_source": expectation_source,
        "input": doc_dict,
        "cpp_expected": doc_dict,
        "python_roundtrip": restored,
        "ops": ops or [],
        "probes": probes or {},
    }


def build_composition_cases() -> list[dict]:
    cases: list[dict] = []

    # 1. empty composition (defaults + schema_version 2).
    cases.append(_comp_case(
        "empty_composition",
        MapCompositionDocument(id="comp_empty", title=""),
        expectation_source="python-product",
        probes={"schema_version": COMPOSITION_SCHEMA_VERSION},
    ))

    # 2. all 24 element types with real registry default properties
    #    (tuples become arrays through the real to_dict path).
    comp = MapCompositionDocument(id="comp_all_types", title="全组件")
    for i, etype in enumerate(ElementType):
        spec = get_spec(etype)
        comp.add_element(ComposerElement(
            id=f"el_{i:02d}", element_type=etype,
            x_mm=10.0 + i, y_mm=20.0, width_mm=40.0, height_mm=30.0,
            z_index=i % 5, properties=copy.deepcopy(dict(spec.default_properties)),
        ))
    cases.append(_comp_case(
        "all_element_types", comp, expectation_source="python-product",
        probes={"element_count": len(ElementType)},
    ))

    # 3. unknown element type → TEXT carrier with _raw_element_type marker;
    #    real from_dict restores the raw type on re-serialization.
    comp = MapCompositionDocument(id="comp_carrier", title="载体")
    comp.add_element(ComposerElement(
        id="el_holo", element_type=ElementType.TEXT,
        x_mm=1.0, y_mm=2.0, width_mm=3.0, height_mm=4.0,
        properties={"text": "未来组件"},
    ))
    raw = comp.to_dict()
    raw["elements"][0]["element_type"] = "hologram_3d"
    restored = MapCompositionDocument.from_dict(raw)
    assert restored.to_dict()["elements"][0]["element_type"] == "hologram_3d"
    cases.append({
        "id": "unknown_element_carrier",
        "expectation_source": "python-product",
        "input": raw,
        "cpp_expected": restored.to_dict(),
        "python_roundtrip": restored.to_dict(),
        "ops": [],
        "probes": {"element_id": "el_holo", "carried_raw_type": True},
    })

    # 4. _raw_element_type as plain data on a genuine TEXT element:
    #    to_dict POPS it and uses it as the element_type (real Python quirk).
    #    The input dict is hand-built (to_dict would pop the marker before we
    #    can freeze the input); the EXPECTATION still comes from real
    #    from_dict().to_dict() below.
    marker_input = {
        "id": "comp_marker", "title": "标记",
        "paper_size": "A4", "orientation": "landscape",
        "width_mm": 297.0, "height_mm": 210.0, "dpi": 300.0,
        "schema_version": 2,
        "elements": [{
            "id": "el_mk", "element_type": "text",
            "x_mm": 1.0, "y_mm": 2.0, "width_mm": 3.0, "height_mm": 4.0,
            "z_index": 0, "visible": True, "locked": False,
            "properties": {"text": "hi", "_raw_element_type": "legend_3d"},
        }],
        "metadata": {},
    }
    marker_roundtrip = MapCompositionDocument.from_dict(marker_input).to_dict()
    assert marker_roundtrip["elements"][0]["element_type"] == "legend_3d"
    cases.append({
        "id": "raw_marker_pop_quirk",
        "expectation_source": "python-product",
        "input": marker_input,
        "cpp_expected": marker_roundtrip,
        "python_roundtrip": marker_roundtrip,
        "ops": [],
        "probes": {},
    })

    # 5. missing element fields → real from_dict defaults.
    sparse = {
        "id": "comp_sparse", "title": "稀疏",
        "paper_size": "A4", "orientation": "landscape",
        "width_mm": 297.0, "height_mm": 210.0, "dpi": 300.0,
        "schema_version": 2,
        "elements": [
            {"id": "e1", "element_type": "title"},
            {"id": "e2", "element_type": "grid", "x_mm": 5.0},
        ],
        "metadata": {},
    }
    sparse_restored = MapCompositionDocument.from_dict(sparse).to_dict()
    cases.append({
        "id": "missing_element_fields",
        "expectation_source": "python-product",
        "input": sparse,
        "cpp_expected": sparse_restored,
        "python_roundtrip": sparse_restored,
        "ops": [],
        "probes": {},
    })

    # 6. falsy fields: 0 collapses to the default via `or` (width_mm 0 → 1.0,
    #    doc width 0 → 297.0, dpi 0 → 300.0); visible/locked use get(default).
    falsy = {
        "id": "comp_falsy", "title": "", "paper_size": "A4",
        "orientation": "landscape", "width_mm": 0, "height_mm": 210.0,
        "dpi": 0, "schema_version": 2,
        "elements": [{
            "id": "ef", "element_type": "title", "x_mm": 0, "y_mm": 0,
            "width_mm": 0, "height_mm": 0, "z_index": 0,
            "visible": False, "locked": False,
            "properties": {"text": "t"},
        }],
        "metadata": {},
    }
    falsy_roundtrip = MapCompositionDocument.from_dict(falsy).to_dict()
    elem = falsy_roundtrip["elements"][0]
    assert elem["width_mm"] == 1.0 and elem["height_mm"] == 1.0
    assert elem["visible"] is False and elem["locked"] is False
    assert falsy_roundtrip["width_mm"] == 297.0 and falsy_roundtrip["dpi"] == 300.0
    cases.append({
        "id": "falsy_fields_collapse_to_defaults",
        "expectation_source": "python-product",
        "input": falsy,
        "cpp_expected": falsy_roundtrip,
        "python_roundtrip": falsy_roundtrip,
        "ops": [],
        "probes": {},
    })

    # 7. string coercion: float("12.5"), int("3"), bool("") → False.
    coerced = {
        "id": "comp_str", "title": "字符串", "paper_size": "A4",
        "orientation": "landscape", "width_mm": "297.5", "height_mm": 210.0,
        "dpi": "300", "schema_version": 2,
        "elements": [{
            "id": "es", "element_type": "text", "x_mm": "12.5", "y_mm": 0,
            "width_mm": "8", "height_mm": 4.0, "z_index": "3",
            "visible": "", "locked": "yes", "properties": {},
        }],
        "metadata": {},
    }
    coerced_rt = MapCompositionDocument.from_dict(coerced).to_dict()
    el = coerced_rt["elements"][0]
    assert el["x_mm"] == 12.5 and el["width_mm"] == 8.0 and el["z_index"] == 3
    assert el["visible"] is False and el["locked"] is True
    assert coerced_rt["width_mm"] == 297.5 and coerced_rt["dpi"] == 300.0
    cases.append({
        "id": "string_coercion",
        "expectation_source": "python-product",
        "input": coerced,
        "cpp_expected": coerced_rt,
        "python_roundtrip": coerced_rt,
        "ops": [],
        "probes": {},
    })

    # 8. locked survives the round trip (registry test contract).
    comp = MapCompositionDocument(id="comp_lock", title="锁定")
    comp.add_element(ComposerElement(
        id="el_lock", element_type=ElementType.NEATLINE,
        x_mm=1.0, y_mm=1.0, width_mm=10.0, height_mm=10.0,
        locked=True, properties={"line_width_mm": 0.8},
    ))
    cases.append(_comp_case(
        "locked_roundtrip", comp, expectation_source="python-product",
        probes={"element_id": "el_lock", "locked": True},
    ))

    # 9. metadata verbatim (unicode + ints), unknown top-level key dropped by
    #    Python but PRESERVED by the C++ extras contract (§7.4) → the C++
    #    expectation is the input itself, python_roundtrip documents the drop.
    meta_input = {
        "id": "comp_meta", "title": "元数据", "paper_size": "A4",
        "orientation": "landscape", "width_mm": 297.0, "height_mm": 210.0,
        "dpi": 300.0, "schema_version": 7, "elements": [],
        "metadata": {"模板": "single_factor", "版本": 3, "tags": ["a", "b"]},
        "future_top_key": {"dropped": "by-python"},
    }
    meta_rt = MapCompositionDocument.from_dict(meta_input).to_dict()
    assert "future_top_key" not in meta_rt
    assert meta_rt["schema_version"] == 2
    # C++ contract: schema_version is canonicalized like Python, but the
    # unknown top-level key survives in extras (§7.4) — so the C++ expectation
    # is the input with only schema_version normalized.
    meta_cpp = copy.deepcopy(meta_input)
    meta_cpp["schema_version"] = COMPOSITION_SCHEMA_VERSION
    cases.append({
        "id": "metadata_and_top_level_extras",
        "expectation_source": "cpp-read-contract",
        "input": meta_input,
        "cpp_expected": meta_cpp,
        "python_roundtrip": meta_rt,
        "ops": [],
        "probes": {},
    })

    # 10. add_element z-sort with a stable tie (real add_element path).
    comp = MapCompositionDocument(id="comp_z", title="排序")
    comp.add_element(ComposerElement(id="el_z2", element_type=ElementType.TITLE,
                                     x_mm=1.0, y_mm=1.0, width_mm=5.0,
                                     height_mm=2.0, z_index=2))
    comp.add_element(ComposerElement(id="el_z0a", element_type=ElementType.TEXT,
                                     x_mm=2.0, y_mm=2.0, width_mm=5.0,
                                     height_mm=2.0, z_index=0))
    comp.add_element(ComposerElement(id="el_z1", element_type=ElementType.LEGEND,
                                     x_mm=3.0, y_mm=3.0, width_mm=5.0,
                                     height_mm=2.0, z_index=1))
    after_add = copy.deepcopy(comp)
    new_elem = ComposerElement(
        id="el_z0b", element_type=ElementType.NORTH_ARROW,
        x_mm=4.0, y_mm=4.0, width_mm=5.0, height_mm=2.0, z_index=0)
    after_add.add_element(copy.deepcopy(new_elem))
    order = [e.id for e in after_add.elements]
    assert order == ["el_z0a", "el_z0b", "el_z1", "el_z2"], order
    cases.append(_comp_case(
        "add_element_stable_zsort", comp, expectation_source="python-product",
        ops=[{
            "op": "add_element",
            "args": [new_elem.to_dict()],
            "expect": after_add.to_dict(),
            "probes": {"element_ids_zorder": order},
        }],
        probes={"element_ids_zorder": [e.id for e in comp.elements]},
    ))

    # 11. set_paper: portrait/landscape geometry + validation error.
    comp = MapCompositionDocument(id="comp_paper", title="纸张")
    a3 = copy.deepcopy(comp)
    a3.set_paper("a3", "portrait")
    assert (a3.width_mm, a3.height_mm, a3.paper_size) == (297.0, 420.0, "A3")
    cases.append(_comp_case(
        "set_paper_portrait_a3", comp, expectation_source="python-product",
        ops=[{
            "op": "set_paper", "args": ["a3", "portrait"],
            "expect": a3.to_dict(),
        }],
    ))
    try:
        comp.set_paper("b5", "landscape")
        raise AssertionError("set_paper('b5') must raise")
    except ValueError as exc:
        error_message = str(exc)
    cases.append({
        "id": "set_paper_unknown_size_error",
        "expectation_source": "python-product",
        "input": comp.to_dict(),
        "cpp_expected": comp.to_dict(),
        "python_roundtrip": comp.to_dict(),
        "ops": [{
            "op": "set_paper_error", "args": ["b5", "landscape"],
            "error": error_message,
        }],
        "probes": {},
    })

    # 12. __ref__ stub properties survive verbatim (identity-contract).
    stub_input = {
        "id": "comp_stub", "title": "引用", "paper_size": "A4",
        "orientation": "landscape", "width_mm": 297.0, "height_mm": 210.0,
        "dpi": 300.0, "schema_version": 2,
        "elements": [{
            "id": "elem_main_map", "element_type": "main_map",
            "x_mm": 12.0, "y_mm": 24.0, "width_mm": 185.0, "height_mm": 142.0,
            "z_index": 1, "visible": True, "locked": False,
            "properties": {
                "map_document": {"__ref__": "map_document",
                                 "id": "map_孔隙度", "layer_count": 4},
                "extent": [114.1, 22.48, 114.42, 22.82],
            },
        }],
        "metadata": {},
    }
    cases.append({
        "id": "ref_stub_properties",
        "expectation_source": "identity-contract",
        "input": stub_input,
        "cpp_expected": stub_input,
        "python_roundtrip": MapCompositionDocument.from_dict(stub_input).to_dict(),
        "ops": [],
        "probes": {},
    })

    # 13. geological factor template via the REAL factory (fixed elem ids).
    pipeline = GeologicalMappingPipeline()
    map_doc = pipeline.build_factor_map_document(
        _well_dataset(4), InterpolationOptions(method="idw", grid_n=6),
        include_grid=True, include_contours=True, include_wells=True,
        title="T1 孔隙度分布图",
    )
    composition = create_geological_factor_map_template(
        map_doc, title="T1 孔隙度分布图", factor_name="孔隙度", unit="%",
    )
    # 14. missing element id: Python generates a random one; the kernel
    #     keeps "" (D-04) — cpp-read-contract, expectation built here.
    no_id = {
        "id": "comp_noid", "title": "缺 id", "paper_size": "A4",
        "orientation": "landscape", "width_mm": 297.0, "height_mm": 210.0,
        "dpi": 300.0, "schema_version": 2,
        "elements": [{
            "element_type": "text", "x_mm": 1.0, "y_mm": 1.0,
            "width_mm": 2.0, "height_mm": 2.0, "z_index": 0,
            "visible": True, "locked": False, "properties": {"text": "x"},
        }],
        "metadata": {},
    }
    no_id_cpp = copy.deepcopy(no_id)
    no_id_cpp["elements"][0]["id"] = ""
    cases.append({
        "id": "missing_element_id_cpp_read_contract",
        "expectation_source": "cpp-read-contract",
        "input": no_id,
        "cpp_expected": no_id_cpp,
        "python_roundtrip": None,
        "ops": [],
        "probes": {},
    })

    # 15. carried unknown type whose properties ALREADY carry a different
    #     _raw_element_type: setdefault keeps the payload's marker (real
    #     from_dict semantics), and to_dict uses it as the element type.
    pre_marker = {
        "id": "comp_pre_marker", "title": "预置标记",
        "paper_size": "A4", "orientation": "landscape",
        "width_mm": 297.0, "height_mm": 210.0, "dpi": 300.0,
        "schema_version": 2,
        "elements": [{
            "id": "el_pm", "element_type": "holo_v9",
            "x_mm": 1.0, "y_mm": 2.0, "width_mm": 3.0, "height_mm": 4.0,
            "z_index": 0, "visible": True, "locked": False,
            "properties": {"text": "x",
                           "_raw_element_type": "holo_v8"},
        }],
        "metadata": {},
    }
    pre_marker_rt = MapCompositionDocument.from_dict(pre_marker).to_dict()
    assert pre_marker_rt["elements"][0]["element_type"] == "holo_v8"
    cases.append({
        "id": "carried_preexisting_marker_wins",
        "expectation_source": "python-product",
        "input": pre_marker,
        "cpp_expected": pre_marker_rt,
        "python_roundtrip": pre_marker_rt,
        "ops": [],
        "probes": {},
    })

    cases.append(_comp_case(
        "geological_factor_template", composition,
        expectation_source="python-product",
        probes={
            "composition_id": composition.id,
            "element_ids_zorder": [e.id for e in composition.elements],
        },
    ))

    return cases


def build_pixel_cases() -> list[dict]:
    dims = [
        (297.0, 210.0, 300.0),
        (210.0, 297.0, 300.0),
        (841.0, 1189.0, 600.0),
        (297.0, 210.0, 150.0),
        (1.143, 1.143, 100.0),   # (1.143/25.4)*100 = 4.500000000000001 in IEEE754
        (2.032, 2.032, 100.0),   # (2.032/25.4)*100 = 8.0 exact
        (0.05, 0.05, 10.0),      # < 1 px → clamped to 1
        (420.0, 594.0, 72.0),
        (13.97, 21.0, 150.0),   # (13.97/25.4)*150 = 82.5 exact → round → 82
        (24.13, 21.0, 150.0),   # (24.13/25.4)*150 = 142.5 exact → round → 142
    ]
    comp = MapCompositionDocument(id="comp_px", title="px",
                                  width_mm=297.0, height_mm=210.0)
    out = []
    for w, h, dpi in dims:
        comp.width_mm, comp.height_mm = w, h
        wpx, hpx = composition_page_pixels(comp, dpi)
        # C++ must reproduce the exact (w / 25.4) * dpi evaluation order.
        raw = (w / 25.4) * dpi
        out.append({
            "width_mm": w, "height_mm": h, "dpi": dpi,
            "raw": raw,
            "width_px": wpx, "height_px": hpx,
        })
    return out


def main() -> None:
    # Freeze the randomness of the real product paths (uuid4-based document /
    # annotation ids) so regeneration is byte-stable. The product code itself
    # is untouched — this patches the generator's import of layers.py only.
    import paleo_workbench.mapping.layers as layers_module

    class _SequentialUUID:
        def __init__(self) -> None:
            self._n = 0

        @property
        def hex(self) -> str:
            self._n += 1
            return f"{self._n:08x}6789abcdef0123456789abcdef"

    layers_module.uuid4 = _SequentialUUID

    map_cases = build_map_document_cases()
    comp_cases = build_composition_cases()
    pixel_cases = build_pixel_cases()

    paper_sizes = {
        "A5": [148.0, 210.0], "A4": [210.0, 297.0], "A3": [297.0, 420.0],
        "A2": [420.0, 594.0], "A1": [594.0, 841.0], "A0": [841.0, 1189.0],
    }
    assert paper_sizes == {k: list(v) for k, v in PAPER_SIZES_MM.items()}

    doc_n = len(map_cases)
    comp_n = len(comp_cases)
    px_n = len(pixel_cases)
    total = doc_n + comp_n + px_n
    assert total >= 30, f"fixture must freeze >= 30 cases, got {total}"

    payload = {
        "schema": "pwb.mapping_document.oracle/1",
        "map_document_cases": map_cases,
        "composition_cases": comp_cases,
        "pixel_cases": pixel_cases,
        "paper_sizes": paper_sizes,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes): "
          f"{doc_n} map-document cases, {comp_n} composition cases, "
          f"{px_n} pixel cases (total {total})")


if __name__ == "__main__":
    main()
