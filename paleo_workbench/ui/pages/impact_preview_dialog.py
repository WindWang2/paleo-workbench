"""破坏性操作前的 impact 预览（V13 W-C/W-F）。

任何 destructive catalog 操作（移出项目/回收站、版本删除）先回答
「删掉会影响什么」：

- catalog 血缘：活跃后代、消费/产出 run、断链数、级联建议
  （``ImpactService.delete_impact``，有界只读）；
- 地图侧用途：哪些编图图层/输入集/成图产品正引用它
  （``mapping_workspace.source_usage``，派生投影）。

用户看到后果并显式确认后才继续。计算同步（有界、LRU 缓存），在
GUI 线程可接受；大工程的首次全量 staleness 走 DataPage 既有 worker。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)


def collect_trash_impact(
    service: Any,
    project: Any,
    *,
    asset_ids: list[str],
    workspace: Any = None,
) -> "TrashImpactSummary":
    """聚合多个资产的删除影响（catalog 血缘 + 地图用途）。"""
    from paleo_workbench.catalog.impact import ImpactService
    from paleo_workbench.mapping_workspace.source_usage import (
        usages_of_asset,
    )

    impact_service = ImpactService(service)
    summary = TrashImpactSummary()
    for asset_id in asset_ids:
        try:
            impact = impact_service.delete_impact(
                asset_id=asset_id, project=project)
        except Exception:
            continue
        summary.descendant_count += len(impact.live_descendants)
        summary.descendant_names.extend(
            item.asset_name for item in impact.live_descendants[:20]
            if getattr(item, "asset_name", ""))
        summary.runs_consuming.extend(impact.runs_consuming[:20])
        summary.linked_entities.extend(impact.linked_entities[:20])
        summary.broken_edges += int(impact.broken_lineage_edges)
        summary.cascade_advice.extend(impact.cascade_advice[:5])
        if workspace is not None:
            report = usages_of_asset(
                asset_id, workspace=workspace, project=project,
                catalog=service)
            summary.map_usages.extend(
                (usage.kind, usage.label) for usage in report.usages[:30])
    return summary


@dataclass
class TrashImpactSummary:
    descendant_count: int = 0
    descendant_names: list[str] = field(default_factory=list)
    runs_consuming: list[str] = field(default_factory=list)
    linked_entities: list[tuple[str, str]] = field(default_factory=list)
    broken_edges: int = 0
    cascade_advice: list[str] = field(default_factory=list)
    map_usages: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_downstream(self) -> bool:
        return bool(self.descendant_count or self.runs_consuming
                    or self.map_usages or self.broken_edges)

    def render_markdown(self) -> str:
        lines: list[str] = []
        if self.descendant_count:
            lines.append(f"**{self.descendant_count} 个活跃下游版本依赖所选资产**"
                         "（删除后这些成果的谱系将指向回收站对象）")
            for name in self.descendant_names[:8]:
                lines.append(f"- {name}")
        if self.map_usages:
            layer_usages = [label for kind, label in self.map_usages
                            if kind == "layer"]
            product_usages = [label for kind, label in self.map_usages
                              if kind != "layer"]
            if layer_usages:
                lines.append(f"**{len(layer_usages)} 个编图图层正在引用**：")
                lines.extend(f"- 图层 {label}" for label in layer_usages[:8])
            if product_usages:
                lines.append(f"**{len(product_usages)} 个地图产品/输入集引用**：")
                lines.extend(f"- {label}" for label in product_usages[:8])
        if self.runs_consuming:
            lines.append(f"**{len(self.runs_consuming)} 个 run 以其为输入**"
                         "（run 保留为历史 provenance，不删除）")
        if self.linked_entities:
            names = ", ".join(
                f"{etype}:{eid[:8]}" for etype, eid in self.linked_entities[:6])
            lines.append(f"关联实体：{names}")
        if self.broken_edges:
            lines.append(f"将产生 {self.broken_edges} 条血缘断链")
        for advice in self.cascade_advice[:3]:
            lines.append(f"建议：{advice}")
        if not lines:
            lines.append("未发现下游依赖或地图引用——可以安全移出"
                         "（回收站可随时还原）。")
        return "\n".join(lines)


def confirm_trash_impact(
    parent,
    service: Any,
    project: Any,
    *,
    asset_ids: list[str],
    asset_names: list[str] | None = None,
    workspace: Any = None,
) -> bool:
    """移出/回收前的 impact 确认。返回 True = 用户确认继续。

    无下游影响时静默返回 True（不打扰）；有影响时展示明细并要求显式
    确认（默认按钮是取消——保守取向）。
    """
    summary = collect_trash_impact(
        service, project, asset_ids=asset_ids, workspace=workspace)
    if not summary.has_downstream:
        return True

    dialog = QDialog(parent)
    dialog.setWindowTitle("移出项目 — 影响预览")
    dialog.resize(560, 420)
    layout = QVBoxLayout(dialog)
    names = "、".join(asset_names[:5]) if asset_names else f"{len(asset_ids)} 个资产"
    header = QLabel(f"即将移出：{names}"
                    + ("…" if asset_names and len(asset_names) > 5 else ""))
    header.setWordWrap(True)
    layout.addWidget(header)
    browser = QTextBrowser()
    browser.setOpenExternalLinks(False)
    try:
        import markdown  # type: ignore

        browser.setHtml(markdown.markdown(summary.render_markdown()))
    except Exception:
        browser.setPlainText(summary.render_markdown())
    layout.addWidget(browser, 1)
    # 默认聚焦取消（保守）：Enter 不会误删。
    cancel_btn = QPushButton("取消")
    cancel_btn.setDefault(True)
    proceed_btn = QPushButton("仍然移出（进回收站）")
    proceed_btn.setObjectName("PrimaryButton")
    from PySide6.QtWidgets import QHBoxLayout

    buttons = QHBoxLayout()
    buttons.addStretch(1)
    buttons.addWidget(cancel_btn)
    buttons.addWidget(proceed_btn)
    layout.addLayout(buttons)

    result = {"proceed": False}
    proceed_btn.clicked.connect(lambda: (result.__setitem__("proceed", True),
                                         dialog.accept()))
    cancel_btn.clicked.connect(dialog.reject)
    dialog.exec()
    return bool(result["proceed"])
