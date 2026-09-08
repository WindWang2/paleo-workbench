"""阶段上下文动作分派（V5 M6–M9）：面板动作 → 具体工作流。

动作语义按阶段（V5 §12/§19/§27）：

* Phase 1：加载初始相图（RAW）、叠加测井/地震预测（模型结果，不可编辑）、
  **RAW→DERIVED 建稿**（人工解释绝不动 RAW）、保存阶段成果。
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


#: 阶段上下文动作单一词表（V7 R2-F1：阶段面板按钮、palette 注册、
#: dispatcher 执行共用这一份——(action_id, label)，按阶段）。
#: 此前三套手维护表（panel._PHASEn_ACTIONS / dispatcher map / profile
#: context_actions）互不推导，存在漂移（评审 R2-F1）。
STAGE_CONTEXT_ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "facies_calibration": (
        ("load_initial_facies", "加载初始相图"),
        ("add_well_prediction_overlay", "叠加测井预测"),
        ("add_seismic_prediction_overlay", "叠加地震预测"),
        ("create_facies_draft", "创建解释草稿"),
        ("stage_save", "保存阶段成果"),
    ),
    "constraint_factor": (
        ("open_factor_workbench", "单因素工作台"),
        ("overlay_factor_results", "叠加单因素结果"),
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

    def dispatch(self, stage_value: str, action_id: str) -> None:
        handler = {
            "load_initial_facies": self.load_initial_facies,
            "add_well_prediction_overlay": self.add_well_prediction_overlay,
            "add_seismic_prediction_overlay": self.add_seismic_prediction_overlay,
            "toggle_prediction_confidence": self.toggle_prediction_confidence,
            "create_facies_draft": self.create_facies_draft,
            "open_factor_workbench": self.open_factor_workbench,
            "run_factor": self.open_factor_workbench,
            "overlay_factor_results": self.overlay_factor_results,
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

    def _stage_role_layer(self, role: LayerRole) -> str | None:
        for layer_id in self.stage_controller.state.layers_with_role(role):
            if self.edit_controller.layer(str(layer_id)) is not None:
                return str(layer_id)
        return None

    # -- Phase 1 ------------------------------------------------------------------

    def load_initial_facies(self) -> None:
        """初始沉积相图（PaleoMapDocument.facies_polygons）→ RAW 叠加图层。

        RAW 不可变（V5 §14）：角色 INITIAL_FACIES_SOURCE 阻止编辑会话。
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
            self.composite.status_message.emit(
                "工程中没有初始沉积相图——先在编图页生成或导入相图文档")
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

    def add_well_prediction_overlay(self) -> None:
        """测井预测结果叠加。

        测井预测是井曲线域结果（WELL_INTERVALS）——地图上以选中井的快速
        联动为主（点击井预测打开测井 dock，V5 §16）。曲线本身不入地图；
        有 VECTOR_POLYGONS 空间结果的预测任务按面叠加。
        """
        self._overlay_polygon_predictions(prefer="well")

    def add_seismic_prediction_overlay(self) -> None:
        """地震预测相叠加（VECTOR_POLYGONS 空间结果 → 独立预测图层）。"""
        self._overlay_polygon_predictions(prefer="seismic")

    @staticmethod
    def _classify_prediction_task(task) -> str:
        """按 machine-readable 信号分类井/震预测（无信号 → unknown）。

        优先 ``input_refs`` 键（well/logs vs seismic）；键无信号时回退任务名
        的显式类别词（此处是展示归类而非科学语义判定，允许名称提示）。
        """
        refs = getattr(task, "input_refs", None) or {}
        keys = " ".join(str(key).lower() for key in refs.keys())
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

    def _overlay_polygon_predictions(self, *, prefer: str) -> None:
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
            if not features:
                continue
            label = f"{getattr(task, 'name', '') or '预测相'}（{'测井' if wanted == 'well' else '地震'}预测）"
            created = self._create_role_layer(
                label, "polygon", role, factor_task_id=task_marker,
                features=[
                    (dict(f.get("geometry") or {}), dict(f.get("properties") or {}))
                    for f in features
                ],
            )
            added += 1 if created else 0
        label = "测井" if wanted == "well" else "地震"
        if not added:
            parts = [f"没有可叠加的{label}预测空间结果（需要 VECTOR_POLYGONS 预测任务）"]
            if unmatched:
                parts.append(f"{unmatched} 个任务无法判别井/震类别（经 input_refs/任务名），未叠加")
            self.composite.status_message.emit("；".join(parts))
        else:
            message = f"已叠加 {added} 个{label}预测结果图层（不可编辑）"
            if already:
                message += f"；{already} 个此前已叠加，跳过"
            self.composite.status_message.emit(message)

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
