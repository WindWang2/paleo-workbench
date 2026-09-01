"""Regression tests for issue #374: phantom project paths.

The correlation page used to fabricate ``project.paleo.json`` (artifacts
leaked into a phantom ``project.artifacts/`` tree in CWD) and four pages
fabricated ``x.paleo.json`` (opening an export dialog created an ``x.
artifacts/`` tree that Save As never migrated).  The real project file path
is now routed to every page via ``set_project_path``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.project.paths import artifact_dir_for, stage_artifact_relocation
from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui.app_shell import AppShell
from paleo_workbench.ui.pages.stratigraphy_correlation_page import (
    StratigraphyCorrelationPage,
)
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.workflow.correlation_lifecycle import (
    new_correlation_draft,
    restore_draft_from_project_ref,
    save_correlation_draft,
)
from paleo_workbench.workflow.stratigraphy_models import FormationTop


def _project(tmp_path: Path, name: str = "tarim") -> ProjectDocument:
    project = ProjectDocument.new(name)
    project.resources.append(
        ResourceItem(name="A1.las", path="/a1.las", type="well_log", format="las")
    )
    return project


def test_set_data_project_path_routes_to_all_pages(qtbot):
    """AppShell must propagate the real path to every page with a hook."""
    shell = AppShell(project=ProjectDocument.new("T"))
    qtbot.addWidget(shell)
    proj_path = Path("/tmp/real/tarim.paleo.json")
    shell.set_data_project_path(proj_path)

    from paleo_workbench.ui.pages.data_page import DataPage

    expected = {
        DataPage: "project_path",
        StratigraphyCorrelationPage: "_project_path",
        VisualizationPage: "_project_path",
        WellLogPredictionPage: "_project_path",
        ReviewExportPage: "_project_path",
    }
    for page_cls, attr in expected.items():
        pages = [p for p in shell._all_pages if isinstance(p, page_cls)]
        assert pages, f"page {page_cls.__name__} not in shell"
        routed = [getattr(p, attr, None) for p in pages]
        assert all(p is not None for p in routed), f"{page_cls.__name__} not routed"
        assert all(Path(p) == proj_path for p in routed), f"{page_cls.__name__} wrong path"


def test_default_export_dir_derived_from_real_project_file(tmp_path: Path):
    """Export dialog dirs must come from the real <name>.paleo.json, never x.paleo.json."""
    proj_path = tmp_path / "tarim.paleo.json"
    proj_path.write_text("{}", encoding="utf-8")
    exports = default_export_dir(proj_path)
    assert exports == tmp_path / "tarim.artifacts" / "exports"
    assert exports.is_dir()
    # No phantom x.artifacts tree.
    assert not (tmp_path / "x.artifacts").exists()
    assert not (tmp_path / "project.artifacts").exists()


def test_pages_export_dir_uses_routed_path(qtbot, tmp_path: Path):
    proj_path = tmp_path / "tarim.paleo.json"
    proj_path.write_text("{}", encoding="utf-8")

    pages = [
        StratigraphyCorrelationPage(),
        VisualizationPage(),
        WellLogPredictionPage(),
        ReviewExportPage(),
    ]
    for page in pages:
        qtbot.addWidget(page)
        if hasattr(page, "set_project"):
            page.set_project(_project(tmp_path))
        page.set_project_path(proj_path)
        assert Path(page._project_path) == proj_path  # noqa: SLF001
    # Opening an export dialog start dir must land in the real tree.
    assert default_export_dir(pages[0]._project_file_path()) == tmp_path / "tarim.artifacts" / "exports"
    assert not (tmp_path / "x.artifacts").exists()


def test_save_as_relocation_then_restore_succeeds(tmp_path: Path):
    """Save interpretation into the real tree, save-as, reopen: no FileNotFoundError."""
    old = tmp_path / "old" / "tarim.paleo.json"
    old.parent.mkdir()
    old.write_text("{}", encoding="utf-8")
    project = _project(tmp_path, name="tarim")
    draft = new_correlation_draft(
        name="连井对比",
        well_resource_ids=["r1"],
        tops=[FormationTop(well_id="r1", well_name="A1", marker="TopA", depth=12.5)],
    )
    ref, msg = save_correlation_draft(draft, project, old)
    assert msg == "ok"
    assert (tmp_path / "old" / "tarim.artifacts" / "correlations").is_dir()
    # Ghost tree must not exist anywhere.
    assert not (tmp_path / "project.artifacts").exists()

    new = tmp_path / "new" / "renamed.paleo.json"
    new.parent.mkdir()
    staged = stage_artifact_relocation(old, new)
    staged.commit()

    # Reopen at the new location: the ref path rebases and restore succeeds.
    reloaded = ProjectDocument.new("tarim")
    reloaded.correlation_interpretations = list(project.correlation_interpretations)
    old_root = artifact_dir_for(old).resolve()
    new_root = artifact_dir_for(new).resolve()
    from paleo_workbench.project.paths import rebase_owned_artifact_path

    for interp in reloaded.correlation_interpretations:
        rebased = rebase_owned_artifact_path(
            interp.artifact_path,
            old_root=old_root,
            new_root=new_root,
            project_dir=old.parent,
        )
        if rebased is not None:
            interp.artifact_path = rebased

    restored = restore_draft_from_project_ref(reloaded, new)
    assert restored is not None
    assert restored.payload.tops[0].marker == "TopA"


def test_open_saved_interpretation_missing_artifact_shows_dialog(qtbot, tmp_path: Path, monkeypatch):
    """Missing interpretation payload must warn, never raise in the Qt slot."""
    proj_path = tmp_path / "tarim.paleo.json"
    proj_path.write_text("{}", encoding="utf-8")
    project = _project(tmp_path)
    # A ref pointing at a payload that does not exist on disk.
    from paleo_workbench.project.models import CorrelationInterpretationRef

    project.correlation_interpretations = [
        CorrelationInterpretationRef(
            id="corr_x",
            name="连井对比",
            current_version_id="ver_gone",
            artifact_path="tarim.artifacts/correlations/corr_x_ver_gone.correlation.json",
        )
    ]
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.set_project_path(proj_path)

    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warnings.append(args[2] if len(args) > 2 else "")),
    )
    # Must not raise.
    page.open_saved_interpretation()
    assert warnings, "expected a warning dialog for the missing artifact"


def test_open_saved_interpretation_canvas_apply_failure_is_visible(
    qtbot, tmp_path: Path, monkeypatch
):
    """#660: canvas apply errors must not still claim the draft is open."""
    from types import SimpleNamespace

    proj_path = tmp_path / "tarim.paleo.json"
    proj_path.write_text("{}", encoding="utf-8")
    project = _project(tmp_path)
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.set_project_path(proj_path)
    draft = SimpleNamespace(
        payload=SimpleNamespace(parent_version_id="ver_1", tops=[]),
        dirty=False,
    )
    monkeypatch.setattr(
        "paleo_workbench.workflow.correlation_lifecycle.restore_draft_from_project_ref",
        lambda *_a, **_k: draft,
    )
    monkeypatch.setattr(page, "_apply_draft_tops_to_canvas", lambda _draft: False)
    page.open_saved_interpretation()
    assert "已打开工作副本" not in page.interp_status.text()
    assert "打开失败" in page.interp_status.text()


def test_unsaved_project_save_interpretation_requires_project_file(qtbot, monkeypatch):
    """Saving an interpretation without a project file must ask to save first."""
    project = _project(Path("/tmp/unsaved"))
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    assert page._project_file_path() is None

    warns: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warns.append(args[2] if len(args) > 2 else "")),
    )
    page.save_interpretation_version()
    assert warns, "expected a '请先保存工程' prompt"
    assert "先保存工程" in warns[0]
