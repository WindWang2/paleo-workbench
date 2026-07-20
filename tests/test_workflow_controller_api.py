"""WorkflowController public API surface (P1 refactor)."""


def test_workflow_controller_exposes_public_wiring_methods():
    from paleo_workbench.ui.workflow_controller import WorkflowController

    for name in (
        "wire_home_page",
        "wire_data_visualization_jump",
        "wire_mapping_page",
        "wire_preparation_page",
        "wire_sequence_page",
        "wire_seismic_page",
        "wire_well_log_page",
        "wire_review_page",
        "show_preview_settings",
        "apply_preview_settings",
    ):
        assert callable(getattr(WorkflowController, name, None)), name


def test_window_delegates_preview_settings_dialog_to_controller(qtbot):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window._preview_settings_dialog is None
    window.workflow_controller.preview_settings_dialog = object()
    assert window._preview_settings_dialog is window.workflow_controller.preview_settings_dialog
