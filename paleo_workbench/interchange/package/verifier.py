"""Package verification and safe (re)opening.

``verify_package`` checks structure, integrity and safety of a package
directory or ``.paleopkg.zip`` container:

- manifest present / parseable / supported schema
- every entry exists, sizes match, sha256 matches (checksum mismatch is an
  error, never a warning)
- paths are safe relative paths (traversal rejected at parse time already)
- symlinks anywhere in the package are rejected
- the project file and the portable catalog manifest parse
- unknown extra files are reported (warning-level, policy-dependent)

``open_package`` materializes a package at a destination and validates it
fail-closed *before* returning the project path; zip extraction validates all
member names first so a malicious archive never writes a single byte.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.interchange.package.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_KIND,
    SUPPORTED_SCHEMA_VERSIONS,
    PackageManifest,
    read_manifest,
)
from paleo_workbench.interchange.path_safety import (
    UnsafePathError,
    check_collision,
    extract_archive,
    safe_relative_path,
)


@dataclass(frozen=True)
class VerifyIssue:
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class PackageVerifyReport:
    package_path: str
    manifest: PackageManifest | None
    issues: list[VerifyIssue] = field(default_factory=list)
    checked_entries: int = 0
    total_size_bytes: int = 0

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def errors(self) -> list[VerifyIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self) -> list[VerifyIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "package_path": self.package_path,
            "ok": self.ok,
            "checked_entries": self.checked_entries,
            "total_size_bytes": self.total_size_bytes,
            "issues": [i.as_dict() for i in self.issues],
            "project_name": self.manifest.project_name if self.manifest else "",
        }


def materialize_package(package_path: Path, dest_dir: Path) -> Path:
    """Materialize a package container at *dest_dir*; returns the package dir.

    Fail-closed: for zip containers every member name is validated (traversal,
    symlinks, collisions) before any byte is written. A plain directory is
    copied with symlink rejection.
    """
    package_path = Path(package_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(package_path):
        target = dest_dir / package_path.stem.removesuffix(".paleopkg")
        if target.exists():
            raise FileExistsError(f"目标已存在: {target}")
        staging = dest_dir / f".{target.name}.staging"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        try:
            with zipfile.ZipFile(package_path) as bundle:
                extract_archive(bundle, staging, what="package")
            staging.rename(target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target
    if package_path.is_dir():
        target = dest_dir / package_path.name
        if target.exists():
            raise FileExistsError(f"目标已存在: {target}")
        staging = dest_dir / f".{target.name}.staging"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            shutil.copytree(
                package_path, staging, symlinks=False,
                ignore=shutil.ignore_patterns("*.staging"),
            )
            staging.rename(target)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return target
    raise ValueError(f"无法识别的包: {package_path}")


def verify_package(package_path: Path, *, deep: bool = True) -> PackageVerifyReport:
    """Verify a package directory or zip container. Read-only."""
    from paleo_workbench.interchange.package.verifier_zip import (
        verify_zip_container,
    )

    package_path = Path(package_path)
    if zipfile.is_zipfile(package_path):
        return verify_zip_container(package_path, deep=deep)
    return _verify_directory(package_path, deep=deep)


# Delivery report files live inside the package but are not manifest entries;
# treat them as known so re-verification doesn't warn about them.
KNOWN_PACKAGE_EXTRA_FILES = frozenset({"delivery-report.json", "delivery-report.md"})


def _verify_directory(package_root: Path, *, deep: bool) -> PackageVerifyReport:
    report = PackageVerifyReport(package_path=str(package_root), manifest=None)
    root = package_root
    if not root.is_dir():
        report.issues.append(VerifyIssue("error", "missing-package", f"包目录不存在: {root}"))
        return report

    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        report.issues.append(VerifyIssue("error", "missing-manifest", "缺少 manifest.json"))
        return report
    try:
        manifest = read_manifest(root)
    except UnsafePathError as exc:
        report.issues.append(VerifyIssue("error", "unsafe-manifest-path", str(exc)))
        return report
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        report.issues.append(VerifyIssue("error", "corrupt-manifest", f"manifest 解析失败: {exc}"))
        return report
    report.manifest = manifest

    if manifest.kind != MANIFEST_KIND:
        report.issues.append(VerifyIssue("error", "wrong-kind", f"manifest kind={manifest.kind!r}"))
    if manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        report.issues.append(VerifyIssue(
            "error", "unsupported-schema",
            f"manifest schema_version={manifest.schema_version}，支持 {SUPPORTED_SCHEMA_VERSIONS}",
        ))

    project_file = root / manifest.project_file if manifest.project_file else None
    if not project_file or not project_file.is_file():
        report.issues.append(VerifyIssue("error", "missing-project", "工程文件缺失"))
    else:
        try:
            json.loads(project_file.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            report.issues.append(VerifyIssue("error", "corrupt-project", f"工程文件损坏: {exc}"))

    catalog_manifest = root / f"{manifest.project_name}.artifacts" / "metadata" / "catalog.json"
    if catalog_manifest.is_file():
        try:
            json.loads(catalog_manifest.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            report.issues.append(VerifyIssue("error", "corrupt-catalog", f"catalog manifest 损坏: {exc}"))
    else:
        report.issues.append(VerifyIssue(
            "warning", "no-catalog", "包内无 portable catalog manifest（仅工程文件包）"
        ))

    seen_casefold: set[str] = set()
    seen_nfc: set[str] = set()
    for entry in manifest.entries:
        try:
            pure = safe_relative_path(entry.path, what="manifest entry")
            check_collision(pure, seen_casefold, seen_nfc)
        except UnsafePathError as exc:
            report.issues.append(VerifyIssue("error", "unsafe-entry", str(exc)))
            continue
        target = root / entry.path
        if target.is_symlink():
            report.issues.append(VerifyIssue("error", "symlink-entry", f"条目是符号链接: {entry.path}"))
            continue
        if not target.is_file():
            report.issues.append(VerifyIssue("error", "missing-entry", f"条目缺失: {entry.path}"))
            continue
        size = target.stat().st_size
        report.checked_entries += 1
        report.total_size_bytes += size
        if size != entry.size_bytes:
            report.issues.append(VerifyIssue(
                "error", "size-mismatch",
                f"{entry.path}: 记录 {entry.size_bytes}B 实际 {size}B",
            ))
            continue
        if deep:
            digest = sha256_file(target)
            if digest != entry.sha256:
                report.issues.append(VerifyIssue(
                    "error", "checksum-mismatch", f"{entry.path}: sha256 不匹配"
                ))

    # unknown files present in the package but absent from the manifest
    known = manifest.entry_paths() | {MANIFEST_FILENAME} | KNOWN_PACKAGE_EXTRA_FILES
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if rel in known:
            continue
        if path.is_symlink():
            report.issues.append(VerifyIssue("error", "symlink-extra", f"未知符号链接: {rel}"))
        elif path.is_file():
            report.issues.append(VerifyIssue(
                "warning", "unknown-file", f"manifest 之外的文件: {rel}"
            ))
    return report


def open_package(package_path: Path, dest_dir: Path, *, deep: bool = True) -> tuple[Path, PackageVerifyReport]:
    """Materialize + verify a package at *dest_dir*; returns (package_dir,
    report). Raises on unsafe materialization; a failing verify leaves the
    extracted directory in place but the report says exactly why it is not
    openable (callers must not open projects from a failed report)."""
    package_dir = materialize_package(package_path, dest_dir)
    report = verify_package(package_dir, deep=deep)
    return package_dir, report
