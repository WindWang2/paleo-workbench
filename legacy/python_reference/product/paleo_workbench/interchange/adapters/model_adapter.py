"""3D model export adapters: FLAC3D (.f3grid) and Abaqus (.inp).

These are *write-only* formats in this repository (structured hex grids from
``viz.geomodel.exporters``). The adapter wraps those writers and adds the
missing half: structural verification that re-parses the written file —
gridpoint/zone counts, 1-based contiguous numbering, node-reference range
checks, finite coordinates — plus a streaming structural inspect for
existing files (O(1) memory).

VTK family / OBJ / STL have no reader or writer anywhere in the repo; they
are declared capability-unavailable in :mod:`.unavailable` instead of being
half-implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class MeshFacts:
    gridpoints: int = 0
    zones: int = 0
    problems: list[str] = field(default_factory=list)


def _check_ids(ids_seen: set[int], what: str, problems: list[str]) -> None:
    if ids_seen and max(ids_seen) != len(ids_seen):
        problems.append(
            f"{what}编号不连续（max id {max(ids_seen)} vs count {len(ids_seen)}）"
        )


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def parse_flac3d(path: Path) -> MeshFacts:
    """Strict grammar scan of this repo's FLAC3D writer output (streaming)."""
    facts = MeshFacts()
    node_ids: set[int] = set()
    zone_refs: list[int] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            tokens = line.split()
            if tokens[0] == "G":
                if len(tokens) != 5:
                    facts.problems.append(f"行 {lineno}: G 记录应为 'G id x y z'")
                    continue
                try:
                    node_id = int(tokens[1])
                    coords = [float(v) for v in tokens[2:5]]
                except ValueError:
                    facts.problems.append(f"行 {lineno}: G 记录数值错误")
                    continue
                node_ids.add(node_id)
                facts.gridpoints += 1
                if not all(_finite(v) for v in coords):
                    facts.problems.append(f"行 {lineno}: 坐标非有限值")
            elif tokens[0] == "Z":
                if len(tokens) < 3 or tokens[1] != "B8":
                    facts.problems.append(f"行 {lineno}: 单元记录应为 'Z B8 id n1..n8'")
                    continue
                try:
                    refs = [int(v) for v in tokens[3:]]
                except (ValueError, IndexError):
                    facts.problems.append(f"行 {lineno}: 单元节点引用非整数")
                    continue
                facts.zones += 1
                zone_refs.extend(refs)
                if len(refs) != 8:
                    facts.problems.append(
                        f"行 {lineno}: B8 单元应有 8 个节点引用，实际 {len(refs)}"
                    )
            elif tokens[0] == "*":
                continue  # comment header written by the exporter
    missing = (set(zone_refs) - node_ids) if zone_refs else ()
    if missing:
        sample = sorted(missing)[:3]
        facts.problems.append(f"{len(missing)} 个单元引用了未定义的节点（如 {sample}）")
    _check_ids(node_ids, "节点", facts.problems)
    return facts


def parse_abaqus(path: Path) -> MeshFacts:
    """Strict grammar scan of this repo's Abaqus writer output (streaming)."""
    facts = MeshFacts()
    section = ""
    node_ids: set[int] = set()
    zone_refs: list[int] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                upper = line.upper()
                if upper.startswith("*NODE"):
                    section = "node"
                elif upper.startswith("*ELEMENT"):
                    section = "element"
                elif upper.startswith("*END"):
                    section = ""
                continue
            parts = [p.strip() for p in line.split(",")]
            if section == "node":
                if len(parts) != 4:
                    facts.problems.append(f"行 {lineno}: *NODE 记录应为 'id, x, y, z'")
                    continue
                try:
                    node_id = int(parts[0])
                    coords = [float(v) for v in parts[1:4]]
                except ValueError:
                    facts.problems.append(f"行 {lineno}: *NODE 记录数值错误")
                    continue
                node_ids.add(node_id)
                facts.gridpoints += 1
                if not all(_finite(v) for v in coords):
                    facts.problems.append(f"行 {lineno}: 坐标非有限值")
            elif section == "element":
                if len(parts) != 9:
                    facts.problems.append(
                        f"行 {lineno}: C3D8 单元应有 8 个节点引用，实际 {len(parts) - 1}"
                    )
                    continue
                try:
                    refs = [int(v) for v in parts[1:]]
                except ValueError:
                    facts.problems.append(f"行 {lineno}: 单元记录格式错误")
                    continue
                facts.zones += 1
                zone_refs.extend(refs)
    missing = (set(zone_refs) - node_ids) if zone_refs else ()
    if missing:
        sample = sorted(missing)[:3]
        facts.problems.append(f"{len(missing)} 个单元引用了未定义的节点（如 {sample}）")
    _check_ids(node_ids, "节点", facts.problems)
    return facts


class _StructuredModelAdapter(FormatAdapter):
    """Shared behaviour for the FLAC3D / Abaqus structured-hex writers."""

    resource_type = "model"

    def capability(self) -> FormatCapability:
        return FormatCapability(
            read=False,
            inspect=True,
            import_data=False,
            export=True,
            roundtrip_verify=True,
            notes=f"结构化六面体网格写出（{self.writer_name}）；无读取器，inspect 为结构扫描",
        )

    def inspect(self, path: Path) -> InspectionResult:
        path = Path(path)
        result = InspectionResult(format_id=self.format_id, object_type=self.resource_type)
        try:
            result.size_bytes = path.stat().st_size
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件状态: {exc}")
            return result
        try:
            facts = self.parse(path)
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件: {exc}")
            return result
        if facts.gridpoints == 0 and facts.zones == 0:
            result.ok = False
            result.errors.append("未识别到网格记录（不是本仓库写出的结构化网格）")
            return result
        result.metadata = {"gridpoints": facts.gridpoints, "zones": facts.zones}
        if facts.problems:
            result.errors.extend(facts.problems[:16])
            result.warnings.append(f"结构问题共 {len(facts.problems)} 处")
        return result

    def parse(self, path: Path) -> MeshFacts:
        raise NotImplementedError

    def plan_import(self, path, inspection, *, managed=True, asset_name=None, options=None):
        plan = super().plan_import(path, inspection, managed=managed, asset_name=asset_name, options=options)
        plan.action = "unsupported"
        plan.warnings.append("模型网格为导出专用格式：无导入路径")
        return plan

    def import_data(self, path, plan, *, work_dir, catalog, cancel=None, progress=None):
        raise FormatNotSupportedError(f"{self.format_id}: 模型网格无导入路径（仅导出）")

    def plan_export(self, source_path, target_path, *, options=None) -> ExportPlan:
        target_path = Path(target_path)
        if target_path.suffix.lower() != f".{self.extensions[0]}":
            raise FormatNotSupportedError(
                f"{self.display_name} 仅支持导出为 .{self.extensions[0]}"
            )
        options = dict(options or {})
        missing = [key for key in ("nx", "ny", "nz") if key not in options]
        if missing:
            raise FormatNotSupportedError(f"缺少网格维度参数: {', '.join(missing)}")
        nx, ny, nz = (int(options[k]) for k in ("nx", "ny", "nz"))
        if min(nx, ny, nz) < 1 or nx * ny * nz > 8_000_000:
            raise FormatNotSupportedError("网格维度非法或超过导出规模上限")
        estimated = (nx + 1) * (ny + 1) * (nz + 1) * 64 + nx * ny * nz * 64
        return ExportPlan(
            format_id=self.format_id,
            source_path=str(source_path),
            target_path=str(target_path),
            estimated_bytes=estimated,
            options=options,
        )

    def export_data(self, source_path, plan, *, work_dir, cancel=None, progress=None) -> Path:
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        from paleo_workbench.resources.exporters import atomic_output

        options = plan.options
        writer_kwargs = {
            "nx": int(options["nx"]),
            "ny": int(options["ny"]),
            "nz": int(options["nz"]),
            "dx": float(options.get("dx", 10.0)),
            "dy": float(options.get("dy", 10.0)),
            "dz": float(options.get("dz", 10.0)),
        }
        writer = self._writer()
        target = Path(plan.target_path)
        with atomic_output(target) as tmp:
            if not writer(str(tmp), **writer_kwargs):
                raise RuntimeError(f"{self.display_name} 导出失败（writer 返回 False）")
        return target

    def _writer(self):
        from paleo_workbench.viz.geomodel import exporters

        return getattr(exporters, self.writer_name)

    def verify_output(self, target_path, plan) -> ExportVerification:
        target_path = Path(target_path)
        checks: list[VerificationCheck] = []
        if not target_path.is_file() or target_path.stat().st_size == 0:
            return ExportVerification(VerificationState.FAILED, checks, detail="输出缺失或为空")
        facts = self.parse(target_path)
        checks.append(VerificationCheck("reparsable", facts.gridpoints > 0 and facts.zones > 0,
                                        f"{facts.gridpoints} gridpoints / {facts.zones} zones"))
        options = plan.options
        if {"nx", "ny", "nz"} <= set(options):
            nx, ny, nz = int(options["nx"]), int(options["ny"]), int(options["nz"])
            expected_gp = (nx + 1) * (ny + 1) * (nz + 1)
            expected_zones = nx * ny * nz
            checks.append(VerificationCheck("gridpoint_count", facts.gridpoints == expected_gp,
                                            f"预期 {expected_gp}，实际 {facts.gridpoints}"))
            checks.append(VerificationCheck("zone_count", facts.zones == expected_zones,
                                            f"预期 {expected_zones}，实际 {facts.zones}"))
        if facts.problems:
            return ExportVerification(
                VerificationState.FAILED, checks,
                detail=f"结构问题: {'; '.join(facts.problems[:4])}",
            )
        failed = [c for c in checks if not c.passed]
        if failed:
            return ExportVerification(VerificationState.FAILED, checks)
        return ExportVerification(VerificationState.VERIFIED, checks)


class Flac3dAdapter(_StructuredModelAdapter):
    format_id = "flac3d_f3grid"
    display_name = "FLAC3D 角点网格"
    extensions = ("f3grid",)
    writer_name = "export_to_flac3d"

    def parse(self, path: Path) -> MeshFacts:
        return parse_flac3d(path)


class AbaqusAdapter(_StructuredModelAdapter):
    format_id = "abaqus_inp"
    display_name = "Abaqus 有限元网格"
    extensions = ("inp",)
    writer_name = "export_to_abaqus"

    def parse(self, path: Path) -> MeshFacts:
        return parse_abaqus(path)
