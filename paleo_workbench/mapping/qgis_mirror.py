"""Snapshot → QGIS mirror upsert, shared by shim and display canvas."""
from __future__ import annotations

import json

_GEOMETRY_TYPE = {"Point": "Point", "MultiPoint": "Point",
                  "LineString": "LineString", "MultiLineString": "LineString",
                  "Polygon": "Polygon", "MultiPolygon": "Polygon"}

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


def release_scalar_data_cache() -> None:
    """Drop stale scalar data mirrors (called on host teardown)."""
    global _SCALAR_DATA_CACHE
    if _SCALAR_DATA_CACHE is not None:
        _SCALAR_DATA_CACHE.clear()
        _SCALAR_DATA_CACHE = None


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
    if snapshot.project_crs:
        try:
            stack.set_destination_crs(canvas_address, str(snapshot.project_crs))
        except Exception as exc:
            failures.append(f"crs {snapshot.project_crs}: {exc}")
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
                        continue  # empty payload: nothing to mirror
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
        try:
            qgis_id = stack.upsert_mirror_layer(
                layer.id, layer.name or layer.id, geom,
                layer.crs or snapshot.project_crs,
                json.dumps({"type": "FeatureCollection", "features": features}),
                renderer_xml, labeling_xml, legacy_style,
                bool(layer.visible), float(layer.opacity),
                is_reference=metadata.get("reference") == "true",
                is_editable=metadata.get("editable") == "true",
                # 参考图层「参与捕捉」勾选态投影到镜像层属性（菜单读取）。
                reference_snap=metadata.get("snap") == "true",
            )
        except Exception as exc:
            if has_qgis_renderer or has_qgis_labeling:
                msg = str(exc).lower()
                if "renderer" in msg or "labeling" in msg or "invalid" in msg:
                    raise
            failures.append(f"layer {layer.id}: {exc}")
            _sink(layer.id, str(exc))
            continue
        seen.append(layer.id)
        mirrored_qgis_ids.append(qgis_id)
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
