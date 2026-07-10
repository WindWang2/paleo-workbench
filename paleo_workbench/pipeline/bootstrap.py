from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import CompilationRun, ProjectDocument
from paleo_workbench.resources.scanner import scan_resources

DEFAULT_SKIP_CHECKSUM = 50 * 1024 * 1024


@dataclass
class BootstrapResult:
    document: ProjectDocument
    skipped: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def resolve_sample_data_root(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve sample data directory.

    Order: explicit → PALEO_SAMPLE_DATA → cwd/data → walk parents for data/ with 井曲线.
    """
    if explicit is not None:
        return Path(explicit)
    environ = env if env is not None else os.environ
    if environ.get("PALEO_SAMPLE_DATA"):
        return Path(environ["PALEO_SAMPLE_DATA"])
    base = cwd if cwd is not None else Path.cwd()
    candidate = base / "data"
    if candidate.is_dir():
        return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        repo_data = parent / "data"
        if repo_data.is_dir() and (repo_data / "井曲线").exists():
            return repo_data
    raise FileNotFoundError(
        "Could not resolve sample data root. Pass data_root, set PALEO_SAMPLE_DATA, "
        "or run from repo with data/ present."
    )


def bootstrap_sample_project(
    data_root: Path,
    *,
    project_name: str = "惠西南样例工程",
    region: str = "惠西南",
    project_path: Path | None = None,
    skip_checksum_over_bytes: int = DEFAULT_SKIP_CHECKSUM,
) -> BootstrapResult:
    root = Path(data_root)
    if not root.is_dir():
        raise FileNotFoundError(f"data_root is not a directory: {root}")

    skipped: list[dict[str, str]] = []
    try:
        resources = scan_resources(
            root,
            project_path=project_path,
            skip_checksum_over_bytes=skip_checksum_over_bytes,
        )
    except OSError as e:
        raise OSError(f"failed to scan {root}: {e}") from e

    # Tag rel_dir for grouping (best-effort).
    root_resolved = root.resolve()
    for res in resources:
        try:
            p = Path(res.path)
            if not p.is_absolute():
                res.parsed_summary.setdefault("rel_dir", str(Path(res.path).parent))
            else:
                try:
                    rel = Path(res.path).resolve().relative_to(root_resolved)
                    res.parsed_summary["rel_dir"] = (
                        str(rel.parent) if rel.parent != Path(".") else ""
                    )
                except ValueError:
                    res.parsed_summary.setdefault("rel_dir", "")
        except OSError as e:
            skipped.append({"path": res.path, "reason": str(e)})

    if not resources:
        raise ValueError("no files under data_root")

    doc = ProjectDocument.new(name=project_name, region=region)
    if project_path is not None:
        doc.meta.project_root = str(Path(project_path).parent)
    else:
        doc.meta.project_root = str(root.parent)

    doc.resources = resources

    horizons = sorted(Path(r.name).stem for r in resources if r.type == "horizon")
    wells = sorted(Path(r.name).stem for r in resources if r.type == "well_log")
    seismic_names = sorted(r.name for r in resources if r.type == "seismic")

    doc.stratigraphy.target_horizon = horizons[0] if horizons else ""
    doc.stratigraphy.sequence_boundaries = horizons
    doc.stratigraphy.applicable_wells = wells
    doc.stratigraphy.applicable_seismic_ranges = seismic_names

    doc.compilation_runs.append(
        CompilationRun(
            name=f"{project_name} 演示编制",
            target_horizon=doc.stratigraphy.target_horizon,
            status="draft",
        )
    )

    by_type: dict[str, int] = {}
    for r in resources:
        by_type[r.type] = by_type.get(r.type, 0) + 1

    return BootstrapResult(
        document=doc,
        skipped=skipped,
        stats={"files": len(resources), "by_type": by_type},
    )


def write_project(doc: ProjectDocument, path: Path) -> Path:
    target = Path(path)
    if not target.name.endswith(".paleo.json"):
        if target.name.endswith(".json"):
            target = target.with_name(target.name[: -len(".json")] + ".paleo.json")
        else:
            target = target.with_name(target.name + ".paleo.json")
    ProjectManager(target).save(doc)
    return target


if __name__ == "__main__":
    from paleo_workbench.pipeline.__main__ import main

    raise SystemExit(main())
