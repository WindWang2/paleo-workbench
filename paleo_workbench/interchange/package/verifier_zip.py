"""Verification of ``.paleopkg.zip`` containers without extracting them."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from paleo_workbench.interchange.package.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_KIND,
    SUPPORTED_SCHEMA_VERSIONS,
    PackageManifest,
)
from paleo_workbench.interchange.package.verifier import (
    KNOWN_PACKAGE_EXTRA_FILES,
    VerifyIssue,
    PackageVerifyReport,
)
from paleo_workbench.interchange.path_safety import UnsafePathError, safe_members

_HASH_CHUNK = 1024 * 1024


def _hash_zip_member(bundle: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with bundle.open(info) as stream:
        while True:
            chunk = stream.read(_HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_zip_container(zip_path: Path, *, deep: bool = True) -> PackageVerifyReport:
    report = PackageVerifyReport(package_path=str(zip_path), manifest=None)
    try:
        bundle = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        report.issues.append(VerifyIssue("error", "bad-zip", f"zip 容器损坏: {exc}"))
        return report

    with bundle:
        try:
            names = safe_members(bundle, what="package zip")
        except UnsafePathError as exc:
            report.issues.append(VerifyIssue("error", "unsafe-zip-entry", str(exc)))
            return report
        names_set = set(names)
        if MANIFEST_FILENAME not in names_set:
            report.issues.append(VerifyIssue("error", "missing-manifest", "缺少 manifest.json"))
            return report

        try:
            manifest = PackageManifest.from_dict(
                json.loads(bundle.read(MANIFEST_FILENAME).decode("utf-8"))
            )
            manifest.validate_paths()
        except (UnsafePathError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
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

        infos = {name: info for name, info in zip(names, bundle.infolist())}
        for key in (manifest.project_file,):
            if key and key in infos:
                try:
                    json.loads(bundle.read(infos[key]).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    report.issues.append(VerifyIssue("error", "corrupt-project", f"工程文件损坏: {exc}"))
            elif key:
                report.issues.append(VerifyIssue("error", "missing-project", "工程文件缺失"))
        catalog_rel = (
            f"{manifest.project_name}.artifacts/metadata/catalog.json"
            if manifest.project_name else ""
        )
        if catalog_rel and catalog_rel in infos:
            try:
                json.loads(bundle.read(infos[catalog_rel]).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                report.issues.append(VerifyIssue("error", "corrupt-catalog", f"catalog manifest 损坏: {exc}"))
        elif catalog_rel:
            report.issues.append(VerifyIssue(
                "warning", "no-catalog", "包内无 portable catalog manifest（仅工程文件包）"
            ))

        for entry in manifest.entries:
            info = infos.get(entry.path)
            if info is None:
                report.issues.append(VerifyIssue("error", "missing-entry", f"条目缺失: {entry.path}"))
                continue
            if info.is_dir():
                report.issues.append(VerifyIssue(
                    "error", "entry-is-directory", f"条目是目录而非文件: {entry.path}"
                ))
                continue
            report.checked_entries += 1
            report.total_size_bytes += info.file_size
            if info.file_size != entry.size_bytes:
                report.issues.append(VerifyIssue(
                    "error", "size-mismatch",
                    f"{entry.path}: 记录 {entry.size_bytes}B 实际 {info.file_size}B",
                ))
                continue
            if deep and _hash_zip_member(bundle, info) != entry.sha256:
                report.issues.append(VerifyIssue(
                    "error", "checksum-mismatch", f"{entry.path}: sha256 不匹配"
                ))

        known = manifest.entry_paths() | {MANIFEST_FILENAME} | set(KNOWN_PACKAGE_EXTRA_FILES)
        for name in names:
            if name not in known:
                report.issues.append(VerifyIssue(
                    "warning", "unknown-file", f"manifest 之外的文件: {name}"
                ))
    return report
