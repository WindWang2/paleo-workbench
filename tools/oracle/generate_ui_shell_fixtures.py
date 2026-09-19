#!/usr/bin/env python3
"""Oracle fixture generator for the C++ ui_shell cores (UI-01).

Imports the REAL Python implementations — paleo_workbench/ui/dock_framework,
navigation, command_registry, dock_manager, layout_presets, operations,
deferred_page_bindings — and freezes their observable outputs to JSON so the
C++ port in libs/ui_shell can be verified symbol-for-symbol.

The host environment has no PySide6. Qt-touching modules (command_registry's
QSettings, operations' QObject/Signal) get a minimal in-memory stub injected
as ``PySide6.QtCore`` — the stub Signal RECORDS emissions, so the frozen
fixtures capture the exact signal emission sequences too.

Seam note: command_registry._stage_reason lazily imports
paleo_workbench.mapping.tool_availability.stage_whitelist_reason. That
reason vocabulary is already C++-ported and oracle-frozen under
libs/tool_policy; here the import is intercepted with a sentinel that echoes
the stage tuple — the fixture verifies the C++ calls the reason function
with the right stage whitelist (the text itself is tool_policy's contract).

Regenerate with:

    python3 tools/oracle/generate_ui_shell_fixtures.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

FIXTURES_PATH = (
    REPO_ROOT / "libs" / "ui_shell" / "ui_shell_tests" / "fixtures"
    / "ui_shell_oracle.json"
)


# ---------------------------------------------------------------------------
# PySide6.QtCore stub (QObject / Signal / QSettings)
# ---------------------------------------------------------------------------

EMITTED: list[tuple[str, object]] = []


class _BoundSignal:
    def __init__(self, name: str) -> None:
        self._name = name
        self._subs: list = []

    def connect(self, fn) -> None:
        self._subs.append(fn)

    def disconnect(self, fn) -> None:
        if fn in self._subs:
            self._subs.remove(fn)

    def emit(self, *args) -> None:
        EMITTED.append((self._name, args[0] if len(args) == 1 else args))
        for fn in list(self._subs):
            fn(*args)


class _SignalDescriptor:
    def __init__(self, *args, **kwargs) -> None:
        self._name = ""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        bound = obj.__dict__.get(self._name)
        if bound is None:
            bound = _BoundSignal(self._name)
            obj.__dict__[self._name] = bound
        return bound


def _Signal(*args, **kwargs):
    return _SignalDescriptor(*args, **kwargs)


class _QObject:
    def __init__(self, parent=None, *args, **kwargs) -> None:
        self._parent = parent


class _QSettings:
    """Dict-backed QSettings stub honoring org/app identity + groups."""

    _stores: dict = {}

    def __init__(self, org=None, app=None, *args, **kwargs) -> None:
        self._store = self._stores.setdefault((org, app), {})
        self._group: list[str] = []

    def _key(self, key: str) -> str:
        return "/".join([*self._group, key]) if self._group else key

    def value(self, key, default=None, type=None):
        return self._store.get(self._key(key), default)

    def setValue(self, key, value) -> None:
        # Real QSettings serializes: snapshot container values so later
        # caller-side mutations do not leak into the store.
        if isinstance(value, (list, tuple)):
            value = list(value)
        elif isinstance(value, dict):
            value = dict(value)
        self._store[self._key(key)] = value

    def beginGroup(self, group) -> None:
        self._group.append(group)

    def endGroup(self) -> None:
        if self._group:
            self._group.pop()

    def allKeys(self):
        prefix = "/".join(self._group) + "/" if self._group else ""
        return [k[len(prefix):] for k in self._store if k.startswith(prefix)]

    def remove(self, key) -> None:
        target = self._key(key)
        for k in [k for k in self._store if k == target
                  or k.startswith(target + "/")]:
            del self._store[k]

    def sync(self) -> None:
        pass


def _install_pyside_stub() -> None:
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtcore.QObject = _QObject
    qtcore.Signal = _Signal
    qtcore.QSettings = _QSettings
    pyside.QtCore = qtcore
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore


def _install_tool_availability_sentinel() -> None:
    """Intercept the lazy tool_availability import inside command_registry
    with a sentinel echoing the stage whitelist (see module docstring)."""
    mapping = types.ModuleType("paleo_workbench.mapping")
    mapping.__path__ = [str(REPO_ROOT / "paleo_workbench" / "mapping")]
    sys.modules["paleo_workbench.mapping"] = mapping
    mod = types.ModuleType("paleo_workbench.mapping.tool_availability")

    def stage_whitelist_reason(stages):
        return "STAGE_SENTINEL[" + ",".join(stages) + "]"

    mod.stage_whitelist_reason = stage_whitelist_reason
    sys.modules["paleo_workbench.mapping.tool_availability"] = mod
    mapping.tool_availability = mod


_install_pyside_stub()
_install_tool_availability_sentinel()

from paleo_workbench.ui import (  # noqa: E402
    command_registry as cr,
    deferred_page_bindings as dpb,
    dock_framework as df,
    dock_manager as dm,
    layout_presets as lp,
    navigation as nav,
    operations as ops,
)


class Ctx:
    """Duck-typed UIContextSnapshot stand-in for evaluate()/find()."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _descriptor_dict(d: df.DockDescriptor) -> dict:
    return {
        "dock_id": d.dock_id,
        "title": d.title,
        "preferred_area": d.preferred_area,
        "importance": d.importance.value,
        "default_visible": d.default_visible,
        "can_float": d.can_float,
        "can_tabify": d.can_tabify,
        "min_floating_size": list(d.min_floating_size),
        "preferred_size": list(d.preferred_size) if d.preferred_size else None,
        "preferred_height": d.preferred_height,
        "workflow_tags": list(d.workflow_tags),
        "context_tags": list(d.context_tags),
        "object_name": d.object_name,
        "remark": d.remark,
    }


def build_dock_framework() -> dict:
    reg = df.workstation_dock_registry
    tags = sorted({t for d in reg.descriptors() for t in d.workflow_tags})
    return {
        "descriptors": [_descriptor_dict(d) for d in reg.descriptors()],
        "ids": list(reg.ids()),
        "by_tag": {t: [d.dock_id for d in reg.by_tag(t)] for t in tags},
        "require_missing_error": str(
            _capture(lambda: reg.require("nonexistent"))),
        "classify_viewport": [
            {"in": w, "out": df.classify_viewport(w).value}
            for w in (-1, 0, 1099, 1100, 1599, 1600, 2199, 2200, 5000)
        ],
    }


def build_navigation() -> dict:
    hubs = range(-1, 6)
    return {
        "hub_names": list(nav.HUB_NAMES),
        "submodules": {
            str(h): [{"key": k, "title": t} for k, t in nav.SUBMODULES.get(h, [])]
            for h in hubs
        },
        "submodule_keys": {str(h): nav.submodule_keys(h) for h in hubs},
        "submodule_title": {
            f"{h}:{k}": nav.submodule_title(h, k)
            for h, k in ((0, "overview"), (0, "missing"), (4, "viz"), (-1, "x"))
        },
        "default_submodule": {str(h): nav.DEFAULT_SUBMODULE.get(h) for h in hubs},
        "legacy_page_to_hub": {
            str(i): list(nav.LEGACY_PAGE_TO_HUB[i])
            if i in nav.LEGACY_PAGE_TO_HUB else None
            for i in range(-1, 12)
        },
    }


def build_command_registry() -> dict:
    score_cases = [
        ("abc", "aXbXc"), ("xyz", "abc"), ("a b", "ab"), ("", "abc"),
        ("k", "keyword"), ("abc", "acb"), ("zz", "zaz"), ("ab", "a"),
        ("open", "打开工程"), ("map", "make a project"),
    ]
    scores = [
        {"needle": n, "haystack": h, "score": cr._subsequence_score(n, h)}
        for n, h in score_cases
    ]

    def spec(**kw) -> cr.CommandSpec:
        return cr.CommandSpec(**kw)

    specs = [
        spec(id="core:open", label="打开工程", group="core",
             keywords="open project dakai", shortcut_hint="Ctrl+O"),
        spec(id="view:zoom", label="缩放画布", group="view",
             keywords="zoom canvas", hint="adjust zoom"),
        spec(id="edit:digitize", label="数字化", group="edit",
             stages=("pick", "digitize"), requires_write=True,
             keywords="digitize shuzihua"),
        spec(id="edit:lock", label="锁定图层", group="edit",
             hidden_when_unavailable=True,
             applicability=lambda ctx: "评审锁定"),
        spec(id="agent:run", label="运行 Agent", group="agent",
             requires_write=True, keywords="agent run"),
        spec(id="view:theme", label="切换主题", group="view",
             context_tags=("theme", "dark"), keywords="theme zhuti"),
    ]

    eval_cases = []
    contexts = {
        "none": None,
        "ro_user": Ctx(write_granted=False, mapping_stage="digitize"),
        "rw_user": Ctx(write_granted=True, mapping_stage="digitize"),
        "unknown_stage": Ctx(write_granted=True, mapping_stage=None),
        "wrong_stage": Ctx(write_granted=True, mapping_stage="interpret"),
    }
    for spec_obj in specs:
        for ctx_name, ctx in contexts.items():
            reg = cr.CommandRegistry()
            for s in specs:
                reg.register(s)
            avail = reg.evaluate(spec_obj.id, ctx)
            eval_cases.append({
                "id": spec_obj.id,
                "ctx": ctx_name,
                "enabled": avail.enabled,
                "reason": avail.reason,
            })
    reg = cr.CommandRegistry()
    eval_cases.append({
        "id": "missing",
        "ctx": "none",
        "enabled": reg.evaluate("missing", None).enabled,
        "reason": reg.evaluate("missing", None).reason,
    })

    find_cases = []
    for query, ctx_name, limit in (
        ("", "none", 50), ("zoom", "none", 50), ("数", "none", 50),
        ("open", "ro_user", 50), ("theme", "none", 2),
        ("dakai", "none", 50), ("edit", "ro_user", 50),
        ("agent", "rw_user", 50), ("zzzzz", "none", 50),
    ):
        reg = cr.CommandRegistry()
        for s in specs:
            reg.register(s)
        ctx = contexts[ctx_name]
        found = reg.find(query, limit=limit, context=ctx)
        find_cases.append({
            "query": query,
            "ctx": ctx_name,
            "limit": limit,
            "ids": [s.id for s in found],
        })

    # Recents: record order, cap at 8, unregistered ids ignored, unregister
    # prunes, load round-trips through the stub QSettings.
    reg = cr.CommandRegistry()
    for s in specs:
        reg.register(s)
    emitted_before = len(EMITTED)
    for cid in ["core:open", "view:zoom", "core:open", "unregistered",
                "edit:digitize"]:
        reg.record_recent(cid)
    reg.unregister("view:zoom")
    recents_after_ops = [s.id for s in reg.recent_specs()]
    reg2 = cr.CommandRegistry()
    for s in specs:
        reg2.register(s)
    reg2.load_recent()
    recents_reloaded = [s.id for s in reg2.recent_specs()]

    # clear(keep_core): only core: survives.
    reg.clear(keep_core=True)
    cleared_ids = [s.id for s in reg.specs()]

    return {
        "subsequence_score": scores,
        "evaluate": eval_cases,
        "find": find_cases,
        "recents": {
            "after_ops": recents_after_ops,
            "reloaded": recents_reloaded,
            "emitted_during": len(EMITTED) - emitted_before,
        },
        "clear_keep_core": cleared_ids,
    }


def _dock_config_dict(c) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "visible": c.visible,
        "floating": c.floating,
        "area": c.area,
    }


def build_dock_manager() -> dict:
    manager = dm.DockManager()
    layouts = {
        preset.value: {
            "name": layout.name,
            "docks": [_dock_config_dict(c) for c in layout.docks],
        }
        for preset in dm.WorkspacePreset
        for layout in [manager.get_layout(preset)]
        if layout is not None
    }

    # Panel registry semantics: exact hit, ':' suffix fallback, miss;
    # register_panel retitle propagates into the preset layout row.
    title_cases = [
        manager.panel_title("layer_tree"),
        manager.panel_title("mapping:layer_tree"),
        manager.panel_title("nonexistent"),
        manager.panel_title("workstation:explorer"),
    ]
    manager.register_panel("layer_tree", "图层管理树·改")
    retitle_layout_title = next(
        c.title
        for c in manager.get_layout(dm.WorkspacePreset.MAP_AUTHORING).docks
        if c.id == "layer_tree"
    )
    new_panel = manager.register_panel(
        "custom:panel", "自定义面板", area="bottom", visible=False)
    return {
        "layouts": layouts,
        "active_default": manager.active_layout.preset.value,
        "after_set_active_existing": (
            manager.set_active_preset(dm.WorkspacePreset.WELL_LOG_INTERPRETATION),
            manager.active_layout.preset.value)[1],
        "panel_title_cases": title_cases,
        "retitle_propagates_to_layout": retitle_layout_title,
        "new_panel": _dock_config_dict(new_panel),
        "has_panel": [manager.has_panel("layer_tree"),
                      manager.has_panel("zzz")],
        "panel_ids_first8": manager.panel_ids()[:8],
        "panel_count_after_custom": len(manager.panel_ids()),
        "seeded_vocabulary": {
            pid: manager.panel_title(pid)
            for pid in ("workstation:logs", "workstation:hub",
                        "workstation:well", "workstation:seismic")
        },
    }


def build_layout_presets() -> dict:
    presets = [
        {
            "id": p.id,
            "label": p.label,
            "description": p.description,
            "visibility": lp.visibility_dict(p.visibility),
        }
        for p in lp.list_presets()
    ]
    manager = dm.DockManager()
    lp.register_with_dock_manager(manager)
    return {
        "presets": presets,
        "labels": [list(pair) for pair in lp.preset_labels()],
        "get_preset_hit": lp.get_preset("composite_default").id,
        "get_preset_miss": lp.get_preset("nonexistent") is None,
        "reset_preset_id": lp.RESET_LAYOUT_PRESET_ID,
        "seeded_panel_titles": {
            pid: manager.panel_title(pid)
            for pid in ("workstation:explorer", "workstation:inspector",
                        "workstation:agent", "workstation:console",
                        "workstation:hub")
        },
    }


def _record_state(r) -> dict | None:
    if r is None:
        return None
    return {
        "op_id": r.op_id,
        "title": r.title,
        "state": r.state.value,
        "object_label": r.object_label,
        "done": r.done,
        "total": r.total,
        "stage": r.stage,
        "error": r.error,
        "cancellable": r.cancellable,
        "result_label": r.result_label,
        "progress_fraction": r.progress_fraction,
    }


def build_operations() -> dict:
    scenarios = []

    def run(name, fn):
        global EMITTED
        EMITTED = []
        reg = ops.OperationRegistry()
        fn(reg)
        scenarios.append({
            "name": name,
            "emitted": [e[1] for e in EMITTED],
        })

    def basic(reg: ops.OperationRegistry):
        reg.begin("op1", "校验", object_label="well-1.las",
                  cancellable=True, total=10)
        reg.update("op1", done=3, stage="SHA-256")
        snap["basic_mid"] = _record_state(reg.record("op1"))
        reg.finish("op1", ops.OperationState.COMPLETED,
                   result_label="通过")
        snap["basic_final"] = _record_state(reg.record("op1"))
        snap["basic_active_label"] = reg.active_label()

    snap: dict = {}
    run("basic", basic)

    def queued(reg: ops.OperationRegistry):
        reg.begin("q1", "排队任务", queued=True)
        snap["queued_initial"] = _record_state(reg.record("q1"))
        reg.update("q1", done=1)
        snap["queued_promoted"] = _record_state(reg.record("q1"))

    run("queued_promotion", queued)

    def live_finish(reg: ops.OperationRegistry):
        reg.begin("f1", "任务")
        reg.finish("f1", ops.OperationState.RUNNING)  # honest degrade
        snap["live_finish"] = _record_state(reg.record("f1"))

    run("finish_live_state", live_finish)

    def late_finish(reg: ops.OperationRegistry):
        reg.begin("t1", "任务")
        reg.finish("t1", ops.OperationState.COMPLETED)
        reg.finish("t1", ops.OperationState.FAILED, error="late")
        snap["late_finish"] = _record_state(reg.record("t1"))
        reg.update("t1", done=9)
        snap["terminal_update_inert"] = _record_state(reg.record("t1"))

    run("late_finish_no_regress", late_finish)

    def cancel_flow(reg: ops.OperationRegistry):
        reg.begin("c1", "可取消", cancellable=True)
        reg.set_cancel("c1", lambda: None)
        snap["cancel_request"] = reg.request_cancel("c1")
        snap["cancel_state"] = _record_state(reg.record("c1"))
        reg.begin("c2", "同步终结", cancellable=True)

        def sync_finish():
            reg.finish("c2", ops.OperationState.CANCELLED)

        reg.set_cancel("c2", sync_finish)
        snap["cancel_sync_terminal"] = reg.request_cancel("c2")
        snap["cancel_sync_state"] = _record_state(reg.record("c2"))
        reg.begin("c3", "取消失败", cancellable=True)

        def boom():
            raise RuntimeError("cancel boom")

        reg.set_cancel("c3", boom)
        snap["cancel_hook_raise"] = reg.request_cancel("c3")
        snap["cancel_raise_state"] = _record_state(reg.record("c3"))
        snap["cancel_missing"] = reg.request_cancel("zzz")
        snap["cancel_terminal"] = reg.request_cancel("c2")
        snap["cancel_again"] = reg.request_cancel("c1")

    run("cancel_flows", cancel_flow)

    def eviction(reg: ops.OperationRegistry):
        for i in range(45):
            op_id = f"e{i:02d}"
            reg.begin(op_id, f"任务{i}")
            reg.finish(op_id, ops.OperationState.COMPLETED)
        snap["evict_remaining_ids"] = sorted(reg._ops.keys())
        snap["evict_terminal_queue"] = list(reg._terminal_order)
        # Reused op_id guard: begin reuses a queued terminal key's id.
        reg.begin("e00", "复活")
        snap["evict_revived"] = _record_state(reg.record("e00"))

    run("terminal_eviction", eviction)

    def ordering(reg: ops.OperationRegistry):
        for i in range(3):
            reg.begin(f"o{i}", f"任务{i}")
        snap["records_order"] = [r.op_id for r in reg.records()]
        snap["active_order"] = [r.op_id for r in reg.active_records()]
        snap["active_label_multi"] = reg.active_label()
        reg.clear()
        snap["after_clear"] = [r.op_id for r in reg.records()]

    run("ordering_and_clear", ordering)

    return {"scenarios": scenarios, "snapshots": snap}


def build_deferred_bindings() -> dict:
    scenarios = []

    def run(name, setup):
        calls: list[str] = []
        bindings = dpb.DeferredPageBindings()
        setup(bindings, calls)
        scenarios.append({"name": name, "calls": calls})

    def order(b: dpb.DeferredPageBindings, calls: list):
        for name in ("a", "b", "c"):
            b.schedule(0, name, lambda n=name: calls.append(n))
        b.flush(0)

    run("schedule_order", order)

    def project_first(b: dpb.DeferredPageBindings, calls: list):
        b.schedule(0, "state", lambda: calls.append("state"))
        b.schedule(0, "project", lambda: calls.append("project"))
        b.schedule(0, "extra", lambda: calls.append("extra"))
        b.flush(0)

    run("project_first", project_first)

    def replace(b: dpb.DeferredPageBindings, calls: list):
        b.schedule(0, "a", lambda: calls.append("a1"))
        b.schedule(0, "b", lambda: calls.append("b"))
        b.schedule(0, "a", lambda: calls.append("a2"))
        b.flush(0)

    run("replace_keeps_position", replace)

    def reentrant(b: dpb.DeferredPageBindings, calls: list):
        def first():
            calls.append("first")
            b.schedule(0, "second", lambda: calls.append("second"))

        b.schedule(0, "first", first)
        b.flush(0)
        calls.append("has_pending=" + str(b.has_pending(0)))

    run("reentrant_drain", reentrant)

    def cross_index(b: dpb.DeferredPageBindings, calls: list):
        b.schedule(0, "zero", lambda: calls.append("zero"))
        b.schedule(1, "one", lambda: calls.append("one"))
        b.flush(0)
        calls.append("pending1=" + str(b.has_pending(1)))
        b.flush(1)

    run("cross_index_isolation", cross_index)

    return {"scenarios": scenarios}


def _capture(fn):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — freeze the error text
        return exc
    return None


def main() -> None:
    fixtures = {
        "meta": {
            "generator": "tools/oracle/generate_ui_shell_fixtures.py",
            "python": sys.version.split()[0],
            "note": ("PySide6 stubbed (QObject/Signal/QSettings in-memory); "
                     "tool_availability.stage_whitelist_reason is a sentinel — "
                     "the real reason text is libs/tool_policy's contract."),
        },
        "dock_framework": build_dock_framework(),
        "navigation": build_navigation(),
        "command_registry": build_command_registry(),
        "dock_manager": build_dock_manager(),
        "layout_presets": build_layout_presets(),
        "operations": build_operations(),
        "deferred_bindings": build_deferred_bindings(),
    }
    FIXTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURES_PATH.write_text(
        json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {FIXTURES_PATH}")


if __name__ == "__main__":
    main()
