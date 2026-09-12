"""CRS truth chain: edit-entry policy + chain facts (V10 M-B/M-C; M0 §6 收敛).

The chain (goal statement):

    ProjectDocument CRS → crs_contract → QgsProject CRS →
    QgsCoordinateTransformContext → QgsMapCanvas destination CRS →
    active layer CRS → transforms (capture/identify/measure/snapping) →
    VectorEditSession storage CRS.

This module owns two things:

* :func:`evaluate_edit_entry` — the **pre-entry** CRS policy of the
  three-stage editing gate (拓扑编辑迁移 M0，决议 #1285). CRS 校验并入
  进前段：会话集合全部层的有效 CRS 与画布同 CRS，且声明 CRS 的有效
  坐标域覆盖数据实际坐标范围（域失配 → 阻止 + 引导，见
  :class:`CrsEntryVerdict.mismatches`）。编辑会话期间 CRS 冻结、提交前
  不重复查——旧 ``evaluate_commit_guard``（数字化提交门）已退休。
* :class:`CrsChainFacts` — a projection of the chain state for consumers
  (status surfaces, ToolContext): declared project CRS, effective storage
  CRS, canvas CRS, and mismatch reasons.

Predicates and normalization come from :mod:`paleo_workbench.mapping.crs_contract`
(the single resolution authority since V9 W3) — nothing here re-derives them.
"""

from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping.crs_contract import (
    DomainMismatch,
    coordinate_domain_mismatch,
    normalize_crs,
)


@dataclass(frozen=True)
class LayerCrsFacts:
    """进前校验的单层 CRS 事实（层声明 CRS + 数据实际坐标范围）。"""

    layer_id: str
    crs: str = ""
    extent: tuple[float, float, float, float] | None = None

    def effective_crs(self, project_crs: str) -> str:
        """有效存储 CRS：层声明优先，未声明回落工程声明（均未声明 = ""）。"""
        return normalize_crs(self.crs) or normalize_crs(project_crs)


@dataclass(frozen=True)
class CrsEntryVerdict:
    """进前段 CRS 门的判定。

    ``allowed`` False 时 ``reason`` 是面向用户的阻断判词；
    ``mismatches`` 携带域失配事实（引导对话框「受影响层」全景的数据源，
    由 ``all_layers`` 供入）。
    """

    allowed: bool
    reason: str = ""
    mismatches: tuple[DomainMismatch, ...] = ()
    canvas_crs: str = ""
    declared_crs: str = ""

    def __bool__(self) -> bool:  # convenience: `if verdict:` = allowed
        return self.allowed


def evaluate_edit_entry(
    layers,
    *,
    canvas_crs: str,
    project_crs: str = "",
    all_layers=None,
    runtime_crs_capable: bool = False,
) -> CrsEntryVerdict:
    """编辑进前段 CRS 门（三段式第 1 段的 CRS 部分，§6 决议 #1285）。

    输入：``layers`` = 会话集合候选层事实（进入编辑 = {活动层}）；
    ``canvas_crs`` = 画布目标 CRS（空串 = 未知，诚实）；
    ``all_layers`` = 工程全部层（缺省 = ``layers``）——只用于域失配的
    「受影响层」全景（引导对话框列出所有失配层，不只是本次候选）。

    判定（按序）：

    1. **域校验**：任一候选层的有效声明 CRS 的坐标域不覆盖其数据范围
       → 拒绝（引导修复：一键改声明为本地/清除）。
    2. **同 CRS**：候选层有效 CRS 与画布 CRS 都已声明且不同 → 拒绝；
       层已声明而画布未知且 runtime CRS 可用 → 拒绝（fail-closed：
       proj 链健康时画布未知 = 真实故障）；其余组合（raw 帧）放行。
    """
    candidate = tuple(layers) if layers is not None else ()
    canvas = normalize_crs(canvas_crs)
    declared = normalize_crs(project_crs)

    mismatches: list[DomainMismatch] = []
    affected: list[str] = []
    facts = candidate if all_layers is None else tuple(all_layers)
    for layer in facts:
        effective = layer.effective_crs(declared)
        mismatch = coordinate_domain_mismatch(effective, layer.extent)
        if mismatch is not None:
            mismatches.append(mismatch)
            affected.append(str(layer.layer_id))
    if mismatches:
        first = mismatches[0]
        return CrsEntryVerdict(
            False,
            f"工程/图层声明的 CRS {first.crs} 与数据实际坐标范围不符"
            f"（{first.describe()}）。受影响图层：{'、'.join(affected)}",
            mismatches=tuple(mismatches),
            canvas_crs=canvas,
            declared_crs=declared,
        )

    for layer in candidate:
        storage = layer.effective_crs(declared)
        if canvas and storage:
            if canvas != storage:
                return CrsEntryVerdict(
                    False,
                    f"画布 CRS {canvas} != 图层「{layer.layer_id}」"
                    f"存储 CRS {storage}",
                    canvas_crs=canvas,
                    declared_crs=declared,
                )
        elif storage and not canvas and runtime_crs_capable:
            return CrsEntryVerdict(
                False,
                f"图层「{layer.layer_id}」声明 CRS {storage}，但画布目标 "
                "CRS 未知（proj 运行链健康的运行时中这是真实故障）",
                canvas_crs=canvas,
                declared_crs=declared,
            )
    return CrsEntryVerdict(True, canvas_crs=canvas, declared_crs=declared)


@dataclass(frozen=True)
class CrsChainFacts:
    """Chain snapshot for status surfaces / ToolContext（只读投影）。"""

    project_crs: str = ""
    canvas_crs: str = ""
    storage_crs: str = ""
    runtime_crs_capable: bool = False

    @property
    def project_declared(self) -> bool:
        return bool(normalize_crs(self.project_crs))

    @property
    def canvas_declared(self) -> bool:
        return bool(normalize_crs(self.canvas_crs))

    @property
    def consistent(self) -> bool:
        verdict = evaluate_edit_entry(
            [LayerCrsFacts(layer_id="<chain>", crs=self.storage_crs)],
            canvas_crs=self.canvas_crs,
            project_crs=self.project_crs,
            runtime_crs_capable=self.runtime_crs_capable,
        )
        return verdict.allowed

    @property
    def reason(self) -> str:
        verdict = evaluate_edit_entry(
            [LayerCrsFacts(layer_id="<chain>", crs=self.storage_crs)],
            canvas_crs=self.canvas_crs,
            project_crs=self.project_crs,
            runtime_crs_capable=self.runtime_crs_capable,
        )
        return verdict.reason

    def as_dict(self) -> dict[str, object]:
        return {
            "project_crs": normalize_crs(self.project_crs),
            "canvas_crs": normalize_crs(self.canvas_crs),
            "storage_crs": normalize_crs(self.storage_crs),
            "runtime_crs_capable": self.runtime_crs_capable,
            "consistent": self.consistent,
            "reason": self.reason,
        }


def runtime_crs_capable() -> bool:
    """True when the vendored runtime can resolve the key CRS set (cached).

    Sourced from :mod:`paleo_workbench.qgis_runtime.health` — the probe is
    process-cached, so calling this per entry is cheap after the first
    call. When the bridge is absent entirely the answer is False (fallback
    canvas: single-frame rendering, raw-frame semantics stay honest).
    """
    try:
        from paleo_workbench.qgis_runtime.health import probe_qgis_runtime

        status = probe_qgis_runtime()
        return bool(status.qgis_available and status.canvas_crs_available)
    except Exception:
        return False
