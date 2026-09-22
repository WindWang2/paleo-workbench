"""Delivery profiles (I15) and delivery QA reports (I16).

A delivery profile is a serializable *configuration*, not scattered export
parameters: what to include, which formats, how external references are
treated, whether the package is verified, and which report files are
generated. Built-in profiles cover common handoff scenarios; none of them
hard-code an organization name.

The QA report is generated from observed facts only: the package manifest,
the verify report, the dependency audit and catalog counts. It is written in
machine-readable JSON and human-readable Markdown into the package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paleo_workbench.interchange.contracts import CancelToken, NULL_CANCEL, ProgressCallback, _null_progress
from paleo_workbench.interchange.dependency_audit import (
    DependencyAuditReport,
    DependencyStatus,
    ExternalDependencyAuditor,
)
from paleo_workbench.interchange.package.builder import (
    ExternalPolicy,
    PackageBuilder,
    PackageOptions,
)
from paleo_workbench.interchange.package.verifier import verify_package
from paleo_workbench.interchange.path_safety import os_replace_atomic


@dataclass
class DeliveryProfile:
    profile_id: str
    display_name: str
    description: str = ""
    external_policy: ExternalPolicy = ExternalPolicy.KEEP
    include_outputs_only: bool = False
    include_formats: tuple[str, ...] | None = None
    include_provenance: bool = True
    container: str = "directory"  # "directory" | "zip"
    verify_package: bool = True
    report_formats: tuple[str, ...] = ("json", "md")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "description": self.description,
            "external_policy": self.external_policy.value,
            "include_outputs_only": self.include_outputs_only,
            "include_formats": list(self.include_formats) if self.include_formats else None,
            "include_provenance": self.include_provenance,
            "container": self.container,
            "verify_package": self.verify_package,
            "report_formats": list(self.report_formats),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeliveryProfile":
        formats = data.get("include_formats")
        return cls(
            profile_id=str(data["profile_id"]),
            display_name=str(data.get("display_name", data["profile_id"])),
            description=str(data.get("description", "")),
            external_policy=ExternalPolicy(str(data.get("external_policy", "keep"))),
            include_outputs_only=bool(data.get("include_outputs_only", False)),
            include_formats=tuple(str(f) for f in formats) if formats else None,
            include_provenance=bool(data.get("include_provenance", True)),
            container=str(data.get("container", "directory")),
            verify_package=bool(data.get("verify_package", True)),
            report_formats=tuple(str(f) for f in data.get("report_formats", ("json", "md"))),
        )


INTERNAL_ARCHIVE = DeliveryProfile(
    profile_id="internal-archive",
    display_name="内部工程归档",
    description="完整工程：全部受管数据 + provenance + 依赖审计；外部引用保持引用",
)
REVIEWER_PACKAGE = DeliveryProfile(
    profile_id="reviewer-package",
    display_name="评审包",
    description="面向评审：成果输出（OUTPUT）+ 工程描述，不含中间数据",
    include_outputs_only=True,
)
PAPER_FIGURE_PACKAGE = DeliveryProfile(
    profile_id="paper-figure-package",
    display_name="论文图件包",
    description="图件交付：图/导出件（PNG/SVG/PDF/GeoJSON）",
    include_formats=("png", "svg", "pdf", "geojson"),
    include_provenance=False,
)
GIS_EXCHANGE_PACKAGE = DeliveryProfile(
    profile_id="gis-exchange",
    display_name="GIS 交换包",
    description="GIS 互操作：矢量/栅格交付格式",
    include_formats=("geojson", "shp_bundle", "tif", "tiff"),
    include_provenance=False,
)
MODELING_HANDOFF_PACKAGE = DeliveryProfile(
    profile_id="modeling-handoff",
    display_name="建模交接包",
    description="数值建模交接：FLAC3D/Abaqus 网格与因子网格",
    include_formats=("f3grid", "inp", "factor_grid"),
    include_provenance=False,
)

BUILTIN_PROFILES: dict[str, DeliveryProfile] = {
    p.profile_id: p
    for p in (
        INTERNAL_ARCHIVE, REVIEWER_PACKAGE, PAPER_FIGURE_PACKAGE,
        GIS_EXCHANGE_PACKAGE, MODELING_HANDOFF_PACKAGE,
    )
}


def get_profile(profile_id: str) -> DeliveryProfile:
    profile = BUILTIN_PROFILES.get(profile_id)
    if profile is None:
        raise KeyError(f"未知交付配置: {profile_id}（可用: {sorted(BUILTIN_PROFILES)}）")
    return profile


@dataclass
class DeliveryResult:
    profile_id: str
    package_dir: Path | None = None
    container_path: Path | None = None
    report_path: Path | None = None
    report_markdown_path: Path | None = None
    verify_ok: bool = False
    plan_summary: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)


class DeliveryReportBuilder:
    """Assemble the delivery QA report from observed facts."""

    def __init__(self, *, project_path: Path, catalog=None) -> None:
        self.project_path = Path(project_path)
        self.catalog = catalog

    def build(
        self,
        *,
        profile: DeliveryProfile,
        package_dir: Path | None,
        plan_summary: dict,
        audit: DependencyAuditReport | None = None,
    ) -> dict:
        from paleo_workbench import __version__

        report: dict[str, Any] = {
            "kind": "paleo-delivery-report",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "application": {"name": "paleo-workbench", "version": __version__},
            "project": {"name": self.project_path.name, "path": self.project_path.name},
            "profile": profile.to_dict(),
            "package": {"plan": plan_summary},
            "assets": self._asset_inventory(),
            "crs": self._collect_crs(),
            "warnings": [],
        }
        if audit is not None:
            report["dependencies"] = audit.to_dict()
            missing = [r for r in audit.records if r.status is DependencyStatus.MISSING]
            changed = [r for r in audit.records if r.status is DependencyStatus.CHANGED]
            for record in missing:
                report["warnings"].append(f"缺失依赖: {record.asset_name} ({record.path})")
            for record in changed:
                report["warnings"].append(f"内容变化: {record.asset_name} ({record.detail})")
        if package_dir is not None:
            verify = verify_package(package_dir)
            report["package"]["verified"] = verify.ok
            report["package"]["verify_state"] = (
                "VERIFIED" if verify.ok else "FAILED"
            )
            report["package"]["checked_entries"] = verify.checked_entries
            report["package"]["total_size_bytes"] = verify.total_size_bytes
            report["package"]["issues"] = [i.as_dict() for i in verify.issues]
            if not verify.ok:
                report["warnings"].append("包校验失败：详见 package.issues")
        else:
            report["package"]["verified"] = False
            report["package"]["verify_state"] = "UNVERIFIED"
        return report

    def _asset_inventory(self) -> dict:
        if self.catalog is None:
            return {"count": 0, "by_type": {}, "versions_by_stage": {}}
        by_type: dict[str, int] = {}
        versions_by_stage: dict[str, int] = {}
        names: list[str] = []
        for asset in self.catalog.list_assets():
            by_type[asset.type] = by_type.get(asset.type, 0) + 1
            names.append(asset.name)
            for version in self.catalog.list_versions(asset.id):
                stage = version.stage.value if hasattr(version.stage, "value") else str(version.stage)
                versions_by_stage[stage] = versions_by_stage.get(stage, 0) + 1
        return {
            "count": len(names),
            "by_type": by_type,
            "versions_by_stage": versions_by_stage,
            "names_preview": sorted(names)[:200],
        }

    def _collect_crs(self) -> list[str]:
        crs: set[str] = set()
        if self.catalog is not None:
            for asset in self.catalog.list_assets():
                for version in self.catalog.list_versions(asset.id):
                    version_crs = (version.metadata or {}).get("crs")
                    if version_crs:
                        crs.add(str(version_crs))
        try:
            payload = self.project_path.read_text(encoding="utf-8")
        except OSError:
            return sorted(crs)
        try:
            document = __import__("json").loads(payload)
        except Exception:
            return sorted(crs)
        coordinate = document.get("coordinate") or {}
        for key in ("project_crs", "target_crs", "display_crs"):
            value = coordinate.get(key)
            if value:
                crs.add(str(value))
        for resource in document.get("resources", ()) or ():
            resource_crs = (resource or {}).get("crs")
            if resource_crs:
                crs.add(str(resource_crs))
        return sorted(crs)


def render_report_markdown(report: dict) -> str:
    """Human-readable rendering. UNVERIFIED/FAILED states are shown as-is."""
    lines: list[str] = []
    project = report.get("project", {})
    app = report.get("application", {})
    profile = report.get("profile", {})
    package = report.get("package", {})
    lines.append("# 交付 QA 报告")
    lines.append("")
    lines.append(f"- 工程: {project.get('name', '?')}")
    lines.append(f"- 生成时间: {report.get('generated_at', '?')}")
    lines.append(f"- 软件版本: {app.get('name', '?')} {app.get('version', '?')}")
    lines.append(f"- 交付配置: {profile.get('display_name', '?')} ({profile.get('profile_id', '?')})")
    lines.append(f"- 包校验状态: **{package.get('verify_state', 'UNVERIFIED')}**")
    lines.append(f"- 包大小: {package.get('total_size_bytes', 0)} 字节 / "
                 f"{package.get('checked_entries', 0)} 条目")
    lines.append("")
    assets = report.get("assets", {})
    lines.append("## 资产")
    lines.append(f"- 资产数量: {assets.get('count', 0)}")
    lines.append(f"- 类型分布: {assets.get('by_type', {})}")
    lines.append(f"- 版本阶段分布: {assets.get('versions_by_stage', {})}")
    crs = report.get("crs", [])
    if crs:
        lines.append("")
        lines.append("## 坐标系")
        lines.extend(f"- {c}" for c in crs)
    dependencies = report.get("dependencies")
    if dependencies:
        lines.append("")
        lines.append("## 依赖审计")
        lines.append(f"- 汇总: {dependencies.get('counts', {})}")
        for record in dependencies.get("records", ()):
            if record.get("status") not in ("valid", "unknown"):
                lines.append(
                    f"- ⚠ {record.get('status')}: {record.get('asset')} — {record.get('path')}"
                )
    warnings = report.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("## 警告")
        lines.extend(f"- {w}" for w in warnings)
    lines.append("")
    return "\n".join(lines)


class DeliveryService:
    """Build a delivery package per profile and write QA reports into it."""

    def __init__(self, project_path: Path, *, catalog=None) -> None:
        self.project_path = Path(project_path)
        self.catalog = catalog

    def build(
        self,
        profile: DeliveryProfile | str,
        output_dir: Path,
        *,
        cancel: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> DeliveryResult:
        cancel = cancel or NULL_CANCEL
        progress = progress or _null_progress
        if isinstance(profile, str):
            profile = get_profile(profile)
        builder = PackageBuilder(
            self.project_path,
            catalog=self.catalog,
            options=PackageOptions(
                external_policy=profile.external_policy,
                include_outputs_only=profile.include_outputs_only,
                include_formats=profile.include_formats,
                include_provenance=profile.include_provenance,
            ),
        )
        plan = builder.plan()
        result = DeliveryResult(
            profile_id=profile.profile_id, plan_summary=plan.summary()
        )
        # Directory first: reports are written INTO the package so even the
        # zip container ships with its QA report.
        build = builder.build(output_dir, cancel=cancel, progress=progress)
        result.package_dir = build.package_dir

        audit = ExternalDependencyAuditor(self.catalog).audit(cancel=cancel) \
            if self.catalog is not None else None
        report_builder = DeliveryReportBuilder(project_path=self.project_path, catalog=self.catalog)
        report = report_builder.build(
            profile=profile,
            package_dir=result.package_dir if profile.verify_package else None,
            plan_summary=plan.summary(),
            audit=audit,
        )
        result.report = report
        result.verify_ok = bool(report.get("package", {}).get("verified", False))
        result.report_path, result.report_markdown_path = self._write_reports(
            report, result.package_dir, profile
        )
        if profile.container == "zip":
            from paleo_workbench.interchange.package.builder import zip_package_dir

            result.container_path = zip_package_dir(
                result.package_dir,
                output_dir / f"{builder.project_name}.paleopkg.zip",
                cancel=cancel,
            )
        return result

    def _write_reports(self, report: dict, package_dir: Path | None, profile: DeliveryProfile):
        json_path = md_path = None
        if package_dir is None or not profile.report_formats:
            return json_path, md_path
        if "json" in profile.report_formats:
            json_path = package_dir / "delivery-report.json"
            tmp = package_dir / ".delivery-report.json.tmp"
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            os_replace_atomic(tmp, json_path)
        if "md" in profile.report_formats:
            md_path = package_dir / "delivery-report.md"
            tmp = package_dir / ".delivery-report.md.tmp"
            tmp.write_text(render_report_markdown(report), encoding="utf-8")
            os_replace_atomic(tmp, md_path)
        return json_path, md_path
