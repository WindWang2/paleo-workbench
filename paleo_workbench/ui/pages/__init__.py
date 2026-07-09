"""Paleogeography Workbench page widgets."""

from importlib import import_module

__all__ = [
    "ActionPanel",
    "DataAssetTable",
    "DataCatalogPanel",
    "DataDetailPanel",
    "DataPage",
    "HomePage",
    "MappingPage",
    "PreparationPage",
    "ReviewExportPage",
    "SequenceFrameworkPage",
    "SeismicPredictionPage",
    "VisualizationPage",
    "WellLogPredictionPage",
]

_EXPORTS = {
    "ActionPanel": "paleo_workbench.ui.pages.action_panel",
    "DataAssetTable": "paleo_workbench.ui.pages.data_asset_table",
    "DataCatalogPanel": "paleo_workbench.ui.pages.data_catalog_panel",
    "DataDetailPanel": "paleo_workbench.ui.pages.data_detail_panel",
    "DataPage": "paleo_workbench.ui.pages.data_page",
    "HomePage": "paleo_workbench.ui.pages.home_page",
    "MappingPage": "paleo_workbench.ui.pages.mapping_page",
    "PreparationPage": "paleo_workbench.ui.pages.preparation_page",
    "ReviewExportPage": "paleo_workbench.ui.pages.review_export_page",
    "SequenceFrameworkPage": "paleo_workbench.ui.pages.sequence_framework_page",
    "SeismicPredictionPage": "paleo_workbench.ui.pages.seismic_prediction_page",
    "VisualizationPage": "paleo_workbench.ui.pages.visualization_page",
    "WellLogPredictionPage": "paleo_workbench.ui.pages.well_log_prediction_page",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
