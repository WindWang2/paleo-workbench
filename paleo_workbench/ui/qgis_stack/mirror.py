"""Snapshot → QGIS mirror upsert, shared by shim and display canvas."""
from __future__ import annotations

import json

_GEOMETRY_TYPE = {"Point": "Point", "MultiPoint": "Point",
                  "LineString": "LineString", "MultiLineString": "LineString",
                  "Polygon": "Polygon", "MultiPolygon": "Polygon"}


def mirror_snapshot_to_stack(stack, canvas_address, snapshot,
                             diagnostics: list | None = None) -> tuple[list[str], list[str]]:
    """Returns (mirrored_qgis_ids, seen_doc_ids).

    #1164: per-layer and tail failures append ``(layer_id, error)`` to
    *diagnostics* (when given) instead of vanishing in ``continue``/``pass``.
    """
    if snapshot.project_crs:
        try:
            stack.set_destination_crs(canvas_address, str(snapshot.project_crs))
        except Exception:
            pass
    seen: list[str] = []
    mirrored_qgis_ids: list[str] = []
    for layer in snapshot.layers:
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
            if diagnostics is not None:
                diagnostics.append((str(getattr(layer, "id", "?")), str(exc)))
            continue
        seen.append(layer.id)
        mirrored_qgis_ids.append(qgis_id)
    try:
        stack.remove_mirror_layers_except(seen)
        stack.set_mirror_layer_order(seen)
        stack.refresh_canvas(canvas_address)
    except Exception as exc:
        if diagnostics is not None:
            diagnostics.append(("<tail>", str(exc)))
    return mirrored_qgis_ids, seen
