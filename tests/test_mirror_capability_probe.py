"""桥能力探测：真桥（pybind11 builtin，无 inspect 签名）上 fields_json/delta 也能上桥。

根因：`_stack_supports_delta` / `_stack_supports_fields_json` 只认
``inspect.signature``；pybind11 builtin 方法抛 ValueError → except 吞掉恒 False，
fields_json 永不上桥（Task 6 打通的 schema 链被拦），delta 通道也从未启用。
修复：signature 优先，ValueError/TypeError 时回退读 ``__doc__``（pybind11 的
docstring 首行即绑定声明），按「参数名+冒号」词边界匹配；无信号仍 False。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.qgis_mirror import (
    _stack_supports_delta,
    _stack_supports_fields_json,
)

_REAL_DECLARATION = (
    "upsert_mirror_layer(self: qgis_render_bridge.mapstack.QgisMapStack, "
    "doc_id: str, name: str, geometry_type: str, crs_auth_id: str, "
    "geojson: str, renderer_xml: str = '', labeling_xml: str = '', "
    "legacy_style: object = None, visible: bool = True, "
    "opacity: typing.SupportsFloat | typing.SupportsIndex = 1.0, "
    "is_reference: bool = False, is_editable: bool = False, "
    "reference_snap: bool = False, "
    "data_revision: typing.SupportsInt | typing.SupportsIndex = 0, "
    "delta: str = '', fields_json: str = '') -> str\n"
)


class _OldBridge:
    """纯 Python 旧桥：无 delta/fields_json kwargs。"""

    def upsert_mirror_layer(self, doc_id, name, geojson):
        raise AssertionError("probe must not call the bridge method")


class _NewBridge:
    """纯 Python 新桥：带全 kwargs。"""

    def upsert_mirror_layer(
        self, doc_id, name, geojson, data_revision=0, delta="",
        fields_json="",
    ):
        raise AssertionError("probe must not call the bridge method")


class _PybindLikeMethod:
    """模拟 pybind11 builtin：无 inspect 签名，声明只在 __doc__。"""

    def __init__(self, doc):
        self.__doc__ = doc

    @property
    def __signature__(self):
        raise ValueError("no signature found for builtin")

    def __call__(self, *args, **kwargs):
        raise AssertionError("probe must not call the bridge method")


class _PybindLikeStack:
    def __init__(self, doc):
        self.upsert_mirror_layer = _PybindLikeMethod(doc)


def test_python_old_bridge_probes_false():
    stack = _OldBridge()
    assert _stack_supports_delta(stack) is False
    assert _stack_supports_fields_json(stack) is False


def test_python_new_bridge_probes_true():
    stack = _NewBridge()
    assert _stack_supports_delta(stack) is True
    assert _stack_supports_fields_json(stack) is True


def test_pybind_like_real_declaration_probes_true():
    stack = _PybindLikeStack(_REAL_DECLARATION)
    assert _stack_supports_delta(stack) is True
    assert _stack_supports_fields_json(stack) is True


def test_pybind_like_doc_without_fields_json():
    doc = (
        "upsert_mirror_layer(self, doc_id: str, geojson: str, "
        "data_revision: int = 0, delta: str = '') -> str"
    )
    stack = _PybindLikeStack(doc)
    assert _stack_supports_delta(stack) is True
    assert _stack_supports_fields_json(stack) is False


def test_pybind_like_doc_without_delta():
    doc = (
        "upsert_mirror_layer(self, doc_id: str, geojson: str, "
        "fields_json: str = '') -> str"
    )
    stack = _PybindLikeStack(doc)
    assert _stack_supports_delta(stack) is False
    assert _stack_supports_fields_json(stack) is True


def test_no_signature_no_docstring_is_honest_false():
    stack = _PybindLikeStack(None)
    assert _stack_supports_delta(stack) is False
    assert _stack_supports_fields_json(stack) is False


@pytest.mark.qgis
def test_real_bridge_probes_true(qapp):
    from tests.qgis_support import require_mapstack

    mapstack = require_mapstack()
    stack = mapstack.QgisMapStack()
    assert _stack_supports_delta(stack) is True
    assert _stack_supports_fields_json(stack) is True
