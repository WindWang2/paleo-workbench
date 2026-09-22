"""Version → mapping usage reverse query (V13 W-I / W-M).

回答「这个 DataVersion 被哪些地图内容引用？」——从既有权威**派生投影**，
不新建任何存储：

- ``MappingWorkspaceState.memberships``：图层级绑定（``source_version_id``，
  V13 起含 ``source_asset_id``）；
- ``ProjectDocument.factor_map_tasks``：factor 任务的产品格网版本
  （``grid_artifact_version_id``）——factor 子图层经任务间接绑定；
- ``ProjectDocument.compilation_input_sets``：综合编图输入集的钉定版本
  （``pinned_version_id`` / ``resolved_asset_id``）；
- ``ProjectDocument.map_products``：成图产品的输出版本与 run 输入；
- 可选 catalog：消费该版本的 run（有界）。

正向（图层→版本）由 membership 记录本身回答；本模块补齐反向闭环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from paleo_workbench.mapping_workspace.stage_state import MappingWorkspaceState
    from paleo_workbench.project.models import ProjectDocument

#: run 级用途的硬上限（run 输入可能非常宽，如 53 井预测）。
MAX_RUN_USAGE_ENTRIES = 100

# 用途类别词汇（稳定字符串，UI/Agent 直接消费）。
USAGE_LAYER = "layer"
USAGE_FACTOR_GRID = "factor_grid"
USAGE_COMPILATION_INPUT = "compilation_input"
USAGE_MAP_PRODUCT_OUTPUT = "map_product_output"
USAGE_MAP_PRODUCT_INPUT = "map_product_input"
USAGE_RUN_INPUT = "run_input"


@dataclass(frozen=True)
class VersionUsage:
    """一条「谁在用这个版本」的记录（纯派生，不持久化）。"""

    kind: str
    ref_id: str
    label: str
    #: 匹配到的版本 id（资产级查询时标明是哪个版本被引用）。
    version_id: str = ""
    stage: str = ""
    role: str = ""
    status: str = ""


@dataclass(frozen=True)
class VersionUsageReport:
    usages: list[VersionUsage] = field(default_factory=list)
    truncated: bool = False


def usages_of_version(
    version_id: str,
    *,
    workspace: "MappingWorkspaceState | None",
    project: "ProjectDocument | None",
    catalog: Any = None,
    include_runs: bool = True,
) -> VersionUsageReport:
    """某 DataVersion 的全部地图侧引用（有界，truncated 标志如实）。"""
    vid = str(version_id or "")
    if not vid:
        return VersionUsageReport()
    usages: list[VersionUsage] = []
    truncated = False
    if workspace is not None:
        for layer_id, record in workspace.memberships.items():
            if record.source_version_id == vid:
                usages.append(VersionUsage(
                    kind=USAGE_LAYER,
                    ref_id=str(layer_id),
                    label=f"图层 {layer_id}",
                    version_id=vid,
                    stage=record.created_stage,
                    role=record.role.value,
                ))
    if project is not None:
        for task in getattr(project, "factor_map_tasks", None) or []:
            if str(getattr(task, "grid_artifact_version_id", "") or "") == vid:
                usages.append(VersionUsage(
                    kind=USAGE_FACTOR_GRID,
                    ref_id=str(task.id),
                    label=str(getattr(task, "name", "") or task.id),
                    version_id=vid,
                    role="factor_grid",
                ))
        for raw in getattr(project, "compilation_input_sets", None) or []:
            if not isinstance(raw, dict):
                continue
            set_id = str(raw.get("id") or "")
            set_name = str(raw.get("name") or set_id)
            frozen = bool(raw.get("frozen"))
            for entry in raw.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("pinned_version_id") or "") == vid:
                    usages.append(VersionUsage(
                        kind=USAGE_COMPILATION_INPUT,
                        ref_id=set_id,
                        label=set_name,
                        version_id=vid,
                        status="frozen" if frozen else "draft",
                    ))
        for record in getattr(project, "map_products", None) or []:
            output_vid = str(getattr(record, "output_version_id", "") or "")
            if output_vid == vid:
                usages.append(VersionUsage(
                    kind=USAGE_MAP_PRODUCT_OUTPUT,
                    ref_id=str(record.id),
                    label=str(getattr(record, "product_name", "") or record.id),
                    version_id=vid,
                    status=str(getattr(record, "lifecycle", "") or ""),
                ))
                continue
            run_id = str(getattr(record, "run_id", "") or "")
            if run_id and catalog is not None:
                if _run_consumes(catalog, run_id, vid):
                    usages.append(VersionUsage(
                        kind=USAGE_MAP_PRODUCT_INPUT,
                        ref_id=str(record.id),
                        label=str(getattr(record, "product_name", "") or record.id),
                        version_id=vid,
                        status=str(getattr(record, "lifecycle", "") or ""),
                    ))
    if include_runs and catalog is not None:
        runs = _runs_consuming(catalog, vid)
        for index, run in enumerate(runs):
            if index >= MAX_RUN_USAGE_ENTRIES:
                truncated = True
                break
            usages.append(VersionUsage(
                kind=USAGE_RUN_INPUT,
                ref_id=str(run.id),
                label=f"run {run.operation}",
                version_id=vid,
                status=str(run.status or ""),
            ))
    return VersionUsageReport(usages=usages, truncated=truncated)


def usages_of_asset(
    asset_id: str,
    *,
    workspace: "MappingWorkspaceState | None",
    project: "ProjectDocument | None",
    catalog: Any = None,
) -> VersionUsageReport:
    """某 DataAsset 的全部地图侧引用（聚合其各版本 + 资产级直绑）。

    有 catalog：遍历资产全部版本逐一反查（版本数通常个位数到几十）。
    无 catalog：只回答资产级绑定（membership.source_asset_id、输入集
    resolved_asset_id）——诚实降级，不伪造版本级结论。
    """
    aid = str(asset_id or "")
    if not aid:
        return VersionUsageReport()
    usages: list[VersionUsage] = []
    seen: set[tuple[str, str, str]] = set()
    if catalog is not None:
        versions = _versions_of_asset(catalog, aid)
        for version in versions:
            report = usages_of_version(
                version.id, workspace=workspace, project=project,
                catalog=catalog, include_runs=False,
            )
            for usage in report.usages:
                key = (usage.kind, usage.ref_id, usage.version_id)
                if key not in seen:
                    seen.add(key)
                    usages.append(usage)
    if workspace is not None:
        for layer_id, record in workspace.memberships.items():
            if record.source_asset_id == aid:
                key = (USAGE_LAYER, str(layer_id), record.source_version_id)
                if key not in seen:
                    seen.add(key)
                    usages.append(VersionUsage(
                        kind=USAGE_LAYER,
                        ref_id=str(layer_id),
                        label=f"图层 {layer_id}",
                        version_id=record.source_version_id,
                        stage=record.created_stage,
                        role=record.role.value,
                    ))
    if project is not None:
        for raw in getattr(project, "compilation_input_sets", None) or []:
            if not isinstance(raw, dict):
                continue
            for entry in raw.get("entries") or []:
                if (isinstance(entry, dict)
                        and str(entry.get("resolved_asset_id") or "") == aid):
                    set_id = str(raw.get("id") or "")
                    key = (USAGE_COMPILATION_INPUT, set_id,
                           str(entry.get("pinned_version_id") or ""))
                    if key not in seen:
                        seen.add(key)
                        usages.append(VersionUsage(
                            kind=USAGE_COMPILATION_INPUT,
                            ref_id=set_id,
                            label=str(raw.get("name") or set_id),
                            version_id=str(entry.get("pinned_version_id") or ""),
                            status="frozen" if raw.get("frozen") else "draft",
                        ))
    return VersionUsageReport(usages=usages, truncated=False)


def usage_counts(report: VersionUsageReport) -> dict[str, int]:
    """按类别计数（状态栏/Inspector 摘要用）。"""
    counts: dict[str, int] = {}
    for usage in report.usages:
        counts[usage.kind] = counts.get(usage.kind, 0) + 1
    return counts


# ---------------------------------------------------------------- helpers
def _run_consumes(catalog: Any, run_id: str, version_id: str) -> bool:
    try:
        run = catalog.get_run(run_id)
    except Exception:
        return False
    if run is None:
        return False
    return version_id in list(run.input_version_ids or [])


def _runs_consuming(catalog: Any, version_id: str) -> list[Any]:
    try:
        runs = catalog.runs_consuming(version_id=version_id)
    except Exception:
        return []
    return list(runs or [])


def _versions_of_asset(catalog: Any, asset_id: str) -> list[Any]:
    try:
        maps = catalog._ensure_maps()
        return list(maps.versions_by_asset.get(asset_id, ()))
    except Exception:
        return []
