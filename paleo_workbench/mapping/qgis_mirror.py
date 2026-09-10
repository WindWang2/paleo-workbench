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
    auth = _normalize_auth_id(crs).upper()
    return auth in {"EPSG:4326", "EPSG:4269", "EPSG:4258"}


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


def _qgis_crs_for_layer(layer, snapshot) -> str:
    auth = _normalize_auth_id(
        getattr(layer, "crs", "") or getattr(snapshot, "project_crs", "") or "")
    if auth and not _extent_fits_crs(auth, getattr(layer, "extent", None)):
        return ""
    return auth


def _qgis_crs_for_snapshot(snapshot) -> str:
    auth = _normalize_auth_id(getattr(snapshot, "project_crs", "") or "")
    if not auth:
        return ""
    for layer in getattr(snapshot, "layers", ()) or ():
        if not _extent_fits_crs(auth, getattr(layer, "extent", None)):
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


def _fields_json_for_metadata(metadata: dict) -> str:
    """fields_json from the layer's recorded role (spec authority)."""
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
    except (KeyError, ValueError):
        return ""  # unknown role: legacy path, honestly un-schematized


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
    __slots__ = ("data_revision", "style_sig", "visible", "opacity",
                 "geom_kind", "features_by_id")

    def __init__(self, data_revision, style_sig, visible, opacity,
                 geom_kind, features_by_id):
        self.data_revision = data_revision
        self.style_sig = style_sig
        self.visible = visible
        self.opacity = opacity
        self.geom_kind = geom_kind
        self.features_by_id = features_by_id


# R2-F8/R3: the ledger is keyed by (stack identity, layer id) — a fresh
# stack object (new test, new project, re-created canvas) never inherits
# another stack's tokens, so entries cannot leak across stacks and force a
# full ship on first publish.  reset_publish_ledger stays for explicit
# project-switch resets.
_MIRROR_LEDGER: dict[tuple[int, str], _LedgerEntry] = {}


def _ledger_key(stack, layer_id: str) -> tuple[int, str]:
    return (id(stack), str(layer_id))


def reset_publish_ledger() -> None:
    """Clear the publish ledger (stack re-created / project switched)."""
    _MIRROR_LEDGER.clear()


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
    canvas_crs = _qgis_crs_for_snapshot(snapshot)
    if canvas_crs:
        try:
            stack.set_destination_crs(canvas_address, canvas_crs)
        except Exception as exc:
            failures.append(f"crs {canvas_crs}: {exc}")
    seen: list[str] = []
    mirrored_qgis_ids: list[str] = []
    data_cache = _scalar_data_cache()
    for layer in snapshot.layers:
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
        # legacy property-only path (honest, no fake enforcement).
        fields_json = _fields_json_for_metadata(metadata)
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
        unchanged = (
            entry is not None
            and entry.data_revision == layer_revision
            and entry.style_sig == style_sig
            and entry.visible == bool(layer.visible)
            and entry.opacity == float(layer.opacity)
            and entry.geom_kind == geom)
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
        full_collection = json.dumps(
            {"type": "FeatureCollection", "features": features})
        delta_supported = _stack_supports_delta(stack)
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
        try:
            qgis_id = stack.upsert_mirror_layer(
                layer.id, layer.name or layer.id, geom,
                _qgis_crs_for_layer(layer, snapshot),
                full_collection,
                renderer_xml, labeling_xml, legacy_style,
                bool(layer.visible), float(layer.opacity),
                **upsert_kwargs,
            )
        except TypeError:
            # signature drift despite the probes — retry once with the
            # minimal legacy kwargs (R3-1: never a blind second full upsert).
            for drop in ("delta", "fields_json", "data_revision"):
                upsert_kwargs.pop(drop, None)
            delta_json = ""
            qgis_id = stack.upsert_mirror_layer(
                layer.id, layer.name or layer.id, geom,
                _qgis_crs_for_layer(layer, snapshot),
                full_collection,
                renderer_xml, labeling_xml, legacy_style,
                bool(layer.visible), float(layer.opacity),
                **upsert_kwargs,
            )
        except Exception as exc:
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
                 _feature_signature(f) for f in features})
        seen.append(layer.id)
        mirrored_qgis_ids.append(qgis_id)
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
            stack.set_mirror_layer_order(seen)
        except Exception as exc:
            failures.append(f"set_order: {exc}")
            _sink("<tail>", str(exc))
    try:
        stack.refresh_canvas(canvas_address)
    except Exception as exc:
        failures.append(f"refresh: {exc}")
        _sink("<tail>", str(exc))
    return mirrored_qgis_ids, seen, failures
