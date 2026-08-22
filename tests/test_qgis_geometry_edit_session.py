"""QGIS geometry operations stay subordinate to VectorEditSession transactions.

The Iron Law here: QGIS computes, Paleo records.  Merge/split through the
QGIS engine must produce normal EditCommands — undoable, auditable,
commit-bumping — and must never mutate raw input or bypass revisions.
"""

from __future__ import annotations

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

pytestmark = pytest.mark.qgis

qgis_render_bridge = pytest.importorskip("qgis_render_bridge", reason=QGIS_SKIP_REASON)

from paleo_workbench.mapping.geometry_service import (
    merge_selected_polygons,
    split_polygon_by_line,
)
from paleo_workbench.mapping.vector_layer import (
    VectorEditSession,
    VectorFeature,
    VectorLayer,
)


def _square(feature_id: str, x: float) -> VectorFeature:
    return VectorFeature(
        feature_id,
        {
            "type": "Polygon",
            "coordinates": [[[x, 0], [x + 10, 0], [x + 10, 10], [x, 10], [x, 0]]],
        },
        {"facies": "sandstone"},
    )


def _line() -> VectorFeature:
    return VectorFeature(
        "cutter",
        {"type": "LineString", "coordinates": [[5, -5], [5, 15]]},
        {},
    )


def _session(*features: VectorFeature) -> VectorEditSession:
    layer = VectorLayer(id="doc:facies", name="Facies", crs="EPSG:3857", features=features)
    return layer.start_editing()


class TestMergeThroughQgis:
    def test_merge_records_undoable_command(self) -> None:
        session = _session(_square("a", 0), _square("b", 10))
        merged_id = merge_selected_polygons(session, ["a", "b"])
        assert merged_id in {feature.feature_id for feature in session.features()}
        assert "a" not in {feature.feature_id for feature in session.features()}
        assert session.is_dirty
        assert session.undo()
        assert "a" in {feature.feature_id for feature in session.features()}
        assert merged_id not in {feature.feature_id for feature in session.features()}
        assert session.redo()

    def test_commit_bumps_data_revision_and_audits(self) -> None:
        layer = VectorLayer(id="doc:facies", name="Facies", crs="EPSG:3857")
        layer.data_revision = 4
        session = layer.start_editing()
        session.add_feature(_square("a", 0))
        session.add_feature(_square("b", 10))
        merge_selected_polygons(session, ["a", "b"])
        audit = session.audit_history()
        assert audit[-1]["command_type"] == "merge_features"
        session.commit_changes()
        assert layer.data_revision == 5
        assert layer.edit_session is None


class TestSplitThroughQgis:
    def test_split_creates_replacements_with_attributes(self) -> None:
        session = _session(_square("target", 0))
        replacements = split_polygon_by_line(session, "target", _line())
        assert len(replacements) >= 2
        ids = {feature.feature_id for feature in session.features()}
        assert "target" not in ids
        for replacement_id in replacements:
            assert replacement_id in ids
            assert session.feature(replacement_id).attributes["facies"] == "sandstone"
        # Undo restores exactly the original feature.
        session.undo()
        assert "target" in {feature.feature_id for feature in session.features()}

    def test_split_validation_errors_are_unchanged(self) -> None:
        session = _session(_square("target", 0))
        point_cutter = VectorFeature(
            "p", {"type": "Point", "coordinates": [1, 1]}, {}
        )
        with pytest.raises(ValueError, match="cutter"):
            split_polygon_by_line(session, "target", point_cutter)

    def test_rollback_discards_qgis_results_without_touching_committed_state(self) -> None:
        layer = VectorLayer(
            id="doc:facies",
            name="Facies",
            crs="EPSG:3857",
            features=(_square("committed-a", 0), _square("committed-b", 20)),
        )
        before_revision = layer.data_revision
        session = layer.start_editing()
        merged_id = merge_selected_polygons(session, ["committed-a", "committed-b"])
        assert session.is_dirty
        session.rollback_changes()
        assert layer.data_revision == before_revision
        assert sorted(feature.feature_id for feature in layer.features()) == [
            "committed-a",
            "committed-b",
        ]
        assert merged_id not in {feature.feature_id for feature in layer.features()}
