"""Package manifest V2: portable, checksummed, path-safe.

Rules:
- Every path is a package-relative POSIX path, validated by
  :func:`paleo_workbench.interchange.path_safety.safe_relative_path` on both
  write and read. Machine-local absolute paths may appear ONLY in the
  explicit ``external_dependencies`` list (that is their purpose) — never as
  the location of packaged content.
- Content integrity: sha256 + byte size per entry; ``total_size_bytes`` for
  quick capacity checks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.interchange.path_safety import safe_relative_path

MANIFEST_FILENAME = "manifest.json"
MANIFEST_KIND = "paleo-package"
MANIFEST_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (2,)


@dataclass
class PackageEntry:
    path: str  # package-relative POSIX
    sha256: str
    size_bytes: int
    kind: str = "artifact"  # "project" | "artifact" | "metadata"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PackageEntry":
        return cls(
            path=str(data["path"]),
            sha256=str(data["sha256"]),
            size_bytes=int(data["size_bytes"]),
            kind=str(data.get("kind", "artifact")),
        )


@dataclass
class PackageManifest:
    kind: str = MANIFEST_KIND
    schema_version: int = MANIFEST_SCHEMA_VERSION
    project_name: str = ""
    project_file: str = ""  # package-relative path of the .paleo.json
    created_at: str = ""
    application_name: str = "paleo-workbench"
    application_version: str = ""
    entries: list[PackageEntry] = field(default_factory=list)
    external_dependencies: list[dict[str, Any]] = field(default_factory=list)
    missing_dependencies: list[dict[str, Any]] = field(default_factory=list)
    generated_outputs: list[str] = field(default_factory=list)  # version ids
    provenance: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    total_size_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "schema_version": self.schema_version,
            "project": {"name": self.project_name, "file": self.project_file},
            "created_at": self.created_at,
            "application": {
                "name": self.application_name,
                "version": self.application_version,
            },
            "entries": [entry.to_dict() for entry in self.entries],
            "external_dependencies": list(self.external_dependencies),
            "missing_dependencies": list(self.missing_dependencies),
            "generated_outputs": list(self.generated_outputs),
            "provenance": dict(self.provenance),
            "options": dict(self.options),
            "total_size_bytes": self.total_size_bytes,
            "entry_count": len(self.entries),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PackageManifest":
        project = data.get("project") or {}
        application = data.get("application") or {}
        raw_version = data.get("schema_version", 0)
        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            raise ValueError(f"schema_version 必须是整数，得到 {raw_version!r}")
        return cls(
            kind=str(data.get("kind", MANIFEST_KIND)),
            schema_version=raw_version,
            project_name=str(project.get("name", "")),
            project_file=str(project.get("file", "")),
            created_at=str(data.get("created_at", "")),
            application_name=str(application.get("name", "paleo-workbench")),
            application_version=str(application.get("version", "")),
            entries=[PackageEntry.from_dict(e) for e in data.get("entries", ())],
            external_dependencies=list(data.get("external_dependencies", ())),
            missing_dependencies=list(data.get("missing_dependencies", ())),
            generated_outputs=[str(v) for v in data.get("generated_outputs", ())],
            provenance=dict(data.get("provenance", {})),
            options=dict(data.get("options", {})),
            total_size_bytes=int(data.get("total_size_bytes", 0)),
        )

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1)

    def entry_paths(self) -> set[str]:
        return {entry.path for entry in self.entries}

    def validate_paths(self) -> None:
        """Fail-closed: every stored path must be a safe, collision-free
        relative path (duplicates after NFC/casefold are rejected)."""
        from paleo_workbench.interchange.path_safety import check_collision

        seen_casefold: set[str] = set()
        seen_nfc: set[str] = set()
        for entry in self.entries:
            pure = safe_relative_path(entry.path, what="manifest entry")
            check_collision(pure, seen_casefold, seen_nfc)
        if self.project_file:
            safe_relative_path(self.project_file, what="manifest project file")


def write_manifest(manifest: PackageManifest, package_root: Path) -> Path:
    manifest.validate_paths()
    target = Path(package_root) / MANIFEST_FILENAME
    payload = manifest.dumps()
    from paleo_workbench.resources.exporters import atomic_output

    with atomic_output(target) as tmp:
        tmp.write_text(payload, encoding="utf-8")
    return target


def read_manifest(package_root: Path) -> PackageManifest:
    """Parse manifest.json; raises ValueError on corrupt JSON or unsafe paths."""
    path = Path(package_root) / MANIFEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = PackageManifest.from_dict(payload)
    manifest.validate_paths()
    return manifest
