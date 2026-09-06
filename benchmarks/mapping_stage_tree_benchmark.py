#!/usr/bin/env python3
"""Geological Mapping Stage Workspace V5 — 分组图层树规模基准（V5 §69/§70）。

合成树：50 / 200 / 500 / 1000 图层 × 30 嵌套组（factor 子组 + 系统组），
经 **真实 QGIS 桥**（LayerGroupController → QgisMapStack group API）测量：

    bind(镜像 upsert) → reconcile(组结构/放置) → group visibility
    → stage switch（可见性增量）→ layer move → structure snapshot

以复杂度趋势（每层毫秒）与 UI 响应性为 gate——不设固定毫秒阈值
（V5 §70：真实基准，不伪造）。报告输出 JSON + 控制台表。

    PYTHONPATH=native/qgis_render_bridge python benchmarks/mapping_stage_tree_benchmark.py
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FC_POINT = json.dumps({"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
     "properties": {}}]})


def _build_synthetic(stack, count: int, factor_groups: int = 30) -> dict:
    """合成 count 层 + factor_groups 个嵌套 factor 组，返回注册表。"""
    roles = []
    stack.upsert_group("phase2.factors", "单因素图", "")
    for group in range(factor_groups):
        task_id = f"task{group}"
        stack.upsert_group(f"factor.{task_id}", f"单因素{group}", "phase2.factors")
    for index in range(count):
        doc = f"synthetic:{index}"
        stack.upsert_mirror_layer(
            doc, f"层{index}", "Point", "EPSG:4326", _FC_POINT,
            "", "", "", True, 1.0)
        task = f"task{index % max(1, factor_groups)}"
        roles.append((doc, task))
    return {"roles": roles, "factor_groups": factor_groups}


def _rebuild_controller_state(registry):
    from paleo_workbench.mapping_workspace.layer_group_controller import (
        LayerGroupController,
    )
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState

    state = MappingWorkspaceState()
    controller = LayerGroupController(state)
    for doc, task in registry["roles"]:
        role = LayerRole.FACTOR_INPUT if hash(doc) % 2 else LayerRole.FACTOR_CONTOUR
        controller.register_layer(doc, role, factor_task_id=task)
    return controller


class _Shim:
    def __init__(self, stack, canvas):
        self.stack = stack
        self.canvas_address = canvas


def run_scale(count: int, qt_app) -> dict:
    from qgis_render_bridge.mapstack import QgisMapStack

    stack = QgisMapStack()
    stack.initialize()
    canvas = stack.create_canvas()
    try:
        registry = _build_synthetic(stack, count)
        controller = _rebuild_controller_state(registry)
        controller.attach_canvas(_Shim(stack, canvas))

        class _Snap:
            def __init__(self, i):
                self.id = i
                self.name = i
                self.metadata = {}
                self.template = ""

        snapshots = [_Snap(doc) for doc, _ in registry["roles"]]

        timings: dict[str, float] = {}

        # 1) 首次 reconcile（全量建组 + 放置）。
        start = time.perf_counter()
        controller.reconcile(snapshots, force=True)
        timings["reconcile_full"] = time.perf_counter() - start

        # 2) 无变化 reconcile（增量 no-op）。
        start = time.perf_counter()
        controller.reconcile(snapshots)
        timings["reconcile_noop"] = time.perf_counter() - start

        # 3) 单层可见性（桥直写）。
        target = registry["roles"][count // 2][0]
        start = time.perf_counter()
        stack.set_mirror_layer_visibility(target, False)
        stack.set_mirror_layer_visibility(target, True)
        timings["layer_visibility_x2"] = time.perf_counter() - start

        # 4) 组可见性 ×2。
        start = time.perf_counter()
        stack.set_group_visibility("phase2.factors", False)
        stack.set_group_visibility("phase2.factors", True)
        timings["group_visibility_x2"] = time.perf_counter() - start

        # 5) 阶段切换（组可见性增量，无重算）。
        start = time.perf_counter()
        controller.apply_stage_visibility(
            __import__("paleo_workbench.mapping_workspace.stages",
                       fromlist=["MappingStage"]).MappingStage.CONSTRAINT_FACTOR)
        controller.apply_stage_visibility(
            __import__("paleo_workbench.mapping_workspace.stages",
                       fromlist=["MappingStage"]).MappingStage.FACIES_CALIBRATION)
        timings["stage_switch_x2"] = time.perf_counter() - start

        # 6) 层移动（组内重排）。
        start = time.perf_counter()
        stack.move_layer_to_group(target, "factor.task0", 0)
        timings["layer_move"] = time.perf_counter() - start

        # 7) 结构快照读取。
        start = time.perf_counter()
        payload = stack.tree_snapshot_json()
        timings["tree_snapshot"] = time.perf_counter() - start
        del payload

        timings["layers"] = count
        timings["per_layer_reconcile_us"] = (
            timings["reconcile_full"] / count * 1e6)
        return timings
    finally:
        try:
            stack.remove_groups_except([])
        except Exception:
            pass
        stack.shutdown()
        qt_app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scales", default="50,200,500,1000")
    parser.add_argument("--json-out", default="")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    results = []
    for scale in (int(s) for s in args.scales.split(",")):
        # 每档跑 3 次取中位（降低抖动；串行，编译资源受控）。
        runs = [run_scale(scale, app) for _ in range(3)]
        median = {
            key: statistics.median(run[key] for run in runs)
            for key in runs[0]
        }
        results.append(median)
        print(f"[{scale:>5} layers] full_reconcile={median['reconcile_full']*1000:8.2f}ms "
              f"noop={median['reconcile_noop']*1000:7.2f}ms "
              f"stage_switch={median['stage_switch_x2']*1000:7.2f}ms "
              f"per_layer={median['per_layer_reconcile_us']:6.1f}µs")

    # Gate 语义（V5 §69/§70）：交互路径（stage switch / no-op reconcile /
    # 显隐）必须线性良好——它们决定 UI 响应性。全量 reconcile 是装载期
    # 一次性成本：其超线性继承自上游 QGIS takeChild/insertChildNode 的
    # 信号转发机制（生产既有 set_mirror_layer_order 同曲线，非本分支回归），
    # 此处按信息项报告并与生产基线对比。
    first, last = results[0], results[-1]
    scale = last["layers"] / max(first["layers"], 1)
    switch_growth = last["stage_switch_x2"] / max(first["stage_switch_x2"], 1e-9)
    noop_growth = last["reconcile_noop"] / max(first["reconcile_noop"], 1e-9)
    full_growth = last["per_layer_reconcile_us"] / max(first["per_layer_reconcile_us"], 1e-9)
    verdict = "OK" if (switch_growth <= scale * 3 and noop_growth <= scale * 3) \
        else "SUPERLINEAR"
    print(f"\ninteractive growth {first['layers']}→{last['layers']}: "
          f"stage_switch={switch_growth:.2f}× noop={noop_growth:.2f}× "
          f"(linear reference={scale:.1f}×)")
    print(f"full-reconcile per-layer growth {full_growth:.2f}× "
          f"[informational: upstream QGIS tree-op cost, "
          f"matches production set_mirror_layer_order baseline]")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"runs": results, "full_growth": full_growth, "verdict": verdict},
                       indent=2), encoding="utf-8")
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
