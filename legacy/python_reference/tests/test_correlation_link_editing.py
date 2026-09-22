"""L4 — correlation link editing + method/confidence provenance.

Session ops (add/remove/edit with suppression), save-time merge (manual
edits survive regeneration), source→method mapping for new tops
(DTW_ASSISTED no longer relabels as IMPORTED), interpreter metadata
carried across save cycles, and the immutable save → reopen round trip
for manual links and suppressions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.correlation_lifecycle import (
    new_correlation_draft,
    restore_draft_from_project_ref,
    save_correlation_draft,
)
from paleo_workbench.workflow.correlation_session import (
    add_manual_link,
    adjacent_links_for_marker,
    edit_link,
    merge_session_links,
    remove_link,
    tops_from_canvas_rows,
)
from paleo_workbench.workflow.stratigraphy_models import (
    CorrelationMethod,
    DepthDomain,
    FormationTop,
)


def _make_tops() -> list[FormationTop]:
    return [
        FormationTop(well_name="W1", well_id="r1", marker="M1", depth=1000.0),
        FormationTop(well_name="W2", well_id="r2", marker="M1", depth=1010.0),
        FormationTop(well_name="W3", well_id="r3", marker="M1", depth=1025.0),
    ]


def _make_draft():
    return new_correlation_draft(
        name="t",
        well_resource_ids=["r1", "r2", "r3"],
        tops=_make_tops(),
    )


class TestLinkOps:
    def test_add_manual_link_cross_well(self):
        draft = _make_draft()
        tops = {t.well_name: t for t in draft.payload.tops}
        link = add_manual_link(draft, tops["W1"].id, tops["W3"].id, notes="跨井对比")
        assert link.adjacent_only is False
        assert link.method == CorrelationMethod.MANUAL
        assert draft.dirty and draft.generation == 1

    def test_add_rejects_duplicates_self_and_unknown(self):
        draft = _make_draft()
        tops = {t.well_name: t for t in draft.payload.tops}
        add_manual_link(draft, tops["W1"].id, tops["W3"].id)
        with pytest.raises(ValueError, match="already exists"):
            add_manual_link(draft, tops["W3"].id, tops["W1"].id)  # either order
        with pytest.raises(ValueError, match="different tops"):
            add_manual_link(draft, tops["W1"].id, tops["W1"].id)
        with pytest.raises(ValueError, match="must be tops"):
            add_manual_link(draft, tops["W1"].id, "top_missing")

    def test_remove_derived_link_records_suppression_and_merge_honours_it(self):
        draft = _make_draft()
        derived = adjacent_links_for_marker(
            draft.payload.tops, well_order=["r1", "r2", "r3"]
        )
        assert len(derived) == 2  # W1–W2, W2–W3
        draft.payload.links = derived
        target = derived[0]
        assert remove_link(draft, target.id) is True
        assert draft.payload.suppressed_link_ids, "adjacency removal suppressed"

        regenerated = adjacent_links_for_marker(
            draft.payload.tops, well_order=["r1", "r2", "r3"]
        )
        merged = merge_session_links(
            regenerated, draft.payload.links, draft.payload.suppressed_link_ids
        )
        assert len(merged) == 1
        assert merged[0].id == derived[1].id  # the un-removed pair survives

    def test_removed_manual_link_not_suppressed(self):
        draft = _make_draft()
        tops = {t.well_name: t for t in draft.payload.tops}
        link = add_manual_link(draft, tops["W1"].id, tops["W3"].id)
        remove_link(draft, link.id)
        assert draft.payload.suppressed_link_ids == []

    def test_readding_suppressed_pair_resurrects_it(self):
        draft = _make_draft()
        derived = adjacent_links_for_marker(
            draft.payload.tops, well_order=["r1", "r2", "r3"]
        )
        draft.payload.links = list(derived)
        remove_link(draft, derived[0].id)
        assert draft.payload.suppressed_link_ids
        add_manual_link(draft, derived[0].top_a_id, derived[0].top_b_id)
        assert draft.payload.suppressed_link_ids == []

    def test_edit_link_changes_method_and_notes(self):
        draft = _make_draft()
        tops = {t.well_name: t for t in draft.payload.tops}
        link = add_manual_link(draft, tops["W1"].id, tops["W3"].id)
        assert edit_link(
            draft, link.id, method=CorrelationMethod.CURVE_SHAPE_ASSISTED, notes="n"
        )
        edited = next(ln for ln in draft.payload.links if ln.id == link.id)
        assert edited.method == CorrelationMethod.CURVE_SHAPE_ASSISTED
        assert edited.notes == "n"
        before = draft.generation
        assert edit_link(draft, link.id, method=CorrelationMethod.CURVE_SHAPE_ASSISTED) is False
        assert draft.generation == before  # no-op edit does not bump

    def test_merge_keeps_manual_edits_on_derived_pairs(self):
        draft = _make_draft()
        derived = adjacent_links_for_marker(
            draft.payload.tops, well_order=["r1", "r2", "r3"]
        )
        # User edited the first derived link's method:
        edited = derived[0].model_copy(
            update={"method": CorrelationMethod.DTW_ASSISTED}
        )
        merged = merge_session_links(derived, [edited])
        by_id = {ln.id: ln for ln in merged}
        assert by_id[derived[0].id].method == CorrelationMethod.DTW_ASSISTED


class TestTopProvenance:
    def test_new_tops_map_canvas_source_to_method(self):
        class _Row:
            def __init__(self, well, marker, depth, source):
                self.well_name = well
                self.formation_name = marker
                self.depth_m = depth
                self.source = source

        tops = tops_from_canvas_rows(
            [
                _Row("W1", "M1", 1000.0, "dtw"),
                _Row("W2", "M1", 1010.0, "manual"),
                _Row("W3", "M1", 1025.0, ""),
            ]
        )
        assert tops[0].method == CorrelationMethod.DTW_ASSISTED
        assert tops[1].method == CorrelationMethod.MANUAL
        assert tops[2].method == CorrelationMethod.IMPORTED  # default

    def test_prev_metadata_survives_resave(self):
        class _Row:
            def __init__(self, well, marker, depth):
                self.well_name = well
                self.formation_name = marker
                self.depth_m = depth

        prev = [
            FormationTop(
                well_name="W1",
                marker="M1",
                depth=1000.0,
                method=CorrelationMethod.DTW_ASSISTED,
                confidence="高",
                status="tentative",
                notes="复查",
            )
        ]
        tops = tops_from_canvas_rows([_Row("W1", "M1", 1002.0)], previous_tops=prev)
        assert tops[0].method == CorrelationMethod.DTW_ASSISTED
        assert tops[0].confidence == "高"
        assert tops[0].status == "tentative"
        assert tops[0].notes == "复查"


class TestSaveReopenRoundTrip:
    def test_manual_links_and_suppressions_survive_save_reopen(self, tmp_path):
        project_file = tmp_path / "demo.paleo.json"
        project = ProjectDocument.new("L4")
        project.meta.project_root = str(tmp_path)
        draft = _make_draft()
        draft.payload.links = adjacent_links_for_marker(
            draft.payload.tops, well_order=["r1", "r2", "r3"]
        )
        tops = {t.well_name: t for t in draft.payload.tops}
        add_manual_link(draft, tops["W1"].id, tops["W3"].id, notes="跨井")
        # Interpreter removed one derived adjacency: "NOT correlated".
        removed = draft.payload.links[0]
        remove_link(draft, removed.id)

        ref, msg = save_correlation_draft(draft, project, project_file)
        assert ref is not None, msg

        reopened = restore_draft_from_project_ref(project, project_file)
        assert reopened is not None
        link_ids = {ln.id for ln in reopened.payload.links}
        manual = next(
            ln for ln in reopened.payload.links if ln.notes == "跨井"
        )
        assert manual.adjacent_only is False
        assert removed.id not in link_ids
        assert removed.id in reopened.payload.suppressed_link_ids

        # The suppression is scientific content: it changes the fingerprint.
        payload = reopened.payload
        assert removed.id in payload.scientific_dict()["suppressed_link_ids"]

    def test_editor_dialog_lists_and_edits(self, qtbot):
        from paleo_workbench.ui.pages.correlation_link_editor import (
            CorrelationLinkEditor,
        )

        draft = _make_draft()
        draft.payload.links = adjacent_links_for_marker(
            draft.payload.tops, well_order=["r1", "r2", "r3"]
        )
        editor = CorrelationLinkEditor(draft)
        qtbot.addWidget(editor)
        assert editor.link_table.rowCount() == 2
        assert editor.top_table.rowCount() == 3

        remove_link(draft, draft.payload.links[0].id)
        editor._rebuild_tables()
        assert editor.link_table.rowCount() == 1
        assert draft.payload.suppressed_link_ids
