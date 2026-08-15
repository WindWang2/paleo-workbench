from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.preview_parsers.models import PreviewResult
from paleo_workbench.resources.preview_parsers.table_parsers import parse_error_preview, safe_stat
from paleo_workbench.viz.well_log_api import fast_las_parse_data

if TYPE_CHECKING:
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings


class _UseLasio(Exception):
    """Internal signal: fall back to the lasio parser for this file."""


def _lasio_data_table(path: Path) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """Parse the LAS data section via lasio (handles wrapped files).

    Returns ((), ()) on any failure.
    """
    try:
        import lasio
        import numpy as np

        las = lasio.read(str(path))
        data_headers = tuple(c.mnemonic for c in las.curves)
        limit = min(len(las.data), 100)
        rows_list = []
        for i in range(limit):
            row_vals = []
            for val in las.data[i]:
                if np.isnan(val):
                    row_vals.append("NaN")
                else:
                    row_vals.append(f"{val:.4f}".rstrip('0').rstrip('.'))
            rows_list.append(tuple(row_vals))
        return data_headers, tuple(rows_list)
    except Exception:
        return (), ()


def las_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    path = Path(resource.path)
    try:
        from geoviz import inspect_las_file

        header = inspect_las_file(str(path))
    except ValueError as exc:
        if str(exc) == "LAS contains no curve headers":
            return PreviewResult(
                mode="well_log",
                title=resource.name,
                path=resource.path,
                revision=safe_stat(path),
                format=resource.format,
                status=resource.status,
                type_label=resource.type,
                summary_rows=(
                    ("井名", path.stem),
                    ("曲线数", "0"),
                    ("采样点", "0"),
                ),
                table_headers=("曲线", "单位", "描述"),
                warning="LAS 文件缺少曲线定义",
            )
        return parse_error_preview(resource, "LAS 预览失败: ValueError")
    except Exception as exc:
        return parse_error_preview(resource, f"LAS 预览失败: {exc.__class__.__name__}")

    curves = header.curves
    rows = tuple(
        (
            str(curve.mnemonic or ""),
            str(curve.unit or ""),
            str(curve.description or ""),
        )
        for curve in curves[: settings.table_max_rows]
    )
    well_name = header.well_name or Path(resource.path).stem
    summary_rows = (
        ("井名", str(well_name)),
        ("曲线数", str(len(curves))),
        ("采样点", str(header.row_count)),
    )
    truncated = len(curves) > settings.table_max_rows

    data_headers = ()
    data_rows = ()
    data_warning = ""
    try:
        import numpy as np

        if getattr(header, "wrapped", False):
            raise _UseLasio  # wrapped LAS: fast channel cannot handle it
        content = path.read_text(encoding="utf-8", errors="replace")
        _headers, arr = fast_las_parse_data(content, header.null_value)
        if arr.ndim == 2 and arr.shape[0] > 0:
            if arr.shape[1] != len(curves):
                data_warning = (
                    f"数据表列数（{arr.shape[1]}）与曲线定义数（{len(curves)}）不一致"
                )
            data_headers = tuple(c.mnemonic for c in curves[: arr.shape[1]])
            limit = min(arr.shape[0], 100)
            rows_list = []
            for i in range(limit):
                row_vals = []
                for val in arr[i]:
                    if np.isnan(val):
                        row_vals.append("NaN")
                    else:
                        row_vals.append(f"{val:.4f}".rstrip('0').rstrip('.'))
                rows_list.append(tuple(row_vals))
            data_rows = tuple(rows_list)
    except _UseLasio:
        data_headers, data_rows = _lasio_data_table(path)
    except Exception:
        pass

    if data_warning:
        warning = "；".join(
            w for w in (data_warning, "曲线列表已按行上限截断" if truncated else "") if w
        )
    else:
        warning = "曲线列表已按行上限截断" if truncated else ""

    return PreviewResult(
        mode="well_log",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        summary_rows=summary_rows,
        table_headers=("曲线", "单位", "描述"),
        table_rows=rows,
        data_headers=data_headers,
        data_rows=data_rows,
        warning=warning,
        truncated=truncated,
    )


def xml_well_log_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult | None:
    path = Path(resource.path)
    try:
        try:
            import lxml.etree as ET
        except ImportError:
            import xml.etree.ElementTree as ET

        tree = ET.parse(str(path))
        root = tree.getroot()
    except Exception:
        return None

    def local_tag(elem) -> str:
        t = elem.tag
        return t.rsplit("}", 1)[-1] if "}" in t else t

    curve_infos: list[tuple[str, str, str]] = []
    data_headers: list[str] = []
    data_rows: list[tuple[str, ...]] = []
    parsed_sheets: list[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]]] = []
    all_rows: list[list[str]] = []
    max_preview_rows = settings.table_max_rows

    for child in root:
        if local_tag(child) == "Worksheet":
            sheet_name = child.attrib.get(
                "{urn:schemas-microsoft-com:office:spreadsheet}Name",
                child.attrib.get("ss:Name", "工作表"),
            )
            sheet_rows: list[list[str]] = []
            for w_child in child:
                if local_tag(w_child) == "Table":
                    for r_elem in w_child:
                        if local_tag(r_elem) == "Row":
                            row_vals: list[str] = []
                            for c_elem in r_elem:
                                if local_tag(c_elem) == "Cell":
                                    txt = ""
                                    for d_elem in c_elem:
                                        if local_tag(d_elem) == "Data":
                                            txt = (d_elem.text or "").strip()
                                            break
                                    if not txt and c_elem.text:
                                        txt = c_elem.text.strip()
                                    row_vals.append(txt)
                            if row_vals:
                                sheet_rows.append(row_vals)
                                if len(sheet_rows) >= max_preview_rows + 1:
                                    break
            if sheet_rows and len(sheet_rows) > 1:
                s_headers = tuple(str(h).strip() for h in sheet_rows[0] if str(h).strip())
                s_data_rows = tuple(
                    tuple(r[: len(s_headers)])
                    for r in sheet_rows[1:max_preview_rows]
                )
                parsed_sheets.append((sheet_name, s_headers, s_data_rows))
                if not all_rows and "测井曲线" in sheet_name:
                    all_rows = sheet_rows

    if not all_rows and parsed_sheets:
        s_name, s_h, s_r = parsed_sheets[0]
        data_headers = list(s_h)
        data_rows = list(s_r)
    elif all_rows and len(all_rows) > 1:
        data_headers = [str(h).strip() for h in all_rows[0] if str(h).strip()]
        raw_data_rows = all_rows[1:]

        if data_headers and data_headers[0] in ("井号", "Well", "WELL_NAME", "WELL"):
            well_names = [r[0] for r in raw_data_rows if r and r[0]]
            if well_names:
                well_name = well_names[0]

        data_rows = [
            tuple(r[: len(data_headers)])
            for r in raw_data_rows[: settings.table_max_rows]
        ]

    if not data_rows:
        for elem in root.iter():
            tag = local_tag(elem).lower()
            if tag in ("logcurveinfo", "curveinfo", "curve"):
                mnemonic = ""
                unit = ""
                desc = ""
                for child in elem:
                    ctag = local_tag(child).lower()
                    if ctag in ("mnemonic", "mnem", "name"):
                        mnemonic = (child.text or "").strip()
                    elif ctag in ("unit", "unitstring"):
                        unit = (child.text or "").strip()
                    elif ctag in ("curvedescription", "description", "desc"):
                        desc = (child.text or "").strip()
                if mnemonic:
                    curve_infos.append((mnemonic, unit, desc))
        if curve_infos and not data_headers:
            data_headers = [c[0] for c in curve_infos]

        for elem in root.iter():
            tag = local_tag(elem).lower()
            if tag in ("logdata",):
                lines: list[str] = []
                if elem.text:
                    lines.extend(elem.text.strip().splitlines())
                for child in elem:
                    if local_tag(child).lower() in ("data", "row", "line") and child.text:
                        lines.extend(child.text.strip().splitlines())
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = [p.strip() for p in re.split(r"[\s,;]+", line)]
                    if parts:
                        data_rows.append(tuple(parts))
                    if len(data_rows) >= settings.table_max_rows:
                        break
                if data_rows:
                    break

    if not data_rows:
        rows_found: list[dict[str, str]] = []
        for elem in root.iter():
            tag = local_tag(elem).lower()
            if tag in ("record", "datapoint", "logdatapoint", "point"):
                row_vals: dict[str, str] = {}
                for child in elem:
                    ctag = local_tag(child)
                    val = (child.text or "").strip()
                    if val:
                        row_vals[ctag] = val
                if row_vals:
                    rows_found.append(row_vals)
                if len(rows_found) >= settings.table_max_rows:
                    break
        if rows_found:
            if not data_headers:
                data_headers = list(rows_found[0].keys())
            data_rows = [tuple(r.get(h, "") for h in data_headers) for r in rows_found]

    if not data_headers and not data_rows:
        return None

    if not curve_infos:
        for h in data_headers:
            h_name = str(h).strip()
            unit = ""
            if h_name.upper() in ("DEPT", "DEPTH", "深度", "TVD", "TVDSS"):
                unit = "m"
            elif "GR" in h_name.upper():
                unit = "gAPI"
            elif "DT" in h_name.upper():
                unit = "us/m"
            elif any(k in h_name for k in ("孔隙度", "POR", "PORO")):
                unit = "%"
            elif any(k in h_name for k in ("渗透率", "PERM")):
                unit = "mD"
            curve_infos.append((h_name, unit, h_name))

    if "well_name" not in locals():
        well_name = path.stem
        for elem in root.iter():
            tag = local_tag(elem).lower()
            if tag in ("namewell", "wellname", "well", "name") and elem.text:
                val = elem.text.strip()
                if val and len(val) < 50:
                    well_name = val
                    break

    summary_rows = (
        ("井名", well_name),
        ("曲线数", str(len(data_headers))),
        ("采样点", str(len(data_rows))),
    )

    return PreviewResult(
        mode="well_log",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label="测井数据",
        summary_rows=summary_rows,
        table_headers=("曲线", "单位", "描述"),
        table_rows=tuple(curve_infos),
        data_headers=tuple(data_headers),
        data_rows=tuple(data_rows),
        sheets=tuple(parsed_sheets) if len(parsed_sheets) > 1 else (),
        visualization_available=True,
    )
