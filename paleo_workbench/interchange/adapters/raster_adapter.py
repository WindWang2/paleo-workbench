"""Raster / GeoTIFF interchange adapter.

Inspection uses rasterio (a hard dependency) for metadata and a *windowed,
overview-preferring* decimated read for finite/nodata statistics — large
rasters are never loaded whole. Export writes a standardized GeoTIFF through
block-wise windowed IO (dtype/CRS/nodata preserved or explicitly converted)
and verification re-opens the output and compares grid facts.
"""

from __future__ import annotations

import math
from pathlib import Path

from paleo_workbench.interchange.contracts import (
    CancelToken,
    ExportPlan,
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
from paleo_workbench.interchange.registry import FormatAdapter

# Decimated inspection read: at most this many pixels per side.
_INSPECT_MAX_SIDE = 1024
# Refuse inspecting files whose declared uncompressed raster is absurd.
_MAX_INSPECT_PIXELS = 512_000_000


class RasterAdapter(FormatAdapter):
    format_id = "raster"
    display_name = "GeoTIFF / GDAL 栅格"
    extensions = ("tif", "tiff", "img", "grd")
    resource_type = "raster"

    def capability(self) -> FormatCapability:
        return FormatCapability(
            read=True,
            inspect=True,
            import_data=True,
            export=True,
            roundtrip_verify=True,
            notes="导出为标准化 GeoTIFF（窗口 IO）；检查统计走 decimated overview 读取",
        )

    def _open(self, path: Path):
        import rasterio

        return rasterio.open(path)

    def sniff(self, path: Path):
        # TIFF magic lives in the shared sniffer; keep evidence precise here.
        return super().sniff(path)

    def inspect(self, path: Path) -> InspectionResult:
        path = Path(path)
        result = InspectionResult(format_id=self.format_id, object_type="raster")
        try:
            result.size_bytes = path.stat().st_size
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件状态: {exc}")
            return result
        try:
            dataset = self._open(path)
        except Exception as exc:
            result.ok = False
            result.errors.append(f"栅格打开失败（文件可能损坏或格式不符）: {exc}")
            return result

        with dataset:
            crs = dataset.crs
            result.crs = str(crs) if crs else None
            if result.crs is None:
                result.warnings.append("缺少 CRS（栅格无地理参考）")
            transform = dataset.transform
            bounds = dataset.bounds
            result.dataset_bounds = (
                float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)
            )
            nodata = dataset.nodata
            scales = tuple(dataset.scales)
            offsets = tuple(dataset.offsets)
            result.units = {}
            band_units = dataset.units or ()
            for index, unit in enumerate(band_units, start=1):
                if unit:
                    result.units[f"band_{index}"] = str(unit)
            result.metadata = {
                "driver": dataset.driver,
                "width": dataset.width,
                "height": dataset.height,
                "count": dataset.count,
                "dtypes": list(dataset.dtypes),
                "nodata": None if nodata is None else float(nodata),
                "geotransform": list(transform)[:6],
                "scales": [float(s) for s in scales],
                "offsets": [float(o) for o in offsets],
                "colorinterp": [c.name for c in dataset.colorinterp],
                "overviews": bool(dataset.overviews(1)),
                "crs_wkt": crs.to_wkt() if crs else None,
            }
            total_pixels = dataset.width * dataset.height * dataset.count
            if total_pixels > _MAX_INSPECT_PIXELS:
                result.warnings.append("声明像素量超过检查上限：跳过有限值统计")
                return result

            # Decimated, overview-preferring statistics (windowed IO).
            stats = self._decimated_stats(dataset, nodata)
            if stats is not None:
                finite_ratio, nodata_ratio, total = stats
                result.metadata["finite_ratio"] = round(finite_ratio, 6)
                result.metadata["nodata_ratio"] = round(nodata_ratio, 6)
                if finite_ratio <= 0:
                    result.warnings.append("首个波段无有效数据（全部为 nodata/非有限值）")
        return result

    def _decimated_stats(self, dataset, nodata):
        import numpy as np
        import rasterio

        scale = max(1, math.ceil(max(dataset.width, dataset.height) / _INSPECT_MAX_SIDE))
        out_height = max(1, dataset.height // scale)
        out_width = max(1, dataset.width // scale)
        try:
            window = rasterio.windows.Window(0, 0, dataset.width, dataset.height)
            data = dataset.read(
                indexes=1,
                out_shape=(out_height, out_width),
                window=window,
                masked=True,
            )
        except Exception:
            return None
        total = int(data.size)
        if total == 0:
            return None
        mask = np.ma.getmaskarray(data)
        nodata_ratio = float(mask.sum()) / total
        filled = np.ma.compressed(data).astype("float64", copy=False)
        finite = filled[np.isfinite(filled)] if filled.size else filled
        finite_ratio = float(finite.size) / total
        return finite_ratio, nodata_ratio, total

    def plan_import(self, path, inspection, *, managed=True, asset_name=None, options=None):
        plan = super().plan_import(
            path, inspection, managed=managed, asset_name=asset_name, options=options
        )
        plan.metadata.setdefault("object_type", self.resource_type)
        return plan

    def import_data(self, path, plan, *, work_dir, catalog, cancel=None, progress=None) -> ImportExecutionResult:
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        version = catalog.import_raw(
            Path(path),
            name=plan.asset_name,
            type=self.resource_type,
            format=Path(path).suffix.lower().lstrip(".") or self.format_id,
            metadata=plan.metadata,
        )
        return ImportExecutionResult(version_id=version.id, asset_id=version.asset_id, managed=True)

    # -- export: standardized GeoTIFF, block-wise ---------------------------
    def plan_export(self, source_path, target_path, *, options=None):
        target_path = Path(target_path)
        if target_path.suffix.lower() not in (".tif", ".tiff"):
            raise FormatNotSupportedError("栅格适配器仅支持导出为 GeoTIFF (.tif/.tiff)")
        try:
            with self._open(Path(source_path)):
                pass
        except Exception as exc:
            raise FormatNotSupportedError(f"源栅格无法打开: {exc}")
        return ExportPlan(
            format_id=self.format_id,
            source_path=str(source_path),
            target_path=str(target_path),
            options=dict(options or {}),
        )

    def export_data(self, source_path, plan, *, work_dir, cancel=None, progress=None):
        import numpy as np
        import rasterio

        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        from paleo_workbench.resources.exporters import atomic_output

        options = plan.options or {}
        target_dtype = options.get("dtype")  # None = keep source dtype
        target = Path(plan.target_path)
        with rasterio.open(source_path) as src:
            profile = {
                "driver": "GTiff",
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "crs": src.crs,
                "transform": src.transform,
                "nodata": src.nodata,
                "compress": options.get("compress", "deflate"),
                "tiled": src.width > 512 or src.height > 512,
            }
            dtype = target_dtype or src.dtypes[0]
            profile["dtype"] = dtype
            with atomic_output(target) as tmp:
                with rasterio.open(tmp, "w", **profile) as dst:
                    block_win = 1024
                    for band in range(1, src.count + 1):
                        cancel.checkpoint()
                        for row in range(0, src.height, block_win):
                            height = min(block_win, src.height - row)
                            for col in range(0, src.width, block_win):
                                width = min(block_win, src.width - col)
                                window = rasterio.windows.Window(col, row, width, height)
                                data = src.read(band, window=window)
                                if target_dtype and target_dtype != src.dtypes[band - 1]:
                                    info = np.iinfo(target_dtype)
                                    scale = 1.0
                                    data = np.clip(
                                        np.nan_to_num(data.astype("float64"), nan=0.0)
                                        * scale,
                                        info.min,
                                        info.max,
                                    ).astype(target_dtype)
                                dst.write(data, band, window=window)
                        scale_meta = src.scales[band - 1]
                        offset_meta = src.offsets[band - 1]
                        dst.update_tags(
                            band,
                            SCALE=float(scale_meta),
                            OFFSET=float(offset_meta),
                        )
        return target

    def verify_output(self, target_path, plan) -> ExportVerification:
        target_path = Path(target_path)
        checks: list[VerificationCheck] = []
        if not target_path.is_file() or target_path.stat().st_size == 0:
            return ExportVerification(VerificationState.FAILED, checks, "输出缺失或为空")
        try:
            out = self._open(target_path)
        except Exception as exc:
            return ExportVerification(VerificationState.FAILED, checks, f"输出无法重新打开: {exc}")
        try:
            with out:
                with self._open(Path(plan.source_path)) as src:
                    checks.append(VerificationCheck("reopen_ok", True))
                    same_grid = (
                        out.width == src.width
                        and out.height == src.height
                        and out.count == src.count
                    )
                    checks.append(
                        VerificationCheck(
                            "grid_shape", same_grid,
                            f"源 {src.width}x{src.height}x{src.count} 输出 {out.width}x{out.height}x{out.count}",
                        )
                    )
                    if src.crs and out.crs:
                        checks.append(
                            VerificationCheck(
                                "crs_preserved",
                                out.crs.to_epsg() == src.crs.to_epsg()
                                or out.crs.to_wkt() == src.crs.to_wkt(),
                                f"源 {src.crs} 输出 {out.crs}",
                            )
                        )
                    elif src.crs and not out.crs:
                        checks.append(VerificationCheck("crs_preserved", False, "输出丢失 CRS"))
                    src_bounds = tuple(round(v, 6) for v in src.bounds)
                    out_bounds = tuple(round(v, 6) for v in out.bounds)
                    checks.append(
                        VerificationCheck("bounds_preserved", src_bounds == out_bounds,
                                          f"源 {src_bounds} 输出 {out_bounds}")
                    )
                    src_nodata = src.nodata
                    out_nodata = out.nodata
                    if src_nodata is None and out_nodata is None:
                        nodata_ok = True
                    elif src_nodata is None or out_nodata is None:
                        nodata_ok = False
                    else:
                        nodata_ok = math.isclose(src_nodata, out_nodata, rel_tol=1e-9)
                    checks.append(
                        VerificationCheck("nodata_preserved", nodata_ok,
                                          f"源 {src_nodata} 输出 {out_nodata}")
                    )
                    dtype_note = plan.options.get("dtype")
                    if dtype_note:
                        checks.append(
                            VerificationCheck(
                                "dtype_converted",
                                out.dtypes[0] == dtype_note,
                                f"输出 dtype {out.dtypes[0]}",
                            )
                        )
                    # Sampled pixel equality on a small window (data fidelity probe).
                    probe = self._probe_window_equals(src, out)
                    checks.append(
                        VerificationCheck(
                            "pixel_probe",
                            probe is not False,
                            "中心窗口采样一致" if probe else "中心窗口采样不一致",
                        )
                    )
        finally:
            pass
        failed = [c for c in checks if not c.passed]
        if failed:
            return ExportVerification(VerificationState.FAILED, checks)
        return ExportVerification(VerificationState.VERIFIED, checks)

    @staticmethod
    def _probe_window_equals(src, out) -> bool | None:
        import numpy as np
        import rasterio

        width = min(64, src.width)
        height = min(64, src.height)
        col = max(0, (src.width - width) // 2)
        row = max(0, (src.height - height) // 2)
        window = rasterio.windows.Window(col, row, width, height)
        a = src.read(1, window=window).astype("float64")
        b = out.read(1, window=window).astype("float64")
        if a.shape != b.shape:
            return False
        return bool(np.array_equal(np.nan_to_num(a, nan=-1e30), np.nan_to_num(b, nan=-1e30)))
