#!/usr/bin/env python3
"""Oracle fixture generator for the C++ ui_map cores (UI-05).

Freezes observable behaviour of the REAL Python implementations behind
``libs/ui_map`` into ``ui_map_tests/fixtures/ui_map_oracle.json`` so the C++
port can be verified symbol-for-symbol.

Two extraction styles:

* **Qt-free imports** — ``viz/mapping_helpers``, ``viz/prediction_helpers``,
  ``mapping/workarea_map_snapshot`` and ``project/domain`` import cleanly
  without PySide6 and are called directly.

* **AST extraction** — the page/panel/widget modules import PySide6 at
  module load, but the *functions under test are pure* (they only touch
  attributes on ``self``). We parse the real source, compile just the
  named function/method, and call it unbound against a fake ``self`` —
  the executed code is the verbatim Python implementation, not a
  transcription. The same trick covers the inline ``__init__`` strip-group
  block (assignments replayed in order) and the work-area widget's click
  handler (fake canvas provides the projection).

Regenerate with:

    python3 tools/oracle/generate_ui_map_fixtures.py
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Import stubs: the oracle host has no PySide6/numpy and the package
# __init__ chains pull the whole app (geoviz -> PySide6). Package stubs with
# __path__ -> the real directory load the REAL module files while skipping
# heavy __init__ side effects; absent third-party deps are generic modules
# whose attributes satisfy import-time references only (never executed in
# the frozen code paths — a path that needed real numpy would fail loudly,
# which is the honest outcome).
# ---------------------------------------------------------------------------


class _AnyClass:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __call__(self, *args, **kwargs):
        return _AnyClass()

    def __getattr__(self, name):
        return _AnyClass(name)


class _AnyModule(types.ModuleType):
    def __getattr__(self, name):
        value = _AnyClass(name)
        setattr(self, name, value)
        return value


def _install_stubs() -> None:
    for name, rel in (
        ("paleo_workbench", "paleo_workbench"),
        ("paleo_workbench.mapping", "paleo_workbench/mapping"),
        ("paleo_workbench.mapping_workspace",
         "paleo_workbench/mapping_workspace"),
        ("paleo_workbench.project", "paleo_workbench/project"),
        ("paleo_workbench.viz", "paleo_workbench/viz"),
    ):
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(REPO_ROOT / rel)]
        pkg.__package__ = name
        sys.modules[name] = pkg
    for name in (
        "numpy",
        "geoviz",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ):
        sys.modules[name] = _AnyModule(name)
    # map_render_backend's internal render helpers pull further Qt chains;
    # only its snapshot dataclasses are consumed, so those modules never
    # need a real body.
    for name in (
        "paleo_workbench.mapping.facies_brush_cache",
        "paleo_workbench.mapping.vector_lod",
        "paleo_workbench.mapping.revision_cache",
    ):
        sys.modules[name] = _AnyModule(name)


def _import_module(name: str, path: Path):
    """Import the REAL module file at ``path`` under stubs."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()

FIXTURES_PATH = (
    REPO_ROOT / "libs" / "ui_map" / "ui_map_tests" / "fixtures"
    / "ui_map_oracle.json"
)

PAGES = REPO_ROOT / "paleo_workbench" / "ui" / "pages"
DISPLAY_CANVAS = (
    REPO_ROOT / "paleo_workbench" / "ui" / "qgis_stack" / "display_canvas.py"
)


# ---------------------------------------------------------------------------
# AST extraction: real function source, no module import
# ---------------------------------------------------------------------------

_TREES: dict[Path, ast.Module] = {}


def _tree(path: Path) -> ast.Module:
    if path not in _TREES:
        _TREES[path] = ast.parse(path.read_text(encoding="utf-8"))
    return _TREES[path]


def _function_node(tree: ast.Module, qualname: str) -> ast.FunctionDef:
    """Find ``qualname`` ("name" or "Class.name") in the module AST."""
    parts = qualname.split(".")
    body: list[ast.stmt] = tree.body
    node: ast.stmt | None = None
    for part in parts:
        node = next(
            (
                stmt
                for stmt in body
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef))
                and stmt.name == part
            ),
            None,
        )
        if node is None:
            raise KeyError(f"{qualname} not found")
        body = getattr(node, "body", [])
    if not isinstance(node, ast.FunctionDef):
        raise KeyError(f"{qualname} is not a function")
    return node


def load_function(path: Path, qualname: str, **namespace) -> object:
    """Compile one real function definition from ``path`` and return it.

    Extra ``namespace`` entries become the function's globals (module
    constants, helper names) — the function body itself is verbatim.
    """
    node = _function_node(_tree(path), qualname)
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    ns: dict = {"__builtins__": __builtins__}
    ns.update(namespace)
    exec(compile(module, str(path), "exec"), ns)
    value = ns[qualname.split(".")[-1]]
    if isinstance(value, property):
        return value.fget
    if isinstance(value, (staticmethod, classmethod)):
        return value.__func__
    return value


def load_init_assigns(path: Path, class_name: str,
                      targets: tuple[str, ...]) -> object:
    """Return a function replaying the named ``__init__`` assignments.

    Used for inline blocks (e.g. the toolbar strip group derivation) that
    have no callable seam of their own: the assignment statements are
    replayed verbatim, in order, against a fake ``self``.
    """
    tree = _tree(path)
    init = _function_node(tree, f"{class_name}.__init__")
    picked = [
        stmt
        for stmt in init.body
        if isinstance(stmt, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id in targets for t in stmt.targets
        )
    ]
    missing = set(targets) - {
        t.id for stmt in picked for t in stmt.targets if isinstance(t, ast.Name)
    }
    if missing:
        raise KeyError(f"{class_name}.__init__ assigns missing: {missing}")

    def replay(self):
        ns = {"self": self, "__builtins__": __builtins__}
        for stmt in picked:
            module = ast.Module(body=[stmt], type_ignores=[])
            ast.fix_missing_locations(module)
            exec(compile(module, str(path), "exec"), ns)
        return {t: ns[t] for t in targets}

    return replay


# ---------------------------------------------------------------------------
# Fake Qt widgets (attribute-level, no PySide6)
# ---------------------------------------------------------------------------


class FakeSignal:
    """Record emissions like the ui_shell stub Signal."""

    def __init__(self) -> None:
        self.emissions: list = []

    def emit(self, *args) -> None:
        self.emissions.append(args[0] if len(args) == 1 else args)

    def connect(self, _fn) -> None:  # pragma: no cover - unused in fakes
        pass


class FakeWidget:
    """Minimal widget stand-in: visibility + width/height + update."""

    def __init__(self, *, width: int = 100, height: int = 100) -> None:
        self.visible = True
        self._w = width
        self._h = height
        self.updates = 0
        self.extents: list = []

    def setVisible(self, value) -> None:
        self.visible = bool(value)

    def isHidden(self) -> bool:
        return not self.visible

    def width(self) -> int:
        return self._w

    def height(self) -> int:
        return self._h

    def update(self) -> None:
        self.updates += 1

    def set_extent(self, extent) -> None:
        self.extents.append(tuple(extent))


class FakeCanvas(FakeWidget):
    """Display-canvas stand-in with a linear map→screen projection.

    ``transform`` is ((sx, ox), (sy, oy)): screen = map * s + o — the same
    transform the replay applies in C++.
    """

    def __init__(self, transform=((1.0, 0.0), (1.0, 0.0)),
                 *, width: int = 100, height: int = 100,
                 extent=(0.0, 0.0, 10.0, 10.0)) -> None:
        super().__init__(width=width, height=height)
        (self._sx, self._ox), (self._sy, self._oy) = transform
        self._extent = tuple(extent)

    def map_to_screen(self, point):
        x = float(point[0]) * self._sx + self._ox
        y = float(point[1]) * self._sy + self._oy
        return types.SimpleNamespace(x=lambda: x, y=lambda: y)

    @property
    def view_extent(self):
        return self._extent


class FakeButton:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked
        self.blocked = False

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value) -> None:
        self._checked = bool(value)

    def blockSignals(self, value) -> None:
        self.blocked = bool(value)


class FakeLayout:
    """QBoxLayout stand-in recording items (sync_area_visibility)."""

    def __init__(self, widgets=()) -> None:
        self.widgets = list(widgets)

    def count(self) -> int:
        return len(self.widgets)

    def itemAt(self, index):
        widget = self.widgets[index]
        return types.SimpleNamespace(widget=lambda: widget)


class FakeStack(FakeWidget):
    """QStackedWidget stand-in recording current index/widget."""

    def __init__(self) -> None:
        super().__init__()
        self.current = None

    def setCurrentIndex(self, index) -> None:
        self.current = index

    def setCurrentWidget(self, widget) -> None:
        self.current = widget


# ---------------------------------------------------------------------------
# Fixture cases
# ---------------------------------------------------------------------------


def _jsonable(value):
    """Tuples -> lists recursively; SimpleNamespace/objects -> repr-safe."""
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _ns_to_dict(value):
    """SimpleNamespace tree -> plain dict tree (JSON-serializable input)."""
    if isinstance(value, types.SimpleNamespace):
        return {k: _ns_to_dict(v) for k, v in vars(value).items()}
    if isinstance(value, (list, tuple)):
        return [_ns_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _ns_to_dict(v) for k, v in value.items()}
    return value


def gen_field_value() -> list:
    from paleo_workbench.viz.prediction_helpers import field_value

    cases = [
        {"source": {"a": 1, "b": None}, "name": "a", "default": 9},
        {"source": {"a": 1, "b": None}, "name": "b", "default": 9},
        {"source": {"a": 1}, "name": "missing", "default": 9},
        {"source": [1, 2], "name": "a", "default": "d"},
        {"source": None, "name": "a", "default": "d"},
        {"source": "text", "name": "a", "default": 0},
        {"source": {"nested": {"x": [1]}}, "name": "nested", "default": {}},
    ]
    return [
        {**case, "expected": _jsonable(
            field_value(case["source"], case["name"], case["default"]))}
        for case in cases
    ]


def gen_active_map_document() -> list:
    from paleo_workbench.viz.mapping_helpers import active_map_document

    docs = [{"id": "m1", "name": "一"}, {"id": "m2"}, {"name": "无id"}]
    cases = [
        {"documents": docs, "prefer_id": "m1"},
        {"documents": docs, "prefer_id": "m2"},
        {"documents": docs, "prefer_id": "missing"},
        {"documents": docs, "prefer_id": None},
        {"documents": [], "prefer_id": "m1"},
        {"documents": None, "prefer_id": None},
        {"documents": [{"name": "x"}], "prefer_id": "z"},
    ]
    out = []
    for case in cases:
        result = active_map_document(case["documents"],
                                     prefer_id=case["prefer_id"])
        out.append({
            **case,
            "expected": _jsonable(result),
            "expected_is_last": (
                result is not None and case["documents"] is not None
                and result is list(case["documents"])[-1]
            ),
        })
    return out


def gen_tree_keys() -> dict:
    from paleo_workbench.viz.prediction_helpers import field_value

    document_key = load_function(
        PAGES / "map_layer_tree.py", "_document_key",
        field_value=field_value)
    reference_layer_key = load_function(
        PAGES / "map_layer_tree.py", "_reference_layer_key",
        field_value=field_value)
    panel_key = load_function(
        PAGES / "map_document_panel.py", "MapDocumentPanel._document_key",
        field_value=field_value)

    docs = [
        {"id": "m1", "name": "甲"},
        {"name": "无id"},
        {"id": ""},
        {"id": "m-中文"},
    ]
    layers = [
        {"id": "ref1"},
        {"name": "无id参考"},
        {"id": ""},
    ]
    return {
        "document_key": [
            {"doc": d, "expected": document_key(d),
             "expected_stable": document_key(d).startswith("doc:")}
            for d in docs
        ],
        "reference_layer_key": [
            {"layer": l, "expected": reference_layer_key(l)}
            for l in layers
        ],
        "document_list_key": [
            {"doc": d, "expected": panel_key(d)}
            for d in docs
        ],
    }


def gen_panel_title() -> list:
    panel_title = load_function(
        PAGES / "map_dock_manager.py", "MapDockManager.panel_title")
    panels = {
        "layers": {"title": "图层面板", "float_key": "mapping:layers"},
        "bottom": {"title": "底部工作区", "float_key": "mapping:bottom"},
    }
    fake = types.SimpleNamespace(_panels=panels)
    cases = ["layers", "mapping:layers", "mapping:bottom", "missing:key",
             "no_colon", "a:b:c", ""]
    return [
        {"key": key, "expected": panel_title(fake, key)} for key in cases
    ]


def gen_chrome() -> dict:
    tree = _tree(PAGES / "map_chrome_panel.py")
    # Module constant (list literal assigned at top level).
    elements = None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id in (
                        "_CHROME_ELEMENTS", "CHROME_ELEMENTS",
                        "DEFAULT_CHROME_ELEMENTS"):
                    elements = ast.literal_eval(stmt.value)
    if elements is None:
        raise KeyError("chrome element constant not found")
    return {"default_elements": list(elements)}


def gen_mode_ui() -> list:
    apply_mode_ui = load_function(
        PAGES / "mapping_page.py", "MappingPage._apply_mode_ui")

    cases = []
    for preview in (False, True):
        for unified_mode in (False, True):
            for priority in (False, True):
                for bottom_user in (False, True):
                    bottom = FakeWidget()
                    manager = types.SimpleNamespace(
                        bottom_user_visible=lambda: bottom_user,
                        is_floating=lambda _k: False,
                    )
                    center = FakeStack()
                    preview_stack = FakeStack()
                    unified_canvas = object()
                    fake = types.SimpleNamespace(
                        _preview_mode=preview,
                        _unified_authoring_mode=unified_mode,
                        _canvas_priority=priority,
                        dock_manager=manager,
                        center_stack=center,
                        preview_canvas_stack=preview_stack,
                        unified_canvas=unified_canvas,
                        bottom_workbench=bottom,
                    )
                    apply_mode_ui(fake)
                    cases.append({
                        "preview_mode": preview,
                        "unified_authoring_mode": unified_mode,
                        "canvas_priority": priority,
                        "bottom_user_visible": bottom_user,
                        "expected": {
                            "center_index": center.current,
                            "preview_is_unified": center.current == 1
                            and preview_stack.current is unified_canvas,
                            "bottom_visible": bottom.visible,
                        },
                    })
    # Floating-bottom variant: window visibility is routed through the
    # manager, not the bare widget.
    for visible_pref in (False, True):
        window_calls: list[bool] = []
        manager = types.SimpleNamespace(
            bottom_user_visible=lambda: visible_pref,
            is_floating=lambda _k: True,
            set_bottom_window_visible=lambda v: window_calls.append(bool(v)),
        )
        fake = types.SimpleNamespace(
            _preview_mode=False, _unified_authoring_mode=False,
            _canvas_priority=False, dock_manager=manager,
            center_stack=FakeStack(), preview_canvas_stack=FakeStack(),
            unified_canvas=object(), bottom_workbench=FakeWidget(),
        )
        apply_mode_ui(fake)
        cases.append({
            "preview_mode": False,
            "unified_authoring_mode": False,
            "canvas_priority": False,
            "bottom_user_visible": visible_pref,
            "bottom_floating": True,
            "expected": {
                "center_index": fake.center_stack.current,
                "window_calls": window_calls,
            },
        })
    return cases


def gen_dock_splitter() -> list:
    saved = load_function(
        PAGES / "mapping_page.py", "MappingPage._saved_dock_splitter_sizes",
        _DOCK_SPLITTER_KEY="mapping:dock_splitter")

    class FakePersistence:
        def __init__(self, records) -> None:
            self._records = records

        def load(self, key):
            return self._records.get(
                key, types.SimpleNamespace(docked_sizes=None))

    cases = [
        ({"mapping:dock_splitter": types.SimpleNamespace(
            docked_sizes=[1, 2, 3]),
          "mapping:layers": types.SimpleNamespace(docked_sizes=[4, 5, 6])},
         [7, 8, 9]),
        ({"mapping:layers": types.SimpleNamespace(docked_sizes=[4, 5, 6])},
         [7, 8, 9]),
        ({}, [7, 8, 9]),
        ({"mapping:dock_splitter": types.SimpleNamespace(docked_sizes=()),
          "mapping:layers": types.SimpleNamespace(docked_sizes=[4])},
         [7, 8, 9]),
    ]
    out = []
    for records, fallback in cases:
        fake = types.SimpleNamespace(
            _layout_persistence=FakePersistence(records),
            _last_dock_sizes=fallback)
        out.append({
            "dock_record": (records.get("mapping:dock_splitter")
                            and records["mapping:dock_splitter"].docked_sizes),
            "layers_record": (records.get("mapping:layers")
                              and records["mapping:layers"].docked_sizes),
            "fallback": fallback,
            "expected": list(saved(fake)),
        })
    return out


def gen_unified_revisions() -> list:
    revisions = load_function(
        PAGES / "mapping_page.py", "MappingPage._unified_data_revisions")

    class FakeAuthoring:
        def __init__(self, keys) -> None:
            self._keys = keys

        def data_revision_key(self, kind):
            return self._keys.get(kind)

    # Sequence: same authoring, raw keys advance -> effective ints count up;
    # a NEW authoring object forces a bump on every kind even when raw keys
    # repeat; authoring None / unified off -> None.
    authoring_a = FakeAuthoring({"facies": ("d1", 5), "well": ("d1", 2)})
    authoring_b = FakeAuthoring({"facies": ("d1", 5), "well": ("d1", 2)})

    def _step(fake):
        return revisions(fake)

    fake = types.SimpleNamespace(
        _authoring_document=authoring_a,
        _unified_authoring_mode=True,
        _unified_raw_revisions={},
        _unified_effective_revisions={},
        _unified_revisions_owner=None,
    )
    trace = []
    trace.append(_jsonable(_step(fake)))
    authoring_a._keys["facies"] = ("d2", 6)
    trace.append(_jsonable(_step(fake)))
    fake._authoring_document = authoring_b  # new object, same raw keys
    trace.append(_jsonable(_step(fake)))
    trace.append(_jsonable(_step(fake)))  # stable now
    fake._authoring_document = None
    trace.append(_jsonable(_step(fake)))
    fake._authoring_document = authoring_a
    fake._unified_authoring_mode = False
    trace.append(_jsonable(_step(fake)))
    return [{"sequence": trace}]


def gen_layer_field_names() -> list:
    field_names = load_function(
        PAGES / "mapping_page.py", "MappingPage._layer_field_names")

    def _run(features):
        scene = types.SimpleNamespace(
            vector_features=lambda _lid: features)
        fake = types.SimpleNamespace(unified_scene=scene)
        return list(field_names(fake, "any"))

    # NOTE: the fixture dump uses sort_keys=True, so the on-disk properties
    # order is alphabetical. Build every properties dict pre-sorted so the
    # frozen `expected` (real Python iteration order) matches the order the
    # C++ replay will iterate the parsed Json — otherwise insertion-order
    # parity is untestable.
    cases = [
        [{"properties": {"a": 1, "b": 2}},
         {"properties": {"__internal": 1, "b": 3, "c": 4}}],
        [{"properties": {"__x": 1, "k": 1}},
         {"properties": None},
         {"properties": {"k2": 2}}],
        [{"properties": dict(sorted(
            {f"f{i}": i for i in range(80)}.items()))}],
        [{"nope": 1}],
        [],
    ]
    return [{"features": c, "expected": _run(c)} for c in cases]


def gen_mapping_context() -> list:
    class MapEditScene:
        """isinstance target: is_dirty() checks scene type."""

        def __init__(self, dirty: bool) -> None:
            self._dirty = dirty

        def is_dirty(self) -> bool:
            return self._dirty

    context = load_function(
        PAGES / "mapping_page.py", "MappingPage.mapping_context")
    is_dirty = load_function(
        PAGES / "mapping_page.py", "MappingPage.is_dirty",
        MapEditScene=MapEditScene)

    def _doc(name=None, horizon=None):
        return types.SimpleNamespace(
            name=name, linked_target_horizon=horizon)

    cases = [
        {"doc": {"name": "图A", "linked_target_horizon": "T3"},
         "dirty_flags": (False, False, False), "preview": False},
        {"doc": {"name": "图A", "linked_target_horizon": "T3"},
         "dirty_flags": (True, False, False), "preview": True},
        {"doc": None, "dirty_flags": (False, False, False),
         "preview": False},
        {"doc": {"name": "", "linked_target_horizon": ""},
         "dirty_flags": (False, True, False), "preview": False},
        {"doc": {"name": "图B"}, "dirty_flags": (False, False, True),
         "preview": False},
    ]
    out = []
    for case in cases:
        d = case["doc"]
        doc = (_doc(d["name"], d.get("linked_target_horizon"))
               if d else None)
        pres, auth, scene = case["dirty_flags"]
        authoring = types.SimpleNamespace(is_dirty=lambda: auth) if auth \
            else None
        scene_obj = MapEditScene(scene) if scene else object()
        fake = types.SimpleNamespace(
            _active_document=doc,
            _presentation_dirty=pres,
            _authoring_document=authoring,
            _preview_mode=case["preview"],
            edit_view=types.SimpleNamespace(scene=lambda: scene_obj),
            is_dirty=lambda: is_dirty(fake),
        )
        out.append({
            "doc": d,
            "dirty_flags": list(case["dirty_flags"]),
            "preview": case["preview"],
            "expected": _jsonable(context(fake)),
        })
    return out


def gen_toolbar_groups() -> list:
    replay = load_init_assigns(
        PAGES / "mapping_page.py", "MappingPage",
        ("core_ids", "grouped", "core_set", "filtered", "listed",
         "leftovers", "strip_groups"))

    class FakeController:
        _SURFACE_ICONS = {"ribbon_ext"}

        def __init__(self, ids) -> None:
            self.actions = list(ids)

    cases = [
        ["pan", "zoom_in", "zoom_out", "full_extent", "previous_extent",
         "next_extent", "refresh", "identify", "select", "measure_distance",
         "toggle_editing", "save_edits", "undo", "redo", "delete_selected",
         "snapping", "topology", "cancel", "ribbon_ext"],
        ["pan", "zoom_in"],
        ["pan", "totally_unknown_action"],
        [],
    ]
    out = []
    for ids in cases:
        fake = types.SimpleNamespace(action_controller=FakeController(ids))
        result = replay(fake)
        out.append({
            "registered": ids,
            "expected": _jsonable(result["strip_groups"]),
        })
    return out


def gen_rebind_tool() -> list:
    rebind = load_function(
        PAGES / "mapping_page.py", "MappingPage._rebind_tool_after_layer_switch")

    tree = _tree(PAGES / "mapping_page.py")
    layer_bound = kind_bound = None
    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == "MappingPage":
            for item in stmt.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if (isinstance(target, ast.Name)
                                and target.id == "_LAYER_BOUND_TOOL_ACTIONS"):
                            layer_bound = eval(compile(ast.Expression(
                                item.value), "<ast>", "eval"))
                        elif (isinstance(target, ast.Name)
                                and target.id == "_KIND_BOUND_TOOL_ACTIONS"):
                            kind_bound = eval(compile(ast.Expression(
                                item.value), "<ast>", "eval"))
    assert layer_bound is not None and kind_bound is not None

    def _run(action, kind, has_authoring=True):
        requested: list = []
        authoring = (
            types.SimpleNamespace(active_kind=kind)
            if has_authoring else None
        )
        fake = types.SimpleNamespace(
            _active_tool_action=action,
            _LAYER_BOUND_TOOL_ACTIONS=layer_bound,
            _KIND_BOUND_TOOL_ACTIONS=kind_bound,
            _authoring_document=authoring,
            _on_action_tool_requested=lambda aid: requested.append(aid),
        )
        rebind(fake)
        return requested

    cases = [
        ("pan", "facies"), ("select", "facies"), ("identify", "facies"),
        ("select_rectangle", "well"), ("move_feature", "facies"),
        ("vertex", "well"), ("add_point", "facies"), ("add_point", "well"),
        ("add_line", "line"), ("add_line", "facies"),
        ("add_polygon", "facies"), ("add_polygon", "well"),
        ("measure_distance", "well"), (None, "facies"), ("zoom_in", "line"),
    ]
    out = [
        {"active_action": action, "kind": kind,
         "requested": _run(action, kind)}
        for action, kind in cases
    ]
    out.append({
        "active_action": "add_point", "kind": None,
        "has_authoring": False,
        "requested": _run("add_point", None, has_authoring=False),
    })
    return out


def gen_kind_visibility() -> list:
    visibility = load_function(
        PAGES / "mapping_page.py", "MappingPage._kind_visibility")

    def _fake(*, registry=None, document=None, tree_state=None):
        scene = (
            types.SimpleNamespace(registry=registry)
            if registry is not None else None
        )
        tree = types.SimpleNamespace(
            layer_is_visible=lambda kind: bool((tree_state or {}).get(
                kind, True)))
        return types.SimpleNamespace(
            _active_document=document, unified_scene=scene,
            layer_tree=tree)

    doc = types.SimpleNamespace(
        id="m1", layer_state={"composition": [
            {"id": "m1:well", "visible": False},
            {"id": "other:line", "visible": True},
        ]})
    cases = [
        # registry entry wins over everything.
        {"registry": {"m1:facies": False}, "document": "doc",
         "tree_state": {}, "kind": "facies"},
        {"registry": {"m1:well": True}, "document": "doc",
         "tree_state": {"well": False}, "kind": "well"},
        # composition entry fallback (registry present, layer absent).
        {"registry": {}, "document": "doc", "tree_state": {"well": True},
         "kind": "well"},
        {"registry": {}, "document": "doc", "tree_state": {},
         "kind": "line"},   # entry id mismatch -> tree default True
        # no registry -> legacy tree checkbox.
        {"registry": None, "document": "doc",
         "tree_state": {"facies": False}, "kind": "facies"},
        {"registry": None, "document": None, "tree_state": {}, "kind": "well"},
    ]
    out = []
    for case in cases:
        registry = (
            {k: types.SimpleNamespace(visible=v)
             for k, v in case["registry"].items()}
            if case["registry"] is not None else None)
        document = doc if case["document"] == "doc" else None
        fake = _fake(registry=registry, document=document,
                     tree_state=case["tree_state"])
        out.append({**{k: v for k, v in case.items() if k != "document"},
                    "document": case["document"],
                    "expected": bool(visibility(fake, case["kind"]))})
    return out


def gen_workarea() -> dict:
    from paleo_workbench.mapping import workarea_map_snapshot as snap
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot, MapRenderSnapshot)

    legend = [list(pair) for pair in snap.WORKAREA_LEGEND_ITEMS]

    # workarea_view_extent: populated-layer union + 15% pad + floors.
    def _layer(features, extent):
        return MapLayerSnapshot(
            id="x", name="x", layer_type="vector", extent=extent,
            crs="", data_revision=1, style_revision=1,
            features=tuple(features), style={}, metadata={})

    extent_cases = [
        [([{"geometry": {}}], (0.0, 0.0, 10.0, 10.0))],
        [([{"geometry": {}}], (5.0, 5.0, 5.0, 5.0))],
        [([{"geometry": {}}], (-2.0, -4.0, 2.0, 4.0)),
         ([{"geometry": {}}], (10.0, 20.0, 30.0, 40.0))],
        [],
        [([], (0.0, 0.0, 1.0, 1.0))],
    ]
    extents = []
    for spec in extent_cases:
        layers = [_layer(f, e) for f, e in spec]
        snapshot = MapRenderSnapshot(project_crs="", layers=tuple(layers))
        result = snap.workarea_view_extent(snapshot)
        extents.append({
            "layers": [{"features": f, "extent": list(e)} for f, e in spec],
            "expected": list(result) if result is not None else None,
        })

    return {"legend_items": legend, "view_extent": extents}


def gen_domain_signature() -> list:
    from paleo_workbench.project.domain import domain_signature

    # project.domain reads attributes — dicts duck-type via getattr in the
    # signature helper; the oracle uses attribute namespaces (real domain
    # objects on the Python side).
    def _project(**kw):
        return types.SimpleNamespace(**kw)

    projects = [
        _project(
            wells=[
                types.SimpleNamespace(
                    id="w1", name="井1", uwi="U1", aliases=["a"],
                    surface_x=1.0, surface_y=2.0, coordinate_status="ok",
                    project_x=10.0, project_y=20.0, spatial_scope="workarea"),
            ],
            seismic_surveys=[
                types.SimpleNamespace(
                    id="s1", name="测线", crs="EPSG:4326",
                    extent=[[0, 0], [1, 0], [1, 1]]),
            ],
            entity_asset_links=[{"well_id": "w1", "survey_id": "s1"}],
            geological_entities=[],
            workarea=types.SimpleNamespace(
                boundary=[[0, 0], [10, 0], [10, 10]],
                boundary_crs="EPSG:4326"),
            coordinate=types.SimpleNamespace(project_crs="EPSG:4326"),
        ),
        _project(wells=[], seismic_surveys=[], entity_asset_links=[],
                 geological_entities=[], workarea=None, coordinate=None),
    ]
    return [
        {"project_index": i, "project": _ns_to_dict(p),
         "expected": _jsonable(domain_signature(p))}
        for i, p in enumerate(projects)
    ]


def gen_workarea_widget() -> dict:
    on_map_clicked = load_function(
        PAGES / "workarea_map_widget.py", "WorkAreaMapWidget._on_map_clicked",
        _WELL_PICK_RADIUS_PX=16.0,
        WELLS_LAYER_ID="home_workarea:wells",
        WELLS_FLAGGED_LAYER_ID="home_workarea:wells_flagged")
    select_well = load_function(
        PAGES / "workarea_map_widget.py", "WorkAreaMapWidget.select_well")
    overlay_state = load_function(
        PAGES / "workarea_map_widget.py", "WorkAreaMapWidget._overlay_state",
        WORKAREA_LEGEND_ITEMS=(
            ("工区边界", "#64748b"),
            ("地震工区", "#0d9488"),
            ("井位", "#409cff"),
            ("井位（坐标待处理）", "#f59e0b"),
        ))
    current_half_span = load_function(
        PAGES / "workarea_map_widget.py",
        "WorkAreaMapWidget._current_half_span")
    well_feature = load_function(
        PAGES / "workarea_map_widget.py", "WorkAreaMapWidget._well_feature",
        WELLS_LAYER_ID="home_workarea:wells",
        WELLS_FLAGGED_LAYER_ID="home_workarea:wells_flagged")

    def _layer(layer_id, features):
        return types.SimpleNamespace(id=layer_id, features=features)

    def _point_feature(well_id, x, y):
        return {
            "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": {"well_id": well_id, "name": well_id},
        }

    snapshot = types.SimpleNamespace(layers=[
        _layer("home_workarea:boundary", [{"geometry": {}}]),
        _layer("home_workarea:wells", [
            _point_feature("w1", 10.0, 10.0),
            _point_feature("w2", 20.0, 20.0),
        ]),
        _layer("home_workarea:wells_flagged", [
            _point_feature("w3", 10.0, 40.0),
        ]),
    ])

    def _widget(transform=((1.0, 0.0), (1.0, 0.0)), *, snap=snapshot,
                extent=(0.0, 0.0, 100.0, 100.0), title="", legend=True):
        canvas = FakeCanvas(transform, extent=extent)
        w = types.SimpleNamespace(
            _snapshot=snap, _selected_well_id="", _title=title,
            _show_legend=legend, map_canvas=canvas,
            well_selected=FakeSignal(), well_activated=FakeSignal())
        w.select_well = lambda well_id, *, zoom=False, emit=False: (
            select_well(w, well_id, zoom=zoom, emit=emit))
        w._well_feature = lambda well_id: well_feature(w, well_id)
        w._current_half_span = lambda: current_half_span(w)
        return w

    # _on_map_clicked: identity transform -> map coords are screen px.
    picks = []
    for point, expected_well in [
        ((10.5, 10.5), "w1"),   # within 16px of w1
        ((19.0, 21.0), "w2"),
        ((50.0, 50.0), ""),     # nothing near
        ((10.0, 39.0), "w3"),   # flagged layer pick
        ((12.0, 12.0), "w1"),   # nearest wins (w1 at 2.8px vs w2 at 11px)
    ]:
        w = _widget()
        on_map_clicked(w, point)
        picks.append({
            "point": list(point),
            "expected_well": expected_well,
            "selected": w._selected_well_id,
            "emitted_selected": list(w.well_selected.emissions),
            "emitted_activated": list(w.well_activated.emissions),
        })
    # None snapshot -> early return, nothing emitted.
    w = _widget(snap=None)
    on_map_clicked(w, (0.0, 0.0))
    picks.append({
        "point": [0.0, 0.0], "snapshot_none": True,
        "expected_well": "", "selected": w._selected_well_id,
        "emitted_selected": [], "emitted_activated": [],
    })
    # Scaled transform (2 map units -> 1 px): wells at map (20,20)/(40,40)
    # land 10px apart on screen; the click picks the projected-nearest.
    w = _widget(transform=((0.5, 0.0), (0.5, 0.0)))
    on_map_clicked(w, (20.0, 20.0))  # click maps to screen (10,10) = w1
    picks.append({
        "point": [20.0, 20.0], "transform": [[0.5, 0.0], [0.5, 0.0]],
        "expected_well": "w1", "selected": w._selected_well_id,
        "emitted_selected": list(w.well_selected.emissions),
        "emitted_activated": list(w.well_activated.emissions),
    })

    # select_well zoom: 20% of the current half span around the well.
    zoom_cases = []
    for extent, well_id in [
        ((0.0, 0.0, 100.0, 100.0), "w1"),
        ((0.0, 0.0, 1.0, 1.0), "w2"),    # degenerate: floor half=1.0
        ((-50.0, -50.0, 50.0, 50.0), "w3"),
    ]:
        w = _widget(extent=extent)
        select_well(w, well_id, zoom=True)
        zoom_cases.append({
            "view_extent": list(extent), "well_id": well_id,
            "set_extent": list(w.map_canvas.extents[-1])
            if w.map_canvas.extents else None,
        })
    # emit=True re-emits well_selected only for a non-empty id.
    w = _widget()
    select_well(w, "w2", emit=True)
    select_well(w, "", emit=True)
    zoom_cases.append({
        "emit": True,
        "emitted_selected": list(w.well_selected.emissions),
        "emitted_activated": list(w.well_activated.emissions),
        "selected": w._selected_well_id,
    })

    # _overlay_state over title/legend/selection combinations.
    overlays = []
    for title, legend, selected in [
        ("", True, ""), ("工区图", True, "w1"), ("工区图", False, ""),
        ("", False, "w2"),
    ]:
        w = _widget(title=title, legend=legend)
        w._selected_well_id = selected
        overlays.append({
            "title": title, "show_legend": legend, "selected": selected,
            "expected": _jsonable(overlay_state(w)),
        })

    # _current_half_span + _well_feature.
    spans = [
        {"extent": (0.0, 0.0, 10.0, 4.0),
         "expected": current_half_span(_widget(extent=(0, 0, 10, 4)))},
        {"extent": (0.0, 0.0, 0.0, 0.0),
         "expected": current_half_span(_widget(extent=(0, 0, 0, 0)))},
    ]
    w = _widget()
    features = [
        {"well_id": "w2",
         "expected": _jsonable(well_feature(w, "w2"))},
        {"well_id": "nope",
         "expected": _jsonable(well_feature(w, "nope"))},
        {"well_id": "",
         "expected": _jsonable(well_feature(w, ""))},
    ]
    w_none = _widget(snap=None)
    features.append({"well_id": "w1", "snapshot_none": True,
                     "expected": _jsonable(well_feature(w_none, "w1"))})

    return {
        "picks": picks,
        "select_zoom": zoom_cases,
        "overlay_state": overlays,
        "half_span": spans,
        "well_feature": features,
    }


def gen_canvas_core() -> dict:
    record_extent = load_function(
        DISPLAY_CANVAS, "QgisDisplayCanvas._record_extent")
    previous_extent = load_function(
        DISPLAY_CANVAS, "QgisDisplayCanvas.previous_extent")
    next_extent = load_function(
        DISPLAY_CANVAS, "QgisDisplayCanvas.next_extent")
    zoom_by = load_function(
        DISPLAY_CANVAS, "QgisDisplayCanvas.zoom_by")
    mupp = load_function(
        DISPLAY_CANVAS, "QgisDisplayCanvas.map_units_per_pixel")
    source_ids = load_function(
        DISPLAY_CANVAS, "QgisDisplayCanvas.snapshot_source_version_ids")

    class FakeHost:
        """QgisDisplayCanvas stand-in for the extent-history methods."""

        def __init__(self) -> None:
            self._extent_history = [(0.0, 0.0, 1.0, 1.0)]
            self._extent_history_index = 0
            self.canvas = FakeWidget(width=200, height=100)
            self.set_calls: list = []
            self._current = self._extent_history[0]

        @property
        def view_extent(self):
            return self._current

        def set_extent(self, extent, *, record_history=True,
                       coalesce_history=False):
            self._current = tuple(extent)
            self.set_calls.append(tuple(extent))
            if record_history:
                record_extent(self, tuple(extent),
                              coalesce=coalesce_history)

        @property
        def can_previous_extent(self):
            return self._extent_history_index > 0

        @property
        def can_next_extent(self):
            return self._extent_history_index + 1 < len(self._extent_history)

    # Extent history: record/coalesce/cap + previous/next navigation.
    host = FakeHost()
    ops = [
        ("record", (1, 1, 2, 2), {}),
        ("record", (1, 1, 2, 2), {}),                # dup tail skipped
        ("record", (3, 3, 4, 4), {"coalesce_history": True}),
        ("previous", None, {}),
        ("next", None, {}),
        ("record", (9, 9, 9, 9), {}),
        ("previous", None, {}),
        ("previous", None, {}),
        ("next", None, {}),
    ]
    history_trace = []
    for op, arg, kw in ops:
        if op == "record":
            host.set_extent(arg, **kw)
        elif op == "previous":
            previous_extent(host)
        else:
            next_extent(host)
        history_trace.append({
            "op": op, "extent": list(arg) if arg else None, **kw,
            "index": host._extent_history_index,
            "history": [list(e) for e in host._extent_history],
            "can_previous": host.can_previous_extent,
            "can_next": host.can_next_extent,
        })
    # 100-cap: record 105 entries -> oldest dropped.
    host_cap = FakeHost()
    for i in range(105):
        host_cap.set_extent((float(i), 0.0, float(i) + 1, 1.0))
    cap = {
        "size": len(host_cap._extent_history),
        "first": list(host_cap._extent_history[0]),
        "last": list(host_cap._extent_history[-1]),
        "index": host_cap._extent_history_index,
    }

    # zoom_by: scale around center (midpoint default); factor<=0 raises.
    zoom_cases = []
    for extent, factor, center in [
        ((0, 0, 10, 10), 0.5, None),
        ((0, 0, 10, 10), 2.0, None),
        ((0, 0, 10, 10), 0.5, (5, 5)),
        ((-10, -10, 10, 10), 0.25, (0, 0)),
        ((0, 0, 4, 2), 1.5, (4, 2)),
    ]:
        h = FakeHost()
        h._current = tuple(extent)
        zoom_by(h, factor, center=center)
        zoom_cases.append({
            "extent": list(extent), "factor": factor,
            "center": list(center) if center else None,
            "expected": list(h.set_calls[-1]),
        })
    err = None
    try:
        zoom_by(FakeHost(), 0.0)
    except ValueError as exc:
        err = str(exc)
    zoom_cases.append({"factor": 0.0, "error": err})

    # map_units_per_pixel via fake canvas size.
    mupp_cases = []
    for extent, w, hgt in [
        ((0, 0, 10, 10), 200, 100),
        ((0, 0, 10, 20), 100, 100),
        ((5, 5, 5, 5), 100, 100),
    ]:
        h = FakeHost()
        h._current = tuple(extent)
        h.canvas = FakeWidget(width=w, height=hgt)
        mupp_cases.append({
            "extent": list(extent), "width": w, "height": hgt,
            "expected": mupp(h),
        })

    # snapshot_source_version_ids: dict.fromkeys order.
    snap_cases = []
    for layers in [
        [{"source_version_id": "a"}, {"source_version_id": "b"},
         {"source_version_id": "a"}],
        [{"source_version_id": ""}, {"source_version_id": "x"}],
        [],
    ]:
        snapshot = types.SimpleNamespace(layers=[
            types.SimpleNamespace(source_version_id=l["source_version_id"])
            for l in layers
        ])
        h = types.SimpleNamespace(_snapshot=snapshot)
        snap_cases.append({
            "layers": layers,
            "expected": list(source_ids(h)),
        })

    return {
        "history_trace": history_trace,
        "history_cap": cap,
        "zoom_by": zoom_cases,
        "map_units_per_pixel": mupp_cases,
        "source_version_ids": snap_cases,
    }


def gen_preview_payload() -> dict:
    from paleo_workbench.viz.mapping_helpers import (
        _close_ring, _normalize_geojson_geometry, facies_to_geojson,
        preview_payload_from_document, preview_payload_from_features,
        well_to_lnglat)

    rings = [
        [[0, 0], [1, 0], [1, 1]],
        [[0, 0], [1, 0], [1, 1], [0, 0]],
        [[0, 0]],
        [],
        [[0, 0], "bad", [1, 1], [0, 0]],
    ]
    close_ring = [{"ring": r, "expected": _jsonable(_close_ring(r))}
                  for r in rings]

    geometries = [
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
        {"type": "Polygon",
         "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        {"type": "MultiPolygon",
         "coordinates": [[[[0, 0], [1, 0], [1, 1]]]]},
        {"type": "Point", "coordinates": [1, 2]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0]]]},
        {"type": "Polygon"},
        {},
    ]
    normalize = [
        {"geometry": g,
         "expected": _jsonable(_normalize_geojson_geometry(g))}
        for g in geometries
    ]

    facies_cases = [
        {"geometry": {"type": "Polygon",
                      "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
         "properties": {"name": "三角洲", "facies": "河道"}},
        {"geometry": {"type": "Polygon",
                      "coordinates": [[[0, 0], [1, 0], [1, 1]]]}},
        {"geometry": {"type": "Point", "coordinates": [1, 2]}},
        {"coordinates": [[[0, 0], [1, 0], [1, 1]]], "name": "raw ring"},
        {},
        {"geometry": None},
    ]
    facies = [{"raw": c, "expected": _jsonable(facies_to_geojson(c))}
              for c in facies_cases]

    well_cases = [
        {"coordinates": [100.5, 30.25], "name": "w1"},
        {"lng": 100.5, "lat": 30.25, "name": "w2"},
        {"x": 100.5, "y": 30.25, "lon": 1, "name": "w3"},
        {"lon": 100.5, "lat": 30.25},
        {"longitude": 100.5, "latitude": 30.25},
        {"coordinates": [100.5], "name": "bad"},
        {"name": "nothing"},
    ]
    wells = [{"raw": c, "expected": _jsonable(well_to_lnglat(c))}
             for c in well_cases]

    # preview_payload_* — real functions, tuple output -> {"features","wells","period"}
    doc_cases = [
        {"facies_polygons": [
            {"geometry": {"type": "Polygon",
                          "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
             "properties": {"name": "P1"}},
            {"geometry": {"type": "Point", "coordinates": [1, 2]}},
        ],
         "well_overlays": [
            {"coordinates": [100.5, 30.25], "name": "w1"},
            {"coordinates": [9], "name": "bad"},
         ],
         "linked_target_horizon": "T3"},
        {"facies_polygons": [], "well_overlays": []},
        {},
    ]
    payloads_doc = []
    for doc in doc_cases:
        f, w, p = preview_payload_from_document(doc)
        payloads_doc.append({
            "document": doc,
            "expected": {"features": _jsonable(f), "wells": _jsonable(w),
                         "period": p},
        })
    payloads_doc.append({
        "document": None,
        "expected": {"features": [], "wells": [], "period": ""},
    })

    feature_cases = [
        [{"kind": "facies",
          "geometry": {"type": "Polygon",
                       "coordinates": [[[0, 0], [1, 0], [1, 1]]]}},
         {"kind": "well", "coordinates": [5.0, 6.0], "name": "w9"},
         {"kind": "line", "geometry": {}},
         "not-a-dict"],
        [],
    ]
    payloads_features = []
    for feats in feature_cases:
        f, w, p = preview_payload_from_features(feats, period_name="T1")
        payloads_features.append({
            "features": feats,
            "period_name": "T1",
            "expected": {"features": _jsonable(f), "wells": _jsonable(w),
                         "period": p},
        })

    return {
        "close_ring": close_ring,
        "normalize_geometry": normalize,
        "facies_to_geojson": facies,
        "well_to_lnglat": wells,
        "payload_from_document": payloads_doc,
        "payload_from_features": payloads_features,
    }


def gen_constants() -> dict:
    return {
        "layer_keys": ["facies", "well", "line", "label"],
        "layer_labels": {"facies": "相带", "well": "井",
                         "line": "线", "label": "注记"},
        "float_keys": ["mapping:layers", "mapping:reference",
                       "mapping:chrome", "mapping:composer",
                       "mapping:bottom"],
        "dock_splitter_key": "mapping:dock_splitter",
        "rail": {"width": 36, "button": 28, "icon": 18},
        "well_pick_radius_px": 16.0,
        "bottom_docked_max_height": 220,
        "widget_size_max": 16777215,
        "workarea_layer_ids": [
            "home_workarea:boundary", "home_workarea:surveys",
            "home_workarea:survey_labels", "home_workarea:wells",
            "home_workarea:wells_flagged"],
        "default_chrome_elements": ["图例", "指北针", "比例尺", "标题栏"],
    }


def main() -> int:
    fixture = {
        "meta": {
            "generator": "tools/oracle/generate_ui_map_fixtures.py",
            "slice": "UI-05 qgs-map",
        },
        "constants": gen_constants(),
        "field_value": gen_field_value(),
        "active_map_document": gen_active_map_document(),
        "tree_keys": gen_tree_keys(),
        "panel_title": gen_panel_title(),
        "chrome": gen_chrome(),
        "mode_ui": gen_mode_ui(),
        "dock_splitter": gen_dock_splitter(),
        "unified_revisions": gen_unified_revisions(),
        "layer_field_names": gen_layer_field_names(),
        "mapping_context": gen_mapping_context(),
        "toolbar_groups": gen_toolbar_groups(),
        "rebind_tool": gen_rebind_tool(),
        "kind_visibility": gen_kind_visibility(),
        "workarea": gen_workarea(),
        "domain_signature": gen_domain_signature(),
        "workarea_widget": gen_workarea_widget(),
        "canvas_core": gen_canvas_core(),
        "preview_payload": gen_preview_payload(),
    }
    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8")
    total = sum(
        len(v) for v in fixture.values() if isinstance(v, list))
    print(f"wrote {FIXTURES_PATH} ({total} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
