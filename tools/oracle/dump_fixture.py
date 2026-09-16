"""Semantic dump of a CPP-B fixture (the Python oracle side).

Writes, next to the fixture:
  oracle_project_dump.json  — raw file content, keys sorted (arrays kept)
  oracle_model_dump.json    — pydantic model_dump(mode="json") (defaults!)
  oracle_catalog_dump.json  — catalog.sqlite per-table rows (natural order)
  oracle_resolve.json       — resource path resolution + existence

All dumps use ``ensure_ascii=False``; floats keep Python repr (exact double
round-trip); int/float distinction survives JSON text ("1" vs "1.0").

Usage (main repo interpreter, read-only):
    <main>/.venv/Scripts/python.exe tools/oracle/dump_fixture.py --fixture <dir>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

TABLES = [
    "assets", "versions", "tags", "asset_tags", "version_tags",
    "runs", "run_inputs", "run_outputs", "lineage",
    "models", "model_versions", "sync_state",
    "staging_leases", "working_copies", "run_ports", "version_members",
]

JSON_COLUMNS = {
    "metadata", "parameters", "model_ref", "provenance",
    "input_schema", "output_schema", "parent_ids",
}


def find_project(fixdir: Path) -> Path | None:
    candidates = sorted(fixdir.glob("*.paleo.json"))
    return candidates[0] if candidates else None


def dump_project(fixdir: Path) -> None:
    project = find_project(fixdir)
    if project is None:
        return
    result: dict = {"_file": project.name}
    try:
        data = json.loads(project.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
        (fixdir / "oracle_project_dump.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        (fixdir / "oracle_model_dump.json").write_text(
            json.dumps({"error": "unavailable"},
                       ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        return
    result["document"] = data
    (fixdir / "oracle_project_dump.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        # 主仓解释器运行时 paleo_workbench 已可导入（主仓根在 sys.path）
        from paleo_workbench.project.models import ProjectDocument

        doc = ProjectDocument.model_validate(data)
        model = doc.model_dump(mode="json")
        # project_root 在运行期为绝对路径，可移植 dump 固定为 "."
        model.setdefault("meta", {})["project_root"] = "."
        payload = {"_file": project.name, "model": model}
    except Exception as error:  # ValidationError 等
        payload = {"_file": project.name,
                   "error": f"{type(error).__name__}: {error}"}
    (fixdir / "oracle_model_dump.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")


def dump_catalog(fixdir: Path) -> None:
    project = find_project(fixdir)
    result: dict = {"_fixture": fixdir.name}
    if project is None:
        return
    db = project.parent / (
        f"{project.name.removesuffix('.paleo.json')}.artifacts/metadata/"
        "catalog.sqlite")
    result["_db"] = str(db.relative_to(fixdir)).replace("\\", "/")
    if not db.is_file():
        result["error"] = "no catalog.sqlite"
    else:
        try:
            conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
            tables = {}
            for table in TABLES:
                try:
                    cursor = conn.execute(f"SELECT * FROM {table}")
                except sqlite3.DatabaseError as error:
                    tables[table] = {"error": str(error)}
                    continue
                names = [d[0] for d in cursor.description]
                rows = []
                for values in cursor.fetchall():
                    row = {}
                    for name, value in zip(names, values):
                        if name in JSON_COLUMNS and isinstance(value, str):
                            try:
                                row[name] = json.loads(value)
                            except ValueError:
                                row[name] = value
                        else:
                            row[name] = value
                    rows.append(row)
                tables[table] = rows
            conn.close()
            result["tables"] = tables
        except sqlite3.DatabaseError as error:
            result["error"] = f"sqlite: {error}"
    (fixdir / "oracle_catalog_dump.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")


def dump_resolve(fixdir: Path) -> None:
    project = find_project(fixdir)
    if project is None:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from paleo_workbench.project.paths import (
        project_dir_for,
        resolve_project_path,
    )

    try:
        data = json.loads(project.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        (fixdir / "oracle_resolve.json").write_text(
            json.dumps({"error": f"{type(error).__name__}: {error}"},
                       ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        return
    project_dir = project_dir_for(project)
    entries = []
    for resource in data.get("resources", []):
        item = {"id": resource.get("id"),
                "stored": resource.get("path")}
        try:
            item["resolved"] = resolve_project_path(
                resource.get("path", ""), project)
            item["exists"] = (Path(item["resolved"]).is_file())
        except Exception as error:
            item["error"] = type(error).__name__
        entries.append(item)
    for doc in data.get("paleomap_documents", []):
        for layer in doc.get("reference_layers", []):
            item = {"id": layer.get("id"), "stored": layer.get("source_path")}
            try:
                item["resolved"] = resolve_project_path(
                    layer.get("source_path", ""), project)
                item["exists"] = Path(item["resolved"]).is_file()
            except Exception as error:
                item["error"] = type(error).__name__
            entries.append(item)
    payload = {"project": project.name,
               "project_dir_exists": project_dir.is_dir(),
               "entries": entries}
    (fixdir / "oracle_resolve.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args()
    fixdir = args.fixture.resolve()
    dump_project(fixdir)
    dump_catalog(fixdir)
    dump_resolve(fixdir)
    print(f"oracle dumps written into {fixdir}")


if __name__ == "__main__":
    main()
