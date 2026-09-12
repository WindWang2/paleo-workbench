"""Snapshot → QGIS mirror upsert, shared by shim and display canvas."""
from __future__ import annotations

import json

# Polygon layers mirror as MultiPolygon so single/multi features share one
# WKB type on the memory provider (matches qgis_layer_schema's
# qgis_geometry_type_name; R2-F3).
_GEOMETRY_TYPE = {"Point": "Point", "MultiPoint": "Point",
                  "LineString": "LineString", "MultiLineString": "LineString",
                  "Polygon": "MultiPolygon", "MultiPolygon": "MultiPolygon"}


def _normalize_auth_id(crs: str) -> str:
    text = str(crs or "").strip()
    if not text:
        return ""
    from paleo_workbench.mapping.map_render_backend import _normalize_crs_name

    return _normalize_crs_name(text)


def _geographic_auth(crs: str) -> bool:
    """V9 W3: axis truth delegated to the CRS contract (single predicate).

    The pre-V9 literal set {4326, 4269, 4258} silently classified CGCS2000
    (4490), Beijing-1954 (4214), Xian-1980 (4610)… as non-geographic, so
    their layers skipped the degree-domain extent check. Unverifiable ids
    stay non-geographic here (fail-open matches the historic contract: the
    extent check only drops CRSs it can prove wrong).
    """
    from paleo_workbench.mapping.crs_contract import crs_is_geographic

    return crs_is_geographic(crs) is True


def _extent_fits_crs(crs: str, extent) -> bool:
    if not extent or len(extent) < 4:
        return True
    if not _geographic_auth(crs):
        return True
    xmin, ymin, xmax, ymax = extent[:4]
    return (
        abs(float(xmin)) <= 180 and abs(float(xmax)) <= 180
        and abs(float(ymin)) <= 90 and abs(float(ymax)) <= 90
    )


def _qgis_crs_for_layer(layer, snapshot, *, on_drop=None) -> str:
    auth = _normalize_auth_id(
        getattr(layer, "crs", "") or getattr(snapshot, "project_crs", "") or "")
    if auth and not _extent_fits_crs(auth, getattr(layer, "extent", None)):
        # V9 W3: a dropped CRS is a degraded mirror state, not a silent one.
        if on_drop is not None:
            on_drop(
                getattr(layer, "id", ""),
                f"layer extent outside degree domain — CRS {auth} not set on mirror",
            )
        return ""
    return auth


def _qgis_crs_for_snapshot(snapshot, *, on_drop=None) -> str:
    auth = _normalize_auth_id(getattr(snapshot, "project_crs", "") or "")
    if not auth:
        return ""
    for layer in getattr(snapshot, "layers", ()) or ():
        if not _extent_fits_crs(auth, getattr(layer, "extent", None)):
            if on_drop is not None:
                on_drop(
                    getattr(layer, "id", ""),
                    f"snapshot layer extent outside degree domain — canvas CRS {auth} not pushed",
                )
            return ""
    return auth

# v7 §5: process-level scalar data mirror shared by every canvas publish
# (both the authoring shim and the display canvas mirror the same science).
_SCALAR_DATA_CACHE = None


def _scalar_data_cache():
    global _SCALAR_DATA_CACHE
    if _SCALAR_DATA_CACHE is not None:
        return _SCALAR_DATA_CACHE
    from paleo_workbench.mapping.scalar_style import scalar_style_pipeline_ready

    if not scalar_style_pipeline_ready()["ready"]:
        return None
    from paleo_workbench.mapping.scalar_data_mirror import ScalarDataMirror

    _SCALAR_DATA_CACHE = ScalarDataMirror()
    return _SCALAR_DATA_CACHE


def _fields_json_for_metadata(metadata: dict, *, on_skip=None) -> str:
    """fields_json from the layer's recorded role (spec authority).

    V9 W6: a role that fails spec resolution is a diagnosable schema gap,
    not a silent legacy path — ``on_skip`` receives the reason whenever the
    caller can record it (mirror diagnostics).
    """
    role = str((metadata or {}).get("role") or "")
    if not role:
        return ""
    try:
        from paleo_workbench.mapping.qgis_layer_schema import (
            fields_json_for_spec,
        )
        from paleo_workbench.mapping_workspace.geological_layer_spec import (
            spec_for_role,
        )

        return json.dumps(
            fields_json_for_spec(spec_for_role(role)), ensure_ascii=False)
    except (KeyError, ValueError) as exc:
        if on_skip is not None:
            on_skip(
                str((metadata or {}).get("id") or ""),
                f"role {role!r} has no GeologicalLayerSpec — layer published "
                f"un-schematized ({exc})",
            )
        return ""

def release_scalar_data_cache() -> None:
    """Drop stale scalar data mirrors (called on host teardown)."""
    global _SCALAR_DATA_CACHE
    if _SCALAR_DATA_CACHE is not None:
        _SCALAR_DATA_CACHE.clear()
        _SCALAR_DATA_CACHE = None


# ---------------------------------------------------------------------------
# v7 §9 — publish ledger: the host-side per-layer revision tokens
# (LayerContentToken = data_revision, LayerStyleToken = style signature,
# LayerPlacementToken/VisibilityToken = placement/visibility).  The publish
# path consults the ledger and ships ONLY what changed: no-op publishes
# touch nothing, single-feature edits ship one feature, style-only changes
# reapply the renderer, visibility-only changes stay on the cheap setters.


def _style_signature(renderer_xml: str, labeling_xml: str, legacy_style) -> str:
    legacy_json = ""
    if legacy_style is not None:
        if isinstance(legacy_style, str):
            legacy_json = legacy_style
        else:
            try:
                import json as _json
                legacy_json = _json.dumps(legacy_style, sort_keys=True)
            except (TypeError, ValueError):
                legacy_json = ""
    return "".join((renderer_xml, labeling_xml, legacy_json))


class _LedgerEntry:
    # V10 M-E（R1 修复）：name 进入 token 集——程序化改名（rename_layer /
    # 属性对话框）现在会触发真实 upsert，C++ upsertMirrorLayer 里的
    # setName 得以执行；此前 no-op 判定漏掉名字，镜像树残留旧名。
    # V10 M-O：scale_range token —— 比例尺可见域变化重新发布。
    __slots__ = ("data_revision", "style_sig", "visible", "opacity",
                 "geom_kind", "features_by_id", "name", "scale_range", "authoritative")

    def __init__(self, data_revision, style_sig, visible, opacity,
                 geom_kind, features_by_id, name="", scale_range=None, authoritative=False):
        self.data_revision = data_revision
        self.style_sig = style_sig
        self.visible = visible
        self.opacity = opacity
        self.geom_kind = geom_kind
        self.features_by_id = features_by_id
        self.name = name
        self.scale_range = scale_range
        # M0 §3 台账对齐：authoritative 标记「镜像=真源」——commit 后经
        # align_publish_ledger 直跳新基线的条目置 True（编辑权威已在镜像侧）。
        self.authoritative = bool(authoritative)


# R2-F8/R3: the ledger is keyed by (stack identity, layer id) — a fresh
# stack object (new test, new project, re-created canvas) never inherits
# another stack's tokens, so entries cannot leak across stacks and force a
# full ship on first publish.  reset_publish_ledger stays for explicit
# project-switch resets.
_MIRROR_LEDGER: dict[tuple[int, str], _LedgerEntry] = {}

# V10 M-E（R2 修复）：id(stack) 复用防护——栈对象被 GC 后其地址可能被新栈
# 复用，旧 token 会让新栈的首次发布被误判 no-op（静默空镜像）。能建弱引用
# 的栈（Python 对象 / 支持弱引用的绑定对象）登记 live 引用，复用即清；
# 不能建弱引用的栈保持旧语义（诚实降级，不虚构安全性）。
_STACK_ID_REFS: dict[int, object] = {}


def _purge_stack_entries(stack_id: int) -> None:
    for key in [key for key in _MIRROR_LEDGER if key[0] == stack_id]:
        del _MIRROR_LEDGER[key]


def _ledger_key(stack, layer_id: str) -> tuple[int, str]:
    stack_id = id(stack)
    registered = _STACK_ID_REFS.get(stack_id)
    if registered is not None and registered is not False:
        live = registered()
        if live is None or live is not stack:
            # 旧栈已亡（回调未及清理）或地址被新栈复用——旧 token 全部失效。
            _purge_stack_entries(stack_id)
            registered = None
    if registered is None:
        try:
            import weakref

            _STACK_ID_REFS[stack_id] = weakref.ref(
                stack, lambda _ref, _sid=stack_id: _purge_stack_entries(_sid))
        except TypeError:
            # 不可弱引用：标记为「不可校验」而非假装安全（旧语义保留）。
            _STACK_ID_REFS[stack_id] = False
    return (stack_id, str(layer_id))


def reset_publish_ledger() -> None:
    """Clear the publish ledger (stack re-created / project switched)."""
    _MIRROR_LEDGER.clear()


def align_publish_ledger(stack, layer) -> bool:
    """M0 §3 台账对齐：commit 后镜像即编辑发生地，无需重发。

    台账直接对齐新基线：``data_revision`` 跳到图层当前修订、
    style/可见性等 token 按当前图层状态重算，条目标记
    ``authoritative``（镜像=真源）。对齐后的下一次发布对数据判 no-op。

    前提：该层此前已发布过（镜像上确有数据——从未发布的层对齐会把
    「镜像缺数据」冻结成 no-op）。无既有条目或修订不可用 → False，
    调用方走正常发布路径。

    fid 反查表：桥侧 fid 表按 provider 现值重建由 M1 committed* 回写
    接线（全量重发路径本就重建）；M0 交付宿主侧对齐机制。
    """
    key = _ledger_key(stack, getattr(layer, "id", ""))
    entry = _MIRROR_LEDGER.get(key)
    if entry is None:
        return False
    try:
        layer_revision = int(getattr(layer, "data_revision", 0) or 0)
    except (TypeError, ValueError):
        return False
    if layer_revision == 0:
        return False
    tokens = _layer_ledger_tokens(layer)
    _MIRROR_LEDGER[key] = _LedgerEntry(
        layer_revision, tokens["style_sig"], bool(layer.visible),
        float(layer.opacity), tokens["geom_kind"],
        tokens["features_by_id"], name=str(layer.name or layer.id),
        scale_range=tokens["scale_range"], authoritative=True)
    return True


def align_publish_ledger_for_layer(stack, layer, *, metadata=None) -> bool:
    """M1 便捷面：把宿主 ``VectorLayer``（真源）适配成台账 token 形状后
    调 :func:`align_publish_ledger`（commit 后直跳新基线）。

    ``metadata`` 只需 ``role``（fields_json 同源）——与快照发布循环的
    token 公式一致（token 公式见 ``_layer_ledger_tokens``）。
    """
    from types import SimpleNamespace

    visible = getattr(layer, "visible", True)
    adapter = SimpleNamespace(
        id=layer.id,
        name=layer.name,
        data_revision=layer.data_revision,
        style=layer.style,
        visible=bool(visible),
        opacity=float(getattr(layer, "opacity", 1.0) or 1.0),
        features=[feature.as_record() for feature in layer.features()],
        metadata=metadata or {},
    )
    return align_publish_ledger(stack, adapter)


def _layer_ledger_tokens(layer) -> dict:
    """按发布循环同构的公式重算一层台账 token（align 专用）。

    与 ``mirror_snapshot_to_stack`` 循环内语义保持一致（qgis_style →
    legacy 回落 → 相图填充 renderer 生成；geom 首要素/类型兜底）——
    偏差表现为对齐后首次发布多一次重发（安全回落），不是静默漂移。
    """
    features = []
    for f in layer.features:
        props = dict(f.get("properties") or {})
        fid = f.get("id")
        if fid is not None:
            props.setdefault("__pwb_fid", str(fid))
        features.append({"type": "Feature",
                         "geometry": f.get("geometry"),
                         "properties": props})
    metadata = getattr(layer, "metadata", None) or {}
    if features:
        geom_raw = features[0].get("geometry") if isinstance(features[0], dict) else None
        geom_type = str(geom_raw.get("type", "")) if isinstance(geom_raw, dict) else ""
        geom = _GEOMETRY_TYPE.get(geom_type, "Point")
    else:
        _KIND_GEOM = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
        geom = _KIND_GEOM.get(str(metadata.get("geometry_kind") or ""), "Point")
    style_raw = getattr(layer, "style", None) or {}
    if not isinstance(style_raw, dict):
        try:
            style_raw = dict(style_raw)
        except Exception:
            style_raw = {}
    qgis_style = style_raw.get("qgis_style") if isinstance(style_raw, dict) else None
    renderer_xml = ""
    labeling_xml = ""
    legacy_style = None
    if isinstance(qgis_style, dict):
        renderer_xml = str(qgis_style.get("renderer_xml") or "")
        labeling_xml = str(qgis_style.get("labeling_xml") or "")
        if not (renderer_xml.strip() or labeling_xml.strip()):
            legacy_style = {k: v for k, v in style_raw.items() if k != "qgis_style"} or None
    else:
        legacy_style = {k: v for k, v in style_raw.items() if k != "qgis_style"} if isinstance(style_raw, dict) else None
        if legacy_style is not None and not legacy_style:
            legacy_style = None
    if (not renderer_xml.strip() and isinstance(legacy_style, dict)
            and legacy_style.get("fill_patterns")
            and str(legacy_style.get("renderer") or "") == "categorized"
            and geom in ("Polygon", "MultiPolygon")):
        try:
            from paleo_workbench.mapping.facies_renderer_xml import (
                categorized_fill_renderer_xml,
            )
            from paleo_workbench.mapping.map_styles import VectorStyle

            parsed = VectorStyle.from_dict(legacy_style)
            if parsed.field and parsed.categories:
                generated = categorized_fill_renderer_xml(
                    field=parsed.field,
                    categories=parsed.categories,
                    fill_patterns=dict(legacy_style.get("fill_patterns") or {}),
                )
                if generated.strip():
                    renderer_xml = generated
                    legacy_style = None
        except Exception:
            pass  # 发布循环同位置只诊断不阻断；对齐回落 = 多一次重发
    return {
        "style_sig": _style_signature(renderer_xml, labeling_xml, legacy_style),
        "geom_kind": geom,
        "features_by_id": {
            str((f.get("properties") or {}).get("__pwb_fid")
             or (f.get("properties") or {}).get("id") or ""):
            _feature_signature(f) for f in features},
        "scale_range": _scale_range_token(layer),
    }
    # V10：栈 id 登记一并清（防长期进程里 False 标记累积）。
    _STACK_ID_REFS.clear()


def _doc_declares(method, *names: str) -> bool:
    """pybind11 binding 声明兜底：builtin 方法无 inspect 签名，但其
    ``__doc__`` 首行即完整绑定声明。按「参数名 + 冒号」词边界匹配（裸子串
    会误命中别的词的一部分），无任何可判定信息时 False。"""
    import re

    try:
        doc = getattr(method, "__doc__", None) or ""
        if not isinstance(doc, str):
            return False
        return all(
            re.search(r"\b%s:" % name, doc) is not None for name in names)
    except (TypeError, ValueError):
        return False


_EMPTY_FEATURE_COLLECTION = '{"type":"FeatureCollection","features":[]}'


def _feature_collection_json(features) -> str:
    return json.dumps({"type": "FeatureCollection", "features": features})


def _stack_supports_delta(stack) -> bool:
    """Capability probe for the delta channel (R3).

    ``inspect.signature`` first (pure-Python fake stacks / older bridges
    behave as before); pybind11 builtins expose no inspect signature
    (``ValueError``), but their ``__doc__`` first line IS the binding
    declaration — fall back to matching its parameter declarations
    (``data_revision:`` + ``delta:``). No usable signal → False
    (honest failure, never a silent assumption). Probing is side-effect
    free and uncached: the bridge method itself is never invoked, and
    monkeypatched stack classes in tests always see a fresh probe.
    """
    import inspect

    method = stack.upsert_mirror_layer
    try:
        params = inspect.signature(method).parameters
        return "data_revision" in params and "delta" in params
    except (TypeError, ValueError):
        return _doc_declares(method, "data_revision", "delta")


def _stack_supports_fields_json(stack) -> bool:
    """R3-1: probe for the fields_json kwarg (older bridges ignore it).

    Same two-tier rule as :func:`_stack_supports_delta` (signature first,
    pybind11 ``__doc__`` binding declaration as fallback); see its
    docstring for the rationale.
    """
    import inspect

    method = stack.upsert_mirror_layer
    try:
        params = inspect.signature(method).parameters
        return "fields_json" in params
    except (TypeError, ValueError):
        return _doc_declares(method, "fields_json")


def _feature_signature(feature: dict) -> tuple:
    return (
        json.dumps(feature.get("geometry"), sort_keys=True),
        json.dumps(feature.get("properties"), sort_keys=True),
    )


def _scale_range_token(layer) -> tuple[float, float] | None:
    """V10 M-O：MapLayer.scale_range (min_denominator, max_denominator)。"""
    raw = getattr(layer, "scale_range", None)
    if not raw:
        return None
    try:
        lo, hi = float(raw[0]), float(raw[1])
    except (TypeError, ValueError, IndexError):
        return None
    if lo <= 0.0 and hi <= 0.0:
        return None
    return (lo, hi)


def _stack_supports_scale_range(stack) -> bool:
    """V10 M-O：桥 upsert_mirror_layer 是否带 min_scale/max_scale 通道。"""
    import inspect

    method = stack.upsert_mirror_layer
    try:
        return "min_scale" in inspect.signature(method).parameters
    except (TypeError, ValueError):
        return _doc_declares(method, "min_scale")


def _verify_published_schema(stack, doc_id: str, fields_json: str, _sink) -> None:
    """V9 W6：发布后读回 provider schema 与 spec wire 比对（漂移进诊断）。

    只比对契约面（字段名序 + 类型）——别名/控件/默认值由 V8 M1 的
    applyFieldSchema 幂等覆盖，等价判据不重复实现。桥缺失自省面或读回
    失败时记录诊断（不阻塞发布——镜像仍可用，漂移在案）。
    """
    probe = getattr(stack, "mirror_layer_schema_json", None)
    if not callable(probe):
        return
    try:
        import json as _json

        reported = _json.loads(probe(str(doc_id)))
        want = _json.loads(fields_json)
    except Exception as exc:
        _sink(str(doc_id), f"schema verify failed: {exc}")
        return
    if not reported.get("exists"):
        _sink(str(doc_id), "schema verify: layer missing after publish")
        return
    # wire 形状 = 字段条目列表（qgis_layer_schema.fields_json_for_spec 与
    # C++ parseFieldSchema 的契约；兼容 {"fields": [...]} 包装形态）。
    want_fields = list(want.get("fields") or ()) if isinstance(want, dict) else list(want)
    got_fields = list(reported.get("fields") or [])
    want_names = [str(field.get("name")) for field in want_fields]
    got_names = [str(field.get("name")) for field in got_fields]
    if want_names != got_names:
        _sink(
            str(doc_id),
            f"schema drift: published fields {got_names} != spec {want_names}",
        )
        return
    want_types = {str(f.get("name")): str(f.get("type")) for f in want_fields}
    for field in got_fields:
        name = str(field.get("name"))
        expected = want_types.get(name, "")
        actual = str(field.get("type") or "")
        if expected and actual and expected != actual:
            _sink(
                str(doc_id),
                f"schema drift: field {name} type {actual!r} != spec {expected!r}",
            )


def _renderer_semantic_signature(renderer_xml: str):
    """V10 M-K：渲染器语义签名（类型 + 符号数 + categorized 字段）。

    QGIS 对 renderer XML 有自己的规范化（属性顺序/默认值补全），逐字节
    比对只会产生噪声；漂移判据取「换了渲染器类型 / 符号数变化 /
    categorized 分类字段变化」这些真实漂移信号。
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(renderer_xml)
    except ET.ParseError:
        return None
    renderer_type = root.get("type") or root.tag
    symbols = len(list(root.iter("symbol")))
    categories = len(list(root.iter("category")))
    field = ""
    for category in root.iter("category"):
        field = str(category.get("attribute") or category.get("attr") or "")
        break
    return (str(renderer_type), symbols, categories, field)


def _verify_published_style(stack, doc_id: str, renderer_xml: str, _sink) -> None:
    """V10 M-K：发布后读回已应用 renderer，与下发负载做语义比对。

    桥无 mirror_style_json 面（<0.6.0a0）→ 跳过（诚实，不虚构验证）；
    读回失败或语义签名漂移 → 诊断（不阻塞发布——镜像仍按旧样式渲染，
    漂移在案）。
    """
    probe = getattr(stack, "mirror_style_json", None)
    if not callable(probe):
        return
    try:
        import json as _json

        reported = _json.loads(probe(str(doc_id)))
    except Exception as exc:
        _sink(str(doc_id), f"style verify failed: {exc}")
        return
    if not reported.get("exists"):
        _sink(str(doc_id), "style verify: layer missing after publish")
        return
    applied = str(reported.get("renderer_xml") or "")
    if not applied.strip():
        _sink(str(doc_id), "style drift: renderer missing after publish")
        return
    want_sig = _renderer_semantic_signature(renderer_xml)
    got_sig = _renderer_semantic_signature(applied)
    if want_sig is None or got_sig is None:
        return
    if want_sig[0] != got_sig[0] or want_sig[1] != got_sig[1] or want_sig[3] != got_sig[3]:
        _sink(
            str(doc_id),
            f"style drift: applied renderer {got_sig[:1] + got_sig[2:]} != payload {want_sig[:1] + want_sig[2:]}",
        )


def mirror_snapshot_to_stack(
    stack, canvas_address, snapshot, diags=None, *, groups: bool = False
) -> tuple[list[str], list[str], list[str]]:
    """Mirror vector layers into the QGIS project (incremental reconcile).

    Returns ``(mirrored_qgis_ids, seen_doc_ids, failures)``.

    #1164: failures are collected and surfaced to the host instead of being
    swallowed — a dropped layer or a failed remove/order/refresh previously
    left the mirror silently diverging from the document while
    ``backend_status_changed`` still reported a healthy backend.

    v7 §5: raster layers (scalar factor grids via the float-GeoTIFF data
    mirror + pseudocolor renderer XML, and raster_source file layers) are
    mirrored with ``upsert_raster_mirror_layer``.  When the scalar data
    pipeline is unavailable the layer is skipped and reported as a failure —
    never silently dropped, never substituted with wrong pixels.

    V5 ``groups=True``（分层编图工作区）：跳过 root 平铺顺序推送——组结构、
    图层放置与组可见性由 ``LayerGroupController`` 经 group API 增量
    reconcile（同一 QGIS 树权威，绝不另建第二棵树）。
    """

    def _sink(doc_id: str, message: str) -> None:
        if diags is not None:
            diags.append((doc_id, message))

    failures: list[str] = []
    canvas_crs = _qgis_crs_for_snapshot(snapshot, on_drop=_sink)
    # V10 M-B（陈旧 CRS 清理）：canvas_crs 为空（工程未声明）时也要显式
    # set_destination_crs("")——否则切工程后画布残留上一个工程的 CRS，
    # 未声明工程会在外国 CRS 下渲染（甚至采集）。无效目标 CRS = QGIS 的
    # no-OTF 模式（raw 坐标渲染），与回退渲染器「未声明即 raw 坐标」对齐。
    try:
        stack.set_destination_crs(canvas_address, canvas_crs)
    except Exception as exc:
        failures.append(f"crs {canvas_crs!r}: {exc}")
    # V10 M-C（transform context 链）：同一 authid 推进 owning QgsProject 的
    # CRS（+由 CRS 派生的 ellipsoid）——measure/identify 等读取
    # QgsProject::transformContext()/ellipsoid() 的消费方不再吃到空默认。
    # 旧桥无此面 → 跳过（诚实降级；manifest flag project_crs_push 标记）。
    if canvas_crs and callable(getattr(stack, "set_project_crs", None)):
        try:
            error = stack.set_project_crs(canvas_crs)
            if error:
                _sink("<crs>", f"project CRS push failed: {error}")
        except Exception as exc:
            _sink("<crs>", f"project CRS push failed: {exc}")
    # V10 M-E（R4）：快照内重复 doc_id 会静默塌缩成一个镜像层——显式诊断
    # 并拒绝第二个（一个 Paleo 层恰好一个 QgsMapLayer 的不变量）。
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for layer in snapshot.layers:
        if layer.id in seen_ids:
            duplicate_ids.add(layer.id)
        else:
            seen_ids.add(layer.id)
    if duplicate_ids:
        for dup in sorted(duplicate_ids):
            failures.append(f"layer {dup}: duplicate layer id in snapshot")
            _sink(dup, "duplicate layer id in snapshot; publishing first occurrence only")
    seen: list[str] = []
    # V11 树事务窗口（桥 begin/end_tree_update）：N 次镜像 upsert + 清理 +
    # 平铺序共享一个原生窗口——零中间画布同步；旧桥透明降级。
    from paleo_workbench.mapping_workspace.tree_transaction import tree_transaction
    with tree_transaction(stack):
        mirrored_qgis_ids: list[str] = []
        data_cache = _scalar_data_cache()
        # M0 §3 停发窗口：编辑会话集合（绑定本发布栈时）整体短路数据重发。
        # 未开启会话 / 会话绑定其他栈 → 空集合，发布行为与 M0 之前逐字节一致。
        from paleo_workbench.mapping.edit_session_set import SESSION_SET

        edit_window = set(SESSION_SET.active_layer_ids(stack))
        for layer in snapshot.layers:
            if layer.id in duplicate_ids and layer.id in seen:
                # 重复 id：首个已发布，后续出现跳过（不再静默塌缩）。
                continue
            if layer.layer_type in ("scalar_grid", "raster_source"):
                try:
                    from paleo_workbench.mapping.scalar_publish import (
                        build_scalar_qgis_payload,
                        raster_source_qgis_payload,
                    )

                    if layer.layer_type == "scalar_grid":
                        payload = None
                        if data_cache is not None:
                            payload = build_scalar_qgis_payload(layer, data_cache)
                        if payload is None:
                            failures.append(
                                f"layer {layer.id}: scalar raster mirror "
                                "unavailable (bridge/gdal); layer not mirrored")
                            _sink(layer.id, "scalar data pipeline unavailable")
                            continue
                    else:
                        payload = raster_source_qgis_payload(layer)
                        if payload is None:
                            # R3-7: an empty reference payload is a real problem
                            # (the layer vanishes from the mirror), not a skip.
                            failures.append(
                                f"layer {layer.id}: empty raster source payload")
                            _sink(layer.id, "empty raster source payload")
                            continue
                    qgis_id = stack.upsert_raster_mirror_layer(
                        layer.id, layer.name or layer.id,
                        payload["source_path"],
                        layer.crs or snapshot.project_crs,
                        payload["renderer_xml"],
                        bool(layer.visible), float(layer.opacity),
                    )
                except Exception as exc:
                    failures.append(f"layer {layer.id}: {exc}")
                    _sink(layer.id, str(exc))
                    continue
                seen.append(layer.id)
                mirrored_qgis_ids.append(qgis_id)
                continue
            if layer.layer_type != "vector":
                continue
            features = []
            for f in layer.features:
                props = dict(f.get("properties") or {})
                # M3：文档 feature_id 随镜像下推（C++ 拾取工具据此回写权威
                # 会话；memory provider 不落属性字段，桥侧自建 fid 映射表）。
                fid = f.get("id")
                if fid is not None:
                    props.setdefault("__pwb_fid", str(fid))
                features.append({"type": "Feature",
                                 "geometry": f.get("geometry"),
                                 "properties": props})
            # 零要素图层同样上树（QGIS memory layer 零要素合法）——否则新建
            # 图层在首次数字化前从图层树消失（M2 终局审查 I1）。几何类型改由
            # metadata.geometry_kind 兜底（点/线/面），无则 Point。
            metadata = getattr(layer, "metadata", None) or {}
            if features:
                geom_raw = features[0].get("geometry") if isinstance(features[0], dict) else None
                geom_type = str(geom_raw.get("type", "")) if isinstance(geom_raw, dict) else ""
                geom = _GEOMETRY_TYPE.get(geom_type, "Point")
            else:
                _KIND_GEOM = {"point": "Point", "line": "LineString", "polygon": "Polygon"}
                geom = _KIND_GEOM.get(str(metadata.get("geometry_kind") or ""), "Point")
            style_raw = getattr(layer, "style", None) or {}
            if not isinstance(style_raw, dict):
                try:
                    style_raw = dict(style_raw)
                except Exception:
                    style_raw = {}
            # v7 R2-F4: spec-authored field schema (fields_json) reaches the
            # mirror when the layer declares its role; absent roles keep the
            # legacy property-only path (honest, no fake enforcement). Unknown
            # roles surface a diagnostic (V9 W6) instead of vanishing.
            fields_json = _fields_json_for_metadata(
                metadata,
                on_skip=lambda _ignored, message, _lid=layer.id: _sink(_lid, message),
            )
            qgis_style = style_raw.get("qgis_style") if isinstance(style_raw, dict) else None
            has_qgis_renderer = False
            has_qgis_labeling = False
            renderer_xml = ""
            labeling_xml = ""
            legacy_style = None
            if isinstance(qgis_style, dict):
                renderer_xml = str(qgis_style.get("renderer_xml") or "")
                labeling_xml = str(qgis_style.get("labeling_xml") or "")
                has_qgis_renderer = bool(renderer_xml.strip())
                has_qgis_labeling = bool(labeling_xml.strip())
                if has_qgis_renderer or has_qgis_labeling:
                    legacy_style = None
                else:
                    legacy_style = {k: v for k, v in style_raw.items() if k != "qgis_style"}
                    if not legacy_style:
                        legacy_style = None
            else:
                legacy_style = {k: v for k, v in style_raw.items() if k != "qgis_style"} if isinstance(style_raw, dict) else None
                if legacy_style is not None and not legacy_style:
                    legacy_style = None
            if (not has_qgis_renderer and isinstance(legacy_style, dict)
                    and legacy_style.get("fill_patterns")
                    and str(legacy_style.get("renderer") or "") == "categorized"
                    and geom in ("Polygon", "MultiPolygon")):
                try:
                    from paleo_workbench.mapping.facies_renderer_xml import (
                        categorized_fill_renderer_xml,
                    )
                    from paleo_workbench.mapping.map_styles import VectorStyle

                    parsed = VectorStyle.from_dict(legacy_style)
                    if parsed.field and parsed.categories:
                        generated = categorized_fill_renderer_xml(
                            field=parsed.field,
                            categories=parsed.categories,
                            fill_patterns=dict(legacy_style.get("fill_patterns") or {}),
                        )
                        if generated.strip():
                            renderer_xml = generated
                            legacy_style = None
                except Exception as exc:
                    _sink(layer.id, f"facies pattern renderer skipped: {exc}")
            # v7 §9: consult the publish ledger — ship only what changed.
            # Duck-typed layers (SimpleNamespace, legacy producers) may not
            # carry revisions: 0 = unknown, ledger disabled, delta channel off.
            style_sig = _style_signature(renderer_xml, labeling_xml, legacy_style)
            entry = _MIRROR_LEDGER.get(_ledger_key(stack, layer.id))
            try:
                layer_revision = int(getattr(layer, "data_revision", 0) or 0)
            except (TypeError, ValueError):
                layer_revision = 0
            ledger_active = layer_revision != 0
            if not ledger_active:
                entry = None
            if layer.id in edit_window:
                # M0 §3 停发窗口：集合内层数据重发短路（镜像即编辑发生地——
                # M1 起编辑直接发生在镜像层上，宿主重发会覆盖编辑缓冲）。
                # 台账冻结（不记新基线，窗口关闭/对齐前的变更全部待发）。
                if renderer_xml:
                    # 样式读回验证照跑（诊断；集合内检出漂移只记录，修复顺延
                    # 到窗口关闭——此时重发/重建会毁掉编辑缓冲）。
                    _verify_published_style(stack, layer.id, renderer_xml, _sink)
                if entry is None:
                    _sink(layer.id, "edit window: layer not yet mirrored; publish deferred")
                _sink(layer.id, "publish:edit-window (data frozen)")
                seen.append(layer.id)
                continue
            unchanged = (
                entry is not None
                and entry.data_revision == layer_revision
                and entry.style_sig == style_sig
                and entry.visible == bool(layer.visible)
                and entry.opacity == float(layer.opacity)
                and entry.geom_kind == geom
                and entry.name == str(layer.name or layer.id)
                and _scale_range_token(layer) == entry.scale_range)
            if unchanged:
                # no-op publish for this layer: tokens unchanged, nothing ships
                _sink(layer.id, "publish:no-op")
                seen.append(layer.id)
                continue

            delta_json = ""
            if (entry is not None and entry.data_revision != layer_revision
                    and _stack_supports_delta(stack) and features):
                changed: list | None = []
                seen_ids = set()
                for feature in features:
                    fid = str((feature.get("properties") or {}).get("__pwb_fid")
                              or (feature.get("properties") or {}).get("id") or "")
                    if not fid:
                        changed = None  # un-id'd payloads cannot delta safely
                        break
                    seen_ids.add(fid)
                    previous = entry.features_by_id.get(fid)
                    signature = _feature_signature(feature)
                    if previous is None or previous != signature:
                        changed.append(feature)
                if changed is not None:
                    removed = [fid for fid in entry.features_by_id
                               if fid not in seen_ids]
                    if (changed or removed) and len(changed) < len(features):
                        delta_json = json.dumps({
                            "base_revision": entry.data_revision,
                            "changed": changed,
                            "removed_ids": removed,
                        })
            delta_supported = _stack_supports_delta(stack)
            shipped_empty_delta = bool(delta_json and delta_supported)
            if shipped_empty_delta:
                # C++ ignores the FeatureCollection when delta_applied (#1272).
                # Empty payload is only safe on that path; failed-delta and
                # TypeError retries must ship the real collection or C++
                # truncates the mirror to empty.
                full_collection = _EMPTY_FEATURE_COLLECTION
            else:
                full_collection = _feature_collection_json(features)
            upsert_kwargs = {
                "is_reference": metadata.get("reference") == "true",
                "is_editable": metadata.get("editable") == "true",
                "reference_snap": metadata.get("snap") == "true",
            }
            if delta_supported:
                upsert_kwargs["data_revision"] = layer_revision
                if delta_json:
                    upsert_kwargs["delta"] = delta_json
            elif delta_json:
                # delta computed but the bridge cannot consume it: full ship
                # (documented in diags, never silent).
                _sink(layer.id, "delta unsupported by bridge; full ship")
                delta_json = ""
            if fields_json and _stack_supports_fields_json(stack):
                upsert_kwargs["fields_json"] = fields_json
            # V10 M-O：比例尺可见域通道（桥有面才推；语义 = QGIS 分母，
            # 0 一侧不限）。
            scale_token = _scale_range_token(layer)
            if scale_token is not None and _stack_supports_scale_range(stack):
                upsert_kwargs["min_scale"] = scale_token[0]
                upsert_kwargs["max_scale"] = scale_token[1]
            crs_auth = _qgis_crs_for_layer(layer, snapshot, on_drop=_sink)
            try:
                qgis_id = stack.upsert_mirror_layer(
                    layer.id, layer.name or layer.id, geom, crs_auth,
                    full_collection,
                    renderer_xml, labeling_xml, legacy_style,
                    bool(layer.visible), float(layer.opacity),
                    **upsert_kwargs,
                )
            except TypeError:
                # signature drift despite the probes — retry once with the
                # minimal legacy kwargs (R3-1: never a blind second full upsert).
                for drop in ("delta", "fields_json", "data_revision",
                             "min_scale", "max_scale"):
                    upsert_kwargs.pop(drop, None)
                delta_json = ""
                if fields_json:
                    # V9 W6: the retry silently published without the spec
                    # schema before — now the drift is on the record.
                    _sink(layer.id, "fields_json dropped on signature drift — published un-schematized")
                full_collection = _feature_collection_json(features)
                qgis_id = stack.upsert_mirror_layer(
                    layer.id, layer.name or layer.id, geom, crs_auth,
                    full_collection,
                    renderer_xml, labeling_xml, legacy_style,
                    bool(layer.visible), float(layer.opacity),
                    **upsert_kwargs,
                )
            except Exception as exc:
                retried = False
                if shipped_empty_delta:
                    try:
                        retry_kwargs = dict(upsert_kwargs)
                        retry_kwargs.pop("delta", None)
                        qgis_id = stack.upsert_mirror_layer(
                            layer.id, layer.name or layer.id, geom, crs_auth,
                            _feature_collection_json(features),
                            renderer_xml, labeling_xml, legacy_style,
                            bool(layer.visible), float(layer.opacity),
                            **retry_kwargs,
                        )
                        _sink(layer.id, f"delta not applied; full ship ({exc})")
                        retried = True
                    except Exception:
                        retried = False
                if not retried:
                    if has_qgis_renderer or has_qgis_labeling:
                        msg = str(exc).lower()
                        if "renderer" in msg or "labeling" in msg or "invalid" in msg:
                            raise
                    failures.append(f"layer {layer.id}: {exc}")
                    _sink(layer.id, str(exc))
                    continue
            if ledger_active:
                _MIRROR_LEDGER[_ledger_key(stack, layer.id)] = _LedgerEntry(
                    layer_revision, style_sig, bool(layer.visible),
                    float(layer.opacity), geom,
                    {str((f.get("properties") or {}).get("__pwb_fid")
                     or (f.get("properties") or {}).get("id") or ""):
                     _feature_signature(f) for f in features},
                    name=str(layer.name or layer.id),
                    scale_range=scale_token)
            seen.append(layer.id)
            mirrored_qgis_ids.append(qgis_id)
            # V9 W6：本次发布了 fields_json 的层做发布后验证（漂移可诊断，
            # 不再静默）。桥无自省面（旧版本）时 probe 缺席 = 跳过（诚实）。
            if fields_json and upsert_kwargs.get("fields_json"):
                _verify_published_schema(stack, layer.id, fields_json, _sink)
            # V10 M-K：renderer/labeling 同样读回验证（语义签名比对——渲染器
            # 类型 + 符号数 + categorized 字段；逐字节比对会被 QGIS 的 XML
            # 规范化噪声淹没）。
            if renderer_xml:
                _verify_published_style(stack, layer.id, renderer_xml, _sink)
        # v7 §9: ledger follows the mirror registry — entries for layers no
        # longer published are dropped so a re-added layer ships fully.
        keep_keys = {_ledger_key(stack, doc_id) for doc_id in seen} | {
            _ledger_key(stack, layer.id) for layer in snapshot.layers
            if layer.layer_type == "raster_source"}
        for stale_key in [key for key in _MIRROR_LEDGER
                          if key[0] == id(stack) and key not in keep_keys]:
            del _MIRROR_LEDGER[stale_key]
        if _SCALAR_DATA_CACHE is not None:
            _SCALAR_DATA_CACHE.retain_layer_ids({
                layer.id for layer in snapshot.layers
                if layer.layer_type == "scalar_grid"})
            _SCALAR_DATA_CACHE.release_stale()
        try:
            stack.remove_mirror_layers_except(seen)
        except Exception as exc:
            failures.append(f"remove_stale: {exc}")
            _sink("<tail>", str(exc))
        if not groups:
            try:
                # V11 顺序约定统一（04-ordering §5）：组装序自下而上，
                # 桥约定 top-first——显式反转，原生平铺画布与 fallback
                # 画笔（后绘在上）对同一快照渲染出相同堆叠（平价测试钉死）。
                stack.set_mirror_layer_order(list(reversed(seen)))
            except Exception as exc:
                failures.append(f"set_order: {exc}")
                _sink("<tail>", str(exc))
        try:
            stack.refresh_canvas(canvas_address)
        except Exception as exc:
            failures.append(f"refresh: {exc}")
            _sink("<tail>", str(exc))
    return mirrored_qgis_ids, seen, failures
