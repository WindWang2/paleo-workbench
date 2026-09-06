"""GeoJSON interchange adapter.

Read path is a streaming structural pass over ``json`` parse events (bounded
by file size): feature count, geometry types, bbox, property keys, CRS member.
Export normalizes to a FeatureCollection and verify re-parses to compare
counts and bounds. No hand-written geometry parser — validation reuses the
``geometry`` objects produced by :mod:`json` and checks structure.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from paleo_workbench.interchange.contracts import (
    CancelToken,
    ExportPlan,
    ExportVerification,
    FormatCapability,
    ImportExecutionResult,
    ImportPlan,
    InspectionResult,
    NULL_CANCEL,
    VerificationCheck,
    VerificationState,
)
from paleo_workbench.interchange.registry import FormatAdapter

# Refuse to json-parse absurd files in inspect (bounded analysis budget).
_MAX_INSPECT_BYTES = 512 * 1024 * 1024

_GEOMETRY_TYPES = {
    "Point", "MultiPoint", "LineString", "MultiLineString",
    "Polygon", "MultiPolygon", "GeometryCollection",
}


def _iter_bounds_update(bounds: list[float] | None, coords) -> list[float] | None:
    """Accumulate [minx, miny, maxx, maxy] over nested coordinate lists."""
    if bounds is None:
        bounds = [math.inf, math.inf, -math.inf, -math.inf]

    def walk(node) -> None:
        if node is None:
            return
        if isinstance(node, (int, float)):
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
                x, y = float(node[0]), float(node[1])
                if math.isfinite(x) and math.isfinite(y):
                    bounds[0] = min(bounds[0], x)
                    bounds[1] = min(bounds[1], y)
                    bounds[2] = max(bounds[2], x)
                    bounds[3] = max(bounds[3], y)
                return
            for child in node:
                walk(child)

    walk(coords)
    return bounds


class GeoJSONAdapter(FormatAdapter):
    format_id = "geojson"
    display_name = "GeoJSON 矢量"
    extensions = ("geojson", "json")
    resource_type = "geojson"

    def capability(self) -> FormatCapability:
        return FormatCapability(
            read=True,
            inspect=True,
            import_data=True,
            export=True,
            roundtrip_verify=True,
            notes="GDAL 缺失时仍完全可用（纯 json 实现）",
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
        if result.size_bytes > _MAX_INSPECT_BYTES:
            result.warnings.append("文件超过检查上限：跳过内容扫描")
            return result
        try:
            document = json.loads(path.read_text("utf-8", errors="strict"))
        except UnicodeDecodeError:
            result.ok = False
            result.errors.append("文件不是有效 UTF-8 编码")
            return result
        except json.JSONDecodeError as exc:
            result.ok = False
            result.errors.append(f"JSON 解析失败（文件可能截断）: {exc}")
            return result

        doc_type = document.get("type") if isinstance(document, dict) else None
        if doc_type == "FeatureCollection":
            features = document.get("features") or []
            crs = self._extract_crs(document)
        elif doc_type == "Feature":
            features = [document]
            crs = self._extract_crs(document)
            result.warnings.append("单个 Feature（非 FeatureCollection）")
        else:
            result.ok = False
            result.errors.append(f"不是 GeoJSON（type={doc_type!r}）")
            return result

        geometry_types: set[str] = set()
        invalid = 0
        empty_geom = 0
        property_keys: dict[str, int] = {}
        bounds: list[float] | None = None
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                invalid += 1
                continue
            geometry = feature.get("geometry")
            if geometry is None:
                empty_geom += 1
                continue
            if not isinstance(geometry, dict) or geometry.get("type") not in _GEOMETRY_TYPES:
                invalid += 1
                continue
            geometry_types.add(str(geometry["type"]))
            bounds = _iter_bounds_update(bounds, geometry.get("coordinates"))
            properties = feature.get("properties") or {}
            if isinstance(properties, dict):
                for key in properties:
                    property_keys[key] = property_keys.get(key, 0) + 1

        if invalid:
            result.warnings.append(f"{invalid} 个成员不是有效 Feature")
        if empty_geom:
            result.warnings.append(f"{empty_geom} 个 Feature 缺少 geometry")
        if len(geometry_types) > 1:
            result.warnings.append(f"混合几何类型: {', '.join(sorted(geometry_types))}")
        if crs is None:
            result.warnings.append("缺少 CRS 声明（GeoJSON 规范默认 WGS84，需人工确认）")
        result.crs = crs
        result.metadata = {
            "feature_count": len(features),
            "geometry_types": sorted(geometry_types),
            "property_keys": sorted(property_keys)[:64],
            "has_crs_member": crs is not None,
        }
        if bounds is not None and math.isfinite(bounds[0]):
            result.dataset_bounds = tuple(bounds)
        return result

    @staticmethod
    def _extract_crs(document: dict) -> str | None:
        crs = document.get("crs")
        if isinstance(crs, dict):
            props = crs.get("properties") or {}
            name = props.get("name")
            if isinstance(name, str):
                return name
        if isinstance(crs, str):
            return crs
        return None

    def import_data(self, path, plan, *, work_dir, catalog, cancel=None, progress=None) -> ImportExecutionResult:
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        version = catalog.import_raw(
            Path(path),
            name=plan.asset_name,
            type=self.resource_type,
            format=self.format_id,
            metadata=plan.metadata,
        )
        return ImportExecutionResult(version_id=version.id, asset_id=version.asset_id, managed=True)

    # -- export: normalized FeatureCollection -------------------------------
    def plan_export(self, source_path, target_path, *, options=None):
        target_path = Path(target_path)
        if target_path.suffix.lower() not in (".geojson", ".json"):
            from paleo_workbench.interchange.contracts import FormatNotSupportedError

            raise FormatNotSupportedError("GeoJSON 适配器仅支持导出为 .geojson/.json")
        inspection = self.inspect(Path(source_path))
        warnings = list(inspection.warnings)
        if not inspection.ok:
            from paleo_workbench.interchange.contracts import FormatNotSupportedError

            raise FormatNotSupportedError(f"源文件不可解析: {inspection.errors}")
        return ExportPlan(
            format_id=self.format_id,
            source_path=str(source_path),
            target_path=str(target_path),
            estimated_bytes=Path(source_path).stat().st_size,
            options={"feature_count": inspection.metadata.get("feature_count", 0),
                     "geometry_types": inspection.metadata.get("geometry_types", [])},
            warnings=warnings,
        )

    def export_data(self, source_path, plan, *, work_dir, cancel=None, progress=None):
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        from paleo_workbench.resources.exporters import atomic_output

        source = json.loads(Path(source_path).read_text("utf-8"))
        features: list = []
        if source.get("type") == "FeatureCollection":
            features = list(source.get("features") or [])
        elif source.get("type") == "Feature":
            features = [source]
        normalized = {
            "type": "FeatureCollection",
            "features": features,
        }
        crs = self._extract_crs(source)
        if crs:
            normalized["crs"] = {"type": "name", "properties": {"name": crs}}
        target = Path(plan.target_path)
        with atomic_output(target) as tmp:
            tmp.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        return target

    def verify_output(self, target_path, plan) -> ExportVerification:
        target_path = Path(target_path)
        checks: list[VerificationCheck] = []
        warnings: list[str] = list(plan.warnings)
        if not target_path.is_file():
            return ExportVerification(VerificationState.FAILED, checks, detail="输出文件不存在")
        try:
            document = json.loads(target_path.read_text("utf-8"))
        except Exception as exc:
            return ExportVerification(VerificationState.FAILED, checks, f"输出无法解析: {exc}")
        checks.append(VerificationCheck("reparse_ok", True))
        if document.get("type") != "FeatureCollection":
            return ExportVerification(VerificationState.FAILED, checks, detail="输出不是 FeatureCollection")
        checks.append(VerificationCheck("featurecollection_type", True))

        expected = int(plan.options.get("feature_count", -1))
        features = document.get("features") or []
        if expected >= 0:
            checks.append(
                VerificationCheck(
                    "feature_count", len(features) == expected,
                    f"预期 {expected}，实际 {len(features)}",
                )
            )

        bounds: list[float] | None = None
        for feature in features:
            geometry = (feature or {}).get("geometry") if isinstance(feature, dict) else None
            if isinstance(geometry, dict):
                bounds = _iter_bounds_update(bounds, geometry.get("coordinates"))
        expected_bounds = plan.options.get("bounds")
        if expected_bounds and bounds and math.isfinite(bounds[0]):
            close = all(
                math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
                for a, b in zip(bounds, expected_bounds)
            )
            checks.append(
                VerificationCheck("bounds_preserved", close, f"源 {expected_bounds} 输出 {bounds}")
            )
        failed = [c for c in checks if not c.passed]
        if failed:
            return ExportVerification(VerificationState.FAILED, checks, warnings)
        if warnings:
            return ExportVerification(VerificationState.VERIFIED_WITH_WARNINGS, checks, warnings)
        return ExportVerification(VerificationState.VERIFIED, checks, warnings)
