"""Mapping-domain harness actions (P2-C).

WRITE risk on document-level operations: every mutation happens on
MapDocument/MapAuthoringDocument objects through the domain services, with
data revisions bumped and (for data products) catalog provenance via the
existing lifecycle helpers. The agent never touches widget internals.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="map.create_factor_map",
            side_effect_notes="publishes the map document in-session; writes an intermediate grid artifact and a catalog run/version",
            output_schema={"type": "object", "properties": {"document_id": {"type": "string"}, "task_id": {"type": "string"}, "name": {"type": "string"}, "version_id": {"type": ["string", "null"]}, "run_id": {"type": ["string", "null"]}}, "required": ["document_id"]},
            description="从井点因素数据生成单因素图（提取→插值→网格/等值线/井位图层→MapDocument），生产管线。",
            handler=_create_factor_map,
            # #1186: writes the grid artifact to disk and registers a DataRun
            # + INTERMEDIATE version in the catalog — a real WRITE, not pure
            # compute.
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 2.0, "estimated_ram_bytes": 512 * 1024**2, "io_weight": 0.5},
            supports_cancel=True,
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "factor_name": {"type": "string", "description": "因素名，如 厚度/砂岩厚度"},
                    "target_horizon": {"type": "string"},
                    "method": {"type": "string", "enum": ["kriging", "idw"]},
                    "grid_n": {"type": "integer", "minimum": 8, "maximum": 1000},
                    "color_ramp": {"type": "string"},
                    "include_contours": {"type": "boolean"},
                    "include_wells": {"type": "boolean"},
                    "title": {"type": "string"},
                },
                "required": ["factor_name"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.create_well_location_map",
            output_schema={"type": "object", "properties": {"document_id": {"type": "string"}, "well_count": {"type": "integer"}, "extent": {"type": "array"}, "name": {"type": "string"}}, "required": ["document_id", "well_count"]},
            description="生成井位图（井点+井名标注+范围），场景 A 的生产路径。",
            handler=_create_well_location_map,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.2},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "label_wells": {"type": "boolean", "description": "是否标注井名"},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.add_layer",
            side_effect_notes="mutates the live map document in-session (layers list)",
            output_schema={"type": "object", "properties": {"added": {"type": "boolean"}, "document_id": {"type": "string"}, "layer_count": {"type": "integer"}}, "required": ["added", "document_id"]},
            description="向当前图文档添加图层（矢量/栅格/点/注释），写操作走文档修订。",
            handler=_add_layer,
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.3, "io_weight": 0.2},
            input_schema={
                "type": "object",
                "properties": {
                    "layer_type": {"type": "string", "enum": ["annotation", "polygon"]},
                    "name": {"type": "string"},
                    "text": {"type": "string", "description": "annotation 文本"},
                    "features": {"type": "array", "description": "GeoJSON-like features"},
                },
                "required": ["layer_type"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.set_style",
            side_effect_notes="mutates a layer style and bumps the style revision in-session",
            output_schema={"type": "object", "properties": {"layer": {"type": "string"}, "style": {"type": "object"}}, "required": ["layer", "style"]},
            description="设置当前图（或指定图层）的样式（颜色/线宽/标注）。",
            handler=_set_style,
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {
                    "layer_name": {"type": "string"},
                    "fill": {"type": "string"},
                    "stroke": {"type": "string"},
                    "stroke_width": {"type": "number", "minimum": 0.1},
                    "label_field": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.apply_template",
            side_effect_notes="creates/updates the composer composition in-session",
            output_schema={"type": "object", "properties": {"document_id": {"type": "string"}, "template": {"type": "string"}, "components": {"type": "array"}}, "required": ["document_id", "template"]},
            description="将制图模板应用到当前图（样式/要素齐备性：图例+比例尺+指北针+标题，可自定义标题）。",
            handler=_apply_template,
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {
                    "template": {"type": "string", "enum": ["standard", "minimal"], "description": "standard=齐备四要素; minimal=仅标题"},
                    "title": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.add_component",
            side_effect_notes="mutates the composer composition in-session",
            output_schema={"type": "object", "properties": {"added": {"type": "string", "description": "本次确保存在的组件名"}, "document_id": {"type": "string"}, "components": {"type": "array"}}, "required": ["added"]},
            description="向当前图的版面添加制图要素（图例/色标/比例尺/指北针/标题/图框）。",
            handler=_add_component,
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "enum": ["legend", "colorbar", "scale_bar", "north_arrow", "title", "map_frame"],
                    },
                    "text": {"type": "string", "description": "title 文本"},
                },
                "required": ["component"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.validate",
            description="校验当前图（图层/范围/CRS/图例/比例尺/导出就绪），返回 PASS/WARNING/FAIL。",
            handler=_validate,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {
                    "require_components": {"type": "boolean", "description": "要求图例/比例尺/指北针/标题齐备"},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.export",
            side_effect_notes="writes a validated export file inside the workspace and registers a catalog OUTPUT version",
            output_schema={"type": "object", "properties": {"exported": {"type": "boolean"}, "artifacts": {"type": "array"}, "provenance": {"type": "object"}, "metrics": {"type": "object"}}, "required": ["exported"]},
            description="导出当前图（PNG/SVG/PDF，生产导出路径），登记 catalog OUTPUT 版本。",
            handler=_export,
            # #1186: writes the exported file into the workspace and registers
            # a catalog OUTPUT version — WRITE, aligned with its side effects.
            risk=ActionRisk.WRITE,
            category="export",
            resource_profile={"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 512 * 1024**2, "io_weight": 2.0},
            input_schema={
                "type": "object",
                "properties": {
                    "output_path": {"type": "string"},
                    "width": {"type": "integer", "minimum": 64, "maximum": 16384},
                    "height": {"type": "integer", "minimum": 64, "maximum": 16384},
                    "dpi": {"type": "number", "minimum": 36, "maximum": 1200},
                    "skip_validation": {"type": "boolean", "description": "跳过导出前校验（不建议）"},
                },
                "required": ["output_path"],
                "additionalProperties": False,
            },
        )
    )


# ------------------------------------------------------------- helpers --
    registry.register(
        ActionSpec(
            action_id="map.describe",
            description="描述当前（或指定）图件文档：图层清单、范围、CRS、样式修订。",
            handler=_describe_map,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            domain_tags=("map", "describe"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.qc",
            description="对当前图件执行导出就绪 QC（图层/范围/CRS/成图要素），FAIL 即不合格。",
            handler=_map_qc,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            input_schema={
                "type": "object",
                "properties": {
                    "require_components": {"type": "boolean", "default": True},
                },
                "additionalProperties": False,
            },
            domain_tags=("map", "qc"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.contour",
            output_schema={"type": "object", "properties": {"draft_id": {"type": ["string", "null"]}, "name": {"type": "string"}, "levels": {"type": "array"}, "segment_count": {"type": "integer"}, "linked_task_id": {"type": ["string", "null"]}}, "required": ["name", "levels"]},
            description="从已插值的因子任务生成等值线初稿（真实 engine isolines，写回工程草稿区）。",
            handler=_map_contour,
            risk=ActionRisk.WRITE,
            category="background.compute",
            version="1.0",
            supports_cancel=True,
            resource_profile={"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 256 * 1024**2, "io_weight": 0.8},
            required_context=("project",),
            side_effect_notes="upserts a ContourDraft into the project document",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "n_levels": {"type": "integer", "minimum": 2, "maximum": 64},
                },
                "additionalProperties": False,
            },
            domain_tags=("map", "contour"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="layer.describe",
            description="描述当前图件中的一个图层：类型、要素数、样式与可见性。",
            handler=_describe_layer,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            input_schema={
                "type": "object",
                "properties": {"layer_name": {"type": "string"}},
                "additionalProperties": False,
            },
            domain_tags=("map", "layer"),
        )
    )

def _artifact_root(context: ActionContext) -> Path:
    """The PROJECT's artifacts tree (``<name>.artifacts``) — V2.

    Never a hardcoded ``demo`` name: a project saved under another name
    must keep its products inside its own tree (same root the catalog
    manages, ``project/paths.artifact_dir_for``). Project-less contexts
    keep the legacy ``./demo.artifacts`` fallback.
    """
    from paleo_workbench.project.paths import artifact_dir_for

    if context.project_path:
        return artifact_dir_for(Path(context.project_path))
    return Path.cwd() / "demo.artifacts"


def _current_document(context: ActionContext) -> Any:
    document = context.map_documents.get(context.current_map_id or "")
    if document is None and len(context.map_documents) == 1:
        document = next(iter(context.map_documents.values()))
    if document is None:
        raise LookupError("no current map document (create one first)")
    return document


def _publish(context: ActionContext, document: Any, document_id: str) -> None:
    context.map_documents[document_id] = document
    context.current_map_id = document_id


# ------------------------------------------------------------- handlers --
def _sanitize_factor_slug(name: Any) -> str:
    """Whitelist slug for agent-supplied factor names (#1174).

    Same rule as the scalar raster mirror slugs
    (``mapping/scalar_raster_mirror.py``): everything outside
    ``[A-Za-z0-9_.-]`` collapses to ``_`` so a factor name can never smuggle
    a path separator, ``..`` traversal or whitespace into a document id /
    artifact filename.
    """
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_") or "factor"


def _create_factor_map(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.services.geological_mapping_service import (
        DEFAULT_GEOLOGICAL_MAPPING_SERVICE,
    )

    document, task = DEFAULT_GEOLOGICAL_MAPPING_SERVICE.create_factor_map(
        context.project,
        parameters["factor_name"],
        target_horizon=parameters.get("target_horizon", ""),
        method=parameters.get("method", "kriging"),
        grid_n=int(parameters.get("grid_n", 50)),
        color_ramp=parameters.get("color_ramp"),
        include_contours=bool(parameters.get("include_contours", True)),
        include_wells=bool(parameters.get("include_wells", True)),
        title=parameters.get("title"),
    )
    # #1174: factor_name is agent input — the document_id (and the artifact
    # filename derived from it) only carries the sanitized slug.
    document_id = f"factor-{_sanitize_factor_slug(parameters['factor_name'])}-{uuid.uuid4().hex[:6]}"
    grid_layers = [l for l in document.layers if getattr(l, "layer_type", "") == "grid"]
    grid = getattr(grid_layers[0], "grid_result", None) if grid_layers else None

    # Side-effect guard (ADR 0066): validate BEFORE publishing/registering —
    # an invalid grid never commits a successful run or a derived version.
    from paleo_workbench.harness.validation import ScientificValidator

    verification = ScientificValidator().validate_grid(
        grid, label=f"factor_map.{parameters['factor_name']}"
    )
    if not verification.passed:
        raise ValueError(
            f"interpolated grid failed scientific validation: {verification.reasons}"
        )

    _publish(context, document, document_id)

    # Provenance: DataRun + INTERMEDIATE grid artifact through the catalog
    # (the single write authority); version identity returned to the caller.
    version_identity = None
    run_id_out = None
    if grid is not None and context.catalog is not None:
        # V2: the project's real artifacts tree, not a hardcoded demo name.
        artifact_dir = _artifact_root(context) / "intermediate"
        artifact_path = artifact_dir / f"{document_id}.npz"
        # #1174: containment after resolution — the slug whitelist above is
        # the primary defense; this guard fail-closes the action (outside the
        # best-effort provenance try) if a path ever escapes anyway.
        try:
            artifact_path.resolve().relative_to(artifact_dir.resolve())
        except ValueError:
            raise PermissionError(
                f"factor-map artifact path {artifact_path} escapes the workspace "
                f"artifacts directory ({artifact_dir})"
            ) from None
        try:
            import numpy as np

            artifact_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                artifact_path,
                grid_z=grid.grid_z,
                grid_x=grid.grid_x,
                grid_y=grid.grid_y,
            )
            run = context.catalog.begin_run(
                operation="factor_map.interpolate",
                input_version_ids=[],
                parameters={
                    "factor_name": parameters["factor_name"],
                    "method": parameters.get("method", "kriging"),
                    "grid_n": int(parameters.get("grid_n", 50)),
                },
                generator_version="geological-mapping-service",
            )
            try:
                version = context.catalog.register_intermediate(
                    run_id=run.run_id,
                    name=f"{parameters['factor_name']} grid",
                    path=str(artifact_path),
                    kind="factor_grid",
                    format="npz",
                )
                context.catalog.complete_run(run.run_id, status="complete")
                version_identity = getattr(version, "version_id", None)
                run_id_out = run.run_id
            except Exception:
                # Never leave a forever-running DataRun behind.
                try:
                    context.catalog.complete_run(run.run_id, status="failed")
                except Exception:
                    pass
                raise
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "factor-map provenance registration failed (map document kept)"
            )

    return {
        "map_document": document,
        "document_id": document_id,
        "task_id": getattr(task, "id", None),
        "version_id": version_identity,
        "run_id": run_id_out,
        "layers": [
            {"name": getattr(l, "name", ""), "type": getattr(l, "layer_type", ""), "visible": getattr(l, "visible", True)}
            for l in document.layers
        ],
        "extent": list(document.extent) if document.extent else None,
        "values": [grid] if grid is not None else [],
        "layer_count": len(document.layers),
        "verification": verification.to_dict(),
    }


def _create_well_location_map(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.mapping.layers import MapDocument, WellPointMapLayer

    wells = [
        w
        for w in context.project.wells
        if (w.project_x is not None or w.surface_x is not None)
    ]
    if not wells:
        raise LookupError("project has no wells with coordinates")
    layer = WellPointMapLayer(name="井位")
    features = []
    for well in wells:
        x = well.project_x if well.project_x is not None else well.surface_x
        y = well.project_y if well.project_y is not None else well.surface_y
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(x), float(y)]},
            "properties": {"name": well.name, "well_id": well.id},
        }
        features.append(feature)
    layer.features = features
    if parameters.get("label_wells", True):
        from paleo_workbench.mapping.map_styles import TextStyle, VectorStyle

        layer.style = VectorStyle(
            marker_size=8.0,
            labels=TextStyle(field="name", size=9.0),
        ).to_dict()
    document = MapDocument(title=parameters.get("title") or "井位图")
    document.add_layer(layer)
    document.recompute_extent()
    document_id = f"wells-{uuid.uuid4().hex[:6]}"
    _publish(context, document, document_id)
    return {
        "map_document": document,
        "document_id": document_id,
        "well_count": len(features),
        "extent": list(document.extent) if document.extent else None,
        "layers": [{"name": "井位", "type": "well_point", "visible": True}],
    }


def _add_layer(context: ActionContext, parameters: dict) -> dict:
    document = _current_document(context)
    layer_type = parameters["layer_type"]
    if layer_type == "annotation":
        from paleo_workbench.mapping.layers import AnnotationMapLayer

        layer = AnnotationMapLayer(name=parameters.get("name", "注释"))
        layer.text = parameters.get("text", "")
        if parameters.get("text"):
            layer.annotations = [{"text": parameters["text"], "x": 0.0, "y": 0.0}]
        document.add_layer(layer)
    elif layer_type == "polygon":
        from paleo_workbench.mapping.layers import PolygonMapLayer

        layer = PolygonMapLayer(name=parameters.get("name", "多边形"))
        layer.features = list(parameters.get("features") or [])
        document.add_layer(layer)
    else:
        raise ValueError(f"unsupported layer_type {layer_type!r}")
    return {
        "document_id": context.current_map_id,
        "layer_count": len(document.layers),
        "added": layer_type,
    }


def _set_style(context: ActionContext, parameters: dict) -> dict:
    document = _current_document(context)
    target = None
    if parameters.get("layer_name"):
        target = document.get_layer(parameters["layer_name"])
        if target is None:
            raise LookupError(f"layer {parameters['layer_name']!r} not found")
    from paleo_workbench.mapping.map_styles import TextStyle, default_style_for

    style_dict = dict(getattr(target, "style", None) or default_style_for("vector").to_dict())
    for key in ("fill", "stroke"):
        if parameters.get(key):
            style_dict[key] = parameters[key]
    if parameters.get("stroke_width"):
        style_dict["stroke_width"] = float(parameters["stroke_width"])
    if parameters.get("label_field"):
        labels = dict(style_dict.get("labels") or {})
        labels["field"] = parameters["label_field"]
        style_dict["labels"] = labels
    if target is not None:
        target.style = style_dict
        target.bump_style_revision()
    return {"layer": parameters.get("layer_name"), "style": style_dict}


def _apply_template(context: ActionContext, parameters: dict) -> dict:
    """Apply a named composition template to the current map document."""
    document = _current_document(context)
    template = parameters.get("template", "standard")
    title = parameters.get("title") or getattr(document, "title", "") or "地质图件"
    from paleo_workbench.mapping.composer.models import (
        ComposerElement,
        ElementType,
        MapCompositionDocument,
    )

    document_id = context.current_map_id or ""
    composition = MapCompositionDocument(id=f"composition-{document_id[:12]}", title=title)
    composition.add_element(
        ComposerElement(
            id="main-map", element_type=ElementType.MAIN_MAP,
            x_mm=10.0, y_mm=10.0, width_mm=200.0, height_mm=150.0, z_index=-1,
            properties={"frame": "neatline"},
        )
    )
    if template == "standard":
        layout = [
            ("legend", ElementType.LEGEND, 5.0, 165.0, {"binding": "layers"}),
            ("scale-bar", ElementType.SCALE_BAR, 120.0, 165.0, {"units": "km"}),
            ("north-arrow", ElementType.NORTH_ARROW, 265.0, 15.0, {}),
            ("title", ElementType.TITLE, 10.0, 3.0, {"text": title}),
        ]
        for elem_id, element_type, x, y, props in layout:
            composition.add_element(
                ComposerElement(
                    id=elem_id, element_type=element_type,
                    x_mm=x, y_mm=y, width_mm=60.0, height_mm=28.0,
                    properties=props,
                )
            )
    elif template == "minimal":
        composition.add_element(
            ComposerElement(
                id="title", element_type=ElementType.TITLE,
                x_mm=10.0, y_mm=3.0, width_mm=120.0, height_mm=20.0,
                properties={"text": title},
            )
        )
    else:
        raise ValueError(f"unknown template {template!r}")
    context.compositions[document_id] = composition
    document.title = title
    return {
        "document_id": document_id,
        "template": template,
        "components": [str(e.element_type).split(".")[-1].lower() for e in composition.elements],
    }


def _add_component(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.mapping.composer.models import (
        ComposerElement,
        ElementType,
        MapCompositionDocument,
    )

    document = _current_document(context)
    document_id = context.current_map_id or ""
    composition = context.compositions.get(document_id)
    if composition is None:
        composition = MapCompositionDocument(
            id=f"composition-{document_id[:12]}",
            title=getattr(document, "title", "") or "地质图件",
        )
        # A composition always contains the map itself: seed the main map
        # frame so the document is layout-complete from the first component.
        composition.add_element(
            ComposerElement(
                id="main-map",
                element_type=ElementType.MAIN_MAP,
                x_mm=10.0,
                y_mm=10.0,
                width_mm=200.0,
                height_mm=150.0,
                z_index=-1,
                properties={"frame": "neatline"},
            )
        )
    component = parameters["component"]
    element_map = {
        "legend": (ElementType.LEGEND, {"binding": "layers"}),
        "colorbar": (ElementType.LEGEND, {"binding": "grid_ramp", "variant": "colorbar"}),
        "scale_bar": (ElementType.SCALE_BAR, {"units": "km"}),
        "north_arrow": (ElementType.NORTH_ARROW, {}),
        "title": (ElementType.TITLE, {"text": parameters.get("text") or composition.title}),
        "map_frame": (ElementType.MAIN_MAP, {"frame": "neatline"}),
    }
    element_type, props = element_map[component]
    existing_types = {str(e.element_type).split(".")[-1].lower() for e in composition.elements}
    wanted = {"legend": "legend", "scale_bar": "scale_bar", "north_arrow": "north_arrow", "title": "title", "map_frame": "main_map", "colorbar": "legend"}[component]
    if wanted == "legend" and "legend" in existing_types and component == "legend":
        # keep one legend; colorbar variant may coexist
        pass
    composition.add_element(
        ComposerElement(
            id=f"{component}-{len(composition.elements) + 1}",
            element_type=element_type,
            x_mm=5.0,
            y_mm=5.0 + 12.0 * len(composition.elements),
            width_mm=60.0,
            height_mm=30.0,
            properties=props,
        )
    )
    context.compositions[document_id] = composition
    return {
        "document_id": document_id,
        "components": [str(e.element_type).split(".")[-1].lower() for e in composition.elements],
        "added": component,
        "composition": composition,
    }


def _validate(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.harness.validation import MapValidationHook

    document = _current_document(context)
    composition = context.compositions.get(context.current_map_id or "")
    report = MapValidationHook().validate(
        document, composition, require_components=bool(parameters.get("require_components", True))
    )
    return {"verification": report.to_dict(), "report": report.to_dict(), "passed": report.passed}


def _safe_filename_segment(raw: str) -> str:
    """#1174: sanitize an agent-supplied name for use as ONE path segment.

    Keeps CJK/word characters and dashes; everything else becomes "_".
    The result never contains separators, "..", or drive syntax, so it
    cannot escape its directory even before containment checks.
    """
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", str(raw), flags=re.UNICODE)
    cleaned = cleaned.strip("._")[:64] or "factor"
    return cleaned


def _resolve_export_path(context: ActionContext, raw: str) -> str:
    """Constrain agent-chosen export paths to the workspace.

    V3: delegates to the provider SDK's single containment implementation
    (:func:`paleo_workbench.providers.paths.resolve_contained_output`,
    #1177) so harness and provider paths cannot drift apart — absolute
    paths must live under the project root, relative paths resolve against
    it, and existing files are refused (no agent-triggered overwrite;
    overwriting is a destructive action the registry does not install).
    Failures surface as ``PermissionError`` (harness action semantics).
    """
    from paleo_workbench.providers import ProviderContext
    from paleo_workbench.providers.errors import ProviderExecutionError
    from paleo_workbench.providers.paths import resolve_contained_output

    root = Path(context.project_path).parent if context.project_path else Path.cwd()
    try:
        resolved = resolve_contained_output(
            ProviderContext(workspace_root=str(root)),
            raw,
            provider_id="harness.map.export",
        )
    except ProviderExecutionError as exc:
        raise PermissionError(str(exc)) from exc
    return str(resolved)


def _export(context: ActionContext, parameters: dict) -> dict:
    document = _current_document(context)
    if not parameters.get("skip_validation", False):
        from paleo_workbench.harness.validation import MapValidationHook

        report = MapValidationHook().validate(
            document,
            context.compositions.get(context.current_map_id or ""),
            require_components=True,
        )
        if not report.passed:
            # FAIL cannot claim completion (ADR 0066): surface as a failed
            # action with the verification reasons, never a success-shaped
            # refusal.
            raise ValueError(
                "map failed validation; fix before export: " + "; ".join(report.reasons)
            )
    from paleo_workbench.providers import execute_provider, get_provider_registry

    provider_context = context.provider_context()
    export_parameters = {"output_path": _resolve_export_path(context, parameters["output_path"])}
    for key in ("width", "height", "dpi"):
        if parameters.get(key) is not None:
            export_parameters[key] = parameters[key]
    # MapDocument is a declared typed input of the exporter provider — the
    # live document travels as a typed object, never an anonymous dict.
    result = execute_provider(
        get_provider_registry().get("export.map_product"),
        inputs={"document": document},
        parameters=export_parameters,
        context=provider_context,
    )
    artifacts = result.to_dict()["artifacts"]
    return {
        "exported": bool(artifacts),
        "artifacts": artifacts,
        "provenance": result.provenance,
        "metrics": result.metrics,
    }

def _describe_map(context: ActionContext, parameters: dict) -> dict:
    document = _current_document(context)
    return {
        "document_id": getattr(document, "id", None),
        "title": getattr(document, "title", ""),
        "crs": getattr(document, "crs", None),
        "extent": list(getattr(document, "extent", ()) or ()),
        "layers": [getattr(l, "name", "") for l in getattr(document, "layers", [])],
        "layer_count": len(getattr(document, "layers", []) or []),
    }


def _map_qc(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.harness.validation import MapValidationHook

    document = _current_document(context)
    composition = context.compositions.get(context.current_map_id or "")
    report = MapValidationHook().validate(
        document,
        composition,
        require_components=bool(parameters.get("require_components", True)),
    )
    return {
        "verdict": report.verdict,
        "passed": report.passed,
        "reasons": list(report.reasons),
        "document_id": getattr(document, "id", None),
    }


def _map_contour(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.contour_draft import (
        contour_draft_from_factor_task,
        upsert_contour_draft,
    )

    project = context.require("project")
    tasks = getattr(project, "factor_map_tasks", []) or []
    task_id = parameters.get("task_id")
    task = None
    if task_id:
        task = next((t for t in tasks if getattr(t, "id", "") == task_id), None)
        if task is None:
            raise LookupError(f"no factor task {task_id!r} in project")
    elif tasks:
        task = tasks[-1]  # most recent interpolated factor task
    if task is None:
        raise LookupError(
            "no factor map task in project — run map.create_factor_map first"
        )
    draft = contour_draft_from_factor_task(
        task,
        n_levels=int(parameters.get("n_levels", 10)),
        cancellation_token=context.cancel,
    )
    upsert_contour_draft(project, draft)
    return {
        "draft_id": getattr(draft, "id", None),
        "name": draft.name,
        "levels": draft.levels,
        "segment_count": len(getattr(draft, "segments", []) or []),
        "linked_task_id": draft.linked_factor_task_id,
    }


def _describe_layer(context: ActionContext, parameters: dict) -> dict:
    document = _current_document(context)
    layers = getattr(document, "layers", []) or []
    wanted = parameters.get("layer_name")
    layer = None
    if wanted:
        layer = next(
            (l for l in layers if getattr(l, "name", "") == wanted), None
        )
        if layer is None:
            raise LookupError(f"document has no layer {wanted!r}")
    elif layers:
        layer = layers[-1]
    if layer is None:
        raise LookupError("document has no layers")
    return {
        "name": getattr(layer, "name", ""),
        "layer_type": getattr(layer, "layer_type", ""),
        "visible": getattr(layer, "visible", None),
        "feature_count": len(getattr(layer, "features", ()) or ()),
        "style": getattr(layer, "style", None),
    }
