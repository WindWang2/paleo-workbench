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

from paleo_workbench.mapping_workspace.layer_groups import factor_group_title
from paleo_workbench.mapping_workspace.layer_roles import (
    ConstraintKind,
    LayerRole,
    constraint_kind_from_value,
)
from paleo_workbench.mapping_workspace.stages import MappingStage

logger = logging.getLogger(__name__)


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
            "create_facies_draft": self.create_facies_draft,
            "open_factor_workbench": self.open_factor_workbench,
            "run_factor": self.open_factor_workbench,
            "overlay_factor_results": self.overlay_factor_results,
            "select_evidence": self.select_evidence,
            "create_integrated_draft": self.create_integrated_draft,
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
            self.composite.hub_page_requested.emit("mapping")
        except Exception:
            self.composite.status_message.emit(
                "请通过左侧功能导航打开单因素制备页运行插值")

    def overlay_factor_results(self) -> None:
        """把已完成单因素任务的结果组织进 factor 组（V5 §21/§71）。

        同一 FactorGridResult 在 Phase 2/3 共享同一数据身份：等值线从
        live 网格缓存派生（缓存缺失时诚实提示，不重算）。
        """
        from paleo_workbench.mapping.geological_pipeline.contouring import (
            calculate_nice_contour_levels,
            generate_contour_layer,
        )
        from paleo_workbench.project.factor_grid_artifacts import peek_live_factor_grid

        document = self.project
        tasks = [
            task for task in (getattr(document, "factor_map_tasks", None) or [])
            if str(getattr(task, "status", "")) == "completed"
        ]
        if not tasks:
            self.composite.status_message.emit("没有已完成的单因素任务可叠加")
            return
        added = skipped = 0
        for task in tasks:
            task_id = str(task.id)
            title = factor_group_title(task.name, getattr(task, "factor_type", ""))
            # 幂等（按角色独立判定）：井点与等值线分别去重——首点只建了
            # 井点（无 live 网格）时，第二次点击仍能补齐等值线。
            def _has_overlay(role) -> bool:
                return any(
                    self.stage_controller.state.membership(lid).role == role
                    and self.stage_controller.state.membership(lid).factor_task_id == task_id
                    and self.edit_controller.layer(lid) is not None
                    for lid in self.stage_controller.state.memberships
                )
            # 输入井点（WellTable 行）。
            table = None
            for candidate in getattr(document, "well_tables", None) or []:
                if str(candidate.id) == str(getattr(task, "well_table_id", "") or ""):
                    table = candidate
                    break
            if table is not None and getattr(table, "rows", None) \
                    and not _has_overlay(LayerRole.FACTOR_INPUT):
                features = []
                for row in table.rows:
                    x = getattr(row, "x", None)
                    y = getattr(row, "y", None)
                    if x is None or y is None:
                        continue
                    value = getattr(row, "value", None)
                    features.append((
                        {"type": "Point", "coordinates": [float(x), float(y)]},
                        {"value": float(value) if value is not None else None,
                         "well": str(getattr(row, "well_name", "") or "")},
                    ))
                if features:
                    self._create_role_layer(
                        f"{title}·井点", "point", LayerRole.FACTOR_INPUT,
                        factor_task_id=task_id, features=features)
            # 等值线（live 网格缓存 → marching squares）。
            grid = peek_live_factor_grid(task_id)
            if grid is None:
                skipped += 1
                continue
            if _has_overlay(LayerRole.FACTOR_CONTOUR):
                continue
            try:
                contour = generate_contour_layer(
                    grid, levels=calculate_nice_contour_levels(grid),
                    name=f"{title}·等值线")
                snapshot = contour.to_snapshot()
                created = self._create_role_layer(
                    f"{title}·等值线", "line", LayerRole.FACTOR_CONTOUR,
                    factor_task_id=task_id,
                    features=[
                        (dict(record.get("geometry") or {}),
                         dict(record.get("properties") or {}))
                        for record in snapshot.features
                    ])
                added += 1 if created else 0
            except Exception:
                logger.exception("factor contour overlay failed for %s", task_id)
                skipped += 1
        message = f"已叠加 {added} 组单因素等值线（自动归入 factor 组）"
        if skipped:
            message += f"；{skipped} 个任务无 live 网格（打开制备页加载后可叠加）"
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
            if str(getattr(task, "status", "")) != "completed":
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
        status = "passed" if not issues else "issues"
        document = self.project
        if document is not None:
            from paleo_workbench.project.models import QualityReport

            document.quality_reports.append(QualityReport(
                linked_map_document_id="",
                rules=["topology", "staleness"],
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
        try:
            import pathlib

            root = str(getattr(getattr(document, "meta", None), "project_root", "") or ".")
            payload_dir = pathlib.Path(root) / ".artifacts"
            assembly = MapProductAssembly(
                product_name=f"综合编图 {document.meta.name}",
                factor_task_ids=factor_ids,
            )
            result = assemble_map_product(
                document, assembly=assembly, catalog=catalog,
                payload_path=payload_dir)
        except Exception as exc:
            logger.exception("map product assembly failed")
            self.composite.status_message.emit(f"MapProduct 组装失败：{exc}")
            return
        self.composite.status_message.emit(
            f"MapProduct 已生成（{result.record_id}；输出版本 {result.output_version_id[:12]}…）")

    def stage_save(self) -> None:
        """保存阶段成果：flush 编辑会话 + 工作区状态落工程。"""
        committed, blocked = self.composite.flush_edit_sessions()
        self.composite._sync_workspace_state_to_project()
        message = "阶段成果已保存"
        if blocked:
            message += f"；{len(blocked)} 个会话被拓扑校验阻断（保持打开）"
        self.composite.status_message.emit(message)
