"""Paleogeography Workbench page widgets."""

from importlib import import_module

__all__ = [
    "DataAssetTable",
    "DataDetailPanel",
    "DataPage",
    "DataToolbar",
    "DataWorkspace",
    "HomePage",
    "MappingPage",
    "PreparationPage",
    "ReviewExportPage",
    "SequenceFrameworkPage",
    "SeismicPredictionPage",
    "StratigraphyCorrelationPage",
    "VisualizationPage",
    "WellLogPredictionPage",
]

_EXPORTS = {
    "DataAssetTable": "paleo_workbench.ui.pages.data_asset_table",
    "DataDetailPanel": "paleo_workbench.ui.pages.data_detail_panel",
    "DataPage": "paleo_workbench.ui.pages.data_page",
    "DataToolbar": "paleo_workbench.ui.pages.data_toolbar",
    "DataWorkspace": "paleo_workbench.ui.pages.data_workspace",
    "HomePage": "paleo_workbench.ui.pages.home_page",
    "MappingPage": "paleo_workbench.ui.pages.mapping_page",
    "PreparationPage": "paleo_workbench.ui.pages.preparation_page",
    "ReviewExportPage": "paleo_workbench.ui.pages.review_export_page",
    "SequenceFrameworkPage": "paleo_workbench.ui.pages.sequence_framework_page",
    "SeismicPredictionPage": "paleo_workbench.ui.pages.seismic_prediction_page",
    "StratigraphyCorrelationPage": "paleo_workbench.ui.pages.stratigraphy_correlation_page",
    "VisualizationPage": "paleo_workbench.ui.pages.visualization_page",
    "WellLogPredictionPage": "paleo_workbench.ui.pages.well_log_prediction_page",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is not None:
        module = import_module(module_name)
        value = getattr(module, name)
        globals()[name] = value
        return value
    # Submodule fall-through: pytest monkeypatch.resolve / importlib walk
    # getattr(package, "submodule") before import_module. Raising here left
    # cached submodules unbound on the parent and broke dotted setattr paths
    # (CI: qgis_stack / version_workbench_dialog AttributeError cascade).
    try:
        value = import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
