#!/usr/bin/env python3
"""Freeze resources/scanner.py + import_service.py as a C++ replay oracle.

Builds a deterministic fixture tree (files with fixed content/mtime) and
freezes: per-file ResourceItem fields, collect warnings, filtered paths,
ImportReport aggregates and summary_text.

Paths are frozen as BASENAMES/relative forms only (tmp dirs differ per
machine); the C++ replay re-materializes the same tree and compares the
relative/portable surfaces.

Run:  python tools/oracle/generate_import_oracle.py
Out:  libs/ui_data_core/ui_data_core_tests/fixtures/import_oracle.json
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.resources.import_service import (  # noqa: E402
    import_files,
    import_folder,
)
from paleo_workbench.resources.scanner import scan_resources  # noqa: E402
from paleo_workbench.resources.geojson_layers import (  # noqa: E402
    _group_stem,
    _stable_group_id,
    normalize_facies_layer_role,
)

OUT = (
    Path(__file__).resolve().parents[2]
    / "libs"
    / "ui_data_core"
    / "ui_data_core_tests"
    / "fixtures"
    / "import_oracle.json"
)

MTIME = 1_700_000_000  # fixed mtime for deterministic isoformat


def write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    os.utime(path, (MTIME, MTIME))


def item_json(r, root: Path) -> dict:
    # Absolute stored paths freeze as tree-relative; project-relative and
    # external forms pass through verbatim.
    path = r.path
    if Path(path).is_absolute():
        try:
            path = Path(path).resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            path = Path(path).name
    return {
        "path": path,
        "name": r.name,
        "type": r.type,
        "format": r.format,
        "status": r.status,
        "source": r.source,
        "external": r.external,
        "checksum": r.checksum,
        "artifact_role": r.artifact_role,
        "tags": list(r.tags or []),
        "parsed_summary": normalize_summary(r, path),
    }


def normalize_summary(r, frozen_path: str) -> dict:
    """facies_product_group_id digests the absolute parent dir at runtime;
    re-key it over the frozen (fixture-relative) parent so the id is
    portable across machines."""
    summary = dict(r.parsed_summary or {})
    if summary.get("facies_product_group_id"):
        role = normalize_facies_layer_role(summary.get("geojson_layer_role"))
        src = str(summary.get("facies_product_source_id") or "").strip()
        if role and not src:
            parent = Path(frozen_path).parent.as_posix()
            key = f"path:{parent}:{_group_stem(r.name, role)}"
            summary["facies_product_group_id"] = _stable_group_id(key)
    return summary


def rel_or_name(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return p.name


def report_json(rep, root: Path) -> dict:
    return {
        "added": [item_json(r, root) for r in rep.added],
        "skipped_path": [rel_or_name(p, root) for p in rep.skipped_path],
        "skipped_checksum": [rel_or_name(p, root) for p in rep.skipped_checksum],
        "skipped_filter": [rel_or_name(p, root) for p in rep.skipped_filter],
        "warnings": [
            (lambda head: (
                str(Path(head).resolve().relative_to(root.resolve()))
                if Path(head).is_absolute()
                and Path(head).resolve().is_relative_to(root.resolve())
                else Path(head).name
            ) + ": " + w.split(": ", 1)[1])(w.split(": ", 1)[0])
            if ": " in w else w
            for w in rep.warnings
        ],
        "added_count": rep.added_count,
        "skipped_count": rep.skipped_count,
        "by_type": rep.by_type,
        "facies_product_count": rep.facies_product_count,
        "summary_text": rep.summary_text(),
    }


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="imp_oracle_"))
    tree = root / "tree"
    files = {
        "well1.las": "~V\nVERS. 2.0\n~W\nWELL. W1\nNULL. -999.25\n"
        "~C\nDEPT.M :d\nGR.API :g\n~A\n1.0 2.0\n",
        "seismic.sgy": b"\xc3\x00" * 4000,
        "table.csv": "a,b\n1,2\n3,4\n",
        "doc.md": "# 标题\n内容\n",
        "notes.txt": "line1\nline2\n",
        "map.geojson": '{"type":"FeatureCollection","features":[]}',
        "data.json": '{"type":"FeatureCollection","features":[]}',
        "plain.json": '{"a": 1}',
        "arr.json": "[1, 2, 3]",
        "broken.json": "{bad",
        "bad.geojson": "{bad",
        "empty.csv": "",
        "._fork.txt": "apple double file",
        "sub/inner.csv": "x,y\n5,6\n",
        "sub/deep/layer.dat": "1 2 3\n",
        "image.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
        "weird.xyz": "unknown ext\n",
        "noext": "no extension\n",
        "相图-相.geojson": '{"type":"FeatureCollection","features":['
        '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[]},'
        '"properties":{}}]}',
        "相图-亚相.geojson": '{"type":"FeatureCollection","features":['
        '{"type":"Feature","geometry":{"type":"Polygon","coordinates":[]},'
        '"properties":{}}]}',
    }
    for rel, content in files.items():
        write(tree / rel, content)

    cases = []

    # ---- scan_resources -----------------------------------------------------
    scanned = scan_resources(tree, max_workers=1)
    cases.append(
        {
            "id": "scan.basic",
            "kind": "scan",
            "items": [item_json(r, tree) for r in scanned],
        }
    )
    scanned_skip = scan_resources(
        tree, max_workers=1, skip_checksum_over_bytes=100
    )
    cases.append(
        {
            "id": "scan.skip_checksum",
            "kind": "scan",
            "items": [item_json(r, tree) for r in scanned_skip],
        }
    )

    # ---- import_folder -------------------------------------------------------
    cases.append(
        {
            "id": "folder.basic",
            "kind": "folder",
            "workers": 1,
            "report": report_json(
                import_folder(tree, [], None), tree
            ),
        }
    )
    cases.append(
        {
            "id": "folder.preferred_only",
            "kind": "folder",
            "workers": 1,
            "preferred_only": True,
            "report": report_json(
                import_folder(tree, [], None, preferred_only=True), tree
            ),
        }
    )
    # Re-import over existing → everything deduped by path.
    first = import_folder(tree, [], None)
    cases.append(
        {
            "id": "folder.dedup_existing",
            "kind": "folder",
            "workers": 1,
            "existing_count": len(first.added),
            "report": report_json(
                import_folder(tree, list(first.added), None), tree
            ),
        }
    )

    # ---- import_files ---------------------------------------------------------
    explicit = [
        tree / "well1.las",
        tree / "missing.las",
        tree / "empty.csv",
        tree / "._fork.txt",
        tree / "sub",  # directory — explicit → warning
        tree / "weird.xyz",
    ]
    cases.append(
        {
            "id": "files.explicit",
            "kind": "files",
            "workers": 1,
            "paths": [str(p.relative_to(tree)) for p in explicit],
            "report": report_json(import_files(explicit, [], None), tree),
        }
    )
    cases.append(
        {
            "id": "files.preferred_only",
            "kind": "files",
            "workers": 1,
            "preferred_only": True,
            "paths": ["well1.las", "weird.xyz", "table.csv"],
            "report": report_json(
                import_files(
                    [tree / "well1.las", tree / "weird.xyz",
                     tree / "table.csv"],
                    [],
                    None,
                    preferred_only=True,
                ),
                tree,
            ),
        }
    )

    # project_path variant: stored paths relativize inside the project dir.
    proj = root / "proj" / "project.pwb"
    (tree).relative_to(proj.parent) if False else None
    proj.parent.mkdir(parents=True, exist_ok=True)
    # move semantics: tree must sit inside proj dir for external=False
    tree2 = proj.parent / "data"
    for rel, content in files.items():
        write(tree2 / rel, content)
    cases.append(
        {
            "id": "folder.project_relative",
            "kind": "folder",
            "workers": 1,
            "project_path": "data/../project.pwb",
            "report": report_json(
                import_folder(tree2, [], proj), proj
            ),
        }
    )

    fixture = {
        "files": {
            rel: (content if isinstance(content, str) else content.hex())
            for rel, content in files.items()
        },
        "binary_names": [
            rel for rel, content in files.items()
            if not isinstance(content, str)
        ],
        "mtime": MTIME,
        "cases": cases,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"frozen {OUT} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
