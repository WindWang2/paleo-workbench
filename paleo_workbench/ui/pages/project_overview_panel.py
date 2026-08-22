"""Project/WorkArea overview panel (工区概览).

Cheap, cached reads only — never triggers filesystem scans or catalog
rebuilds.  Numbers come from the in-memory domain registries plus the
CatalogCounts the data page already computed for the navigation tree.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens


def _stat_label() -> QLabel:
    label = QLabel("—")
    label.setStyleSheet(f"font-size: {tokens.FONT_SIZE_BASE}px; font-weight: 600;")
    return label


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
    return label


class ProjectOverviewPanel(QWidget):
    """工区概览: identity, CRS, extent and lifecycle counts at a glance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectOverviewPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4)
        root.setSpacing(tokens.SPACE_4)

        self.title_label = QLabel("工区概览")
        self.title_label.setStyleSheet(f"font-size: {tokens.FONT_SIZE_TITLE}px; font-weight: 700;")
        root.addWidget(self.title_label)

        self.meta_label = QLabel("未打开工程")
        self.meta_label.setWordWrap(True)
        root.addWidget(self.meta_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(tokens.SPACE_4)
        grid.setVerticalSpacing(tokens.SPACE_3)
        self._values: dict[str, QLabel] = {}
        specs = [
            ("wells", "井"),
            ("surveys", "地震工区"),
            ("raw", "原始输入 RAW"),
            ("derived", "派生 DERIVED"),
            ("output", "成果 OUTPUT"),
            ("issues", "缺失 / 外部异常"),
            ("unresolved", "待治理实体"),
            ("recent", "最近任务"),
        ]
        for index, (key, caption) in enumerate(specs):
            value = _stat_label()
            self._values[key] = value
            grid.addWidget(value, index // 2, (index % 2) * 2)
            grid.addWidget(_caption(caption), index // 2, (index % 2) * 2 + 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        root.addLayout(grid)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        self.hint_label.setVisible(False)
        root.addWidget(self.hint_label)
        root.addStretch(1)

    # ------------------------------------------------------------------

    def refresh_from_project(
        self,
        project: Any,
        *,
        counts: Any = None,
    ) -> None:
        """Re-render from the in-memory document (no IO)."""
        if project is None:
            self.meta_label.setText("未打开工程")
            return
        workarea = getattr(project, "workarea", None)
        meta = project.meta
        coordinate = project.coordinate
        crs = getattr(workarea, "project_crs", "") or coordinate.project_crs
        region = str(getattr(meta, "region", "") or "")
        name = str(getattr(workarea, "name", "") or meta.name or "")
        self.title_label.setText(f"工区 · {name}")
        self.meta_label.setText(f"CRS: {crs or '未设置'}" + (f"　区域: {region}" if region else ""))

        wells = list(getattr(project, "wells", None) or [])
        surveys = list(getattr(project, "seismic_surveys", None) or [])
        links = list(getattr(project, "entity_asset_links", None) or [])
        unresolved = sum(1 for link in links if link.unresolved)
        from paleo_workbench.project.domain import coordinate_status_is_flagged

        bad_coords = sum(
            1 for well in wells if coordinate_status_is_flagged(well.coordinate_status)
        )

        stages = dict(getattr(counts, "stages", {}) or {})
        integrity = dict(getattr(counts, "integrity", {}) or {})
        self._values["wells"].setText(str(len(wells)))
        self._values["surveys"].setText(str(len(surveys)))
        self._values["raw"].setText(str(stages.get("raw", 0)))
        self._values["derived"].setText(
            str(stages.get("derived", 0) + stages.get("intermediate", 0))
        )
        self._values["output"].setText(str(stages.get("output", 0)))
        missing = integrity.get("missing", 0) + integrity.get("modified", 0)
        self._values["issues"].setText(str(missing))
        self._values["unresolved"].setText(str(unresolved + bad_coords))

        runs = list(getattr(project, "compilation_runs", None) or [])
        latest = max(runs, key=lambda run: run.updated_at, default=None)
        self._values["recent"].setText(
            str(getattr(latest, "name", "") or "—") if latest is not None else "—"
        )

        hints: list[str] = []
        if unresolved:
            hints.append(f"{unresolved} 条数据关联存在歧义，请在井列表中治理。")
        if bad_coords:
            hints.append(f"{bad_coords} 口井坐标缺少 CRS 或转换失败，地图按源坐标显示。")
        boundary = list(getattr(workarea, "boundary", None) or []) if workarea else []
        if boundary:
            xs = [float(point[0]) for point in boundary if len(point) >= 2]
            ys = [float(point[1]) for point in boundary if len(point) >= 2]
            if xs and ys:
                hints.append(
                    f"工区范围: X [{min(xs):.1f}, {max(xs):.1f}] · Y [{min(ys):.1f}, {max(ys):.1f}]"
                )
        elif wells:
            xs = [well.project_x for well in wells if well.project_x is not None]
            ys = [well.project_y for well in wells if well.project_y is not None]
            if xs and ys:
                hints.append(
                    f"井位范围: X [{min(xs):.1f}, {max(xs):.1f}] · Y [{min(ys):.1f}, {max(ys):.1f}]"
                )
        self.hint_label.setText("\n".join(hints))
        self.hint_label.setVisible(bool(hints))
