"""Portable project package (I10-I12): manifest V2, builder, verifier.

A package is a *directory* shaped exactly like a portable project root::

    <pkg>/<name>.paleo.json
    <pkg>/<name>.artifacts/{raw,derived,intermediate,outputs,metadata,blobs}/...
    <pkg>/manifest.json

so "copy the directory to a new root" IS the restore operation; a zip
container is optional transport. The manifest is a projection of catalog
state — the catalog remains the lifecycle authority, the package never
becomes a second one.
"""

from __future__ import annotations

from paleo_workbench.interchange.package.manifest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    PackageEntry,
    PackageManifest,
)
from paleo_workbench.interchange.package.builder import (
    BuildResult,
    ExternalPolicy,
    PackageBuilder,
    PackageOptions,
    PackagePlan,
)
from paleo_workbench.interchange.package.verifier import (
    PackageVerifyReport,
    open_package,
    verify_package,
)

__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "BuildResult",
    "ExternalPolicy",
    "PackageBuilder",
    "PackageOptions",
    "PackageEntry",
    "PackageManifest",
    "PackagePlan",
    "PackageVerifyReport",
    "open_package",
    "verify_package",
]
