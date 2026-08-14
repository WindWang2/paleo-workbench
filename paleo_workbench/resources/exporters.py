"""Format conversion exporters for the data page and export service."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Callable, Iterator

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.io_registry import CONVERT_LABEL_EXT


class ExportError(Exception):
    """Raised when a format conversion fails."""


@contextmanager
def atomic_output(output_path: Path) -> Iterator[Path]:
    """Yield a temp path beside *output_path*; atomically replace on success.

    Converters write to the temp file first and only ``Path.replace`` it onto
    the final name after a successful conversion, so a failed export never
    leaves a corrupt partial file at the user-visible destination. The temp
    keeps the target suffix so extension-based format inference (e.g. pandas
    ``to_excel``) still works.
    """
    output_path = Path(output_path)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=output_path.suffix,
        dir=str(output_path.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        yield tmp_path
        tmp_path.replace(output_path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


# Input format sets
_LAS_FORMATS = {"las"}
_TABLE_FORMATS = {"csv", "xlsx", "xls"}
_IMAGE_FORMATS = {"tif", "tiff", "png", "jpg", "jpeg", "bmp"}
_TEXT_FORMATS = {"txt", "md", "markdown", "json", "xml", "log", "dat"}
_SEISMIC_FORMATS = {"sgy", "segy"}
_GEOJSON_FORMATS = {"geojson", "json"}


def las_to_csv(input_path: Path, output_path: Path) -> None:
    try:
        import lasio
        import pandas as pd

        las = lasio.read(str(input_path))
        df = las.df()
        with atomic_output(output_path) as tmp:
            df.to_csv(tmp, index=True)
    except Exception as exc:
        raise ExportError(f"LAS -> CSV 失败: {exc}") from exc


def las_to_xlsx(input_path: Path, output_path: Path) -> None:
    try:
        import lasio
        import pandas as pd

        las = lasio.read(str(input_path))
        df = las.df()
        with atomic_output(output_path) as tmp:
            df.to_excel(tmp, index=True)
    except Exception as exc:
        raise ExportError(f"LAS -> XLSX 失败: {exc}") from exc


def las_to_json_summary(input_path: Path, output_path: Path) -> None:
    """Export LAS curve headers + sample counts (not full samples)."""
    try:
        import lasio

        las = lasio.read(str(input_path), ignore_header_errors=True)
        curves = []
        for curve in list(getattr(las, "curves", []) or []):
            curves.append(
                {
                    "mnemonic": str(getattr(curve, "mnemonic", "") or ""),
                    "unit": str(getattr(curve, "unit", "") or ""),
                    "descr": str(getattr(curve, "descr", "") or ""),
                }
            )
        well_name = ""
        well = getattr(las, "well", None)
        if well is not None:
            for key in ("WELL", "WN", "UWI"):
                try:
                    item = well[key]
                    well_name = str(getattr(item, "value", item) or "")
                    if well_name:
                        break
                except Exception:
                    continue
        payload = {
            "source": str(input_path),
            "well_name": well_name or input_path.stem,
            "curve_count": len(curves),
            "curves": curves,
        }
        with atomic_output(output_path) as tmp:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception as exc:
        raise ExportError(f"LAS -> JSON 摘要失败: {exc}") from exc


def table_to_json(input_path: Path, output_path: Path) -> None:
    try:
        import pandas as pd

        ext = input_path.suffix.lower().lstrip(".")
        if ext == "csv":
            df = pd.read_csv(input_path)
        else:
            df = pd.read_excel(input_path)
        with atomic_output(output_path) as tmp:
            df.to_json(tmp, orient="records", force_ascii=False)
    except Exception as exc:
        raise ExportError(f"表格 -> JSON 失败: {exc}") from exc


def table_to_xlsx(input_path: Path, output_path: Path) -> None:
    try:
        import pandas as pd

        ext = input_path.suffix.lower().lstrip(".")
        if ext == "csv":
            df = pd.read_csv(input_path)
        elif ext in {"xlsx", "xls"}:
            df = pd.read_excel(input_path)
        else:
            raise ExportError(f"不支持的表格格式: {ext}")
        with atomic_output(output_path) as tmp:
            df.to_excel(tmp, index=False)
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"表格 -> XLSX 失败: {exc}") from exc


def image_to_png(input_path: Path, output_path: Path) -> None:
    try:
        from PIL import Image

        with Image.open(input_path) as img:
            with atomic_output(output_path) as tmp:
                img.save(tmp, "PNG")
    except Exception as exc:
        raise ExportError(f"图像 -> PNG 失败: {exc}") from exc


def text_to_txt(input_path: Path, output_path: Path) -> None:
    try:
        text = input_path.read_text(encoding="utf-8", errors="replace")
        with atomic_output(output_path) as tmp:
            tmp.write_text(text, encoding="utf-8")
    except Exception as exc:
        raise ExportError(f"文本 -> TXT 失败: {exc}") from exc


def geojson_normalize(input_path: Path, output_path: Path) -> None:
    """Pretty-print / validate GeoJSON FeatureCollection."""
    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ExportError("GeoJSON 根节点必须是对象")
        if data.get("type") not in {"FeatureCollection", "Feature", "GeometryCollection"}:
            # Still write normalized JSON for generic .json
            pass
        with atomic_output(output_path) as tmp:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"GeoJSON 规范化失败: {exc}") from exc


def seismic_to_summary_json(input_path: Path, output_path: Path) -> None:
    """Export SEGY volume metadata via engine SeismicLoader (no full volume)."""
    try:
        from geoviz import SeismicLoader

        loader = SeismicLoader(str(input_path))
        try:
            meta = loader.inspect()
            payload = {
                "source": str(input_path),
                "n_inlines": meta.n_inlines,
                "n_crosslines": meta.n_crosslines,
                "n_samples": meta.n_samples,
                "dt_ms": meta.dt_ms,
                "t0_ms": meta.t0_ms,
                "iline_start": meta.iline_start,
                "iline_step": meta.iline_step,
                "xline_start": meta.xline_start,
                "xline_step": meta.xline_step,
            }
        finally:
            loader.close()
        with atomic_output(output_path) as tmp:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except Exception as exc:
        raise ExportError(f"SEGY -> 摘要 JSON 失败: {exc}") from exc


# Registry: (label, input_formats, convert_fn)
_CONVERTERS: list[tuple[str, set[str], Callable]] = [
    ("CSV", _LAS_FORMATS, las_to_csv),
    ("XLSX", _LAS_FORMATS, las_to_xlsx),
    ("JSON", _LAS_FORMATS, las_to_json_summary),
    ("JSON", _TABLE_FORMATS, table_to_json),
    ("XLSX", {"csv"}, table_to_xlsx),
    ("PNG", _IMAGE_FORMATS, image_to_png),
    ("TXT", _TEXT_FORMATS, text_to_txt),
    ("GeoJSON", _GEOJSON_FORMATS, geojson_normalize),
    ("SUMMARY", _SEISMIC_FORMATS, seismic_to_summary_json),
]


def get_available_formats(
    asset: ResourceItem | ExportArtifact,
) -> list[tuple[str, Callable]]:
    """Return [(label, convert_fn), ...] for formats the asset can export to."""
    if isinstance(asset, ExportArtifact):
        return []
    fmt = (asset.format or "").lower().lstrip(".")
    # Preserve order, allow multiple targets with same label from different sets
    # by returning unique labels (first wins for label collision on same fmt).
    seen: set[str] = set()
    result: list[tuple[str, Callable]] = []
    for label, inputs, fn in _CONVERTERS:
        if fmt in inputs and label not in seen:
            seen.add(label)
            result.append((label, fn))
    return result


def extension_for_label(label: str) -> str:
    return CONVERT_LABEL_EXT.get(label, ".out")
