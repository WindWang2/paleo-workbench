"""GDAL/OGR vector interchange adapter (Shapefile / GeoPackage / ...).

Pure re-export of the vendored GDAL capability behind an interchange face:
multi-layer inspection (not just layer 0), sidecar completeness for
Shapefile, field-name truncation and mixed-geometry diagnostics. Managed copy
of sidecar families stages a deterministic zip bundle so a shapefile keeps
its .shx/.dbf/.prj/.cpg — importing a lone .shp would be silent data loss.
When GDAL is unavailable the adapter declares itself unusable (fail-closed)
instead of pretending.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path

from paleo_workbench.interchange.contracts import (
    CancelToken,
    ExportVerification,
    FormatCapability,
    FormatNotSupportedError,
    ImportExecutionResult,
    ImportPlan,
    InspectionResult,
    NULL_CANCEL,
    VerificationCheck,
    VerificationState,
)
from paleo_workbench.interchange.registry import FormatAdapter, SNIFF_PREFIX_BYTES

_SHAPEFILE_SIDECARS = (".shx", ".dbf")
_SHAPEFILE_OPTIONAL = (".prj", ".cpg", ".sbn", ".sbk", ".qix")


def gdal_available() -> bool:
    try:
        from osgeo import gdal  # noqa: F401
        from osgeo import ogr  # noqa: F401
    except Exception:
        return False
    return True


class VectorAdapter(FormatAdapter):
    format_id = "vector_gdal"
    display_name = "GIS 矢量（GDAL）"
    extensions = ("shp", "gpkg", "kml", "gml", "geojson", "tab", "mif")
    resource_type = "vector"

    def capability(self) -> FormatCapability:
        if not gdal_available():
            return FormatCapability(
                read=False,
                inspect=False,
                import_data=False,
                export=False,
                notes="GDAL (osgeo) 不可用：vendored 构建未安装（ADR 0060）",
            )
        return FormatCapability(
            read=True,
            inspect=True,
            import_data=True,
            export=False,  # no OGR write path in this repo; GeoJSON export lives in GeoJSONAdapter
            roundtrip_verify=False,
            notes="管理拷贝对 Shapefile 打包 sidecar；导出能力由 GeoJSON 适配器承担",
        )

    def inspect(self, path: Path) -> InspectionResult:
        path = Path(path)
        result = InspectionResult(format_id=self.format_id, object_type="vector_layer")
        try:
            result.size_bytes = path.stat().st_size
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件状态: {exc}")
            return result
        if not gdal_available():
            result.ok = False
            result.errors.append("GDAL (osgeo) 不可用，无法检查矢量数据")
            return result

        # Sidecar completeness first: a shapefile without .shx/.dbf fails in
        # GDAL with a confusing low-level message; report the actionable cause.
        if path.suffix.lower() == ".shp":
            self._check_shapefile_sidecars(path, result)
            if not result.ok:
                return result

        from osgeo import gdal, ogr

        try:
            dataset = gdal.OpenEx(
                str(path),
                gdal.OF_READONLY | gdal.OF_VECTOR | gdal.OF_VERBOSE_ERROR,
            )
        except Exception as exc:
            result.ok = False
            result.errors.append(f"GDAL 打开失败（文件可能损坏或格式不符）: {exc}")
            return result
        if dataset is None:
            result.ok = False
            result.errors.append("GDAL 无法识别为矢量数据源")
            return result

        try:
            layers: list[dict] = []
            for index in range(dataset.GetLayerCount()):
                layer = dataset.GetLayerByIndex(index)
                if layer is None:
                    continue
                definition = layer.GetLayerDefn()
                fields = []
                truncated_fields: list[str] = []
                for i in range(definition.GetFieldCount()):
                    field_def = definition.GetFieldDefn(i)
                    name = field_def.GetName()
                    fields.append({"name": name, "type": field_def.GetTypeName()})
                    if path.suffix.lower() == ".shp" and len(name.encode("utf-8", "replace")) > 10:
                        truncated_fields.append(name)
                geometry = layer.GetSpatialRef()
                crs = None
                if geometry is not None:
                    authority = geometry.GetAuthorityCode(None)
                    crs = f"EPSG:{authority}" if authority else geometry.GetName()
                if crs is None:
                    result.warnings.append(f"图层 {layer.GetName()} 缺少 CRS")
                geometry_types = self._layer_geometry_types(layer)
                if len(geometry_types) > 1:
                    result.warnings.append(
                        f"图层 {layer.GetName()} 混合几何类型: {', '.join(sorted(geometry_types))}"
                    )
                invalid = self._count_invalid_geometries(layer)
                if invalid:
                    result.warnings.append(f"图层 {layer.GetName()} 含 {invalid} 个无效几何")
                if truncated_fields:
                    result.warnings.append(
                        f"字段名超过 Shapefile 10 字节限制（可能被截断）: {', '.join(truncated_fields)}"
                    )
                layers.append(
                    {
                        "name": layer.GetName(),
                        "feature_count": layer.GetFeatureCount(),
                        "extent": list(layer.GetExtent()) if layer.GetExtent() else None,
                        "crs": crs,
                        "fields": fields,
                        "geometry_types": sorted(geometry_types),
                    }
                )
            result.metadata = {
                "driver": dataset.GetDriver().ShortName if dataset.GetDriver() else "",
                "layers": layers,
            }
            if layers:
                result.crs = layers[0].get("crs")
                extent = layers[0].get("extent")
                if extent and all(
                    isinstance(v, (int, float)) and math.isfinite(float(v)) for v in extent
                ):
                    result.dataset_bounds = tuple(float(v) for v in extent)
        finally:
            dataset = None

        return result

    @staticmethod
    def _layer_geometry_types(layer) -> set[str]:
        types: set[str] = set()
        layer.ResetReading()
        for _ in range(4096):
            feature = layer.GetNextFeature()
            if feature is None:
                break
            geometry = feature.GetGeometryRef()
            if geometry is not None:
                types.add(geometry.GetGeometryName())
        layer.ResetReading()
        return types

    @staticmethod
    def _count_invalid_geometries(layer) -> int:
        layer.ResetReading()
        invalid = 0
        for _ in range(4096):
            feature = layer.GetNextFeature()
            if feature is None:
                break
            geometry = feature.GetGeometryRef()
            if geometry is not None and not geometry.IsValid():
                invalid += 1
        layer.ResetReading()
        return invalid

    @staticmethod
    def _check_shapefile_sidecars(path: Path, result: InspectionResult) -> None:
        stem = path.with_suffix("")
        missing = [suffix for suffix in _SHAPEFILE_SIDECARS if not Path(f"{stem}{suffix}").exists()]
        if missing:
            result.warnings.append(
                "Shapefile 缺少必需 sidecar: " + ", ".join(missing) + "（导入被拒绝，避免数据不完整）"
            )
            result.errors.append("Shapefile sidecar 不完整")
            result.ok = False
        optional_missing = [
            suffix for suffix in _SHAPEFILE_OPTIONAL if not Path(f"{stem}{suffix}").exists()
        ]
        if ".prj" in optional_missing:
            result.warnings.append("缺少 .prj（无投影定义）")

    def plan_import(self, path, inspection, *, managed=True, asset_name=None, options=None):
        plan = super().plan_import(
            path, inspection, managed=managed, asset_name=asset_name, options=options
        )
        plan.metadata.setdefault("object_type", self.resource_type)
        if Path(path).suffix.lower() == ".shp" and managed and inspection.ok:
            plan.action = "transform_import"
            plan.transform = "shapefile_sidecar_bundle"
            plan.warnings.append("Shapefile 管理拷贝将打包全部 sidecar（zip bundle）")
        return plan

    def import_data(self, path, plan, *, work_dir, catalog, cancel=None, progress=None) -> ImportExecutionResult:
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        source = Path(path)
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        staged: Path | None = None
        if plan.action == "transform_import" and plan.transform == "shapefile_sidecar_bundle":
            staged = work_dir / f"{source.stem}.shp_bundle.zip"
            self._stage_sidecar_bundle(source, staged)
            version = catalog.import_raw(
                staged,
                name=plan.asset_name,
                type=self.resource_type,
                format="shp_bundle",
                metadata={**plan.metadata, "bundled_from": str(source.name)},
            )
        else:
            version = catalog.import_raw(
                source,
                name=plan.asset_name,
                type=self.resource_type,
                format=self.format_id,
                metadata=plan.metadata,
            )
        if staged is not None:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
        return ImportExecutionResult(version_id=version.id, asset_id=version.asset_id, managed=True)

    @staticmethod
    def _stage_sidecar_bundle(source: Path, target: Path) -> None:
        stem = source.with_suffix("")
        members = [source]
        for suffix in _SHAPEFILE_SIDECARS + _SHAPEFILE_OPTIONAL:
            candidate = Path(f"{stem}{suffix}")
            if candidate.exists():
                members.append(candidate)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as bundle:
            for member in members:
                bundle.write(member, arcname=member.name)

    def verify_output(self, target_path, plan) -> ExportVerification:
        target_path = Path(target_path)
        checks: list[VerificationCheck] = []
        if not target_path.is_file():
            return ExportVerification(VerificationState.FAILED, checks, detail="输出不存在")
        return ExportVerification.unverified("vector_gdal 无导出路径；verify 仅存在性检查无意义")

    # export capability declared False; plan/export raise the default
    # FormatNotSupportedError from FormatAdapter.
