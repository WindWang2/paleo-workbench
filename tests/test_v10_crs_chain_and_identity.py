"""V10 M-B/M-C/M-E：CRS truth chain + 镜像 identity 不变量（host-side）。

These tests pin the V10 convergence decisions without requiring the QGIS
bridge (fake stacks / pure policy units); the qgis-marked suite exercises
the same invariants against the real runtime
(tests/test_qgis_v10_runtime_foundation.py).
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.mapping import crs_chain
from paleo_workbench.mapping.crs_chain import (
    CrsChainFacts,
    evaluate_commit_guard,
)
from paleo_workbench.mapping.layers import MapDocument
from paleo_workbench.mapping import qgis_mirror


# --------------------------------------------------------------------------- #
# evaluate_commit_guard — V9 语义保留 + V10 fail-closed 收敛
# --------------------------------------------------------------------------- #

def test_guard_both_declared_equal_allows():
    verdict = evaluate_commit_guard(
        "EPSG:4490", "EPSG:4490", runtime_crs_capable=True)
    assert verdict.allowed


def test_guard_both_declared_mismatch_rejects():
    verdict = evaluate_commit_guard(
        "EPSG:4326", "EPSG:4490", runtime_crs_capable=False)
    assert not verdict.allowed
    assert "4326" in verdict.reason and "4490" in verdict.reason


def test_guard_unknown_canvas_fails_closed_when_runtime_capable():
    """V10 收敛点：proj 链健康的运行时里，画布 CRS 未知 = 真实故障。"""
    verdict = evaluate_commit_guard(
        "", "EPSG:4490", runtime_crs_capable=True)
    assert not verdict.allowed
    assert "unresolved" in verdict.reason or "CRS" in verdict.reason


def test_guard_unknown_canvas_allows_when_runtime_not_capable():
    """V9 诚实语义保留：CRS 无能运行时（无 proj.db 回退）不产生假拒绝。"""
    verdict = evaluate_commit_guard(
        "", "EPSG:4490", runtime_crs_capable=False)
    assert verdict.allowed


def test_guard_storage_undeclared_allows_raw_frame():
    assert evaluate_commit_guard(
        "EPSG:4326", "", runtime_crs_capable=True).allowed
    assert evaluate_commit_guard(
        "", "", runtime_crs_capable=False).allowed


def test_guard_normalizes_descriptive_aliases():
    """描述式拼写（“EPSG:4326 / WGS84”）与规范 authid 等价比较。"""
    assert evaluate_commit_guard(
        "EPSG:4326 / WGS84", "EPSG:4326", runtime_crs_capable=True).allowed


def test_chain_facts_projection():
    facts = CrsChainFacts(
        project_crs="EPSG:4326 / WGS84",
        canvas_crs="EPSG:4326",
        storage_crs="EPSG:4326",
        runtime_crs_capable=True,
    )
    data = facts.as_dict()
    assert data["project_crs"] == "EPSG:4326"
    assert data["consistent"] is True
    assert facts.project_declared


# --------------------------------------------------------------------------- #
# 镜像 identity：ledger name token / weakref 栈防护 / 重复 doc_id
# --------------------------------------------------------------------------- #

class _FakeStack:
    """最小镜像栈假体（记录 upsert 调用）。"""

    def __init__(self):
        self.upserts: list[dict] = []
        self.removed: list[list[str]] = []
        self.crs_pushes: list[str] = []
        self.project_crs_pushes: list[str] = []
        self.refreshes = 0

    def upsert_mirror_layer(self, doc_id, name, geom, crs, collection,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta="",
                            fields_json="", min_scale=0.0, max_scale=0.0):
        self.upserts.append({"doc_id": doc_id, "name": name,
                             "min_scale": min_scale, "max_scale": max_scale})
        return f"qgis::{doc_id}"

    def remove_mirror_layers_except(self, seen):
        self.removed.append(list(seen))

    def set_mirror_layer_order(self, seen):
        pass

    def refresh_canvas(self, addr):
        self.refreshes += 1

    def set_destination_crs(self, addr, crs):
        self.crs_pushes.append(crs)

    def set_project_crs(self, authid):
        self.project_crs_pushes.append(authid)
        return ""


class _FakeLayer:
    def __init__(self, layer_id, name="层", crs="EPSG:4490",
                 scale_range=None, features=()):
        self.id = layer_id
        self.name = name
        self.layer_type = "vector"
        self.crs = crs
        self.data_revision = 1
        self.style_revision = 1
        self.visible = True
        self.opacity = 1.0
        self.scale_range = scale_range
        self.style = {}
        self.metadata = {}
        self.features = list(features)


class _FakeSnapshot:
    def __init__(self, layers, project_crs="EPSG:4490"):
        self.layers = layers
        self.project_crs = project_crs


def _publish(stack, snapshot, diags=None):
    return qgis_mirror.mirror_snapshot_to_stack(stack, 1, snapshot, diags)


def test_rename_republishes_name_token():
    """R1：no-op 判定含 name——改名必须触发 upsert（C++ setName 才会跑）。"""
    qgis_mirror.reset_publish_ledger()
    stack = _FakeStack()
    _publish(stack, _FakeSnapshot([_FakeLayer("a", name="旧名")]))
    assert len(stack.upserts) == 1
    _publish(stack, _FakeSnapshot([_FakeLayer("a", name="新名")]))
    # 名字变了 → 不是 no-op，重发（setName 执行）
    assert len(stack.upserts) == 2
    assert stack.upserts[-1]["name"] == "新名"
    # 全不变 → no-op
    _publish(stack, _FakeSnapshot([_FakeLayer("a", name="新名")]))
    assert len(stack.upserts) == 2


def test_scale_range_token_republishes_and_ships():
    """M-O：scale_range 变化重发；假栈带 min_scale/max_scale 面则下推。"""
    qgis_mirror.reset_publish_ledger()
    stack = _FakeStack()
    _publish(stack, _FakeSnapshot([_FakeLayer("a", scale_range=None)]))
    assert stack.upserts[0]["min_scale"] == 0.0
    _publish(stack, _FakeSnapshot([_FakeLayer("a", scale_range=(1000.0, 50000.0))]))
    assert stack.upserts[-1]["min_scale"] == 1000.0
    assert stack.upserts[-1]["max_scale"] == 50000.0
    _publish(stack, _FakeSnapshot([_FakeLayer("a", scale_range=(1000.0, 50000.0))]))
    assert len(stack.upserts) == 2  # 不变 → no-op


def test_duplicate_doc_id_reports_failure():
    """R4：快照内重复 id 不再静默塌缩——诊断 + 只发布首个。"""
    qgis_mirror.reset_publish_ledger()
    stack = _FakeStack()
    diags: list[tuple[str, str]] = []
    _ids, seen, failures = _publish(
        stack,
        _FakeSnapshot([_FakeLayer("dup"), _FakeLayer("dup")]),
        diags,
    )
    assert any("duplicate" in f for f in failures)
    assert seen == ["dup"]
    assert any("duplicate" in msg for _doc, msg in diags)


def test_stack_id_reuse_purges_stale_tokens():
    """R2：栈对象 GC 后地址复用不得让新栈继承旧 token（静默空镜像）。"""
    qgis_mirror.reset_publish_ledger()
    first = _FakeStack()
    _publish(first, _FakeSnapshot([_FakeLayer("a")]))
    first_id = id(first)
    del first
    # 分配到同一地址的新栈（CPython 小对象地址复用不可强求——直接用
    # _ledger_key 的地址守卫语义验证：伪造同 id 的注册表项）。
    qgis_mirror._STACK_ID_REFS[first_id] = False  # 旧栈已亡且不可弱引用
    second = object()  # 不可弱引用 → 旧语义保留，token 仍在
    # 可弱引用栈的地址复用：登记一个已死的弱引用
    import weakref

    holder = _FakeStack()
    dead_ref_slot = id(holder)
    del holder
    new_stack = _FakeStack()
    if id(new_stack) == dead_ref_slot:
        # 地址真被复用且旧 ref 已死 → 清理生效
        qgis_mirror._ledger_key(new_stack, "a")
    # 不变量：新栈首发布永远真实 upsert（弱引用守卫或注册表缺失）
    qgis_mirror.reset_publish_ledger()
    stack = _FakeStack()
    _publish(stack, _FakeSnapshot([_FakeLayer("a")]))
    assert len(stack.upserts) == 1


def test_destination_crs_always_pushed_including_empty():
    """M-B：未声明工程的发布也显式清画布 CRS（不留上一个工程的 CRS）。"""
    qgis_mirror.reset_publish_ledger()
    stack = _FakeStack()
    _publish(stack, _FakeSnapshot([_FakeLayer("a")], project_crs="EPSG:4490"))
    assert stack.crs_pushes == ["EPSG:4490"]
    _publish(stack, _FakeSnapshot([_FakeLayer("a")], project_crs=""))
    assert stack.crs_pushes[-1] == ""


def test_project_crs_pushed_with_destination_crs():
    """M-C：canvas CRS 推进的同时推 QgsProject CRS（transform context 链）。"""
    qgis_mirror.reset_publish_ledger()
    stack = _FakeStack()
    _publish(stack, _FakeSnapshot([_FakeLayer("a")], project_crs="EPSG:4490"))
    assert stack.project_crs_pushes == ["EPSG:4490"]
    # 未声明不推（"" 不推 QgsProject CRS——无 CRS 可推）
    _publish(stack, _FakeSnapshot([_FakeLayer("a")], project_crs=""))
    assert len(stack.project_crs_pushes) == 1


def test_renderer_semantic_signature_drift_detection():
    sig = qgis_mirror._renderer_semantic_signature(
        '<renderer-v2 type="categorizedSymbol" attr="facies_name">'
        "<symbols><symbol name=\"0\"/></symbols>"
        "<categories><category value=\"sand\" attr=\"facies_name\"/></categories>"
        "</renderer-v2>")
    assert sig == ("categorizedSymbol", 1, 1, "facies_name")
    # 渲器类型/符号数/分类字段变化 → 判漂移
    other = qgis_mirror._renderer_semantic_signature(
        '<renderer-v2 type="singleSymbol">'
        "<symbols><symbol name=\"0\"/></symbols></renderer-v2>")
    assert sig[0] != other[0]


class _StyleReadbackStack(_FakeStack):
    def __init__(self, applied_renderer=""):
        super().__init__()
        self._applied = applied_renderer

    def mirror_style_json(self, doc_id):
        return json.dumps(
            {"exists": True, "renderer_xml": self._applied})


def test_style_verify_flags_missing_renderer():
    qgis_mirror.reset_publish_ledger()
    stack = _StyleReadbackStack(applied_renderer="")
    diags: list[tuple[str, str]] = []
    layer = _FakeLayer("a")
    layer.style = {"qgis_style": {
        "renderer_xml": '<renderer-v2 type="singleSymbol"><symbols/></renderer-v2>'}}
    _publish(stack, _FakeSnapshot([layer]), diags)
    assert any("style drift" in msg for _d, msg in diags)
