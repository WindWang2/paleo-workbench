"""Mock 沉积相预测（well/seismic）原生 QGIS 桥端到端验证。

Usage (repo root):
  QT_QPA_PLATFORM=offscreen .venv/bin/python scratch/e2e_mock_facies_native.py

流程：rm -rf 后复制真实 project_area → /tmp/e2e_project_area（只读真实工程，
mtime 必须不变）→ offscreen QApplication + 原生桥 CompositeDocument +
DataCatalogService.open(副本) → target_horizon="Sq1" → dispatch 两个 mock
动作并做任务/血缘/叠加层/原生桥侧断言 → well mock 重复一次并断言叠加层已刷新
（无 stale）→ 逐项打印 VERDICT → reset_catalog + service.close()。

产品代码零修改；失败只记 FAIL 不抛栈；exit 0 = 全 PASS。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REAL_JSON = "/home/kevin/projects/paleo_project/data/project_area/project_area.paleo.json"
COPY_DIR = "/tmp/e2e_project_area"
COPY_JSON = os.path.join(COPY_DIR, "project_area.paleo.json")
STAGE = "facies_calibration"

results: list[tuple[str, bool, str]] = []


def record(name: str, func) -> bool:
    try:
        ok, detail = func()
        results.append((name, bool(ok), str(detail or "")))
        return bool(ok)
    except Exception as exc:  # noqa: BLE001 — 失败记 FAIL，不抛栈
        results.append((name, False, f"exception: {exc!r}"))
        return False


def main() -> int:
    real_mtime_before = os.stat(REAL_JSON).st_mtime_ns

    # ---- setup：重建副本 ----
    shutil.rmtree(COPY_DIR, ignore_errors=True)
    shutil.copytree(
        os.path.dirname(REAL_JSON), COPY_DIR, symlinks=False,
        ignore_dangling_symlinks=True,
    )

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService
    from paleo_workbench.catalog.models import DataStage
    from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
    from paleo_workbench.mapping.well_prediction_surface import (
        POINTS_LAYER_TASK_ID,
    )
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.project.manager import ProjectManager
    from paleo_workbench.ui.workstation.composite_document import (
        CompositeDocument,
    )

    project = ProjectManager(COPY_JSON).load()
    doc = CompositeDocument(project)
    doc.resize(900, 600)
    doc.show()

    def pump(seconds: float = 1.0) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)

    pump(2.0)

    service = DataCatalogService.open(COPY_JSON)
    set_catalog(CoreCatalogAdapter(service))
    try:
        project.stratigraphy.target_horizon = "Sq1"
        messages: list[str] = []
        doc.status_message.connect(messages.append)

        expected_well_ids = {
            str(r.id) for r in (getattr(project, "resources", None) or [])
            if getattr(r, "type", "") == "well_log"
        }
        expected_seismic_ids = {
            str(r.id) for r in (getattr(project, "resources", None) or [])
            if getattr(r, "type", "") == "seismic"
        }
        n_wells = len(list(getattr(project, "wells", None) or []))
        xy_wells = [
            w for w in (getattr(project, "wells", None) or [])
            if getattr(w, "project_x", None) is not None
            and getattr(w, "project_y", None) is not None
        ]
        n_xy = len(xy_wells)
        missing_xy_names = sorted({
            str(getattr(w, "name", "?")) for w in
            (getattr(project, "wells", None) or [])
        } - {str(getattr(w, "name", "?")) for w in xy_wells})
        ring = list((getattr(project, "workarea", None).boundary or []))
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        bbox = (min(xs), max(xs), min(ys), max(ys))

        def tree_ids() -> set[str]:
            payload = json.loads(doc.canvas.stack.tree_snapshot_json())
            found: set[str] = set()

            def _walk(node) -> None:
                if isinstance(node, dict):
                    nid = node.get("id")
                    if nid:
                        found.add(str(nid))
                    for child in node.get("children", []) or []:
                        _walk(child)

            _walk(payload)
            return found

        def canvas_count() -> int:
            return int(doc.canvas.stack.canvas_layer_count(
                doc.canvas.canvas_address))

        def point_layers() -> list[str]:
            state = doc.stage_controller.state
            return [
                str(lid)
                for lid in state.layers_with_role(
                    LayerRole.WELL_FACIES_PREDICTION)
                if state.membership(lid).factor_task_id == POINTS_LAYER_TASK_ID
                and doc.edit_controller.layer(str(lid)) is not None
            ]

        # ---- well mock ----
        n_before = len(project.prediction_tasks)
        doc.stage_actions.dispatch(STAGE, "run_well_facies_mock")
        pump(1.0)

        def _well_dispatched():
            ok = len(project.prediction_tasks) == n_before + 1
            return ok, (
                f"tasks {n_before}->{len(project.prediction_tasks)} "
                f"msgs={messages[-2:]}"
            )

        record("well: dispatch 产出 1 个新 task", _well_dispatched)
        well_task = (
            project.prediction_tasks[-1]
            if len(project.prediction_tasks) == n_before + 1 else None
        )

        if well_task is not None:
            def _well_task():
                s = well_task.result_summary or {}
                regions = s.get("predicted_regions") or []
                units = {r.get("stratigraphic_unit") for r in regions}
                ok = (
                    well_task.adapter_kind == "mock"
                    and s.get("is_mock") is True
                    and len(regions) == n_wells == 21
                    and units == {"Sq1"}
                )
                return ok, (
                    f"adapter={well_task.adapter_kind} "
                    f"is_mock={s.get('is_mock')} "
                    f"regions={len(regions)} units={units}"
                )

            record("well: task 结构（mock/21 井/Sq1）", _well_task)

            def _well_inputs():
                got = set((well_task.input_refs or {}).get(
                    "well_log_resource_ids") or [])
                return got == expected_well_ids and len(got) == 21, (
                    f"input_refs={len(got)} expected={len(expected_well_ids)}"
                )

            record("well: input_refs 记 21 个 well_log", _well_inputs)

            def _well_lineage():
                run = service.get_run(well_task.model_metadata["run_id"])
                stages = {
                    v.stage for v in service.document.versions
                    if v.id in set(run.output_version_ids)
                }
                ok = (
                    run.status == "complete"
                    and run.parameters.get("_domain_task_id") == well_task.id
                    and well_task.model_metadata["prediction_version_id"]
                    in run.output_version_ids
                    and DataStage.DERIVED in stages
                    and DataStage.INTERMEDIATE in stages
                )
                return ok, (
                    f"run={run.status} link={run.parameters.get('_domain_task_id') == well_task.id} "
                    f"stages={sorted(str(s) for s in stages)}"
                )

            record("well: 血缘（run complete/三向链接/DERIVED+INTERMEDIATE）",
                   _well_lineage)

            def _well_overlay():
                ids = doc.stage_controller.state.layers_with_role(
                    LayerRole.WELL_FACIES_PREDICTION)
                pls = point_layers()
                n_feat = -1
                if pls:
                    n_feat = len(list(
                        doc.edit_controller.layer(pls[0]).features()))
                ok = bool(ids) and len(pls) == 1 and n_feat == n_xy
                return ok, (
                    f"role_layers={len(ids)} point_layers={len(pls)} "
                    f"features={n_feat} expected_xy={n_xy} "
                    f"no_xy_wells={missing_xy_names}"
                )

            record("well: 叠加层（井点层唯一/21 要素）", _well_overlay)

            def _well_native():
                pls = point_layers()
                tids = tree_ids()
                n = canvas_count()
                ok = bool(pls) and all(p in tids for p in pls) and n > 0
                return ok, (
                    f"point_layer_in_tree={bool(pls) and pls[0] in tids} "
                    f"canvas_layers={n}"
                )

            record("well: 原生桥侧（层 id 进 tree/canvas>0）", _well_native)
        else:
            for name in ("well: task 结构（mock/21 井/Sq1）",
                         "well: input_refs 记 21 个 well_log",
                         "well: 血缘（run complete/三向链接/DERIVED+INTERMEDIATE）",
                         "well: 叠加层（井点层唯一/21 要素）",
                         "well: 原生桥侧（层 id 进 tree/canvas>0）"):
                results.append((name, False, "dispatch 未产出 task，跳过"))

        # ---- seismic mock ----
        n_before = len(project.prediction_tasks)
        doc.stage_actions.dispatch(STAGE, "run_seismic_facies_mock")
        pump(1.0)

        def _seis_dispatched():
            ok = len(project.prediction_tasks) == n_before + 1
            return ok, (
                f"tasks {n_before}->{len(project.prediction_tasks)} "
                f"msgs={messages[-2:]}"
            )

        record("seismic: dispatch 产出 1 个新 task", _seis_dispatched)
        seis_task = (
            project.prediction_tasks[-1]
            if len(project.prediction_tasks) == n_before + 1 else None
        )

        if seis_task is not None:
            def _seis_task():
                s = seis_task.result_summary or {}
                spatial = s.get("spatial") or {}
                feats = spatial.get("features") or []
                in_box = True
                for f in feats:
                    for ring_ in (f.get("geometry") or {}).get(
                            "coordinates") or []:
                        for x, y in ring_:
                            if not (bbox[0] - 1 <= x <= bbox[1] + 1
                                    and bbox[2] - 1 <= y <= bbox[3] + 1):
                                in_box = False
                ok = (spatial.get("type") == "VECTOR_POLYGONS"
                      and bool(feats) and in_box)
                return ok, (
                    f"type={spatial.get('type')} features={len(feats)} "
                    f"in_workarea_bbox={in_box}"
                )

            record("seismic: task 空间结果（VECTOR_POLYGONS/工区内）",
                   _seis_task)

            def _seis_lineage():
                run = service.get_run(seis_task.model_metadata["run_id"])
                stages = {
                    v.stage for v in service.document.versions
                    if v.id in set(run.output_version_ids)
                }
                ok = (
                    run.status == "complete"
                    and run.parameters.get("extent_source")
                    == "workarea_boundary"
                    and run.parameters.get("_domain_task_id") == seis_task.id
                    and DataStage.DERIVED in stages
                    and DataStage.INTERMEDIATE in stages
                )
                return ok, (
                    f"run={run.status} "
                    f"extent_source={run.parameters.get('extent_source')} "
                    f"stages={sorted(str(s) for s in stages)}"
                )

            record("seismic: 血缘（extent_source=workarea_boundary）",
                   _seis_lineage)

            def _seis_native():
                ids = [
                    str(lid) for lid in
                    doc.stage_controller.state.layers_with_role(
                        LayerRole.SEISMIC_FACIES_PREDICTION)
                    if doc.edit_controller.layer(str(lid)) is not None
                ]
                tids = tree_ids()
                n = canvas_count()
                ok = bool(ids) and all(i in tids for i in ids) and n > 0
                return ok, (
                    f"role_layers={len(ids)} in_tree={bool(ids) and ids[0] in tids} "
                    f"canvas_layers={n}"
                )

            record("seismic: 叠加层 + 原生桥侧（进 tree/canvas>0）",
                   _seis_native)
        else:
            for name in ("seismic: task 空间结果（VECTOR_POLYGONS/工区内）",
                         "seismic: 血缘（extent_source=workarea_boundary）",
                         "seismic: 叠加层 + 原生桥侧（进 tree/canvas>0）"):
                results.append((name, False, "dispatch 未产出 task，跳过"))

        # ---- well mock 重复一次：叠加层刷新、无 stale ----
        first_well_id = well_task.id if well_task is not None else ""
        n_before = len(project.prediction_tasks)
        doc.stage_actions.dispatch(STAGE, "run_well_facies_mock")
        pump(1.0)

        def _repeat():
            ok_tasks = len(project.prediction_tasks) == n_before + 1
            second_well_id = (
                project.prediction_tasks[-1].id if ok_tasks else "")
            task_ids = {first_well_id, second_well_id} - {""}
            pls = point_layers()
            covered: set[str] = set()
            n_feat = -1
            if pls:
                layer = doc.edit_controller.layer(pls[0])
                feats = list(layer.features())
                n_feat = len(feats)
                covered = {
                    str(f.attributes.get("prediction_task_id") or "")
                    for f in feats
                }
            ok = (ok_tasks and bool(task_ids) and len(pls) == 1
                  and n_feat == 2 * n_xy and task_ids <= covered)
            return ok, (
                f"tasks {n_before}->{len(project.prediction_tasks)} "
                f"point_layers={len(pls)} features={n_feat} "
                f"expected={2 * n_xy} "
                f"covers_both_well_tasks={task_ids <= covered}"
            )

        record("well-repeat: 新 task + 井点层重建覆盖双 task（无 stale）",
               _repeat)
    finally:
        try:
            reset_catalog()
        finally:
            service.close()

    def _mtime():
        after = os.stat(REAL_JSON).st_mtime_ns
        return after == real_mtime_before, f"mtime_ns {after}"

    record("真实工程 project_area.paleo.json mtime 不变", _mtime)

    failed = [(n, d) for n, ok, d in results if not ok]
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}"
              + (f" :: {detail}" if (detail and not ok) else ""))
    print(f"VERDICT: {'ALL PASS' if not failed else f'{len(failed)} FAILED'} "
          f"({len(results) - len(failed)}/{len(results)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
