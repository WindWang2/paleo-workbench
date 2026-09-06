"""LineageExplorerDialog — 血缘 / 溯源浏览器 (goal D8).

Standalone explorer centered on ONE version: a summary card (asset, stage,
checksum, path) + a provenance card (producing run + parameters) + a lazily
expanded provenance tree with the established interleaved run-node idiom
(OUTPUT → ⚙ Run → INPUT, see ``inspector_panel.LineageTreeWidget``).

Scale contract (feat/catalog-scale-v5):

- The tree is LAZY: every expansion performs exactly ONE
  :meth:`DataCatalogService.get_lineage` hop (direct parents / children).
  The full-chain helper ``get_lineage_chain`` is never called here — no
  full-graph traversal on load or on expand.
- 「展开至 RAW 根」 walks ancestors iteratively via one-hop calls with hard
  caps (depth ≤ :data:`MAX_EXPAND_DEPTH`, nodes ≤ :data:`MAX_EXPAND_NODES`);
  past the cap the button disables with a status note.
- Every expansion renders at most :data:`MAX_CHILDREN_PER_NODE` rows; the
  remainder collapses into a disabled 「…还有 N 个（未展开）」 row.
- A parent id that ``get_lineage`` no longer resolves (purged / dangling)
  renders as a red 「⚠ 断链: <id>」 node instead of being silently dropped.

Read-only: the dialog only calls ``get_version`` / ``get_asset`` / ``get_run``
/ ``get_lineage`` / ``resolve_path`` — the catalog is never mutated. Double-
click or 「在数据页定位」 emits :attr:`version_activated` so the host page can
select the corresponding asset row.
"""
from __future__ import annotations

import json
from collections import deque
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from paleo_workbench.catalog.models import CatalogError, DataStage, DataVersion
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_view_models import stage_icon, stage_label

# Hard display caps (module constants so tests can tighten them).
MAX_CHILDREN_PER_NODE = 200
MAX_EXPAND_DEPTH = 25
MAX_EXPAND_NODES = 1000

_SHORT_ID_LEN = 12


class LineageExplorerDialog(QDialog):
    """Lazy lineage explorer centered on one catalog version (D8)."""

    # Emitted when the user activates a version node (double-click /
    # 「在数据页定位」 / context menu); the host selects the asset row.
    version_activated = Signal(str)

    def __init__(
        self,
        parent=None,
        *,
        service_provider: Callable[[], Any],
        version_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("血缘 / 溯源浏览器 (Lineage Explorer)")
        self.resize(860, 680)
        self._service_provider = service_provider
        self._current_version_id: str | None = None
        self._current_asset_id: str | None = None
        self.up_branch: QTreeWidgetItem | None = None
        self.down_branch: QTreeWidgetItem | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_2)

        # -- top bar: version locator ----------------------------------------
        locator_row = QHBoxLayout()
        locator_row.setSpacing(tokens.SPACE_2)
        locator_row.addWidget(QLabel("版本 ID:"))
        self.version_edit = QLineEdit()
        self.version_edit.setPlaceholderText("输入版本 ID (ver_…) 后回车或点击「定位」")
        self.version_edit.returnPressed.connect(self._on_locate_clicked)
        locator_row.addWidget(self.version_edit, 1)
        self.locate_btn = QPushButton("定位")
        self.locate_btn.setObjectName("PrimaryButton")
        self.locate_btn.clicked.connect(self._on_locate_clicked)
        locator_row.addWidget(self.locate_btn)
        layout.addLayout(locator_row)

        # Inline warning (unknown id / empty input) — never a modal, never a crash.
        self.locate_warning = QLabel("")
        self.locate_warning.setStyleSheet(f"color: {tokens.WARNING}; font-size: 11px;")
        self.locate_warning.setWordWrap(True)
        self.locate_warning.hide()
        layout.addWidget(self.locate_warning)

        # -- current node summary card ---------------------------------------
        summary_card = QFrame()
        summary_card.setObjectName("LineageSummaryCard")
        summary_card.setStyleSheet(
            f"QFrame#LineageSummaryCard {{ background: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        summary_layout.setSpacing(tokens.SPACE_1)
        self.summary_title_label = QLabel("未选择版本")
        self.summary_title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600; font-size: {tokens.FONT_SIZE_TITLE};"
        )
        self.summary_title_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_title_label)
        self.summary_meta_label = QLabel("")
        self.summary_meta_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        self.summary_meta_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_meta_label)
        self.summary_path_label = QLabel("")
        self.summary_path_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
            f" font-family: {tokens.FONT_FAMILY_MONO};"
        )
        self.summary_path_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_path_label)
        layout.addWidget(summary_card)

        # -- provenance card (producing run) ----------------------------------
        run_card = QFrame()
        run_card.setObjectName("LineageRunCard")
        run_card.setStyleSheet(
            f"QFrame#LineageRunCard {{ background: {tokens.BG_HEADER};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        run_layout = QVBoxLayout(run_card)
        run_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        run_layout.setSpacing(tokens.SPACE_1)
        self.run_title_label = QLabel("—")
        self.run_title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600; font-size: {tokens.FONT_SIZE_BASE};"
        )
        self.run_title_label.setWordWrap(True)
        run_layout.addWidget(self.run_title_label)
        self.run_meta_label = QLabel("")
        self.run_meta_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        self.run_meta_label.setWordWrap(True)
        run_layout.addWidget(self.run_meta_label)
        self.run_params_view = QPlainTextEdit()
        self.run_params_view.setReadOnly(True)
        self.run_params_view.setMaximumHeight(110)
        self.run_params_view.setPlaceholderText("运行参数 (JSON)")
        self.run_params_view.setStyleSheet(
            f"font-family: {tokens.FONT_FAMILY_MONO}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        run_layout.addWidget(self.run_params_view)
        layout.addWidget(run_card)

        # -- lazy lineage tree -------------------------------------------------
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("血缘链（懒加载：展开节点查询一层）")
        self.tree.setColumnCount(1)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_STATUS};"
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # -- bottom buttons -----------------------------------------------------
        buttons = QHBoxLayout()
        buttons.setSpacing(tokens.SPACE_2)
        self.expand_raw_btn = QPushButton("展开至 RAW 根")
        self.expand_raw_btn.setObjectName("SecondaryButton")
        self.expand_raw_btn.setEnabled(False)
        self.expand_raw_btn.clicked.connect(self._on_expand_raw)
        buttons.addWidget(self.expand_raw_btn)
        self.locate_in_page_btn = QPushButton("在数据页定位")
        self.locate_in_page_btn.setObjectName("SecondaryButton")
        self.locate_in_page_btn.setEnabled(False)
        self.locate_in_page_btn.clicked.connect(self._on_locate_in_page)
        buttons.addWidget(self.locate_in_page_btn)
        self.copy_id_btn = QPushButton("复制版本 ID")
        self.copy_id_btn.setObjectName("SecondaryButton")
        self.copy_id_btn.setEnabled(False)
        self.copy_id_btn.clicked.connect(self._on_copy_version_id)
        buttons.addWidget(self.copy_id_btn)
        buttons.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        if version_id is not None:
            self._recenter(str(version_id))
        else:
            self._show_empty_state()

    # -- service access ---------------------------------------------------------

    def _service(self) -> Any | None:
        return self._service_provider()

    def current_version_id(self) -> str | None:
        """The version the explorer is currently centered on (None if none)."""
        return self._current_version_id

    def _get_lineage(self, version_id: str) -> dict[str, Any] | None:
        """One-hop lineage read; ``None`` when the version vanished mid-flight."""
        service = self._service()
        if service is None:
            return None
        try:
            return service.get_lineage(version_id)
        except CatalogError:
            return None

    def _asset_name(self, asset_id: str) -> str:
        service = self._service()
        if service is None:
            return asset_id
        try:
            return service.get_asset(asset_id).name
        except CatalogError:
            return asset_id  # purged zombie asset — degrade to the raw id

    # -- locating / loading ------------------------------------------------------

    def _warn(self, message: str) -> None:
        self.locate_warning.setText(message)
        self.locate_warning.show()

    def _on_locate_clicked(self) -> None:
        self._recenter(self.version_edit.text())

    def _recenter(self, version_id: str) -> bool:
        """Center the explorer on *version_id*. Returns True on success.

        Unknown ids surface as an inline warning — the dialog keeps showing
        the previous node instead of crashing.
        """
        vid = version_id.strip()
        if not vid:
            self._warn("请输入版本 ID")
            return False
        service = self._service()
        if service is None:
            self._warn("未连接数据目录（请先打开项目）")
            return False
        try:
            version = service.get_version(vid)
        except CatalogError:
            self._warn(f"未找到版本：{vid}")
            return False
        self.locate_warning.hide()
        self._load_version(version)
        return True

    def _load_version(self, version: DataVersion) -> None:
        service = self._service()
        if service is None:  # defensive: callers already guard
            return
        self._current_version_id = version.id
        self._current_asset_id = version.asset_id
        asset_name = self._asset_name(version.asset_id)
        self._fill_summary(version, asset_name, service)
        lineage = self._get_lineage(version.id)
        run = lineage.get("run") if lineage else None
        self._fill_run_card(run)
        self._rebuild_tree(version, asset_name)

    def _fill_summary(self, version: DataVersion, asset_name: str, service: Any) -> None:
        stage = version.stage
        self.summary_title_label.setText(
            f"{stage_icon(stage)} {asset_name} · v{version.version_number} · {stage_label(stage)}"
        )
        checksum = version.sha256 or "无"
        if len(checksum) > 16:
            checksum = f"{checksum[:12]}…"
        managed_text = "受管 (Managed)" if version.managed else "外部 (External)"
        self.summary_meta_label.setText(
            f"ID: {version.id} · 校验和: {checksum} · "
            f"创建于: {version.created_at or '—'} · {managed_text}"
        )
        path_text = f"路径: {version.path or '—'}"
        resolved = service.resolve_path(version)
        if not resolved.is_file():
            path_text += "　⚠ 源文件缺失"
        self.summary_path_label.setText(path_text)

    def _fill_run_card(self, run: Any) -> None:
        if run is None:
            self.run_title_label.setText("无生成运行")
            self.run_meta_label.setText("")
            self.run_params_view.hide()
            return
        self.run_title_label.setText(f"⚙ 生成运行 · {run.operation}")
        self.run_meta_label.setText(
            f"状态: {run.status or '—'} · 生成器: {run.generator or '—'} · {run.created_at or '—'}"
        )
        self.run_params_view.setPlainText(
            json.dumps(run.parameters or {}, ensure_ascii=False, indent=2)
        )
        self.run_params_view.show()

    def _rebuild_tree(self, version: DataVersion, asset_name: str) -> None:
        self.tree.clear()
        self.up_branch = None
        self.down_branch = None
        current_item = QTreeWidgetItem(
            self.tree,
            [
                f"■ 当前: {stage_icon(version.stage)} {asset_name} · "
                f"v{version.version_number} · {stage_label(version.stage)} · {version.id[:_SHORT_ID_LEN]}"
            ],
        )
        current_item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "kind": "version",
                "version_id": version.id,
                "asset_id": version.asset_id,
                "stage": version.stage.value,
                "direction": None,
                "ancestors": (version.id,),
                "lazy": False,
            },
        )
        current_item.setChildIndicatorPolicy(
            QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
        )
        self.up_branch = self._make_branch(current_item, "⬆ 上游 (← RAW)", "up", version.id)
        self.down_branch = self._make_branch(current_item, "⬇ 下游 (→ 产物)", "down", version.id)
        current_item.setExpanded(True)
        # Pre-expand one lazy hop upstream (the primary question); downstream
        # stays collapsed — it can be wide (same policy as the inspector).
        self.up_branch.setExpanded(True)
        self.tree.setCurrentItem(current_item)
        self.expand_raw_btn.setEnabled(True)
        self.locate_in_page_btn.setEnabled(True)
        self.copy_id_btn.setEnabled(True)

    def _make_branch(
        self, parent_item: QTreeWidgetItem, label: str, direction: str, version_id: str
    ) -> QTreeWidgetItem:
        branch = QTreeWidgetItem(parent_item, [label])
        branch.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "kind": "branch",
                "direction": direction,
                "version_id": version_id,
                "ancestors": (version_id,),
                "lazy": True,
            },
        )
        branch.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        branch.setFlags(branch.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        return branch

    def _show_empty_state(self) -> None:
        self._current_version_id = None
        self._current_asset_id = None
        self.up_branch = None
        self.down_branch = None
        self.summary_title_label.setText("未选择版本")
        self.summary_meta_label.setText("请在上方输入版本 ID 并点击「定位」查看血缘。")
        self.summary_path_label.setText("")
        self.run_title_label.setText("—")
        self.run_meta_label.setText("")
        self.run_params_view.hide()
        self.tree.clear()
        placeholder = QTreeWidgetItem(self.tree, ["（未定位到版本 — 请输入版本 ID）"])
        placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.expand_raw_btn.setEnabled(False)
        self.locate_in_page_btn.setEnabled(False)
        self.copy_id_btn.setEnabled(False)

    # -- lazy population -----------------------------------------------------

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._populate_lazy(item)

    def _populate_lazy(self, item: QTreeWidgetItem) -> None:
        """Populate an item's children on first expansion (idempotent)."""
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict) or not payload.get("lazy"):
            return
        payload["lazy"] = False
        item.setData(0, Qt.ItemDataRole.UserRole, payload)
        kind = payload.get("kind")
        if kind in ("branch", "version"):
            if payload.get("direction") == "up":
                self._populate_inputs(item, payload["version_id"], payload["ancestors"])
            elif payload.get("direction") == "down":
                self._populate_outputs(
                    item, payload["version_id"], payload.get("ancestors", ())
                )

    def _populate_inputs(
        self, holder: QTreeWidgetItem, version_id: str, ancestors: tuple[str, ...]
    ) -> None:
        """List the DIRECT parents of *version_id* under *holder*.

        Exactly one :meth:`get_lineage` hop. When a producing run exists it
        is interleaved between the version and its inputs (OUTPUT → Run →
        INPUT idiom); unresolved parent ids render as red 「⚠ 断链」 nodes
        instead of being silently dropped.
        """
        lineage = self._get_lineage(version_id)
        if lineage is None:
            self._add_note(holder, "（无法读取血缘）")
            return
        version = lineage["version"]
        run = lineage["run"]
        parent_holder = holder
        if run is not None:
            run_item = QTreeWidgetItem(
                holder, [f"⚙ {run.operation} · {run.status or '—'}"]
            )
            run_item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"kind": "run", "run_id": run.id, "output_version_id": version.id},
            )
            run_item.setChildIndicatorPolicy(
                QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator
            )
            parent_holder = run_item
        resolved = {p.id: p for p in lineage["parents"]}
        parent_ids = list(version.parent_version_ids)
        shown = 0
        for pid in parent_ids:
            if shown >= MAX_CHILDREN_PER_NODE:
                self._add_overflow_note(parent_holder, len(parent_ids) - shown)
                break
            parent = resolved.get(pid)
            if pid in ancestors:
                # Cycle check FIRST: a resolvable parent that is already on
                # the current path must not become a re-expandable node.
                self._add_note(parent_holder, f"↺ 循环引用: {pid}")
                shown += 1
                continue
            if parent is not None:
                self._make_version_item(parent_holder, parent, "up", ancestors + (pid,))
            else:
                broken = QTreeWidgetItem(parent_holder, [f"⚠ 断链: {pid}"])
                broken.setData(
                    0, Qt.ItemDataRole.UserRole, {"kind": "broken", "parent_id": pid}
                )
                broken.setForeground(0, QBrush(Qt.GlobalColor.red))
                broken.setFlags(broken.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            shown += 1
        if not parent_ids:
            self._add_note(parent_holder, "（无上游 — RAW 根）")

    def _populate_outputs(
        self, holder: QTreeWidgetItem, version_id: str, ancestors: tuple[str, ...]
    ) -> None:
        """List the DIRECT children of *version_id* under *holder* (one hop).
        Cyclic data (possible via raw attach_lineage) renders a ↺ note for a
        child already on the current path instead of re-expanding forever."""
        lineage = self._get_lineage(version_id)
        if lineage is None:
            self._add_note(holder, "（无法读取血缘）")
            return
        children = list(lineage["children"])
        for child in children[:MAX_CHILDREN_PER_NODE]:
            if child.id in ancestors:
                self._add_note(holder, f"↺ 循环引用: {child.id}")
                continue
            self._make_version_item(holder, child, "down", ancestors + (child.id,))
        if len(children) > MAX_CHILDREN_PER_NODE:
            self._add_overflow_note(holder, len(children) - MAX_CHILDREN_PER_NODE)
        if not children:
            self._add_note(holder, "（无下游衍生）")

    def _make_version_item(
        self,
        parent_item: QTreeWidgetItem,
        version: DataVersion,
        direction: str,
        ancestors: tuple[str, ...],
    ) -> QTreeWidgetItem:
        asset_name = self._asset_name(version.asset_id)
        label = (
            f"{stage_icon(version.stage)} {asset_name} · v{version.version_number} · "
            f"{stage_label(version.stage)} · {version.id[:_SHORT_ID_LEN]}"
        )
        if version.trashed:
            label += " 🗑"
        item = QTreeWidgetItem(parent_item, [label])
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "kind": "version",
                "version_id": version.id,
                "asset_id": version.asset_id,
                "stage": version.stage.value,
                "direction": direction,
                "ancestors": ancestors + (version.id,),
                "lazy": True,
            },
        )
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        return item

    def _add_note(self, parent: QTreeWidgetItem, text: str) -> QTreeWidgetItem:
        note = QTreeWidgetItem(parent, [text])
        note.setFlags(note.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        note.setForeground(0, QBrush(QColor(tokens.TEXT_SECONDARY)))
        return note

    def _add_overflow_note(self, parent: QTreeWidgetItem, remaining: int) -> QTreeWidgetItem:
        note = self._add_note(parent, f"…还有 {remaining} 个（未展开）")
        note.setDisabled(True)
        return note

    # -- expand to RAW ----------------------------------------------------------

    def _input_holder(self, item: QTreeWidgetItem) -> QTreeWidgetItem:
        """Where the inputs of *item*'s version hang (the run node if shown)."""
        for i in range(item.childCount()):
            child = item.child(i)
            payload = child.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict) and payload.get("kind") == "run":
                return child
        return item

    def _iter_version_children(self, holder: QTreeWidgetItem):
        """Yield version rows under *holder*, descending through run rows.

        Inputs hang beneath the interleaved run node (OUTPUT → Run → INPUT),
        so both the upstream branch and a version's input holder may wrap
        their version rows inside a run row.
        """
        for i in range(holder.childCount()):
            child = holder.child(i)
            payload = child.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict):
                continue
            kind = payload.get("kind")
            if kind == "version":
                yield child
            elif kind == "run":
                yield from self._iter_version_children(child)

    def _on_expand_raw(self) -> None:
        """Iteratively expand the upstream branch to every RAW root.

        Bounded walk (depth ≤ :data:`MAX_EXPAND_DEPTH`, nodes ≤
        :data:`MAX_EXPAND_NODES`) using one-hop ``get_lineage`` reads only;
        past the cap the button disables with a status note.
        """
        if self._current_version_id is None or self.up_branch is None:
            return
        self.expand_raw_btn.setEnabled(False)
        visited = {self._current_version_id}
        roots = 0
        capped = False
        self._populate_lazy(self.up_branch)
        self.up_branch.setExpanded(True)
        pending: deque[tuple[QTreeWidgetItem, int]] = deque()
        for child in self._iter_version_children(self.up_branch):
            pending.append((child, 1))
        while pending:
            item, depth = pending.popleft()
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict) or payload.get("kind") != "version":
                continue
            vid = payload.get("version_id")
            if vid is None or vid in visited:
                continue
            if depth > MAX_EXPAND_DEPTH or len(visited) >= MAX_EXPAND_NODES:
                capped = True
                break
            visited.add(vid)
            self._populate_lazy(item)
            item.setExpanded(True)
            if payload.get("stage") == DataStage.RAW.value:
                roots += 1
                continue  # a RAW root stops the upward walk
            holder = self._input_holder(item)
            holder.setExpanded(True)
            for child in self._iter_version_children(holder):
                pending.append((child, depth + 1))
        if capped:
            self.status_label.setText(
                f"⚠ 展开至 RAW 已停止：达到保护上限（深度 ≤ {MAX_EXPAND_DEPTH}，"
                f"节点 ≤ {MAX_EXPAND_NODES}）"
            )
        else:
            self.status_label.setText(
                f"已展开上游至 {roots} 个 RAW 根（共 {max(len(visited) - 1, 0)} 个上游版本）"
            )
            self.expand_raw_btn.setEnabled(True)

    # -- activation / context actions -------------------------------------------

    def _selected_or_current_version_id(self) -> str | None:
        items = self.tree.selectedItems()
        for item in items:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict) and payload.get("kind") == "version":
                return payload["version_id"]
        return self._current_version_id

    def _on_locate_in_page(self) -> None:
        vid = self._selected_or_current_version_id()
        if vid is not None:
            self.version_activated.emit(vid)

    def _on_copy_version_id(self) -> None:
        vid = self._selected_or_current_version_id()
        if vid is not None:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(vid)

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict) and payload.get("kind") == "version":
            self.version_activated.emit(payload["version_id"])

    def _show_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict) or payload.get("kind") != "version":
            return
        vid = payload["version_id"]
        menu = QMenu(self)
        locate_action = menu.addAction("在数据页定位")
        copy_action = menu.addAction("复制版本 ID")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is locate_action:
            self.version_activated.emit(vid)
        elif chosen is copy_action:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(vid)
