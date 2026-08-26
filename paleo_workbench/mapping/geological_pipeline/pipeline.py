"""Geological Mapping Pipeline: End-to-end orchestration from Well Data to MapDocument and Composer."""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from paleo_workbench.mapping.color_ramps import get_color_ramp
from paleo_workbench.mapping.composer.models import MapCompositionDocument
from paleo_workbench.mapping.geological_pipeline.contouring import generate_contour_layer
from paleo_workbench.mapping.geological_pipeline.interpolator import (
    IDWInterpolator,
    Interpolator,
    KrigingInterpolator,
    interpolate_factor,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import generate_facies_polygon_layer
from paleo_workbench.mapping.geological_pipeline.templates import create_geological_factor_map_template
from paleo_workbench.mapping.layers import (
    ContourMapLayer,
    GridMapLayer,
    MapDocument,
    MapLayer,
    PolygonMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.map_styles import (
    MarkerSymbol,
    TextStyle,
    VectorStyle,
    default_style_for,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


# Factor property defaults (units and recommended color ramps)
FACTOR_DEFAULTS = {
    "孔隙度": {"unit": "%", "color_ramp": "porosity"},
    "porosity": {"unit": "%", "color_ramp": "porosity"},
    "POR": {"unit": "%", "color_ramp": "porosity"},
    "PORO": {"unit": "%", "color_ramp": "porosity"},
    "PHIE": {"unit": "%", "color_ramp": "porosity"},
    "PHIT": {"unit": "%", "color_ramp": "porosity"},
    "渗透率": {"unit": "mD", "color_ramp": "permeability"},
    "permeability": {"unit": "mD", "color_ramp": "permeability"},
    "PERM": {"unit": "mD", "color_ramp": "permeability"},
    "PERMEABILITY": {"unit": "mD", "color_ramp": "permeability"},
    "K": {"unit": "mD", "color_ramp": "permeability"},
    "有效厚度": {"unit": "m", "color_ramp": "sand_thickness"},
    "net_pay": {"unit": "m", "color_ramp": "sand_thickness"},
    "NET_PAY": {"unit": "m", "color_ramp": "sand_thickness"},
    "净产层厚度": {"unit": "m", "color_ramp": "sand_thickness"},
    "H_pay": {"unit": "m", "color_ramp": "sand_thickness"},
    "H_net": {"unit": "m", "color_ramp": "sand_thickness"},
    "PAY_THICKNESS": {"unit": "m", "color_ramp": "sand_thickness"},
    "地层厚度": {"unit": "m", "color_ramp": "thickness"},
    "formation_thickness": {"unit": "m", "color_ramp": "thickness"},
    "thickness": {"unit": "m", "color_ramp": "thickness"},
    "H_t": {"unit": "m", "color_ramp": "thickness"},
    "TOTAL_THICKNESS": {"unit": "m", "color_ramp": "thickness"},
    "砂岩厚度": {"unit": "m", "color_ramp": "sand_thickness"},
    "sand_thickness": {"unit": "m", "color_ramp": "sand_thickness"},
    "H_s": {"unit": "m", "color_ramp": "sand_thickness"},
    "SAND_THICKNESS": {"unit": "m", "color_ramp": "sand_thickness"},
    "砂地比": {"unit": "%", "color_ramp": "sand_thickness"},
    "sand_ratio": {"unit": "%", "color_ramp": "sand_thickness"},
    "R_s": {"unit": "%", "color_ramp": "sand_thickness"},
    "SAND_RATIO": {"unit": "%", "color_ramp": "sand_thickness"},
    "地层顶界": {"unit": "m", "color_ramp": "elevation"},
    "顶界深度": {"unit": "m", "color_ramp": "elevation"},
    "top_depth": {"unit": "m", "color_ramp": "elevation"},
    "top_md": {"unit": "m", "color_ramp": "elevation"},
    "top_tvd": {"unit": "m", "color_ramp": "elevation"},
    "TOP": {"unit": "m", "color_ramp": "elevation"},
    "TOP_DEPTH": {"unit": "m", "color_ramp": "elevation"},
    "地层底界": {"unit": "m", "color_ramp": "elevation"},
    "底界深度": {"unit": "m", "color_ramp": "elevation"},
    "base_depth": {"unit": "m", "color_ramp": "elevation"},
    "base_md": {"unit": "m", "color_ramp": "elevation"},
    "base_tvd": {"unit": "m", "color_ramp": "elevation"},
    "BASE": {"unit": "m", "color_ramp": "elevation"},
    "BASE_DEPTH": {"unit": "m", "color_ramp": "elevation"},
    "TOC": {"unit": "%", "color_ramp": "toc"},
    "toc": {"unit": "%", "color_ramp": "toc"},
    "古水深": {"unit": "m", "color_ramp": "water_depth"},
    "water_depth": {"unit": "m", "color_ramp": "water_depth"},
}

_FACTOR_ALIAS_GROUPS: dict[str, tuple[str, ...]] = {
    "porosity": ("porosity", "por", "poro", "phie", "phit", "孔隙度"),
    "permeability": ("permeability", "perm", "k", "渗透率"),
    "net_pay": ("net_pay", "h_pay", "h_net", "pay_thickness", "有效厚度", "净产层厚度"),
    "formation_thickness": ("formation_thickness", "thickness", "h_t", "total_thickness", "地层厚度"),
    "sand_thickness": ("sand_thickness", "h_s", "sand", "砂岩厚度"),
    "sand_ratio": ("sand_ratio", "r_s", "砂地比"),
    "top_depth": ("top_depth", "top_md", "top_tvd", "top", "地层顶界", "顶界深度", "tops", "formation_top"),
    "base_depth": ("base_depth", "base_md", "base_tvd", "base", "地层底界", "底界深度", "formation_base"),
    "toc": ("toc",),
    "water_depth": ("water_depth", "古水深"),
}


def _find_matching_aliases(factor_name: str) -> list[str]:
    """Return all known mnemonic and localized aliases for a factor name."""
    norm = factor_name.strip().lower()
    for group_key, aliases in _FACTOR_ALIAS_GROUPS.items():
        if norm == group_key or norm in aliases:
            return list(aliases)
    return [factor_name, norm]


class GeologicalMappingPipeline:
    """End-to-end Geological Mapping Pipeline.

    Transforms:
      Well Data → Factor Extraction → Validation → Spatial Interpolation → Grid
      → Contour (Marching Squares) → Zone Polygonization → GIS Layers
      → MapDocument → Cartographic Layout Composer
    """

    def __init__(self, interpolator: Interpolator | None = None) -> None:
        self.interpolator = interpolator or KrigingInterpolator()

    def extract_factors(
        self,
        records: Iterable[Mapping[str, Any]],
        factor_name: str,
        *,
        target_horizon: str = "",
        unit: str | None = None,
        crs: str = "EPSG:4326",
    ) -> GeologicalFactorDataset:
        """Extract typed GeologicalFactor points from raw well table rows or dictionary records."""
        defaults = FACTOR_DEFAULTS.get(factor_name, FACTOR_DEFAULTS.get(factor_name.lower(), {}))
        resolved_unit = unit if unit is not None else defaults.get("unit", "")
        aliases = _find_matching_aliases(factor_name)

        points: list[GeologicalFactor] = []
        for rec in records:
            if not isinstance(rec, Mapping):
                continue
            # Extract coordinates
            x = rec.get("x") or rec.get("lng") or rec.get("longitude") or rec.get("project_x") or rec.get("surface_x")
            y = rec.get("y") or rec.get("lat") or rec.get("latitude") or rec.get("project_y") or rec.get("surface_y")
            if x is None or y is None:
                coords = rec.get("coordinates")
                if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                    x, y = coords[0], coords[1]

            if x is None or y is None:
                continue

            try:
                fx = float(x)
                fy = float(y)
            except (TypeError, ValueError):
                continue

            # Extract factor value
            val = None
            if factor_name in rec:
                val = rec[factor_name]
            elif "value" in rec:
                val = rec["value"]
            elif "val" in rec:
                val = rec["val"]
            else:
                # Search via aliases in top-level record keys (case-insensitive)
                rec_lower = {str(k).lower(): v for k, v in rec.items()}
                for alias in aliases:
                    if alias.lower() in rec_lower:
                        val = rec_lower[alias.lower()]
                        break

            # Search in attributes or properties dictionaries
            if val is None:
                for sub_dict_key in ("attributes", "properties", "metadata"):
                    sub_dict = rec.get(sub_dict_key)
                    if isinstance(sub_dict, Mapping):
                        if factor_name in sub_dict:
                            val = sub_dict[factor_name]
                            break
                        if "value" in sub_dict:
                            val = sub_dict["value"]
                            break
                        sub_lower = {str(k).lower(): v for k, v in sub_dict.items()}
                        for alias in aliases:
                            if alias.lower() in sub_lower:
                                val = sub_lower[alias.lower()]
                                break
                    if val is not None:
                        break

            # Derived factor calculations
            if val is None:
                norm_factor = factor_name.lower()
                rec_lower = {str(k).lower(): v for k, v in rec.items()}
                if norm_factor in ("砂地比", "sand_ratio", "r_s"):
                    sand_aliases = _find_matching_aliases("sand_thickness")
                    thick_aliases = _find_matching_aliases("formation_thickness")
                    hs = None
                    ht = None
                    for sa in sand_aliases:
                        if sa.lower() in rec_lower:
                            hs = rec_lower[sa.lower()]
                            break
                    for ta in thick_aliases:
                        if ta.lower() in rec_lower:
                            ht = rec_lower[ta.lower()]
                            break
                    if hs is not None and ht is not None:
                        try:
                            f_hs, f_ht = float(hs), float(ht)
                            if f_ht > 0:
                                val = f_hs / f_ht
                        except (TypeError, ValueError):
                            pass
                elif norm_factor in ("地层厚度", "formation_thickness", "thickness", "h_t", "total_thickness"):
                    base_aliases = _find_matching_aliases("base_depth")
                    top_aliases = _find_matching_aliases("top_depth")
                    base = None
                    top = None
                    for ba in base_aliases:
                        if ba.lower() in rec_lower:
                            base = rec_lower[ba.lower()]
                            break
                    for ta in top_aliases:
                        if ta.lower() in rec_lower:
                            top = rec_lower[ta.lower()]
                            break
                    if base is not None and top is not None:
                        try:
                            f_base, f_top = float(base), float(top)
                            if f_base > f_top:
                                val = f_base - f_top
                        except (TypeError, ValueError):
                            pass

            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue

            well_id = str(rec.get("well_id") or rec.get("id") or "")
            well_name = str(rec.get("name") or rec.get("well_name") or rec.get("well") or well_id)
            qc_flag = str(rec.get("qc_flag") or "ok")
            formation = str(rec.get("formation") or rec.get("target_horizon") or target_horizon)

            points.append(
                GeologicalFactor(
                    name=factor_name,
                    value=fval,
                    unit=resolved_unit,
                    well_id=well_id,
                    well_name=well_name,
                    x=fx,
                    y=fy,
                    crs=crs,
                    formation=formation,
                    qc_flag=qc_flag,
                    metadata=dict(rec.get("properties") or {}),
                )
            )

        return GeologicalFactorDataset(
            factor_name=factor_name,
            unit=resolved_unit,
            target_horizon=target_horizon,
            crs=crs,
            points=points,
        )

    def interpolate(
        self,
        dataset: GeologicalFactorDataset,
        options: InterpolationOptions | None = None,
    ) -> FactorGridResult:
        """Run spatial interpolation on the geological factor dataset."""
        opts = options or InterpolationOptions()
        return interpolate_factor(dataset, opts)

    def create_grid_layer(
        self,
        grid_result: FactorGridResult,
        color_ramp: str | None = None,
        opacity: float = 0.85,
        layer_id: str | None = None,
        name: str | None = None,
    ) -> GridMapLayer:
        """Create a standard GIS GridMapLayer from a FactorGridResult."""
        defaults = FACTOR_DEFAULTS.get(grid_result.factor_name, {})
        ramp_name = color_ramp or defaults.get("color_ramp", "viridis")

        return GridMapLayer(
            id=layer_id or f"grid_{grid_result.factor_name}",
            name=name or f"{grid_result.factor_name} 连续分布栅格",
            grid_result=grid_result,
            color_ramp_name=ramp_name,
            opacity=opacity,
            crs=grid_result.crs or "EPSG:4326",
            unit=grid_result.unit or "",
        )

    def create_contour_layer(
        self,
        grid_result: FactorGridResult,
        levels: list[float] | None = None,
        interval: float | None = None,
        layer_id: str | None = None,
        name: str | None = None,
    ) -> ContourMapLayer:
        """Extract and generate a standard GIS ContourMapLayer."""
        return generate_contour_layer(
            grid_result,
            levels=levels,
            interval=interval,
            layer_id=layer_id,
            name=name,
        )

    def create_well_point_layer(
        self,
        dataset: GeologicalFactorDataset,
        layer_id: str | None = None,
        name: str | None = None,
    ) -> WellPointMapLayer:
        """Create a standard GIS WellPointMapLayer from the geological factor dataset."""
        features: list[dict[str, Any]] = []
        for p in dataset.valid_points:
            features.append(
                {
                    "type": "Feature",
                    "id": p.well_id or f"well_{p.well_name}",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [p.x, p.y],
                    },
                    "properties": {
                        "name": p.well_name,
                        "well_id": p.well_id,
                        "value": p.value,
                        "unit": p.unit,
                        "factor": p.name,
                        "formation": p.formation,
                        "qc_flag": p.qc_flag,
                    },
                }
            )

        style = VectorStyle(
            fill="#22b8a7",
            stroke="#182431",
            stroke_width=1.0,
            marker=MarkerSymbol.WELL,
            marker_size=8.0,
            labels=TextStyle(field="name", size=9.0, color="#ffffff", halo_color="#000000", halo_width=1.0),
        ).to_dict()

        return WellPointMapLayer(
            id=layer_id or f"wells_{dataset.factor_name}",
            name=name or f"{dataset.factor_name} 井位与取值",
            extent=dataset.extent,
            crs=dataset.crs,
            features=tuple(features),
            factor_name=dataset.factor_name,
            unit=dataset.unit,
            style=style,
        )

    def create_polygon_layer(
        self,
        grid_result: FactorGridResult,
        thresholds: list[float] | None = None,
        facies_names: list[str] | None = None,
        colors: list[str] | None = None,
        layer_id: str | None = None,
        name: str | None = None,
    ) -> PolygonMapLayer:
        """Classify grid and generate a standard GIS PolygonMapLayer."""
        return generate_facies_polygon_layer(
            grid_result,
            thresholds=thresholds,
            facies_names=facies_names,
            colors=colors,
            layer_id=layer_id,
            name=name,
        )

    def build_factor_map_document(
        self,
        dataset: GeologicalFactorDataset,
        options: InterpolationOptions | None = None,
        *,
        include_grid: bool = True,
        include_contours: bool = True,
        include_wells: bool = True,
        include_polygons: bool = False,
        include_annotations: bool = False,
        annotations: Sequence[Mapping[str, Any]] | None = None,
        title: str | None = None,
        run_id: str | None = None,
        input_version_ids: list[str] | None = None,
    ) -> MapDocument:
        """Execute the end-to-end pipeline and return a multi-layer MapDocument."""
        opts = options or InterpolationOptions()
        grid_result = self.interpolate(dataset, opts)

        effective_run_id = run_id if run_id is not None else grid_result.run_ref
        effective_input_version_ids = (
            list(input_version_ids)
            if input_version_ids is not None
            else list(grid_result.source_refs)
        )
        if run_id is not None and not grid_result.run_ref:
            grid_result.run_ref = run_id
        if input_version_ids is not None and not grid_result.source_refs:
            grid_result.source_refs = list(input_version_ids)

        primary_source_version_id = (
            effective_input_version_ids[0] if effective_input_version_ids else ""
        )

        doc_title = title or f"{dataset.target_horizon} {dataset.factor_name} 分布图"
        doc_metadata: dict[str, Any] = {
            "factor_name": dataset.factor_name,
            "target_horizon": dataset.target_horizon,
            "unit": dataset.unit,
            "algorithm_id": grid_result.algorithm_id,
            "n_samples": len(dataset.valid_points),
        }
        if effective_run_id is not None:
            doc_metadata["run_id"] = effective_run_id
        if effective_input_version_ids:
            doc_metadata["input_version_ids"] = list(effective_input_version_ids)

        map_doc = MapDocument(
            id=f"map_{dataset.factor_name}",
            title=doc_title,
            crs=dataset.crs or opts.crs,
            extent=grid_result.extent,
            metadata=doc_metadata,
        )

        # Layer order (bottom to top):
        # 1. Grid layer (continuous raster)
        if include_grid:
            grid_layer = self.create_grid_layer(grid_result, color_ramp=opts.color_ramp)
            if primary_source_version_id and not grid_layer.source_version_id:
                grid_layer.source_version_id = primary_source_version_id
            map_doc.add_layer(grid_layer)

        # 2. Polygon / Facies zones
        if include_polygons:
            poly_layer = self.create_polygon_layer(grid_result)
            if primary_source_version_id and not poly_layer.source_version_id:
                poly_layer.source_version_id = primary_source_version_id
            map_doc.add_layer(poly_layer)

        # 3. Contour lines
        if include_contours:
            contour_layer = self.create_contour_layer(
                grid_result,
                levels=opts.contour_levels,
                interval=opts.contour_interval,
            )
            if primary_source_version_id and not contour_layer.source_version_id:
                contour_layer.source_version_id = primary_source_version_id
            map_doc.add_layer(contour_layer)

        # 4. Well points (top layer)
        if include_wells:
            well_layer = self.create_well_point_layer(dataset)
            if primary_source_version_id and not well_layer.source_version_id:
                well_layer.source_version_id = primary_source_version_id
            map_doc.add_layer(well_layer)

        # 5. Optional Annotation layer
        if include_annotations or annotations:
            from paleo_workbench.mapping.layers import AnnotationMapLayer
            annos = annotations or ()
            anno_layer = AnnotationMapLayer(
                id=f"annotations_{dataset.factor_name}",
                name=f"{dataset.factor_name} 标注",
                extent=grid_result.extent,
                crs=dataset.crs or opts.crs,
                annotations=tuple(dict(a) for a in annos),
            )
            if primary_source_version_id and not anno_layer.source_version_id:
                anno_layer.source_version_id = primary_source_version_id
            map_doc.add_layer(anno_layer)

        map_doc.recompute_extent()
        return map_doc

    def build_factor_composition(
        self,
        map_doc: MapDocument,
        title: str | None = None,
        paper_size: str = "A4",
        orientation: str = "landscape",
    ) -> MapCompositionDocument:
        """Build standard cartographic composition layout for the MapDocument."""
        factor_name = str(map_doc.metadata.get("factor_name") or "")
        unit = str(map_doc.metadata.get("unit") or "")
        return create_geological_factor_map_template(
            map_doc,
            title=title,
            factor_name=factor_name,
            unit=unit,
            paper_size=paper_size,
            orientation=orientation,
        )


# Global default instance
DEFAULT_GEOLOGICAL_PIPELINE = GeologicalMappingPipeline()
