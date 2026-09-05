"""PackageBuilder: project → portable package directory (or zip).

Nothing is silently omitted: the resulting :class:`PackagePlan` records every
catalog version as included / external / missing / stale / excluded. Building
streams every payload once (no full-file in-memory copies), hashes each file
exactly once, and publishes the staging tree with a single atomic rename.
"""

from __future__ import annotations

import enum
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.interchange.contracts import (
    CancelToken,
    NULL_CANCEL,
    ProgressCallback,
    _null_progress,
)
from paleo_workbench.interchange.path_safety import (
    os_replace_atomic,
    safe_relative_path,
)
from paleo_workbench.interchange.package.manifest import (
    MANIFEST_FILENAME,
    PackageEntry,
    PackageManifest,
    write_manifest,
)

# Artifacts subdirs copied into packages, and those excluded by policy.
INCLUDE_ARTIFACT_DIRS = ("raw", "derived", "intermediate", "outputs", "metadata", "blobs")
EXCLUDE_ARTIFACT_DIRS = ("working", "trash", "cache", "thumbnails")
# The sqlite index is machine-buildable state, not portable truth: on reopen
# the service rebuilds it from catalog.json (documented resolution order).
EXCLUDED_METADATA_FILES = ("catalog.sqlite", "catalog.sqlite-wal", "catalog.sqlite-shm")

EXTERNAL_FINGERPRINT_MAX_BYTES = 8 * 1024 * 1024 * 1024


class ExternalPolicy(str, enum.Enum):
    KEEP = "keep"          # stay referenced; recorded in the manifest
    VENDOR = "vendor"      # copied into the package under artifacts/external/
    EXCLUDE = "exclude"    # dropped with an explicit manifest record


@dataclass
class PackageOptions:
    external_policy: ExternalPolicy = ExternalPolicy.KEEP
    include_outputs_only: bool = False  # True: only OUTPUT-stage payloads
    include_provenance: bool = True


@dataclass
class PackageItem:
    version_id: str | None
    asset_name: str
    path: str  # source absolute path
    size_bytes: int
    stage: str
    status: str  # "included" | "external" | "missing" | "stale" | "excluded"
    detail: str = ""


@dataclass
class PackagePlan:
    project_file: str
    items: list[PackageItem] = field(default_factory=list)
    excluded_dirs: list[str] = field(default_factory=list)
    estimated_bytes: int = 0

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.status] = counts.get(item.status, 0) + 1
        return {
            "project_file": self.project_file,
            "counts": counts,
            "estimated_bytes": self.estimated_bytes,
            "excluded_dirs": list(self.excluded_dirs),
        }


@dataclass
class BuildResult:
    package_dir: Path
    manifest_path: Path
    project_path: Path
    manifest: PackageManifest
    plan: PackagePlan


def _stage_of(version) -> str:
    return version.stage.value if hasattr(version.stage, "value") else str(version.stage)


class PackageBuilder:
    """Build a portable package from a project (+ its catalog when present)."""

    def __init__(
        self,
        project_path: Path,
        *,
        catalog=None,
        options: PackageOptions | None = None,
    ) -> None:
        self.project_path = Path(project_path).resolve()
        if not self.project_path.name.endswith(".paleo.json"):
            raise ValueError(f"不是工程文件: {self.project_path.name}")
        self.catalog = catalog
        self.options = options or PackageOptions()
        self.project_name = self.project_path.name.removesuffix(".paleo.json")
        self.artifacts_dir = self.project_path.with_name(f"{self.project_name}.artifacts")

    # -- plan ---------------------------------------------------------------
    def plan(self) -> PackagePlan:
        plan = PackagePlan(project_file=self.project_path.name)
        plan.excluded_dirs = list(EXCLUDE_ARTIFACT_DIRS)
        plan.estimated_bytes += self.project_path.stat().st_size
        plan.items.append(
            PackageItem(
                version_id=None,
                asset_name=self.project_path.name,
                path=str(self.project_path),
                size_bytes=self.project_path.stat().st_size,
                stage="project",
                status="included",
            )
        )
        for version, asset_name, payload_path in self._iter_catalog_versions():
            stage = _stage_of(version)
            if not version.managed:
                plan.items.append(PackageItem(
                    version.id, asset_name, str(payload_path),
                    payload_path.stat().st_size if payload_path.is_file() else 0,
                    stage, "external", "外部引用（按策略处理）",
                ))
                continue
            if not payload_path.is_file():
                plan.items.append(PackageItem(
                    version.id, asset_name, str(payload_path), 0, stage, "missing",
                    "managed payload 不存在",
                ))
                continue
            if self.options.include_outputs_only and stage != "output":
                plan.items.append(PackageItem(
                    version.id, asset_name, str(payload_path), payload_path.stat().st_size,
                    stage, "excluded", "include_outputs_only 策略",
                ))
                continue
            size = payload_path.stat().st_size
            expected = version.size_bytes
            stale = expected is not None and expected != size
            if stale:
                plan.items.append(PackageItem(
                    version.id, asset_name, str(payload_path), size, stage, "stale",
                    "size 与 catalog 记录不一致（内容可能被改动）",
                ))
            plan.estimated_bytes += size
            plan.items.append(PackageItem(
                version.id, asset_name, str(payload_path), size, stage, "included",
            ))
        return plan

    # -- build --------------------------------------------------------------
    def build(
        self,
        output_dir: Path,
        *,
        cancel: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> BuildResult:
        cancel = cancel or NULL_CANCEL
        progress = progress or _null_progress
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        package_dir = output_dir / self.project_name
        if package_dir.exists():
            raise FileExistsError(f"包目录已存在: {package_dir}")
        staging = output_dir / f".{self.project_name}.staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            return self._build_into(staging, package_dir, cancel, progress)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def build_zip(self, output_dir: Path, *, cancel=None, progress=None) -> Path:
        """Build the package directory and zip it next to it."""
        import zipfile

        result = self.build(output_dir, cancel=cancel, progress=progress)
        zip_path = result.package_dir.with_name(f"{result.package_dir.name}.paleopkg.zip")
        cancel = cancel or NULL_CANCEL
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            for path in sorted(result.package_dir.rglob("*")):
                cancel.checkpoint()
                if path.is_symlink():
                    raise ValueError(f"包内出现符号链接: {path}")
                if path.is_file():
                    bundle.write(path, path.relative_to(result.package_dir).as_posix())
        return zip_path

    # -- internals ----------------------------------------------------------
    def _build_into(self, staging: Path, package_dir: Path, cancel, progress) -> BuildResult:
        from paleo_workbench import __version__

        plan = self.plan()
        manifest = PackageManifest(
            project_name=self.project_name,
            project_file=self.project_path.name,
            created_at=datetime.now(timezone.utc).isoformat(),
            application_version=__version__,
            options={
                "external_policy": self.options.external_policy.value,
                "include_outputs_only": self.options.include_outputs_only,
            },
        )

        # 1) project file
        cancel.checkpoint()
        progress(0.05, "打包工程文件")
        manifest.entries.append(
            self._copy_payload(self.project_path, self.project_path.name, staging, kind="project")
        )

        # 2) managed artifacts directory (payloads + portable catalog manifest)
        if self.artifacts_dir.is_dir():
            progress(0.15, "打包受管数据")
            if self.catalog is not None:
                # Checkpoint the portable truth so the package never ships a
                # stale manifest while the live catalog is still open.
                self.catalog.export_manifest()
            copied = self._copy_artifacts_tree(staging, manifest, cancel)
            progress(0.7, f"已复制 {copied} 个受管文件")

        # 3) external references per policy
        progress(0.8, "处理外部引用")
        self._handle_externals(plan, staging, manifest)

        # 4) missing deps / generated outputs / provenance
        for item in plan.items:
            if item.status == "missing":
                manifest.missing_dependencies.append(
                    {"version_id": item.version_id, "asset": item.asset_name,
                     "path": item.path, "reason": item.detail}
                )
        self._record_provenance(manifest)

        manifest.total_size_bytes = sum(e.size_bytes for e in manifest.entries)
        cancel.checkpoint()
        progress(0.95, "写入 manifest")
        write_manifest(manifest, staging)
        # single atomic publish: staging tree → final name
        os_replace_atomic(staging, package_dir)
        progress(1.0, "打包完成")
        return BuildResult(
            package_dir=package_dir,
            manifest_path=package_dir / MANIFEST_FILENAME,
            project_path=package_dir / self.project_path.name,
            manifest=manifest,
            plan=plan,
        )

    def _copy_payload(self, source: Path, rel_name: str, staging: Path, *, kind: str) -> PackageEntry:
        digest = sha256_file(source)
        size = source.stat().st_size
        target = staging / rel_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return PackageEntry(path=rel_name, sha256=digest, size_bytes=size, kind=kind)

    def _copy_artifacts_tree(self, staging: Path, manifest: PackageManifest, cancel) -> int:
        copied = 0
        for dir_name in INCLUDE_ARTIFACT_DIRS:
            source_dir = self.artifacts_dir / dir_name
            if not source_dir.is_dir():
                continue
            for source in sorted(source_dir.rglob("*")):
                cancel.checkpoint()
                if source.is_dir():
                    continue
                if source.is_symlink():
                    raise ValueError(f"受管数据中出现符号链接: {source}")
                if dir_name == "metadata" and source.name in EXCLUDED_METADATA_FILES:
                    continue
                rel = source.relative_to(self.artifacts_dir.parent).as_posix()
                safe_relative_path(rel, what="artifact path")
                target = staging / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                manifest.entries.append(PackageEntry(
                    path=rel, sha256=sha256_file(source),
                    size_bytes=source.stat().st_size,
                    kind="metadata" if dir_name == "metadata" else "artifact",
                ))
                copied += 1
        return copied

    def _handle_externals(self, plan: PackagePlan, staging: Path, manifest: PackageManifest) -> None:
        policy = self.options.external_policy
        for item in plan.items:
            if item.status != "external":
                continue
            record: dict = {
                "version_id": item.version_id,
                "asset": item.asset_name,
                "path": item.path,
                "size_bytes": item.size_bytes,
            }
            if policy is ExternalPolicy.KEEP:
                record["policy"] = "keep"
                manifest.external_dependencies.append(record)
            elif policy is ExternalPolicy.EXCLUDE:
                record["policy"] = "exclude"
                manifest.external_dependencies.append(record)
            elif policy is ExternalPolicy.VENDOR:
                source = Path(item.path)
                if not source.is_file():
                    record["policy"] = "missing"
                    manifest.missing_dependencies.append(record)
                    continue
                rel = f"artifacts/external/{item.asset_name}/{source.name}"
                safe_relative_path(rel, what="vendored external")
                manifest.entries.append(self._copy_payload(source, rel, staging, kind="artifact"))
                record["policy"] = "vendor"
                record["packaged_path"] = rel
                manifest.external_dependencies.append(record)

    def _record_provenance(self, manifest: PackageManifest) -> None:
        if not self.options.include_provenance or self.catalog is None:
            return
        runs: list[dict] = []
        outputs: list[str] = []
        try:
            for run in self.catalog.list_runs():
                runs.append({"id": run.id, "operation": run.operation, "status": run.status})
            for asset in self.catalog.list_assets():
                for version in self.catalog.list_versions(asset.id):
                    if _stage_of(version) == "output":
                        outputs.append(version.id)
        except Exception:
            return
        manifest.provenance = {"runs": runs[:1000], "run_count": len(runs)}
        manifest.generated_outputs = outputs[:1000]

    def _iter_catalog_versions(self):
        if self.catalog is not None:
            for asset in self.catalog.list_assets():
                for version in self.catalog.list_versions(asset.id):
                    try:
                        payload = self.catalog.resolve_path(version)
                    except Exception:
                        payload = self.project_path.parent / version.path
                    yield version, asset.name, Path(payload)
        else:
            yield from self._iter_project_resources()

    def _iter_project_resources(self):
        """Catalog-less fallback: external resources straight from the project
        JSON so external references are still declared (never silent)."""
        try:
            payload = json.loads(self.project_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        project_dir = self.project_path.parent
        for resource in payload.get("resources", ()) or ():
            if not isinstance(resource, dict):
                continue
            raw_path = str(resource.get("path", ""))
            if not raw_path:
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = project_dir / candidate
            yield _ResourceShim(resource), str(resource.get("name", raw_path)), candidate


class _ResourceShim:
    """Minimal read-only stand-in mirroring the DataVersion surface the
    builder consumes (managed / id / stage / size_bytes) for legacy
    ResourceItems when no catalog is open."""

    def __init__(self, resource: dict) -> None:
        self.id = str(resource.get("id", ""))
        self.managed = not bool(resource.get("external", False))
        self.stage = "input"
        self.size_bytes = None
        self.path = str(resource.get("path", ""))
