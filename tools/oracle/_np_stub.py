"""Minimal numpy stub for the V14 composer oracle generator.

The frozen Python composer reference imports `numpy` transitively
(`mapping.renderers` → numpy) and `mapping.edit_delta` asserts a numpy
dtype's itemsize at import time. The oracle generator never executes
numeric code — it only renders SVG strings and serialises templates — so a
non-numeric stub is sufficient to import the frozen modules on a machine
without numpy (this sandbox has no pip).

Only the two import-time numpy behaviours are modelled:
`np.dtype(...).itemsize == 128` and attribute access returning inert
objects. Anything else would be a numeric computation, which this
generator never performs.
"""

import sys
import types


class _Inert:
    """An object that tolerates any attribute access / call / iteration."""

    def __getattr__(self, name):
        return _Inert()

    def __call__(self, *args, **kwargs):
        return _Inert()

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return False

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    def __index__(self):
        return 0

    def __repr__(self):
        return "<numpy-stub>"


class _Dtype:
    """Stand-in for np.dtype with the 128-byte itemsize edit_delta asserts."""

    itemsize = 128

    def __init__(self, spec=None):
        self.spec = spec

    def __getattr__(self, name):
        return _Inert()


def _dtype(*args, **kwargs):
    return _Dtype(*args, **kwargs)


def install():
    """Install the stub as `numpy` (idempotent)."""
    if "numpy" in sys.modules:
        return
    module = types.ModuleType("numpy")
    module.dtype = _dtype
    module.ndarray = _Inert
    module.__getattr__ = lambda name: _Inert()
    sys.modules["numpy"] = module


class _InertModule(types.ModuleType):
    """A module whose every attribute access yields an inert object."""

    def __getattr__(self, name):
        return _Inert()


class _PySideFinder:
    """Import hook that materialises inert PySide6.* modules.

    The frozen composer reference imports PySide6 at module scope through
    the `paleo_workbench.mapping` package __init__ (map_render_backend),
    while the renderer/template/export code paths the oracle exercises are
    Qt-free (Qt is imported lazily inside export functions). An inert module
    therefore lets the frozen modules import without a Qt installation.
    """

    prefix = "PySide6"

    def find_module(self, fullname, path=None):
        return self if fullname == self.prefix or fullname.startswith(self.prefix + ".") else None

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.prefix and not fullname.startswith(self.prefix + "."):
            return None
        import importlib.util

        spec = importlib.util.spec_from_loader(fullname, _InertLoader())
        return spec

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        module = _InertModule(fullname)
        module.__path__ = []
        module.__loader__ = _InertLoader()
        sys.modules[fullname] = module
        return module


class _InertLoader:
    def create_module(self, spec):
        module = _InertModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module):
        return None


def install_pyside_stub():
    """Install the inert PySide6 import hook (idempotent)."""
    if any(isinstance(finder, _PySideFinder) for finder in sys.meta_path):
        return
    sys.meta_path.insert(0, _PySideFinder())
