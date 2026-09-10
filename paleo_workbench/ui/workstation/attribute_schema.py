"""Attribute-table field descriptors — QGIS provider schema consumption (V9 W5).

综合编修属性表此前只读 Python 模板 schema（``schema_fields``），V8 M1 建
立的 provider 字段（ValueMap/Range/CheckBox/约束/别名）在 UI 无消费者。
本模块把「一层在属性表里如何呈现/编辑」收敛为单一派生：

1. **字段元数据**（:class:`AttributeFieldMeta`）——图层有角色时取
   ``GeologicalLayerSpec``（与镜像 ``fields_json`` 同一权威，无 schema
   漂移）；无角色回落模板 schema；额外属性键以 text 附加。
2. **QGIS provider parity**（:func:`qgis_schema_parity`）——发布后的
   ``mirror_layer_schema_json``（QGIS 真实 QgsFields）与派生描述比对，
   给出 ``synced``/``drift``/``unavailable`` 三态与差异明细。表格数据
   权威仍是 Python 会话；QGIS 侧事实用于呈现一致性标注，不反向写。

不做的（防第二真源）：不在这里复制 spec 字段值语义（校验在写入路径
``_write_attribute`` 经会话/schema 执行）；不发明 QGIS 之外的控件词表
（ValueMap/Range/CheckBox 与 ``qgis_layer_schema`` 推断同词）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "AttributeFieldMeta",
    "field_descriptors_for_layer",
    "qgis_schema_parity",
]


@dataclass(frozen=True, slots=True)
class AttributeFieldMeta:
    """属性表一列的呈现/编辑元数据（spec→模板→额外键 单一派生）。"""

    key: str
    label: str
    kind: str                     # text/int/real/bool/datetime
    choices: tuple[str, ...] = ()
    required: bool = False
    unique: bool = False
    expression: str = ""
    value_range: tuple[float, float] | None = None
    editor_widget: str = ""       # QGIS 控件词汇（ValueMap/Range/CheckBox…）
    #: 来源标记：spec（角色权威）/ template（模板）/ extra（要素属性键）。
    origin: str = "template"

    @property
    def numeric(self) -> bool:
        return self.kind in {"int", "real"}


def _spec_descriptors(role_value: str) -> list[AttributeFieldMeta] | None:
    """角色 spec → 描述符；无角色/未知角色返回 None（不猜）。"""
    if not role_value:
        return None
    try:
        from paleo_workbench.mapping_workspace.geological_layer_spec import (
            spec_for_role,
        )
    except Exception:
        return None
    try:
        spec = spec_for_role(role_value)
    except (KeyError, ValueError):
        return None
    descriptors: list[AttributeFieldMeta] = []
    for field in spec.fields:
        widget = str(field.editor_widget or "")
        if not widget:
            if field.choices:
                widget = "ValueMap"
            elif field.kind == "bool":
                widget = "CheckBox"
            elif field.value_range is not None:
                widget = "Range"
        descriptors.append(
            AttributeFieldMeta(
                key=field.name,
                label=field.label or field.name,
                kind=field.kind,
                choices=tuple(field.choices or ()),
                required=bool(field.required),
                unique=bool(field.unique),
                expression=str(field.expression or ""),
                value_range=tuple(field.value_range) if field.value_range else None,
                editor_widget=widget,
                origin="spec",
            )
        )
    return descriptors


def field_descriptors_for_layer(controller, layer_id: str) -> tuple[AttributeFieldMeta, ...]:
    """一层属性表的列元数据（spec 优先 → 模板 → 额外键；额外键不变 spec 序）。

    ``controller`` 是 CompositeEditController 鸭子类型（需要
    ``layer_schema``/``layer``/``role_of_layer``）——测试可注入假体。
    """
    layer_id = str(layer_id)
    descriptors: list[AttributeFieldMeta] = []
    seen: set[str] = set()
    spec_fields = _spec_descriptors(controller.role_of_layer(layer_id))
    if spec_fields is not None:
        descriptors.extend(spec_fields)
        seen.update(field.key for field in spec_fields)
    else:
        from paleo_workbench.ui.workstation.composite_editing import schema_fields

        for field in schema_fields(controller.layer_schema(layer_id)):
            descriptors.append(
                AttributeFieldMeta(
                    key=field.name,
                    label=field.label or field.name,
                    kind=field.kind,
                    choices=tuple(getattr(field, "choices", ()) or ()),
                    required=bool(getattr(field, "required", False)),
                )
            )
            seen.add(field.name)
    layer = controller.layer(layer_id)
    features: tuple[Any, ...] = ()
    if layer is not None:
        session = layer.edit_session
        features = session.features() if session is not None else layer.features()
    for feature in features:
        for key in sorted(getattr(feature, "attributes", {}) or {}):
            if key not in seen:
                descriptors.append(
                    AttributeFieldMeta(key=key, label=key, kind="text", origin="extra")
                )
                seen.add(key)
    return tuple(descriptors) or (
        AttributeFieldMeta(key="id", label="ID", kind="text", origin="extra"),
    )


def qgis_schema_parity(canvas, layer_id: str, descriptors) -> tuple[str, str]:
    """QGIS provider schema 与派生描述的比对（呈现标注用）。

    返回 ``(state, detail)``：state ∈ synced/drift/unavailable。数据权威
    仍是 Python 会话——drift 只呈现（字段级差异进 detail），不阻塞编辑。
    """
    stack = getattr(canvas, "stack", None)
    probe = getattr(stack, "mirror_layer_schema_json", None)
    if stack is None or not callable(probe):
        return "unavailable", "QGIS provider 自省面不可用（旧桥或回退画布）"
    try:
        import json

        reported = json.loads(probe(str(layer_id)))
    except Exception as exc:
        return "unavailable", f"QGIS provider 自省失败：{exc}"
    if not reported.get("exists"):
        return "unavailable", "图层尚未镜像到 QGIS（无 provider schema）"
    got_names = [str(field.get("name")) for field in reported.get("fields") or []]
    want_names = [field.key for field in descriptors if field.origin != "extra"]
    if got_names == want_names:
        return "synced", f"字段 schema 与 QGIS provider 一致（{len(got_names)} 字段）"
    missing = [name for name in want_names if name not in got_names]
    extra = [name for name in got_names if name not in want_names]
    parts = []
    if missing:
        parts.append(f"缺 {missing}")
    if extra:
        parts.append(f"多 {extra}")
    return "drift", "QGIS provider schema 漂移：" + "，".join(parts)
