"""跨阶段成果依赖与新鲜度（freshness）服务。

复用 Catalog 的 version/run/lineage 权威（V5 §32「不要另造 dependency
DB」）：本服务只做 **domain 查询**——按阶段成果的版本钉住关系
（pinned inputs）评估每项成果的 freshness，并汇总下游 STALE 提示。

阶段成果与钉住关系：

* Phase 1 解释草稿（``phase1_draft:<layer_id>``）钉住 RAW 初始相图版本
  （membership ``source_version_id``）；
* 单因素任务（``factor:<task_id>``）钉住其 DataRun 的 input versions
  （经 ``grid_artifact_version_id`` → run → inputs 解析）；
* 综合解释（``integrated:<layer_id>``）钉住 ``compilation_input_set``
  （Compilation Input Set，V5 §57：明确选择的证据版本/指纹）；
* MapProduct（``mapproduct:<record_id>``）钉住其组装 run 的 inputs。

判定规则（V5 §31/§32）：

* 钉住的输入版本缺失/被清理 → ``MISSING_INPUT``；
* 输入所在资产已有更新版本（pinned ≠ current）→ ``STALE``；
* 成果自身输出不再是资产当前版本 → ``SUPERSEDED``；
* 指纹类输入（约束内容指纹）与当前不符 → ``STALE``；
* 其余 → ``CURRENT``；无法判定（无版本/无 run）→ ``UNKNOWN``。

**绝不自动删除或覆盖旧成果**——STALE 只是标记与提示。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage


class FreshnessStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    MISSING_INPUT = "missing_input"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


_STATUS_LABELS = {
    FreshnessStatus.CURRENT: "最新",
    FreshnessStatus.STALE: "已过期",
    FreshnessStatus.MISSING_INPUT: "输入缺失",
    FreshnessStatus.SUPERSEDED: "已被取代",
    FreshnessStatus.UNKNOWN: "状态未知",
}


@dataclass(frozen=True)
class ArtifactFreshness:
    """一项阶段成果的新鲜度评估。"""

    artifact_key: str
    artifact_type: str  # phase1_draft | factor | constraint | integrated | mapproduct
    stage: MappingStage
    status: FreshnessStatus
    detail: str = ""
    #: 钉住的输入（版本 id 或 fingerprint 引用）。
    pinned_inputs: tuple[tuple[str, str], ...] = ()
    #: 导致过期/缺失的上游（artifact_key 或 version_id）。
    upstream_culprits: tuple[str, ...] = ()

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS[self.status]

    @property
    def is_problem(self) -> bool:
        return self.status in (
            FreshnessStatus.STALE,
            FreshnessStatus.MISSING_INPUT,
            FreshnessStatus.SUPERSEDED,
       )


@dataclass(frozen=True)
class StaleSummary:
    """整个工作区的新鲜度汇总（供阶段切换提示/就绪度/图层指示）。"""

    artifacts: tuple[ArtifactFreshness, ...] = ()

    @property
    def stale_entries(self) -> tuple[ArtifactFreshness, ...]:
        return tuple(a for a in self.artifacts if a.is_problem)

    @property
    def stale_count(self) -> int:
        return len(self.stale_entries)

    def by_stage(self, stage: MappingStage) -> tuple[ArtifactFreshness, ...]:
        return tuple(a for a in self.artifacts if a.stage == stage)

    def stage_stale_count(self, stage: MappingStage) -> int:
        return sum(1 for a in self.stale_entries if a.stage == stage)

    def get(self, artifact_key: str) -> ArtifactFreshness | None:
        for artifact in self.artifacts:
            if artifact.artifact_key == artifact_key:
                return artifact
        return None

    @property
    def headline(self) -> str:
        if not self.stale_entries:
            return ""
        if self.stale_count == 1:
            return "1 项输入成果已过期"
        return f"{self.stale_count} 项输入成果已过期"


class MappingDependencyService:
    """评估跨阶段成果 freshness（纯 domain 查询，无缓存、不写 Catalog）。"""

    def evaluate(
        self,
        document,
        workspace_state=None,
        catalog=None,
    ) -> StaleSummary:
        """对工程的全部阶段成果做一次新鲜度评估。"""
        entries: list[ArtifactFreshness] = []
        if document is None:
            return StaleSummary(tuple(entries))
        entries.extend(self._evaluate_phase1_drafts(document, workspace_state, catalog))
        entries.extend(self._evaluate_factors(document, catalog))
        entries.extend(self._evaluate_integrated(document, workspace_state, catalog))
        entries.extend(self._evaluate_map_products(document, catalog))
        return StaleSummary(tuple(entries))

    # -- 内部：版本查询辅助 -----------------------------------------------------

    def _asset_current_version(self, catalog, asset_id: str) -> str | None:
        """资产当前版本 id（list_versions 最大 version_number）。"""
        if catalog is None or not asset_id:
            return None
        try:
            versions = catalog.list_versions(asset_id=asset_id) or []
        except Exception:
            return None
        best = None
        best_number = -1
        for version in versions:
            number = int(getattr(version, "version_number", 0) or 0)
            if number > best_number:
                best_number = number
                best = str(getattr(version, "id", "") or "")
        return best

    def _version_info(self, catalog, version_id: str):
        if catalog is None or not version_id:
            return None
        try:
            return catalog.resolve_version(version_id)
        except Exception:
            return None

    def _run_input_versions(self, catalog, run_id: str) -> list[str]:
        if catalog is None or not run_id:
            return []
        try:
            run = catalog.resolve_run(run_id)
        except Exception:
            return []
        if run is None:
            return []
        return [str(v) for v in (getattr(run, "input_version_ids", None) or [])]

    def _check_pinned_versions(
        self,
        catalog,
        pinned: list[str],
    ) -> tuple[FreshnessStatus, list[str], str]:
        """一组钉住版本的 currency 检查 → (status, culprits, detail)。"""
        missing: list[str] = []
        stale: list[str] = []
        for version_id in pinned:
            info = self._version_info(catalog, version_id)
            if info is None:
                missing.append(version_id)
                continue
            asset_id = str(getattr(info, "asset_id", "") or "")
            current = self._asset_current_version(catalog, asset_id)
            if current and current != version_id:
                stale.append(version_id)
        if missing:
            return FreshnessStatus.MISSING_INPUT, missing, "输入版本缺失或已清理"
        if stale:
            return FreshnessStatus.STALE, stale, "上游输入已有新版本"
        return FreshnessStatus.CURRENT, [], ""

    def _check_output_superseded(self, catalog, output_version_id: str) -> bool:
        info = self._version_info(catalog, output_version_id)
        if info is None:
            return False
        asset_id = str(getattr(info, "asset_id", "") or "")
        current = self._asset_current_version(catalog, asset_id)
        return bool(current and current != output_version_id)

    # -- 各阶段成果 -------------------------------------------------------------

    def _evaluate_phase1_drafts(self, document, workspace_state, catalog) -> list:
        results: list[ArtifactFreshness] = []
        if workspace_state is None:
            return results
        for layer_id, record in workspace_state.memberships.items():
            if record.role != LayerRole.INITIAL_FACIES_DRAFT:
                continue
            key = f"phase1_draft:{layer_id}"
            pinned = [record.source_version_id] if record.source_version_id else []
            if not pinned:
                results.append(ArtifactFreshness(
                    key, "phase1_draft", MappingStage.FACIES_CALIBRATION,
                    FreshnessStatus.UNKNOWN, "草稿未钉住 RAW 版本（旧工程迁移）"))
                continue
            status, culprits, detail = self._check_pinned_versions(catalog, pinned)
            results.append(ArtifactFreshness(
                key, "phase1_draft", MappingStage.FACIES_CALIBRATION,
                status, detail, pinned_inputs=tuple(
                    ("version", p) for p in pinned),
                upstream_culprits=tuple(culprits)))
        return results

    def _evaluate_factors(self, document, catalog) -> list:
        results: list[ArtifactFreshness] = []
        for task in getattr(document, "factor_map_tasks", None) or []:
            key = f"factor:{task.id}"
            grid_version = str(getattr(task, "grid_artifact_version_id", "") or "")
            if not grid_version:
                results.append(ArtifactFreshness(
                    key, "factor", MappingStage.CONSTRAINT_FACTOR,
                    FreshnessStatus.UNKNOWN, "任务尚无插值结果版本"))
                continue
            info = self._version_info(catalog, grid_version)
            run_id = str(getattr(info, "run_id", "") or "") if info is not None else ""
            inputs = self._run_input_versions(catalog, run_id)
            if not inputs:
                results.append(ArtifactFreshness(
                    key, "factor", MappingStage.CONSTRAINT_FACTOR,
                    FreshnessStatus.UNKNOWN, "插值 run 未登记输入版本"))
                continue
            status, culprits, detail = self._check_pinned_versions(catalog, inputs)
            if status == FreshnessStatus.CURRENT and self._check_output_superseded(
                    catalog, grid_version):
                status = FreshnessStatus.SUPERSEDED
                detail = "已有更新的插值结果版本"
            results.append(ArtifactFreshness(
                key, "factor", MappingStage.CONSTRAINT_FACTOR,
                status, detail,
                pinned_inputs=tuple(("version", v) for v in inputs),
                upstream_culprits=tuple(culprits)))
        return results

    def _evaluate_integrated(self, document, workspace_state, catalog) -> list:
        """传播式评估：综合解释的过期 = 其证据引用的上游成果过期。

        证据引用契约（select_evidence 写入）：
        * ``draft:<layer_id>`` → 传播 ``phase1_draft:<layer_id>`` 的评估；
        * ``factor:<task_id>:<version>`` → factor 评估 + 版本是否仍为该任务
          当前结果版本（否则 SUPERSEDED/STALE）；
        * ``constraints:current`` → 未钉版本的约束内容（诚实 UNKNOWN，
          **绝不**谎报 STALE——没有比较基准时不可断言过期）；
        * 裸版本 id（``_looks_like_version_id``）→ 直接版本货币性检查。
        """
        results: list[ArtifactFreshness] = []
        if workspace_state is None:
            return results
        input_set = dict(workspace_state.compilation_input_set or {})
        # 先算上游（draft/factor），传播时复用。
        upstream: dict[str, ArtifactFreshness] = {
            entry.artifact_key: entry
            for entry in self._evaluate_phase1_drafts(
                document, workspace_state, catalog)
                + self._evaluate_factors(document, catalog)
        }
        task_grid_version = {
            str(task.id): str(getattr(task, "grid_artifact_version_id", "") or "")
            for task in (getattr(document, "factor_map_tasks", None) or [])
        }
        for layer_id, record in workspace_state.memberships.items():
            if record.role not in (LayerRole.INTEGRATED_FACIES,
                                   LayerRole.INTEGRATED_BOUNDARY):
                continue
            key = f"integrated:{layer_id}"
            if not input_set:
                results.append(ArtifactFreshness(
                    key, "integrated", MappingStage.INTEGRATED_COMPILATION,
                    FreshnessStatus.UNKNOWN,
                    "未选择证据版本（Compilation Input Set 为空）"))
                continue
            pinned_inputs: list[tuple[str, str]] = []
            culprits: list[str] = []
            worst: FreshnessStatus | None = None
            detail = ""
            for ref_key, value in input_set.items():
                value = str(value or "")
                if not value:
                    continue
                if value.startswith("draft:"):
                    upstream_entry = upstream.get(
                        f"phase1_draft:{value[len('draft:'):] }")
                    if upstream_entry is not None:
                        pinned_inputs.append((ref_key, value))
                        if upstream_entry.is_problem and worst is not FreshnessStatus.MISSING_INPUT:
                            worst = upstream_entry.status
                            culprits.append(upstream_entry.artifact_key)
                            detail = f"上游证据已过期：{upstream_entry.artifact_key}"
                elif value.startswith("factor:"):
                    parts = value.split(":")
                    task_id = parts[1] if len(parts) > 1 else ""
                    pinned_version = parts[2] if len(parts) > 2 else ""
                    pinned_inputs.append((ref_key, value))
                    if pinned_version and task_grid_version.get(task_id) \
                            and task_grid_version[task_id] != pinned_version:
                        if worst is not FreshnessStatus.MISSING_INPUT:
                            worst = FreshnessStatus.SUPERSEDED
                            culprits.append(f"factor:{task_id}")
                            detail = f"证据单因素已有新结果版本（{ref_key}）"
                elif value.startswith("constraints:"):
                    # V8 M2: constraint refs now resolve against committed
                    # catalog versions — `constraints:current` compares the
                    # live document to the latest commit (CLEAN/STALE, or
                    # UNKNOWN when nothing was ever committed — never a
                    # fabricated verdict); `constraints:<group>:<version>`
                    # pins check supersession like factor pins.
                    pinned_inputs.append((ref_key, value))
                    try:
                        from paleo_workbench.workflow.constraint_versions import (
                            resolve_constraint_ref,
                        )

                        verdict = resolve_constraint_ref(document, catalog, value)
                        status = verdict["status"]
                        if status is not FreshnessStatus.CURRENT and (
                            status is not FreshnessStatus.UNKNOWN
                            and worst is not FreshnessStatus.MISSING_INPUT
                        ):
                            worst = status
                            culprits.append(ref_key)
                            detail = verdict["detail"]
                    except Exception:  # noqa: BLE001 — freshness stays honest
                        # resolution failure must not fabricate freshness
                        pass
                elif _looks_like_version_id(value):
                    pinned_inputs.append((ref_key, value))
                    status, bad, why = self._check_pinned_versions(
                        catalog, [value])
                    if status != FreshnessStatus.CURRENT and (
                            worst is not FreshnessStatus.MISSING_INPUT):
                        worst = status
                        culprits.extend(bad)
                        detail = why
            if worst is None:
                worst = FreshnessStatus.CURRENT
            results.append(ArtifactFreshness(
                key, "integrated", MappingStage.INTEGRATED_COMPILATION,
                worst, detail,
                pinned_inputs=tuple(pinned_inputs),
                upstream_culprits=tuple(culprits)))
        return results

    def _evaluate_map_products(self, document, catalog) -> list:
        results: list[ArtifactFreshness] = []
        for record in getattr(document, "map_products", None) or []:
            key = f"mapproduct:{record.id}"
            output_version = str(getattr(record, "output_version_id", "") or "")
            run_id = str(getattr(record, "run_id", "") or "")
            inputs = self._run_input_versions(catalog, run_id)
            if not output_version or not inputs:
                results.append(ArtifactFreshness(
                    key, "mapproduct", MappingStage.INTEGRATED_COMPILATION,
                    FreshnessStatus.UNKNOWN, "产品未登记完整溯源 run"))
                continue
            status, culprits, detail = self._check_pinned_versions(catalog, inputs)
            if status == FreshnessStatus.CURRENT and self._check_output_superseded(
                    catalog, output_version):
                status = FreshnessStatus.SUPERSEDED
                detail = "产品已被更新版本取代"
            results.append(ArtifactFreshness(
                key, "mapproduct", MappingStage.INTEGRATED_COMPILATION,
                status, detail,
                pinned_inputs=tuple(("version", v) for v in inputs),
                upstream_culprits=tuple(culprits)))
        return results


def _looks_like_version_id(value: str) -> bool:
    """区分 version id 与内容指纹：version id 带 ``ver_``/uuid 形态。"""
    text = str(value or "")
    return text.startswith(("ver_", "dver_")) or (
        len(text) >= 32 and "-" in text and not text.startswith("sha:")
    )
