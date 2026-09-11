"""CRS truth chain: guard policy + chain facts (V10 M-B/M-C).

The chain (goal statement):

    ProjectDocument CRS → crs_contract → QgsProject CRS →
    QgsCoordinateTransformContext → QgsMapCanvas destination CRS →
    active layer CRS → transforms (capture/identify/measure/snapping) →
    VectorEditSession storage CRS.

This module owns two things:

* :func:`evaluate_commit_guard` — the digitize-commit policy. V9 semantics
  were "any side unknown = no compare" (honest, because a missing proj.db
  made the canvas side unknowable). V10 keeps that honesty for genuinely
  incapable runtimes but **fails closed when the runtime is CRS-capable and
  the canvas side is still unknown** — with proj.db provisioned
  (:mod:`paleo_workbench.qgis_runtime`) an unknown canvas CRS is a real
  failure, not a recipe constraint.
* :class:`CrsChainFacts` — a projection of the chain state for consumers
  (status surfaces, ToolContext): declared project CRS, effective storage
  CRS, canvas CRS, and mismatch reasons.

Predicates and normalization come from :mod:`paleo_workbench.mapping.crs_contract`
(the single resolution authority since V9 W3) — nothing here re-derives them.
"""

from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.mapping.crs_contract import normalize_crs


@dataclass(frozen=True)
class GuardVerdict:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # convenience: `if verdict:` = allowed
        return self.allowed


def evaluate_commit_guard(
    canvas_crs: str,
    storage_crs: str,
    *,
    runtime_crs_capable: bool,
) -> GuardVerdict:
    """Digitize-commit CRS guard（V9 W7 的 V10 收敛版）。

    输入语义：``canvas_crs`` = 画布目标 CRS（``destination_crs()`` 诚实
    空串 = 未知）；``storage_crs`` = 捕获层的有效存储 CRS（layer.crs 或
    由宿主解析的工程 CRS——由 provider 侧解析，未声明 = 空串）。

    判定表：

    - 两侧已声明：相同 authid → 允许；不同 → 拒绝（V9 起不变）。
    - 存储已声明、画布未知：runtime CRS 可用 → **拒绝**（fail-closed：
      可解析的运行时里画布 CRS 未知 = 真实故障）；不可用 → 允许
      （V9 诚实语义：未知不比对）。
    - 画布已声明、存储未声明：允许（raw 帧采集——镜像把画布 CRS 设为
      工程 CRS，未声明层以 raw 画布坐标存储，构造上自洽），reason 备注。
    - 两侧都未知：允许（raw 帧编辑）。
    """
    canvas = normalize_crs(canvas_crs)
    storage = normalize_crs(storage_crs)
    if canvas and storage:
        if canvas == storage:
            return GuardVerdict(True)
        return GuardVerdict(
            False,
            f"canvas CRS {canvas} != layer storage CRS {storage}",
        )
    if storage and not canvas:
        if runtime_crs_capable:
            return GuardVerdict(
                False,
                "canvas destination CRS unresolved in a CRS-capable runtime "
                "(proj chain broken?) — commit rejected",
            )
        return GuardVerdict(True, "canvas CRS unknown (runtime not CRS-capable); no compare")
    if canvas and not storage:
        return GuardVerdict(True, "storage CRS undeclared (raw frame); no compare")
    return GuardVerdict(True, "both sides undeclared (raw frame)")


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
        verdict = evaluate_commit_guard(
            self.canvas_crs,
            self.storage_crs,
            runtime_crs_capable=self.runtime_crs_capable,
        )
        return verdict.allowed

    @property
    def reason(self) -> str:
        return evaluate_commit_guard(
            self.canvas_crs,
            self.storage_crs,
            runtime_crs_capable=self.runtime_crs_capable,
        ).reason

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
    process-cached, so calling this per commit is cheap after the first
    call. When the bridge is absent entirely the answer is False (fallback
    canvas: single-frame rendering, the guard keeps V9 honesty).
    """
    try:
        from paleo_workbench.qgis_runtime.health import probe_qgis_runtime

        status = probe_qgis_runtime()
        return bool(status.qgis_available and status.canvas_crs_available)
    except Exception:
        return False
