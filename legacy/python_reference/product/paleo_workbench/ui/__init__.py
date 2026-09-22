"""Paleogeography Workbench UI shell package."""

from importlib import import_module

__all__ = [
    "AppShell",
    "StatusBar",
]

_EXPORTS = {
    "AppShell": "paleo_workbench.ui.app_shell",
    "StatusBar": "paleo_workbench.ui.status_bar",
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
