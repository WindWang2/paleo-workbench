"""LAS well-log interchange adapter.

Wraps the existing parsers (geoviz ``las_preview.inspect_las_file`` for the
header, the native ``fast_las_parse_data`` path for data, lasio as the
wrapped-file fallback) and adds interchange-grade diagnostics: duplicate
mnemonics, depth ordering, malformed rows, encoding, and null handling.

There is no LAS *writer* in this repository, so export is limited to the
reliably expressible conversions already shipped by
``paleo_workbench.resources.exporters`` (CSV / JSON summary via lasio), now
backed by structural verification.
"""

from __future__ import annotations

import csv as _csv
import json
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
    ProgressCallback,
    _null_progress,
)
from paleo_workbench.interchange.registry import FormatAdapter, SNIFF_PREFIX_BYTES

# Full data scan above this size only reports header facts (bounded inspect).
_FULL_SCAN_MAX_BYTES = 64 * 1024 * 1024


class LasAdapter(FormatAdapter):
    format_id = "las"
    display_name = "LAS 测井曲线"
    extensions = ("las",)
    resource_type = "well_log"

    def capability(self) -> FormatCapability:
        return FormatCapability(
            read=True,
            inspect=True,
            import_data=True,
            export=True,  # CSV / JSON summary only; never a .las rewrite
            roundtrip_verify=True,
            notes="导出仅支持 CSV/JSON 摘要（lasio）；不提供 LAS 写入器",
        )

    # -- inspect ------------------------------------------------------------
    def inspect(self, path: Path) -> InspectionResult:
        path = Path(path)
        result = InspectionResult(format_id=self.format_id, object_type=self.resource_type)
        try:
            result.size_bytes = path.stat().st_size
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件状态: {exc}")
            return result

        header = self._inspect_header(path, result)
        if header is not None:
            self._check_encoding(path, result)
            self._scan_ascii_stream(path, header, result)
        return result

    def _inspect_header(self, path: Path, result: InspectionResult):
        try:
            from geoviz_well_log.las_preview import inspect_las_file
        except Exception:
            inspect_las_file = None
        if inspect_las_file is not None:
            try:
                # Full row count only within the bounded-scan budget; larger
                # files get header-only structure (data facts come from the
                # streaming scan or are skipped with a note).
                header = inspect_las_file(
                    path, header_only=result.size_bytes > _FULL_SCAN_MAX_BYTES
                )
            except Exception as exc:
                result.ok = False
                result.errors.append(f"LAS 头解析失败: {exc}")
                return None
            result.metadata = {
                "well_name": header.well_name,
                "null_value": header.null_value,
                "wrapped": header.wrapped,
                "delimiter": header.delimiter,
                "row_count": header.row_count,
                "curves": [
                    {"mnemonic": c.mnemonic, "unit": c.unit, "description": c.description}
                    for c in header.curves
                ],
            }
            for curve in header.curves:
                if curve.unit:
                    result.units[curve.mnemonic] = curve.unit
            names = [c.mnemonic for c in header.curves]
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                result.warnings.append(f"重复曲线助记名: {', '.join(dupes)}")
            if header.row_count <= 0:
                result.warnings.append("~A 数据区为空或不可读")
            return header

        # geoviz unavailable: minimal bounded fallback so preflight still works.
        try:
            text = path.read_text("utf-8", errors="replace")[: SNIFF_PREFIX_BYTES * 4]
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件: {exc}")
            return None
        curves: list[dict] = []
        in_curve = False
        null_value = -999.25
        well_name = ""
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("~"):
                in_curve = s.upper().startswith("~C")
                continue
            if not s or s.startswith("#"):
                continue
            if in_curve and "." in s:
                mnemonic = s.split(".", 1)[0].strip()
                unit = ""
                after_dot = s.split(".", 1)[1]
                if " " in after_dot:
                    unit = after_dot.split(" ", 1)[0].strip()
                curves.append({"mnemonic": mnemonic, "unit": unit, "description": ""})
            elif "." in s and ":" in s:
                key = s.split(".", 1)[0].strip().upper()
                value = s.split(":", 1)[0].split(".", 1)[1].strip()
                if key == "NULL":
                    try:
                        null_value = float(value)
                    except ValueError:
                        pass
                elif key == "WELL":
                    well_name = value
        result.metadata = {"well_name": well_name, "null_value": null_value, "curves": curves,
                           "row_count": 0, "wrapped": False, "delimiter": "SPACE"}
        result.warnings.append("geoviz 引擎不可用：使用受限头解析（无行数统计）")
        for curve in curves:
            if curve["unit"]:
                result.units[curve["mnemonic"]] = curve["unit"]
        return None

    def _check_encoding(self, path: Path, result: InspectionResult) -> None:
        try:
            with open(path, "rb") as fh:
                raw = fh.read(SNIFF_PREFIX_BYTES)
            raw.decode("utf-8")
        except UnicodeDecodeError:
            result.warnings.append("文件前缀不是有效 UTF-8（LAS 规范为 ASCII）")

    @staticmethod
    def _parse_depth_header(path: Path) -> dict:
        """Bounded read of STRT/STOP/STEP declarations (~W section)."""
        import re

        try:
            with open(path, "rb") as fh:
                raw = fh.read(SNIFF_PREFIX_BYTES * 2)
        except OSError:
            return {}
        text = raw.decode("utf-8", errors="replace")
        header: dict[str, float] = {}
        for key in ("STRT", "STOP", "STEP"):
            match = re.search(
                rf"^{key}\.\s*\S+\s+([-+0-9.eE]+)", text, re.MULTILINE | re.IGNORECASE
            )
            if match:
                try:
                    header[key.lower()] = float(match.group(1))
                except ValueError:
                    continue
        return header

    def _scan_ascii_stream(self, path: Path, header, result: InspectionResult) -> None:
        """Streaming O(1)-memory scan of the ~A section: depth order/malformed rows."""
        if result.size_bytes > _FULL_SCAN_MAX_BYTES:
            result.warnings.append("文件超过全量扫描上限：跳过深度顺序检查")
            return
        depth_header = self._parse_depth_header(path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                self._scan_ascii_lines(fh, header, result, depth_header)
        except OSError as exc:
            result.warnings.append(f"数据区扫描失败: {exc}")

    def _scan_ascii_lines(self, fh, header, result: InspectionResult,
                          depth_header: dict | None = None) -> None:
        in_ascii = False
        prev_depth: float | None = None
        direction: str | None = None
        depth_index = header.depth_index if header is not None else 0
        malformed = 0
        rows = 0
        null_depths = 0
        non_monotonic = 0
        null_value = result.metadata.get("null_value", -999.25)
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("~"):
                in_ascii = s.upper().startswith("~A")
                continue
            if not in_ascii:
                continue
            tokens = s.split()
            if len(tokens) <= depth_index:
                malformed += 1
                continue
            try:
                depth = float(tokens[depth_index])
            except ValueError:
                malformed += 1
                continue
            rows += 1
            if not math.isfinite(depth) or math.isclose(depth, null_value, abs_tol=1e-6):
                null_depths += 1
                prev_depth = depth
                continue
            if prev_depth is not None and math.isfinite(prev_depth) and depth != prev_depth:
                if direction is None:
                    direction = "increasing" if depth > prev_depth else "decreasing"
                elif direction == "increasing" and depth < prev_depth:
                    non_monotonic += 1
                elif direction == "decreasing" and depth > prev_depth:
                    non_monotonic += 1
            prev_depth = depth
        if direction:
            result.metadata["depth_direction"] = direction
        if malformed:
            result.warnings.append(f"{malformed} 行数据格式异常（列数不足或非数值）")
        if null_depths:
            result.warnings.append(f"深度列含 {null_depths} 个空值/非有限值")
        if non_monotonic:
            result.warnings.append(f"深度顺序异常（非单调/重复）共 {non_monotonic} 处")
        self._check_declared_extent(rows, depth_header or {}, result)

    @staticmethod
    def _check_declared_extent(rows: int, depth_header: dict, result: InspectionResult) -> None:
        strt = depth_header.get("strt")
        stop = depth_header.get("stop")
        step = depth_header.get("step")
        if strt is None or stop is None or not step:
            return
        try:
            expected = int(round(abs(stop - strt) / abs(step))) + 1
        except (ZeroDivisionError, TypeError):
            return
        if rows + 1 < expected:  # tolerate a single dropped row
            result.warnings.append(
                f"数据行数（{rows}）少于头声明（STRT/STOP/STEP 推算 {expected}）：文件可能截断"
            )

    # -- plan / execute -----------------------------------------------------
    def plan_import(self, path, inspection, *, managed=True, asset_name=None, options=None):
        plan = super().plan_import(
            path, inspection, managed=managed, asset_name=asset_name, options=options
        )
        plan.metadata.setdefault("object_type", self.resource_type)
        return plan

    def import_data(self, path, plan, *, work_dir, catalog, cancel=None, progress=None) -> ImportExecutionResult:
        cancel = cancel or NULL_CANCEL
        progress = progress or _null_progress
        cancel.checkpoint()
        progress(0.1, f"导入 LAS: {plan.asset_name}")
        version = catalog.import_raw(
            path,
            name=plan.asset_name,
            type=self.resource_type,
            format=self.format_id,
            metadata=plan.metadata,
        )
        progress(1.0, "LAS 导入完成")
        return ImportExecutionResult(version_id=version.id, asset_id=version.asset_id, managed=True)

    # -- export (CSV / JSON summary only) -----------------------------------
    def plan_export(self, source_path, target_path, *, options=None) -> ExportPlan:
        target_path = Path(target_path)
        suffix = target_path.suffix.lower()
        if suffix not in (".csv", ".json"):
            raise FormatNotSupportedError(
                "LAS 仅支持导出为 CSV 或 JSON 摘要；不提供 LAS 写入器"
            )
        return ExportPlan(
            format_id=self.format_id,
            source_path=str(source_path),
            target_path=str(target_path),
            estimated_bytes=Path(source_path).stat().st_size,
            options=dict(options or {}),
            warnings=["LAS 导出为摘要转换，不保留原始 LAS 头/单位以外的信息"],
        )

    def export_data(self, source_path, plan, *, work_dir, cancel=None, progress=None) -> Path:
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        from paleo_workbench.resources.exporters import atomic_output, las_to_csv, las_to_json_summary

        target = Path(plan.target_path)
        converter = las_to_csv if target.suffix.lower() == ".csv" else las_to_json_summary
        with atomic_output(target) as tmp:
            converter(Path(source_path), tmp)
        return target

    def verify_output(self, target_path, plan) -> ExportVerification:
        target_path = Path(target_path)
        checks: list[VerificationCheck] = []
        warnings: list[str] = []
        if not target_path.is_file():
            return ExportVerification.failed(checks, "输出文件不存在")
        if target_path.stat().st_size == 0:
            return ExportVerification(VerificationState.FAILED, checks, "输出文件为空")

        source_curves = plan_to_curve_names(plan)
        if target_path.suffix.lower() == ".json":
            try:
                payload = json.loads(target_path.read_text("utf-8"))
            except Exception as exc:
                return ExportVerification.failed(checks, f"JSON 无法解析: {exc}")
            curves = payload.get("curves") or payload.get("well", {}).get("curves") or []
            checks.append(VerificationCheck("json_parsable", True))
            if source_curves:
                names = {c.get("mnemonic") for c in curves if isinstance(c, dict)}
                checks.append(
                    VerificationCheck(
                        "curve_names_preserved",
                        source_curves.issubset(names),
                        f"源 {len(source_curves)} 条，输出命中 {len(source_curves & names)} 条",
                    )
                )
        else:
            try:
                with open(target_path, newline="", encoding="utf-8-sig") as fh:
                    rows = list(_csv.reader(fh))
            except Exception as exc:
                return ExportVerification.failed(checks, f"CSV 无法解析: {exc}")
            checks.append(VerificationCheck("csv_parsable", bool(rows), f"{len(rows)} 行"))
            if len(rows) < 2:
                checks.append(VerificationCheck("csv_nonempty_data", False, "缺少数据行"))
            if source_curves and rows:
                header_cells = {c.strip().upper() for c in rows[0]}
                missing = {n.upper() for n in source_curves} - header_cells
                if missing:
                    warnings.append(f"CSV 表头缺少曲线列: {', '.join(sorted(missing))}")

        failed = [c for c in checks if not c.passed]
        if failed:
            return ExportVerification(VerificationState.FAILED, checks, warnings)
        if warnings:
            return ExportVerification(VerificationState.VERIFIED_WITH_WARNINGS, checks, warnings)
        return ExportVerification(VerificationState.VERIFIED, checks, warnings)


def plan_to_curve_names(plan: ExportPlan) -> set[str]:
    names = plan.options.get("curve_names")
    if isinstance(names, (list, tuple, set)) and names:
        return {str(n) for n in names}
    source = Path(plan.source_path)
    if not source.is_file():
        return set()
    try:
        from geoviz_well_log.las_preview import inspect_las_file

        header = inspect_las_file(source, header_only=True)
        return {c.mnemonic for c in header.curves}
    except Exception:
        return set()
