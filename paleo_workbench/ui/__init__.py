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
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + __all__)
