"""阶段上下文动作分派（V5 M6–M9）：面板动作 → 具体工作流。

动作语义按阶段（V5 §12/§19/§27）：

* Phase 1（智能预测）：叠加地震相预测、叠加测井相预测（井点；
  VECTOR_POLYGONS 仍按面叠加）、测井点到面、可选加载初始相图 /
  RAW→DERIVED 建稿、保存阶段成果。
* Phase 2：typed 约束创建（物源线/展布线/古岸线/相带边界/断层/掩膜…）、
  单因素工作台/运行（导航至既有制备 UI，不在本分支重实现插值）、
  叠加单因素结果（factor 组自动组织）。
* Phase 3：证据版本选择（Compilation Input Set）、创建综合解释草稿、
  运行 QA、生成 MapProduct。

分派器只做编排（图层创建/角色注册/溯源钉住/导航请求）；科学算法全部
复用现有 production service。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from paleo_workbench.project.models import FACTOR_TASK_STATUS_COMPLETE
from paleo_workbench.mapping_workspace.layer_roles import (
    ConstraintKind,
    LayerRole,
    constraint_kind_from_value,
)
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord

logger = logging.getLogger(__name__)


#: 阶段动作 → 工具面 tool id（V8 M6：有映射的阶段动作在执行前经
#: canonical evaluator re-gate；palette 注册与执行分派共用这一份——
#: 阶段面板按钮不再绕过 blocking/project 门禁）。
STAGE_ACTION_TOOLS: dict[str, str] = {
    "open_factor_workbench": "factor_workbench",
    "run_factor": "factor_workbench",
    "overlay_factor_results": "factor_overlay",
    "run_qa": "qa_run",
    "stage_qc": "qa_run",
    "assemble_map_product": "map_product_assemble",
}


#: 阶段上下文动作单一词表（V7 R2-F1：阶段面板按钮、palette 注册、
#: dispatcher 执行共用这一份——(action_id, label)，按阶段）。
#: 此前三套手维护表（panel._PHASEn_ACTIONS / dispatcher map / profile
#: context_actions）互不推导，存在漂移（评审 R2-F1）。
STAGE_CONTEXT_ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "facies_calibration": (
        ("add_seismic_prediction_overlay", "叠加地震相预测"),
        ("add_well_prediction_overlay", "叠加测井相预测"),
        ("well_prediction_point_to_surface", "测井点到面"),
        ("run_well_facies_mock", "运行测井相预测（mock）"),
        ("run_seismic_facies_mock", "运行地震相面预测（mock）"),
        ("load_initial_facies", "加载初始相图"),
        ("create_facies_draft", "创建解释草稿"),
        ("stage_save", "保存阶段成果"),
    ),
    "constraint_factor": (
        ("open_factor_workbench", "单因素工作台"),
        ("overlay_factor_results", "叠加单因素结果"),
        ("commit_constraints", "提交约束版本"),
        ("stage_save", "保存阶段成果"),
    ),
    "integrated_compilation": (
        ("select_evidence", "选择证据版本"),
        ("create_integrated_draft", "创建综合草稿"),
        ("run_qa", "运行 QA"),
        ("assemble_map_product", "生成 MapProduct"),
    ),
}


def stage_context_actions(stage_value: str) -> tuple[tuple[str, str], ...]:
    """某阶段的上下文动作表（未知阶段 → 空表，fail-closed）。"""
    from paleo_workbench.mapping_workspace.stages import stage_from_value

    stage = stage_from_value(str(stage_value or ""))
    if stage is None:
        return ()
    return STAGE_CONTEXT_ACTIONS.get(stage.value, ())


class StageActionDispatcher:
    """宿主为 CompositeDocument；动作结果经 status_message 反馈。"""

    def __init__(self, composite):
        self.composite = composite
        self.edit_controller = composite.edit_controller
        self.stage_controller = composite.stage_controller

    # -- 入口 -------------------------------------------------------------------

    #: 相图按层位进行：这些动作在未设定编图层位时拒绝执行。
    _REQUIRES_HORIZON = frozenset({
        "load_initial_facies",
        "add_well_prediction_overlay",
        "add_seismic_prediction_overlay",
        "well_prediction_point_to_surface",
        "run_well_facies_mock",
        "run_seismic_facies_mock",
        "toggle_prediction_confidence",
        "create_facies_draft",
        "open_factor_workbench",
        "run_factor",
        "overlay_factor_results",
        "select_evidence",
        "create_integrated_draft",
        "create_integrated_boundary",
        "run_fusion",
        "run_qa",
        "assemble_map_product",
        "stage_qc",
    })

    def dispatch(self, stage_value: str, action_id: str) -> None:
        if str(action_id) in self._REQUIRES_HORIZON and not self._mapping_horizon():
            self.composite.status_message.emit(
                "请先设定编图层位（相图按层位进行）")
            return
        handler = {
            "load_initial_facies": self.load_initial_facies,
            "add_well_prediction_overlay": self.add_well_prediction_overlay,
            "add_seismic_prediction_overlay": self.add_seismic_prediction_overlay,
            "well_prediction_point_to_surface": self.well_prediction_point_to_surface,
            "run_well_facies_mock": self.run_well_facies_mock,
            "run_seismic_facies_mock": self.run_seismic_facies_mock,
            "toggle_prediction_confidence": self.toggle_prediction_confidence,
            "create_facies_draft": self.create_facies_draft,
            "open_factor_workbench": self.open_factor_workbench,
            "run_factor": self.open_factor_workbench,
            "overlay_factor_results": self.overlay_factor_results,
            "commit_constraints": self.commit_constraints,
            "select_evidence": self.select_evidence,
            "create_integrated_draft": self.create_integrated_draft,
            "create_integrated_boundary": self.create_integrated_boundary,
            "run_fusion": self.run_fusion,
            "run_qa": self.run_qa,
            "assemble_map_product": self.assemble_map_product,
            "stage_save": self.stage_save,
            "stage_qc": self.run_qa,
        }.get(str(action_id))
        if handler is None:
            self.composite.status_message.emit(f"未知阶段动作：{action_id}")
            return
        try:
            handler()
        except Exception as exc:  # 动作失败必须可见，绝不静默
            logger.exception("stage action %s failed", action_id)
            self.composite.status_message.emit(f"阶段动作失败（{action_id}）：{exc}")

    # -- 通用辅助 ---------------------------------------------------------------

    @property
    def project(self) -> Any:
        return self.composite._project

    def _create_role_layer(
        self,
        name: str,
        kind: str,
        role: LayerRole,
        *,
        template: str = "",
        constraint_kind: str = "",
        factor_task_id: str = "",
        source_version_id: str = "",
        features: list | None = None,
    ) -> str | None:
        """创建图层 + 注册角色成员资格 + 触发组合同步；返回 layer_id。"""
        layer = self.edit_controller.create_layer(name=name, kind=kind, template=template)
        if layer is None:
            self.composite.status_message.emit(f"创建图层失败：{name}")
            return None
        self.stage_controller.group_controller.register_layer(
            layer.id, role,
            factor_task_id=factor_task_id,
            constraint_kind=constraint_kind,
            source_version_id=source_version_id,
        )
        if features:
            from paleo_workbench.mapping.vector_layer import VectorFeature

            # 可信导入通道（领域建稿 = 数据初始落盘，非用户编辑；RAW
            # 保护约束的是后者——见 import_layer_features docstring）。
            self.composite.edit_controller.import_layer_features(
                layer.id, [
                    VectorFeature(
                        feature_id=f"f{uuid.uuid4().hex[:10]}",
                        geometry=geometry,
                        attributes=dict(properties or {}),
                    )
                    for geometry, properties in features
                ]
            )
        self.composite._sync_composition_now()
        return layer.id

    def _mapping_horizon(self) -> str:
        project = self.project
        if project is None:
            return ""
        try:
            from paleo_workbench.workflow.stratigraphy import active_target_horizon

            return active_target_horizon(project)
        except Exception:
            return str(
                getattr(getattr(project, "stratigraphy", None), "target_horizon", "")
                or ""
            ).strip()

    def _stage_role_layer(self, role: LayerRole) -> str | None:
        for layer_id in self.stage_controller.state.layers_with_role(role):
            if self.edit_controller.layer(str(layer_id)) is not None:
                return str(layer_id)
        return None

    # -- Phase 1 ------------------------------------------------------------------

    def _default_blank_facies_features(self) -> list[tuple[dict, dict]]:
        """工区默认空白相：未指定初始相图时的回退（一整块工区范围）。

        工区边界有效点 ≥3 则闭合 ring 并产出单个 Polygon 特征；否则返回 []。
        """
        import math

        project = self.project
        boundary = getattr(getattr(project, "workarea", None), "boundary", None) or []
        ring: list[list[float]] = []
        for vertex in boundary:
            try:
                x, y = float(vertex[0]), float(vertex[1])
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                ring.append([x, y])
        if len(ring) < 3:
            return []
        if ring[0] != ring[-1]:
            ring.append(list(ring[0]))
        return [(
            {"type": "Polygon", "coordinates": [ring]},
            {"facies": "空白相", "source": "workarea_default"},
        )]

    def load_initial_facies(self) -> None:
        """初始沉积相图（PaleoMapDocument.facies_polygons）→ RAW 叠加图层。

        未指定初始相图时回退到工区默认空白相；RAW 不可变（V5 §14）：角色
        INITIAL_FACIES_SOURCE 阻止编辑会话。
        """
        existing = self._stage_role_layer(LayerRole.INITIAL_FACIES_SOURCE)
        if existing is not None:
            self.composite.status_message.emit("初始相图已在图层树（01 初始沉积相）")
            return
        document = self.project
        candidates = [
            doc for doc in (getattr(document, "paleomap_documents", None) or [])
            if getattr(doc, "facies_polygons", None)
        ]
        if not candidates:
            features = self._default_blank_facies_features()
            if not features:
                self.composite.status_message.emit(
                    "工程中没有初始沉积相图——先在编图页生成或导入相图文档")
                return
            layer_id = self._create_role_layer(
                "初始相图（工区默认空白相）", "polygon",
                LayerRole.INITIAL_FACIES_SOURCE, features=features,
            )
            if layer_id:
                from paleo_workbench.mapping.map_styles import VectorStyle

                # 默认空白相只是占位底：一整块不透明填充会压住基础层，
                # 淡色半透明（#AARRGGBB 约 10%，比工区边界 13% 更淡）只示意范围。
                self.edit_controller.set_layer_style(
                    layer_id,
                    VectorStyle(
                        fill="#1a64748b", stroke="#94a3b8", stroke_width=1.0,
                    ).to_dict(),
                )
                self.composite.status_message.emit(
                    "工程未指定初始相图，已按工区范围默认生成空白相"
                    "（1 个相面，RAW 不可编辑——用「创建解释草稿」开始校正）")
            return
        doc = candidates[0]
        features = []
        for polygon in doc.facies_polygons:
            geometry = polygon.get("geometry") if isinstance(polygon, dict) else None
            if not isinstance(geometry, dict):
                continue
            properties = dict(polygon.get("properties") or {})
            properties.setdefault("facies", str(polygon.get("facies") or ""))
            features.append((geometry, properties))
        if not features:
            self.composite.status_message.emit("初始相图没有有效相面几何")
            return
        layer_id = self._create_role_layer(
            f"{doc.name}（原始）", "polygon", LayerRole.INITIAL_FACIES_SOURCE,
            features=features,
        )
        if layer_id:
            self.composite.status_message.emit(
                f"已叠加初始相图（{len(features)} 个相面，RAW 不可编辑——"
                "用「创建解释草稿」开始校正）")

    # -- Phase 1：mock 预测生成（生产 → 落编目 → 自动叠加） ---------------------

    def run_well_facies_mock(self) -> None:
        """对目标层位的全部井生成 mock 测井沉积相，并叠加井点显示。"""
        self._run_mock_prediction(kind="well")

    def run_seismic_facies_mock(self) -> None:
        """对目标层位平面范围生成 mock 面状沉积相，并叠加相区显示。"""
        self._run_mock_prediction(kind="seismic")

    def _run_mock_prediction(self, *, kind: str) -> None:
        from paleo_workbench.catalog.runtime import get_catalog_service

        service = get_catalog_service()
        if service is None:
            self.composite.status_message.emit(
                "数据编目不可用——无法运行 mock 预测（预测结果必须落编目建血缘）")
            return
        project = self.project
        horizon = self._mapping_horizon()
        import secrets

        from paleo_workbench.prediction.inference_service import (
            execute_run,
            link_run_to_domain_task,
            materialize_prediction_task,
            resolve_prediction_inputs,
            start_inference,
        )
        from paleo_workbench.prediction.mock_facies import (
            ensure_mock_facies_models,
        )
        from paleo_workbench.prediction.providers import InferenceInputError

        well_version, seismic_version = ensure_mock_facies_models(service)
        model_version = well_version if kind == "well" else seismic_version
        try:
            parameters = self._mock_run_parameters(project, horizon, kind=kind)
        except InferenceInputError as exc:
            self.composite.status_message.emit(str(exc))
            return
        parameters["seed"] = secrets.randbelow(2**31)
        operation = "well_facies_mock" if kind == "well" else "seismic_facies_mock"
        input_ids = resolve_prediction_inputs(project, service)
        run = start_inference(
            service,
            model_version_id=model_version.id,
            input_version_ids=input_ids,
            parameters=parameters,
            operation=operation,
        )
        try:
            outcome = execute_run(service, run.id)
        except Exception as exc:
            # execute_run 已把 run 置 failed（诚实失败）；此处只负责可见性。
            self.composite.status_message.emit(f"mock 预测失败：{exc}")
            return
        if outcome.get("result") is None:
            # execute_run 失败时返回 result=None 而不抛出（失败已记在 run
            # 上）；空结果绝不 materialize 成任务，只报可见失败。
            detail = ""
            try:
                failed_run = service.get_run(run.id)
                error = str((failed_run.parameters or {}).get("error") or "")
                if error:
                    detail = f"：{error}"
            except Exception:
                detail = ""
            self.composite.status_message.emit(f"mock 预测失败{detail}")
            return
        payload = dict(outcome.get("result") or {})
        try:
            self._register_mock_intermediates(service, run.id, payload, kind=kind)
        except Exception as exc:
            # 中间登记失败不得 orphan 主结果：DERIVED 已落盘、run 已 complete，
            # task 照建，只是明示中间文件缺失。
            self.composite.status_message.emit(
                f"中间文件登记失败（主结果已保留）：{exc}")
        resources = getattr(project, "resources", None) or []
        # input_refs 按 kind 只记本类输入：Task 2 分类语义看“键值非空”，
        # 跨类全带会把 seismic 任务误判为 well（反之亦然）。
        well_ids = [
            str(r.id) for r in resources
            if getattr(r, "type", "") == "well_log"
        ]
        seismic_ids = [
            str(r.id) for r in resources
            if getattr(r, "type", "") == "seismic"
        ]
        task = materialize_prediction_task(
            project,
            payload,
            name_prefix=(
                "测井相预测（mock）" if kind == "well" else "地震相面预测（mock）"),
            workflow=operation,
            target_horizon=horizon,
            well_log_resource_ids=well_ids if kind == "well" else [],
            seismic_resource_ids=seismic_ids if kind == "seismic" else [],
            run_id=run.id,
            output_version_id=str(
                getattr(outcome.get("output_version"), "id", "") or ""),
        )
        project.prediction_tasks.append(task)
        try:
            link_run_to_domain_task(service, run.id, task.id)
        except Exception:
            task.model_metadata["link_failed"] = True
            logger.exception("link_run_to_domain_task failed for run %s", run.id)
        summary = dict(task.result_summary or {})
        if kind == "well":
            self._drop_stale_well_points_layer()
            self.add_well_prediction_overlay()
            count = len(summary.get("predicted_regions") or [])
            self.composite.status_message.emit(
                f"已生成 {count} 口井的预测沉积相（mock，层位 {horizon}），"
                "已叠加井点显示")
        else:
            self.add_seismic_prediction_overlay()
            features = (summary.get("spatial") or {}).get("features") or []
            self.composite.status_message.emit(
                f"已生成面状沉积相（mock，层位 {horizon}）："
                f"{len(features)} 个相区，已叠加显示")

    def _drop_stale_well_points_layer(self) -> None:
        """删掉旧井点层，让随后的叠加重建出含新任务的层。

        `_overlay_well_prediction_points` 是单层幂等语义（层在即复用、不重建）——
        那是「叠加已有结果」动作的契约，本生成路径不碰它；但每次 mock 生成都产出
        新 task，不先删旧层新任务在图上不可见。删旧建新 precedented by
        `well_prediction_point_to_surface`。
        """
        from paleo_workbench.mapping.well_prediction_surface import (
            POINTS_LAYER_TASK_ID,
        )

        role = LayerRole.WELL_FACIES_PREDICTION
        stale = [
            lid for lid in self.stage_controller.state.layers_with_role(role)
            if self.stage_controller.state.membership(lid).factor_task_id
            == POINTS_LAYER_TASK_ID
            and self.edit_controller.layer(str(lid)) is not None
        ]
        for lid in stale:
            self.stage_controller.group_controller.unregister_layer(lid)
            self.edit_controller.remove_layer(lid)

    def _mock_run_parameters(self, project, horizon: str, *, kind: str) -> dict:
        from paleo_workbench.prediction.providers import InferenceInputError

        if kind == "well":
            wells = list(getattr(project, "wells", None) or [])
            if not wells:
                raise InferenceInputError("工程中没有井，无法生成测井相预测")
            # 双键：`_` 键留作 run 参数留存（血缘可见），非下划线键穿过
            # execute_run 的 `_` 过滤真正到达 provider（服务语义使然）。
            well_rows = [
                {
                    "well_id": str(getattr(w, "id", "") or ""),
                    "well_name": str(getattr(w, "name", "") or ""),
                    "td": getattr(w, "td", None),
                }
                for w in wells
            ]
            return {
                "target_horizon": horizon,
                "_wells": well_rows,
                "wells": well_rows,
            }
        extent, ring, extent_source = self._mock_areal_extent(project)
        if extent is None:
            raise InferenceInputError(
                "无可用平面范围（工区边界 / 井位 / 地震工区均为空），"
                "无法生成面状沉积相")
        crs = str(
            getattr(getattr(project, "coordinate", None), "project_crs", "")
            or "")
        return {
            "target_horizon": horizon,
            "_extent": extent,
            "extent": extent,
            "_clip_ring": ring,
            "clip_ring": ring,
            "_crs": crs,
            "crs": crs,
            "grid_n": 80,
            # 非下划线键：进 run parameters 与 snapshot，进血缘。
            "extent_source": extent_source,
        }

    @staticmethod
    def _mock_areal_extent(project):
        """mock 面状相的平面范围：工区边界 bbox（带 clip ring）→ 井位 bbox
        +10% padding → 地震工区角点 bbox。

        返回 (extent|None, ring|None, extent_source)。extent_source 记范围出处
        （"workarea_boundary" / "well_bbox" / "seismic_survey" / ""），随 run
        parameters 进血缘；与在途 point_to_surface 的工区优先惯例一致。
        """
        import math

        def _bbox(points):
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return (min(xs), min(ys), max(xs), max(ys))

        boundary = getattr(getattr(project, "workarea", None), "boundary", None) or []
        ring = [
            (float(x), float(y)) for x, y, *_ in boundary
            if math.isfinite(float(x)) and math.isfinite(float(y))
        ]
        if len(ring) >= 3:
            return _bbox(ring), ring, "workarea_boundary"
        well_points = [
            (float(w.project_x), float(w.project_y))
            for w in (getattr(project, "wells", None) or [])
            if math.isfinite(float(getattr(w, "project_x", float("nan"))))
            and math.isfinite(float(getattr(w, "project_y", float("nan"))))
        ]
        if well_points:
            xmin, ymin, xmax, ymax = _bbox(well_points)
            pad_x = max((xmax - xmin) * 0.1, 1.0)
            pad_y = max((ymax - ymin) * 0.1, 1.0)
            return (xmin - pad_x, ymin - pad_y, xmax + pad_x, ymax + pad_y), None, "well_bbox"
        corners = []
        for survey in (getattr(project, "seismic_surveys", None) or []):
            for point in (getattr(survey, "extent", None) or []):
                try:
                    x, y = float(point[0]), float(point[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if math.isfinite(x) and math.isfinite(y):
                    corners.append((x, y))
        if len(corners) >= 3:
            return _bbox(corners), None, "seismic_survey"
        return None, None, ""

    def _register_mock_intermediates(
            self, service, run_id: str, payload: dict, *, kind: str) -> None:
        """中间文件登记：同 run 的 INTERMEDIATE 版本（用户硬性要求）。

        注意 DERIVED 结果 JSON（execute_run 已落盘）仍含这些数据——此处
        弹出只是为了 task.result_summary 干净；中间版本才是规范留存。
        """
        import json
        import tempfile
        from pathlib import Path

        from paleo_workbench.catalog.models import DataStage

        if kind == "well":
            detail = payload.pop("well_detail", None)
            if not detail:
                return
            fd, tmp = tempfile.mkstemp(
                prefix="mock_well_facies_", suffix=".json")
            try:
                with open(fd, "w", encoding="utf-8") as handle:
                    json.dump({"wells": detail}, handle,
                              ensure_ascii=False, indent=2)
                service.register_result_asset(
                    name="测井相预测（mock）逐井明细",
                    type="prediction_intermediate",
                    format="json",
                    asset_metadata={"kind": "prediction_intermediate"},
                    source_path=tmp,
                    stage=DataStage.INTERMEDIATE,
                    run_id=run_id,
                    version_metadata={
                        "kind": "prediction_intermediate", "mock": True},
                )
            finally:
                try:
                    Path(tmp).unlink()
                except OSError:
                    pass
            return
        grid = payload.pop("mock_grid", None)
        if not grid:
            return
        import numpy as np

        from paleo_workbench.catalog.grid_artifact import write_grid_artifact
        from paleo_workbench.workflow.factor_grid_result import FactorGridResult

        result = FactorGridResult(
            grid_z=np.asarray(grid["grid_z"], dtype=np.float32),
            grid_x=np.asarray(grid["grid_x"], dtype=np.float64),
            grid_y=np.asarray(grid["grid_y"], dtype=np.float64),
            factor_name="地震相面预测（mock）中间栅格",
            algorithm_id="mock_nearest_neighbor",
            algorithm_parameters={"grid_n": int(grid.get("grid_n", 80))},
            crs=grid.get("crs") or None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_grid_artifact(result, tmpdir, "mock_seismic_facies")
            service.register_result_asset(
                name="地震相面预测（mock）中间栅格",
                type="prediction_intermediate",
                format="npz",
                asset_metadata={"kind": "prediction_intermediate"},
                source_path=artifact,
                stage=DataStage.INTERMEDIATE,
                run_id=run_id,
                version_metadata={
                    "kind": "prediction_intermediate", "mock": True},
            )

    def add_well_prediction_overlay(self) -> None:
        """测井相预测结果叠加：井点（区间 + 井位）以及已有相面。"""
        poly_added, poly_already, unmatched = self._overlay_polygon_predictions(
            prefer="well", emit=False)
        point_added, point_already, missing_xy = self._overlay_well_prediction_points()
        parts: list[str] = []
        if point_added:
            parts.append(f"已叠加 {point_added} 个测井预测井点")
        elif point_already:
            parts.append("测井预测井点已在图层树")
        if poly_added:
            parts.append(f"已叠加 {poly_added} 个测井预测相面（不可编辑）")
        elif poly_already:
            parts.append(f"{poly_already} 个测井预测相面此前已叠加")
        if not parts:
            detail = ["没有可叠加的测井相预测结果（需要井位坐标 + 预测区间，或 VECTOR_POLYGONS）"]
            if missing_xy:
                detail.append(f"{missing_xy} 个测井任务缺少井位，未落点")
            if unmatched:
                detail.append(f"{unmatched} 个任务无法判别井/震类别")
            self.composite.status_message.emit("；".join(detail))
            return
        if missing_xy:
            parts.append(f"{missing_xy} 个测井任务缺少井位，未落点")
        self.composite.status_message.emit("；".join(parts))

    def add_seismic_prediction_overlay(self) -> None:
        """地震预测相叠加（VECTOR_POLYGONS 空间结果 → 独立预测图层）。"""
        self._overlay_polygon_predictions(prefer="seismic")

    def well_prediction_point_to_surface(self) -> None:
        """测井预测井点 → 最近邻相面（明确动作，不在阶段切换时重算）。"""
        from paleo_workbench.mapping.well_prediction_surface import (
            SURFACE_LAYER_TASK_ID,
            point_to_surface_features,
            well_facies_points,
        )

        role = LayerRole.WELL_FACIES_PREDICTION
        existing = [
            lid for lid in self.stage_controller.state.memberships
            if self.stage_controller.state.membership(lid).role == role
            and self.stage_controller.state.membership(lid).factor_task_id
            == SURFACE_LAYER_TASK_ID
            and self.edit_controller.layer(lid) is not None
        ]
        points = well_facies_points(self.project)
        if not points:
            self.composite.status_message.emit(
                "没有可做点到面的测井预测井点——需要测井相预测结果，且井位要有坐标")
            return
        features = point_to_surface_features(points, project=self.project)
        if not features:
            self.composite.status_message.emit(
                "点到面未生成相面（井点不足或工区范围无效）")
            return
        horizon = self._mapping_horizon()
        if horizon:
            features = [
                (geometry, {**dict(properties), "horizon": horizon})
                for geometry, properties in features
            ]
        for lid in existing:
            self.stage_controller.group_controller.unregister_layer(lid)
            self.edit_controller.remove_layer(lid)
        title = "测井预测相（点到面）"
        if horizon:
            title = f"{title} · {horizon}"
        created = self._create_role_layer(
            title, "polygon", role,
            factor_task_id=SURFACE_LAYER_TASK_ID,
            features=features,
        )
        if created:
            scope = f"（层位 {horizon}）" if horizon else ""
            self.composite.status_message.emit(
                f"已由 {len(points)} 个测井预测井点生成点到面相面{scope}"
                f"（{len(features)} 个相多边形，不可编辑）")
        else:
            self.composite.status_message.emit("测井点到面图层创建失败")

    def _overlay_well_prediction_points(self) -> tuple[int, int, int]:
        """返回 (added_points, already, tasks_missing_xy)。"""
        from paleo_workbench.mapping.well_prediction_surface import (
            POINTS_LAYER_TASK_ID,
            point_features,
            well_facies_points,
            well_prediction_tasks,
        )

        role = LayerRole.WELL_FACIES_PREDICTION
        existing = [
            lid for lid in self.stage_controller.state.memberships
            if self.stage_controller.state.membership(lid).role == role
            and self.stage_controller.state.membership(lid).factor_task_id
            == POINTS_LAYER_TASK_ID
            and self.edit_controller.layer(lid) is not None
        ]
        points = well_facies_points(self.project)
        well_tasks = well_prediction_tasks(self.project)
        missing_xy = max(0, len(well_tasks) - len({p.task_id for p in points if p.task_id}))
        if existing:
            return 0, len(points) or 1, missing_xy
        if not points:
            return 0, 0, missing_xy
        horizon = self._mapping_horizon()
        features = point_features(points)
        if horizon:
            features = [
                (geometry, {**dict(properties), "horizon": horizon})
                for geometry, properties in features
            ]
        title = "测井预测相（井点）"
        if horizon:
            title = f"{title} · {horizon}"
        created = self._create_role_layer(
            title, "point", role,
            factor_task_id=POINTS_LAYER_TASK_ID,
            features=features,
        )
        return (len(points) if created else 0), 0, missing_xy

    @staticmethod
    def _classify_prediction_task(task) -> str:
        """按 machine-readable 信号分类井/震预测（无信号 → unknown）。

        优先 ``input_refs`` 键（well/logs vs seismic）；键无信号时回退任务名
        的显式类别词（此处是展示归类而非科学语义判定，允许名称提示）。
        materialize_prediction_task 恒写双键（值可为空列表），只看键名会把 pipeline 任务误判为 seismic。
        """
        refs = getattr(task, "input_refs", None) or {}
        keys = " ".join(
            str(key).lower() for key, value in refs.items() if value
        )
        if "seis" in keys:
            return "seismic"
        if "well" in keys or "log" in keys:
            return "well"
        name = str(getattr(task, "name", "") or "").lower()
        if "seis" in name or "地震" in name:
            return "seismic"
        if "well" in name or "测井" in name or "井" in name:
            return "well"
        return "unknown"

    def _overlay_polygon_predictions(
        self, *, prefer: str, emit: bool = True,
    ) -> tuple[int, int, int]:
        from paleo_workbench.prediction.spatial_result import extract_polygon_features

        tasks = getattr(self.project, "prediction_tasks", None) or []
        wanted = "well" if prefer == "well" else "seismic"
        role = (LayerRole.WELL_FACIES_PREDICTION if wanted == "well"
                else LayerRole.SEISMIC_FACIES_PREDICTION)
        added = unmatched = already = 0
        for task in tasks:
            category = self._classify_prediction_task(task)
            if category != wanted:
                if category == "unknown":
                    unmatched += 1
                continue
            # 幂等：该任务在该角色下已有叠加图层则跳过（防连点堆积）。
            task_marker = str(getattr(task, "id", "") or "")
            existing = [
                lid for lid in self.stage_controller.state.memberships
                if self.stage_controller.state.membership(lid).role == role
                and self.stage_controller.state.membership(lid).factor_task_id == task_marker
                and self.edit_controller.layer(lid) is not None
            ]
            if existing:
                already += 1
                continue
            summary = dict(getattr(task, "result_summary", None) or {})
            spatial = summary.get("spatial") or {}
            features_raw = spatial.get("features")
            payload = {"result_summary": summary}
            if features_raw:
                features = [f for f in features_raw if isinstance(f, dict)]
            else:
                try:
                    features = extract_polygon_features(payload)
                except Exception:
                    features = []
            features = [
                feat for feat in features
                if isinstance(feat.get("geometry"), dict)
                and feat["geometry"].get("type") in {"Polygon", "MultiPolygon"}
            ]
            if not features:
                continue
            horizon = self._mapping_horizon()
            kind_label = "测井" if wanted == "well" else "地震"
            title = f"{getattr(task, 'name', '') or '预测相'}（{kind_label}预测）"
            if horizon:
                title = f"{title} · {horizon}"
            created = self._create_role_layer(
                title, "polygon", role, factor_task_id=task_marker,
                features=[
                    (
                        dict(f.get("geometry") or {}),
                        {**dict(f.get("properties") or {}),
                         **({"horizon": horizon} if horizon else {})},
                    )
                    for f in features
                ],
            )
            added += 1 if created else 0
        if emit:
            label = "测井" if wanted == "well" else "地震"
            if not added:
                parts = [f"没有可叠加的{label}预测空间结果（需要 VECTOR_POLYGONS 预测任务）"]
                if unmatched:
                    parts.append(
                        f"{unmatched} 个任务无法判别井/震类别（经 input_refs/任务名），未叠加")
                self.composite.status_message.emit("；".join(parts))
            else:
                message = f"已叠加 {added} 个{label}预测结果图层（不可编辑）"
                if already:
                    message += f"；{already} 个此前已叠加，跳过"
                self.composite.status_message.emit(message)
        return added, already, unmatched

    def toggle_prediction_confidence(self) -> None:
        """预测置信度叠加开关（§10 P1；stage_profiles 已声明动作 id）。

        幂等 toggle：已有置信度叠加图层 → 移除；否则从带 probability
        字段的 VECTOR_POLYGONS 预测结果建层。**无持久化**——
        StageViewState 只有组/图层可见性覆盖语义，没有动作级开关状态；
        当前为按需叠加（重开工程后需重新触发），不伪造持久开关。
        """
        from paleo_workbench.mapping.factor_layer_products import (
            confidence_overlay_layers,
        )

        state = self.stage_controller.state
        roles = (LayerRole.WELL_FACIES_CONFIDENCE,
                 LayerRole.SEISMIC_FACIES_CONFIDENCE)
        existing = [
            lid for lid in state.memberships
            if state.membership(lid).role in roles
            and self.edit_controller.layer(lid) is not None
        ]
        if existing:
            for lid in existing:
                self.stage_controller.group_controller.unregister_layer(lid)
                self.edit_controller.remove_layer(lid)
            self.composite._sync_composition_now()
            self.composite.status_message.emit(
                f"已移除 {len(existing)} 个预测置信度叠加图层")
            return
        added = 0
        for task in getattr(self.project, "prediction_tasks", None) or []:
            for descriptor in confidence_overlay_layers(self.project, task):
                created = self._create_role_layer(
                    descriptor["title"], descriptor["geometry_kind"],
                    descriptor["role"],
                    factor_task_id=str(
                        descriptor["metadata"].get("prediction_task_id") or ""),
                    features=descriptor.get("features"))
                added += 1 if created else 0
        if not added:
            self.composite.status_message.emit(
                "没有可叠加的预测置信度结果（需要带 probability 字段的 "
                "VECTOR_POLYGONS 预测任务）")
        else:
            self.composite.status_message.emit(
                f"已叠加 {added} 个预测置信度图层（不可编辑）")

    def create_facies_draft(self) -> None:
        """RAW → DERIVED：从初始相图创建可编辑解释草稿（V5 §14）。

        RAW 保持不可变；草稿注册 INITIAL_FACIES_DRAFT 角色并钉住来源。
        """
        existing = self._stage_role_layer(LayerRole.INITIAL_FACIES_DRAFT)
        if existing is not None:
            self.composite.status_message.emit("解释草稿已存在（05 人工解释与修编）")
            return
        raw = self._stage_role_layer(LayerRole.INITIAL_FACIES_SOURCE)
        source_features: list = []
        source_name = "初始相图"
        if raw is not None:
            layer = self.edit_controller.layer(raw)
            source_name = f"{layer.name} 校正稿"
            source_features = [
                (feature.geometry, dict(feature.attributes or {}))
                for feature in layer.features()
            ]
        else:
            document = self.project
            docs = [
                doc for doc in (getattr(document, "paleomap_documents", None) or [])
                if getattr(doc, "facies_polygons", None)
            ]
            if docs:
                source_name = f"{docs[0].name} 校正稿"
                for polygon in docs[0].facies_polygons:
                    geometry = polygon.get("geometry") if isinstance(polygon, dict) else None
                    if isinstance(geometry, dict):
                        source_features.append(
                            (geometry, dict(polygon.get("properties") or {})))
            else:
                source_features = self._default_blank_facies_features()
                if source_features:
                    source_name = "初始相图（工区默认空白相）校正稿"
        if not source_features:
            self.composite.status_message.emit(
                "没有可校正的初始相图——先加载初始相图（RAW）")
            return
        source_version = ""
        record = self.stage_controller.state.membership(raw) if raw else None
        if record is not None:
            source_version = record.source_version_id
        layer_id = self._create_role_layer(
            source_name, "polygon", LayerRole.INITIAL_FACIES_DRAFT,
            features=source_features, source_version_id=source_version,
        )
        if layer_id:
            self.stage_controller.state.set_maturity(
                f"phase1_draft:{layer_id}", "draft")
            self.edit_controller.set_active_layer(layer_id)
            self.composite.layer_manager.select_layer(layer_id)
            self.composite.status_message.emit(
                "已创建解释草稿（DERIVED）——RAW 保持不变，编辑保存在草稿上")

    # -- Phase 2 ------------------------------------------------------------------

    def open_factor_workbench(self) -> None:
        """单因素工作台：导航到既有制备/编图 hub（不在本分支重实现插值）。"""
        try:
            # V7 R1-P2：单因素工作台在「数据制备」子页（FactorTaskPanel），
            # 此前路由到编图画布页。
            self.composite.hub_page_requested.emit("preparation")
        except Exception:
            self.composite.status_message.emit(
                "请通过左侧功能导航打开单因素制备页运行插值")

    def overlay_factor_results(self) -> None:
        """把已完成单因素任务的结果组织进 factor 组（V5 §21/§71；§10-12 六子层）。

        同一 FactorGridResult 在 Phase 2/3 共享同一数据身份：栅格派生子层
        （等值线/分级/不确定性）从 live 网格缓存派生（缓存缺失时诚实留空，
        不重算）。标量子层（栅格/不确定性）为 descriptor-only 域登记——
        画布标量发布路径（snapshot 消费）不在本动作内，桥缺失时登记仍完成。
        """
        from paleo_workbench.mapping.factor_layer_products import factor_group_layers
        from paleo_workbench.project.factor_grid_artifacts import peek_live_factor_grid

        document = self.project
        tasks = [
            task for task in (getattr(document, "factor_map_tasks", None) or [])
            if str(getattr(task, "status", "")) == FACTOR_TASK_STATUS_COMPLETE
        ]
        if not tasks:
            self.composite.status_message.emit("没有已完成的单因素任务可叠加")
            return
        state = self.stage_controller.state
        vector_added = raster_registered = empty_children = 0
        no_grid_tasks = 0
        for task in tasks:
            task_id = str(task.id)
            grid = peek_live_factor_grid(task_id)
            if grid is None:
                no_grid_tasks += 1
            for descriptor in factor_group_layers(document, task, grid=grid):
                role = descriptor["role"]
                layer_id = str(descriptor.get("layer_id") or "")
                # 幂等（按子层角色独立判定）：首个动作只建了井点（无 live
                # 网格）时，第二次点击仍能补齐其余子层。
                if descriptor.get("geometry_kind") == "raster":
                    if state.membership(layer_id) is not None:
                        continue
                    state.set_membership(LayerMembershipRecord(
                        layer_id=layer_id, role=role,
                        factor_task_id=task_id,
                        created_stage=state.current_stage.value,
                    ))
                    raster_registered += 1
                    continue
                present = any(
                    state.membership(lid).role == role
                    and state.membership(lid).factor_task_id == task_id
                    and self.edit_controller.layer(lid) is not None
                    for lid in state.memberships
                )
                if present:
                    continue
                features = descriptor.get("features") or []
                if not features:
                    # 空矢量子层（如无 live 网格的等值线/分级）不建空图层；
                    # 缺失原因由 QC 子层与消息诚实报告。
                    empty_children += 1
                    continue
                created = self._create_role_layer(
                    descriptor["title"], descriptor["geometry_kind"], role,
                    factor_task_id=task_id, features=features)
                vector_added += 1 if created else 0
        message = (f"已叠加单因素组：矢量子层 {vector_added}，标量子层登记 "
                   f"{raster_registered}（descriptor-only，画布标量发布待接入）")
        if no_grid_tasks:
            message += (f"；{no_grid_tasks} 个任务无 live 网格（等值线/分级/"
                        "不确定性子层留空，打开制备页加载后可叠加）")
        if empty_children:
            message += f"；{empty_children} 个矢量子层无内容（详见 QC 子层）"
        self.composite.status_message.emit(message)

    def create_constraint(self, kind_value: str) -> None:
        """typed 约束创建（V5 §22/§50）：编辑图层 + 工程约束线记录。"""
        kind = constraint_kind_from_value(kind_value)
        if kind is None:
            self.composite.status_message.emit(f"未知约束类型：{kind_value}")
            return
        sequence = 1 + sum(
            1 for record in self.stage_controller.state.memberships.values()
            if record.constraint_kind == kind.value
            and self.edit_controller.layer(record.layer_id) is not None
        )
        name = f"{kind.label} {sequence}"
        geometry_kind = kind.geometry_kind
        layer_id = self._create_role_layer(
            name, geometry_kind, kind.layer_role,
            template=kind.value, constraint_kind=kind.value,
        )
        if layer_id is None:
            return
        # 同步登记到 project.constraint_layers（插值引擎的既有权威）。
        document = self.project
        if document is not None:
            from paleo_workbench.project.models import ConstraintLayers, ConstraintLine

            target = None
            for candidate in getattr(document, "constraint_layers", None) or []:
                target = candidate
                break
            if target is None:
                target = ConstraintLayers(name="约束层")
                document.constraint_layers.append(target)
            target.lines.append(ConstraintLine(
                name=name,
                role=kind.interpolation_role,
                properties={"layer_id": layer_id,
                            "constraint_kind": kind.value},
            ))
        self.edit_controller.set_active_layer(layer_id)
        self.composite.layer_manager.select_layer(layer_id)
        self.composite.status_message.emit(
            f"已创建 {kind.label}（自动进入 02 地质约束组；数字化后保存生效）")

    def commit_constraints(self) -> None:
        """提交约束版本（V9 P0-2）：约束编辑 → catalog DERIVED 版本链。

        与 harness ``constraint.commit`` 调用同一领域函数
        （``commit_all_constraints``）——单一实现，双入口。此前提交仅
        agent 可达：生产 UI 永远无法建立约束版本链，
        ``constraints:current`` 新鲜度永久 UNKNOWN。
        """
        document = self.project
        if document is None:
            self.composite.status_message.emit("未打开工程")
            return
        from paleo_workbench.catalog.runtime import get_catalog_service
        from paleo_workbench.workflow.constraint_versions import (
            commit_all_constraints,
        )

        try:
            service = get_catalog_service()
        except Exception:
            service = None
        if service is None:
            self.composite.status_message.emit(
                "目录服务不可用——无法提交约束版本（不伪称已提交）")
            return
        try:
            reports = commit_all_constraints(
                document, service, actor="workstation")
        except Exception as exc:  # 提交失败必须可见
            self.composite.status_message.emit(f"约束提交失败：{exc}")
            return
        committed = [r for r in reports if r.committed]
        unchanged = sum(1 for r in reports if r.reason == "unchanged")
        no_content = sum(1 for r in reports if r.reason == "no_content")
        if committed:
            versions = ", ".join(r.version_id or "?" for r in committed)
            self.composite.status_message.emit(
                f"已提交 {len(committed)} 个约束组新版本（{versions}）；"
                f"{unchanged} 组内容未变，{no_content} 组无内容")
            self.composite._sync_workspace_state_to_project()
        else:
            self.composite.status_message.emit(
                f"无新版本：{unchanged} 组内容未变，{no_content} 组无内容"
                if reports else "工程内没有约束组")

    # -- Phase 3 ------------------------------------------------------------------

    def select_evidence(self) -> None:
        """证据版本选择（Compilation Input Set，V5 §57）。"""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QInputDialog, QVBoxLayout

        document = self.project
        if document is None:
            return
        entries: list[tuple[str, str]] = []
        # 阶段1解释草稿（draft:<layer_id>——dependencies 传播式评估契约）
        for layer_id in self.stage_controller.state.layers_with_role(
                LayerRole.INITIAL_FACIES_DRAFT):
            layer = self.edit_controller.layer(str(layer_id))
            if layer is not None:
                entries.append((f"阶段1解释草稿：{layer.name}", f"draft:{layer_id}"))
        # 单因素任务（版本钉住）
        for task in getattr(document, "factor_map_tasks", None) or []:
            if str(getattr(task, "status", "")) != FACTOR_TASK_STATUS_COMPLETE:
                continue
            version = str(getattr(task, "grid_artifact_version_id", "") or "")
            entries.append((f"单因素：{task.name}", f"factor:{task.id}:{version}"))
        # 约束内容指纹
        entries.append(("地质约束（当前内容）", "constraints:current"))
        if not entries:
            self.composite.status_message.emit("没有可选证据——先完成上阶段成果")
            return
        labels = [label for label, _ in entries]
        chosen, ok = QInputDialog.getItem(
            self.composite, "选择证据版本",
            "综合编图输入证据（可多选经重复执行本动作累积）：",
            labels, 0, False,
        )
        del QDialog, QDialogButtonBox, QVBoxLayout
        if not ok or not chosen:
            return
        value = dict(entries)[chosen]
        self.stage_controller.state.compilation_input_set[chosen] = value
        self.composite._sync_workspace_state_to_project()
        self.composite.status_message.emit(f"已加入证据集：{chosen}")

    def create_integrated_draft(self) -> None:
        """综合解释草稿：新解释产品（绝不修改 Stage 1 相图，V5 §30）。"""
        existing = self._stage_role_layer(LayerRole.INTEGRATED_FACIES)
        if existing is not None:
            self.composite.status_message.emit("综合解释草稿已存在（02 综合解释）")
            return
        if not self.stage_controller.state.compilation_input_set:
            self.composite.status_message.emit(
                "先选择证据版本（Compilation Input Set 为空）")
            return
        # 以阶段1草稿为几何底稿（若存在），否则空面层。
        base = self._stage_role_layer(LayerRole.INITIAL_FACIES_DRAFT)
        features: list = []
        if base is not None:
            layer = self.edit_controller.layer(base)
            features = [
                (feature.geometry, dict(feature.attributes or {}))
                for feature in layer.features()
            ]
        layer_id = self._create_role_layer(
            "综合沉积相（草稿）", "polygon", LayerRole.INTEGRATED_FACIES,
            features=features,
        )
        if layer_id:
            self.stage_controller.state.set_maturity(
                f"integrated:{layer_id}", "draft")
            self.edit_controller.set_active_layer(layer_id)
            self.composite.layer_manager.select_layer(layer_id)
            self.composite.status_message.emit(
                f"已创建综合解释草稿（证据 {len(self.stage_controller.state.compilation_input_set)} 项）")

    def create_integrated_boundary(self) -> None:
        """综合相带边界（V5 §30，§12）：从综合/阶段1草稿的相面环提取边界线。

        与 create_integrated_draft 同构（role INTEGRATED_BOUNDARY，可编辑）。
        注：stage_profiles 的 P3 context_actions 尚未声明本动作 id——面板
        入口待声明后出现；dispatch 已注册，动作可直达。
        """
        from paleo_workbench.mapping.factor_layer_products import (
            boundary_features_from_polygons,
            integrated_boundary_action_helpers,
        )

        existing = self._stage_role_layer(LayerRole.INTEGRATED_BOUNDARY)
        if existing is not None:
            self.composite.status_message.emit("综合相带边界已存在（02 综合解释）")
            return
        source = (self._stage_role_layer(LayerRole.INTEGRATED_FACIES)
                  or self._stage_role_layer(LayerRole.INITIAL_FACIES_DRAFT))
        features: list = []
        source_id = ""
        if source is not None:
            layer = self.edit_controller.layer(source)
            source_id = source
            features = boundary_features_from_polygons(
                [(feature.geometry, dict(feature.attributes or {}))
                 for feature in layer.features()],
                source_layer_id=source,
            )
        elif self.project is not None:
            # 无 live 编辑层时退回工程侧草稿（重开工程后的持久化几何）。
            state = self.stage_controller.state
            for role in (LayerRole.INTEGRATED_FACIES,
                         LayerRole.INITIAL_FACIES_DRAFT):
                for layer_id in state.layers_with_role(role):
                    descriptor = integrated_boundary_action_helpers(
                        self.project, str(layer_id))
                    if descriptor is not None:
                        features = [
                            (geometry, dict(properties))
                            for geometry, properties in descriptor["features"]
                        ]
                        source_id = str(layer_id)
                        break
                if features:
                    break
        if not features:
            self.composite.status_message.emit(
                "没有可提取边界的草稿相面——先创建综合解释草稿（含相面几何）")
            return
        layer_id = self._create_role_layer(
            "综合相带边界", "line", LayerRole.INTEGRATED_BOUNDARY,
            features=features,
        )
        if layer_id:
            self.stage_controller.state.set_maturity(
                f"integrated:{layer_id}", "draft")
            self.edit_controller.set_active_layer(layer_id)
            self.composite.layer_manager.select_layer(layer_id)
            self.composite.status_message.emit(
                f"已创建综合相带边界（{len(features)} 条，源自草稿 "
                f"{source_id or '（工程侧）'} 相面环）")

    def run_fusion(self) -> None:
        """§12 计算融合入口：证据集 → workflow.integrated_compilation 融合。

        证据集中 ``factor:<task>:<version>`` 条目 → FusionModel（等权 +
        低/中/高三分默认，全部记入 qc）→ fuse → 目录注册（有目录服务时）。
        科学全部在 workflow.factor_fusion / integrated_compilation；本动作
        只做编排。

        面板声明缺口：stage_profiles 的 P3 context_actions 尚未声明
        ``run_fusion`` 动作 id（同 create_integrated_boundary 先例）——
        dispatch 已注册，动作可直达，面板入口待声明后出现。

        融合面登记（descriptor-only）：似然/置信度（及方差）为 scalar_grid
        descriptor（factor_layer_products 词表 + metadata["fusion"]），按
        overlay_factor_results 的 raster 分支同构登记 memberships——画布
        标量发布路径（snapshot 消费）不在本动作内，登记仍完成。

        融合初稿：分级多边形存在且尚无 INTEGRATED_FACIES 层时经
        _create_role_layer 建可编辑初稿（计算播种，人工修编）；已有草稿
        绝不覆盖（人工解释优先，融合结果见 descriptor 登记）。

        无目录服务时 register=False 诚实降级（状态消息明示，不伪称已
        版本钉住）；证据集为空/无 factor 条目/网格不可解析时逐条原因
        报告，绝不静默。
        """
        from paleo_workbench.workflow.integrated_compilation import (
            run_integrated_fusion,
        )

        document = self.project
        state = self.stage_controller.state
        evidence = dict(state.compilation_input_set or {})
        if not evidence:
            self.composite.status_message.emit("证据集为空——先选择证据版本（Compilation Input Set）")
            return
        if not any(str(value).startswith("factor:") for value in evidence.values()):
            self.composite.status_message.emit(
                "证据集中没有单因素证据（factor 条目）——计算融合至少需要一个单因素网格")
            return
        catalog = None
        try:
            from paleo_workbench.catalog.runtime import get_catalog_service

            catalog = get_catalog_service()
        except Exception:
            catalog = None
        try:
            summary = run_integrated_fusion(
                document, evidence, catalog, register=catalog is not None)
        except Exception as exc:
            logger.exception("run_fusion failed")
            self.composite.status_message.emit(f"融合失败：{exc}")
            return
        # 标量 descriptor-only 登记（幂等：按 layer_id 已存在则跳过）。
        registered = 0
        for descriptor in (
            summary["likelihood_descriptor"],
            summary["confidence_descriptor"],
            summary.get("variance_descriptor"),
        ):
            if not descriptor:
                continue
            layer_id = str(descriptor.get("layer_id") or "")
            if not layer_id or state.membership(layer_id) is not None:
                continue
            state.set_membership(LayerMembershipRecord(
                layer_id=layer_id, role=descriptor["role"],
                created_stage=state.current_stage.value,
            ))
            registered += 1
        # 融合初稿（仅有分级多边形且无既有草稿时创建；绝不覆盖人工解释）。
        features = list(summary.get("classification_features") or [])
        if features and self._stage_role_layer(LayerRole.INTEGRATED_FACIES) is None:
            created = self._create_role_layer(
                "综合沉积相（融合初稿）", "polygon", LayerRole.INTEGRATED_FACIES,
                features=features,
            )
            if created:
                self.stage_controller.state.set_maturity(
                    f"integrated:{created}", "draft")
                draft_note = f"；已创建融合初稿（{len(features)} 个分级面，可编辑修编）"
            else:
                draft_note = ""
        elif features:
            draft_note = "；已有综合解释草稿，融合分级未覆盖（人工解释优先，见融合登记）"
        else:
            draft_note = "；融合分级无多边形（阈值内无有效面，未建初稿）"
        counts = dict((summary["qc"].get("class_counts") or {}))
        counts_text = "，".join(f"{n} {c}" for n, c in counts.items()) or "无"
        coverage = dict(summary["qc"].get("confidence_coverage") or {})
        fraction = coverage.get("finite_fraction")
        coverage_text = (
            f"{float(fraction):.0%}" if isinstance(fraction, (int, float)) else "无")
        if summary.get("registered"):
            reg_text = f"已注册目录版本 {str(summary.get('catalog_version_id') or '')[:12]}…"
        else:
            reg_text = "未注册目录（无目录服务，诚实降级——重开工程后可补注册）"
        self.composite.status_message.emit(
            f"融合完成：{summary['n_factors']} 因子（{reg_text}）；分类 {counts_text}；"
            f"置信度覆盖 {coverage_text}；标量登记 {registered}"
            f"（descriptor-only，画布标量发布待接入）{draft_note}")

    def run_qa(self) -> None:
        """QA：拓扑校验综合解释图层 + 汇总过期输入。"""
        controller = self.stage_controller
        targets = controller.state.layers_with_role(LayerRole.INTEGRATED_FACIES) + \
            controller.state.layers_with_role(LayerRole.INTEGRATED_BOUNDARY)
        issues: list[dict] = []
        for layer_id in targets:
            layer = self.edit_controller.layer(str(layer_id))
            if layer is None:
                continue
            try:
                found = self.edit_controller.topology.validate([layer])
            except Exception:
                # V7 R1-P1：验证器崩溃不得静默跳过——否则「QA 通过」是在
                # 未验证的图层上得出的假结论；转为 error 级 issue。
                logger.exception("topology validate crashed for %s", layer_id)
                issues.append({
                    "kind": "error",
                    "message": f"拓扑验证失败（验证器异常）：{layer.name}",
                    "layer_id": str(layer_id),
                })
                continue
            for problem in found or []:
                issues.append({
                    "kind": str((problem or {}).get("kind") or "topology"),
                    "message": str((problem or {}).get("message") or problem),
                    "layer_id": str(layer_id),
                })
        stale = controller.stale_summary
        for artifact in stale.stale_entries:
            issues.append({
                "kind": "stale",
                "message": f"{artifact.artifact_key}：{artifact.status_label}（{artifact.detail}）",
                "layer_id": "",
            })
        # §14 cartographic rules (localization: rule/severity/reason/layer or
        # feature ref).  Rule evaluation is best-effort per rule; collector
        # failures never block the topology/staleness core of this action.
        carto_rules: list[str] = []
        try:
            from paleo_workbench.workflow.map_qa_rules import cartographic_issues

            found = cartographic_issues(
                self.project,
                stale_summary=stale,
            )
            carto_rules = sorted({str(i.get("rule") or "cartographic")
                                  for i in found})
            issues.extend(found)
        except Exception as exc:  # noqa: BLE001 — QA action must survive
            issues.append({
                "kind": "cartographic",
                "message": f"制图 QA 规则集评估失败：{exc}",
                "layer_id": "",
            })
        status = "passed" if not issues else "issues"
        document = self.project
        if document is not None:
            from paleo_workbench.project.models import QualityReport

            document.quality_reports.append(QualityReport(
                linked_map_document_id="",
                rules=["topology", "staleness", *carto_rules],
                issues=issues,
                status=status,
            ))
        controller.refresh_evaluation()
        if not issues:
            self.composite.status_message.emit("QA 通过：无几何/拓扑问题，无过期输入")
        else:
            self.composite.status_message.emit(f"QA 发现 {len(issues)} 个问题（见 05 QA/QC）")

    def assemble_map_product(self) -> None:
        """生成 MapProduct（复用 workflow.map_product 组装器，V5 §58）。"""
        document = self.project
        if document is None:
            return
        try:
            from paleo_workbench.catalog.runtime import get_catalog_service
            from paleo_workbench.workflow.map_product import (
                MapProductAssembly,
                assemble_map_product,
            )
        except Exception:
            self.composite.status_message.emit("MapProduct 组装需要打开工程与数据目录")
            return
        factor_ids = []
        for value in self.stage_controller.state.compilation_input_set.values():
            text = str(value)
            if text.startswith("factor:"):
                factor_ids.append(text.split(":")[1])
        if not factor_ids:
            self.composite.status_message.emit(
                "证据集中没有单因素任务——先选择证据（含 factor 版本）")
            return
        try:
            catalog = get_catalog_service()
        except Exception:
            self.composite.status_message.emit("数据目录不可用（先打开工程文件）")
            return
        from paleo_workbench.workflow.map_product import write_product_manifest

        staged_path = None
        try:
            staged_path = write_product_manifest(
                document,
                product_name=f"综合编图 {document.meta.name}",
                factor_task_ids=factor_ids,
            )
            assembly = MapProductAssembly(
                product_name=f"综合编图 {document.meta.name}",
                factor_task_ids=factor_ids,
            )
            result = assemble_map_product(
                document, assembly=assembly, catalog=catalog,
                payload_path=staged_path)
        except Exception as exc:
            logger.exception("map product assembly failed")
            self.composite.status_message.emit(f"MapProduct 组装失败：{exc}")
            return
        finally:
            if staged_path is not None:
                # The catalog copied the payload into the managed OUTPUT
                # store; the staging file must not linger in temp.
                try:
                    staged_path.unlink(missing_ok=True)
                except OSError:
                    pass
        self.composite.status_message.emit(
            f"MapProduct 已生成（{result.record_id}；输出版本 {result.output_version_id[:12]}…）")
        # V7 §8：新装配的成果进入 Inspector（staleness 来自依赖评估权威）。
        record = next(
            (item for item in getattr(document, "map_products", None) or []
             if str(getattr(item, "id", "")) == str(result.record_id)),
            None,
        )
        if record is not None:
            from paleo_workbench.ui.workstation.state_language import state_token

            freshness = self.stage_controller.group_controller.artifact_freshness(
                f"mapproduct:{record.id}")
            self.composite.object_selected.emit({
                "kind": "map_product",
                "object": record,
                "staleness": (
                    state_token("freshness", freshness.status.value)
                    if freshness is not None else None),
            })

    def stage_save(self) -> None:
        """保存阶段成果：flush 编辑会话 + 约束几何回填 + 工作区状态落工程。

        blocked（RAW 门禁拒绝/拓扑失败）逐条原因已由 flush 自身经
        status_message 发出（composite.flush 只返回提交数）。
        """
        committed = self.composite.flush_edit_sessions()
        synced = self._sync_constraint_geometry()
        self.composite._sync_workspace_state_to_project()
        message = "阶段成果已保存"
        if committed:
            message += f"（提交 {committed} 个编辑会话）"
        if synced:
            message += f"；回填 {synced} 条约束几何（含内容指纹）"
        self.composite.status_message.emit(message)

    def _sync_constraint_geometry(self) -> int:
        """约束几何回填（§11 P0-3）：数字化矢量 → ConstraintLine.coordinates。

        flush 后 user_vector_layers 已写回工程文档，此处按 layer_id 邮戳
        迭代约束线并回填。失败（空层/未知层）不阻断保存——保存语义优先。
        """
        from paleo_workbench.mapping_workspace.constraints_sync import (
            sync_constraint_geometry,
        )

        document = self.project
        if document is None:
            return 0
        count = 0
        seen: set[str] = set()
        for group in getattr(document, "constraint_layers", None) or []:
            for line in list(group.lines):
                layer_id = str((line.properties or {}).get("layer_id") or "")
                if not layer_id or layer_id in seen:
                    continue
                seen.add(layer_id)
                try:
                    report = sync_constraint_geometry(document, layer_id)
                except Exception:
                    logger.exception(
                        "constraint geometry sync failed for %s", layer_id)
                    continue
                if report.get("ok"):
                    count += int(report.get("lines_synced") or 0)
        return count
