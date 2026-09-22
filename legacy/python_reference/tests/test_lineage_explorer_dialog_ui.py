"""LineageExplorerDialog UI behavior (D8) — lazy provenance tree.

Uses the real DataCatalogService on a tmp_path project. Everything is
synchronous: the tree populates via one-hop ``get_lineage`` reads at
expansion time, so no qtbot waits are needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import paleo_workbench.ui.pages.lineage_explorer_dialog as lineage_module
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.ui.pages.data_view_models import stage_icon, stage_label
from paleo_workbench.ui.pages.lineage_explorer_dialog import LineageExplorerDialog


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


@pytest.fixture
def chain(service, tmp_path):
    """RAW a → ⚙filter → derived b → ⚙classify → derived c (+ sibling d)."""
    raw = service.import_raw(_make_source(tmp_path, "a.las", b"a-bytes"))
    mid = service.create_derived(
        _make_source(tmp_path, "b.csv", b"b-bytes"),
        parent_version_ids=[raw.id],
        operation="filter",
        parameters={"cutoff": 5, "mode": "lowpass"},
        generator="paleo-workbench 0.1.0",
    )
    out = service.create_derived(
        _make_source(tmp_path, "c.csv", b"c-bytes"),
        parent_version_ids=[mid.id],
        operation="classify",
        parameters={"threshold": 0.7},
        generator="paleo-workbench 0.1.0",
    )
    sibling = service.create_derived(
        _make_source(tmp_path, "d.csv", b"d-bytes"),
        parent_version_ids=[mid.id],
        operation="smooth",
        parameters={"window": 3},
    )
    return {"raw": raw, "mid": mid, "out": out, "sibling": sibling}


def _child_texts(item) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


def _walk_texts(item) -> list[str]:
    texts = [item.text(0)]
    for i in range(item.childCount()):
        texts.extend(_walk_texts(item.child(i)))
    return texts


def test_summary_and_run_card_show_current_node(service, chain, qtbot):
    mid = chain["mid"]
    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=mid.id)
    qtbot.addWidget(dialog)

    assert dialog.current_version_id() == mid.id
    title = dialog.summary_title_label.text()
    assert "b" in title  # asset name defaults to the source stem
    assert "v1" in title
    assert stage_label(mid.stage) in title
    meta = dialog.summary_meta_label.text()
    assert mid.sha256[:12] in meta
    assert "受管 (Managed)" in meta
    path_text = dialog.summary_path_label.text()
    assert mid.path in path_text
    assert "源文件缺失" not in path_text  # managed payload exists on disk

    assert "filter" in dialog.run_title_label.text()
    assert "生成运行" in dialog.run_title_label.text()
    assert "paleo-workbench 0.1.0" in dialog.run_meta_label.text()
    assert dialog.run_params_view.isVisibleTo(dialog)
    params = dialog.run_params_view.toPlainText()
    assert '"cutoff": 5' in params
    assert '"mode": "lowpass"' in params


def test_upstream_expands_to_raw_with_interleaved_run_nodes(service, chain, qtbot):
    out = chain["out"]
    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=out.id)
    qtbot.addWidget(dialog)

    assert dialog.up_branch is not None
    # Load pre-expands one lazy hop: out's run row + parent (mid) are visible.
    pre_texts = _walk_texts(dialog.up_branch)
    assert any("⚙ classify" in t for t in pre_texts)
    assert any("b" in t and "v1" in t for t in pre_texts)

    dialog.expand_raw_btn.click()
    texts = _walk_texts(dialog.up_branch)
    joined = "\n".join(texts)
    # RAW root reached…
    assert any(stage_label(DataStage.RAW) in t for t in texts)
    # …with both producing runs interleaved (out → ⚙classify → mid → ⚙filter → raw).
    assert "⚙ classify" in joined
    assert "⚙ filter" in joined
    assert "RAW 根" in dialog.status_label.text()


def test_upstream_version_node_holds_parents_under_its_run_row(service, chain, qtbot):
    """Interleaved idiom: out's row expands to [⚙ classify → mid], never a
    bare parent row beside the run row."""
    out = chain["out"]
    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=out.id)
    qtbot.addWidget(dialog)

    up_children = _child_texts(dialog.up_branch)
    assert len(up_children) == 1
    assert "⚙ classify" in up_children[0]
    run_item = dialog.up_branch.child(0)
    mid_texts = _child_texts(run_item)
    assert len(mid_texts) == 1
    assert "b" in mid_texts[0] and "v1" in mid_texts[0]
    assert mid_texts[0].startswith(stage_icon(DataStage.DERIVED))


def test_downstream_branch_lists_direct_children(service, chain, qtbot):
    mid = chain["mid"]
    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=mid.id)
    qtbot.addWidget(dialog)

    assert dialog.down_branch is not None
    assert dialog.down_branch.childCount() == 0  # lazy: nothing fetched yet
    dialog.down_branch.setExpanded(True)
    texts = _child_texts(dialog.down_branch)
    assert len(texts) == 2  # direct children only: c and d
    assert any("c" in t and "v1" in t for t in texts)
    assert any("d" in t and "v1" in t for t in texts)


def test_broken_parent_renders_broken_link_node(service, tmp_path, qtbot):
    raw = service.import_raw(_make_source(tmp_path, "raw_src.las", b"raw-bytes"))
    child = service.create_derived(
        _make_source(tmp_path, "orphan.csv", b"orphan-bytes"),
        parent_version_ids=[raw.id],  # no operation → 无生成运行
    )
    # Break the dependency through the service lifecycle path: trash + purge
    # removes the parent version entirely; the child keeps the dangling id.
    service.trash_version(raw.id, reason="test break")
    service.purge_trashed()

    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=child.id)
    qtbot.addWidget(dialog)

    assert dialog.up_branch is not None
    texts = _child_texts(dialog.up_branch)
    assert texts == [f"⚠ 断链: {raw.id}"]
    broken = dialog.up_branch.child(0)
    assert broken.foreground(0).color() == QColor(Qt.GlobalColor.red)
    # No run → honest 无生成运行 provenance card.
    assert dialog.run_title_label.text() == "无生成运行"
    assert not dialog.run_params_view.isVisibleTo(dialog)


def test_unknown_version_id_shows_inline_warning(service, chain, qtbot):
    mid = chain["mid"]
    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=mid.id)
    qtbot.addWidget(dialog)
    assert not dialog.locate_warning.isVisibleTo(dialog)

    dialog.version_edit.setText("ver_does_not_exist")
    dialog.locate_btn.click()
    assert dialog.locate_warning.isVisibleTo(dialog)
    assert "未找到版本" in dialog.locate_warning.text()
    assert "ver_does_not_exist" in dialog.locate_warning.text()
    assert dialog.current_version_id() == mid.id  # previous node kept, no crash

    dialog.version_edit.setText("   ")
    dialog.locate_btn.click()
    assert "请输入版本 ID" in dialog.locate_warning.text()


def test_locator_recenters_and_emits_version_activated(service, chain, qtbot):
    out = chain["out"]
    dialog = LineageExplorerDialog(
        service_provider=lambda: service, version_id=chain["raw"].id
    )
    qtbot.addWidget(dialog)

    activated: list[str] = []
    dialog.version_activated.connect(activated.append)

    dialog.version_edit.setText(out.id)
    dialog.locate_btn.click()
    assert not dialog.locate_warning.isVisibleTo(dialog)
    assert dialog.current_version_id() == out.id
    current_text = dialog.tree.topLevelItem(0).text(0)
    assert "■ 当前" in current_text
    assert "c" in current_text  # out's asset name (stem of c.csv)

    dialog.locate_in_page_btn.click()
    assert activated == [out.id]

    # Double-click path emits the same signal with the current node's id.
    dialog._on_double_clicked(dialog.tree.topLevelItem(0), 0)
    assert activated == [out.id, out.id]

    # 复制版本 ID lands on the clipboard.
    dialog.copy_id_btn.click()
    assert QApplication.clipboard().text() == out.id


def test_child_cap_renders_disabled_overflow_row(
    service, chain, tmp_path, qtbot, monkeypatch
):
    monkeypatch.setattr(lineage_module, "MAX_CHILDREN_PER_NODE", 2)
    mid = chain["mid"]
    third = service.create_derived(
        _make_source(tmp_path, "e.csv", b"e-bytes"),
        parent_version_ids=[mid.id],
        operation="resample",
    )
    assert len(service.get_lineage(mid.id)["children"]) == 3

    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=mid.id)
    qtbot.addWidget(dialog)
    dialog.down_branch.setExpanded(True)

    texts = _child_texts(dialog.down_branch)
    assert len(texts) == 3
    assert third.id not in "".join(texts)  # capped before the third child
    note = dialog.down_branch.child(2)
    assert note.text(0) == "…还有 1 个（未展开）"
    assert note.isDisabled()


def test_expand_raw_disables_past_depth_cap_with_note(service, tmp_path, qtbot):
    raw = service.import_raw(_make_source(tmp_path, "deep_raw.las", b"r"))
    version = raw
    for i in range(27):  # 27 hops → deeper than MAX_EXPAND_DEPTH (25)
        version = service.create_derived(
            _make_source(tmp_path, f"deep_{i}.csv", b"x" * (i + 1)),
            parent_version_ids=[version.id],
            operation=f"step{i}",
        )

    dialog = LineageExplorerDialog(service_provider=lambda: service, version_id=version.id)
    qtbot.addWidget(dialog)
    dialog.expand_raw_btn.click()

    texts = _walk_texts(dialog.up_branch)
    # The RAW root sits 27 hops up — past the cap the walk stops, the RAW row
    # never renders, and the control disables itself with a status note.
    assert not any("🔒" in t for t in texts)
    assert not any(stage_label(DataStage.RAW) in t for t in texts)
    assert "上限" in dialog.status_label.text()
    assert not dialog.expand_raw_btn.isEnabled()


def test_constructor_without_version_id_shows_empty_state(service, qtbot):
    dialog = LineageExplorerDialog(service_provider=lambda: service)
    qtbot.addWidget(dialog)

    assert dialog.current_version_id() is None
    assert "未选择版本" in dialog.summary_title_label.text()
    assert not dialog.expand_raw_btn.isEnabled()
    assert not dialog.locate_in_page_btn.isEnabled()
    assert dialog.tree.topLevelItemCount() == 1
    assert "未定位到版本" in dialog.tree.topLevelItem(0).text(0)
