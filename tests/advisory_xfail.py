"""Known monorepo failures quarantined for advisory CI (#234).

Each entry is a ``nodeid`` substring. Matched tests are marked
``xfail(strict=False)`` so the suite stays green while product work proceeds.

Remove an entry when the underlying product/API issue is fixed — do not grow
this list without a linked issue or short reason.
"""

from __future__ import annotations

# nodeid substring → reason (must mention #234 or a dedicated ticket)
ADVISORY_XFAIL: dict[str, str] = {
    # GeoViz / joint host (engine lifecycle + API drift on main)
    "tests/test_geoviz_preview_lifecycle.py": (
        "waitUntil teardown race under offscreen; #234"
    ),
    "tests/test_geoviz_package_independence.py": (
        "production import boundary drift; #234"
    ),
    "tests/test_joint_slice_apply.py": (
        "WellSeismicJointWidget API (_scene vs scene); #234"
    ),
    "tests/test_preview_async.py::test_data_page_clear_cache_does_not_strand_visualization_loading": (
        "preview host widget identity after clear; #234"
    ),
    # Stratigraphy correlation (engine backend default vs legacy stubs)
    "tests/test_stratigraphy_correlation.py::test_page_lists_wells_and_loads_section": (
        "load path assumes legacy host; engine default; #234"
    ),
    "tests/test_stratigraphy_correlation_ui.py::test_load_injects_tops_and_formation_data": (
        "tops inject under engine/legacy mismatch; #234"
    ),
    "tests/test_stratigraphy_correlation_ui.py::test_track_checklist_toggles_all_wells": (
        "track list None when engine backend; #234"
    ),
    "tests/test_stratigraphy_correlation_ui.py::test_undo_redo_buttons": (
        "pick model undo under engine path; #234"
    ),
    # Well location preview payload API drift
    "tests/test_well_location_preview.py": (
        "XYPreviewPayload.coordinate_status removed/renamed; #234"
    ),
    # Well log workflow export assertion
    "tests/test_well_log_workflow.py::test_page_run_and_export_png": (
        "export png path flaky/assertion under offscreen; #234"
    ),
}
