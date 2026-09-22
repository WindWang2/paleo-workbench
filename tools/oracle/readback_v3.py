"""Read-only Python oracle readback for C++ v3 writes (read-only usage of an existing interpreter).

Reopens, WITHOUT ANY WRITE, a project copy that the C++ data kernel has
modified (edit commit + run registration + single-result publish) and
verifies the new rows with the legacy Python stack:

  * the C++-written ``.paleo.json`` still validates as a pydantic
    ``ProjectDocument`` (old-version reopen compatibility);
  * catalog.sqlite (opened ``mode=ro``) carries the new version rows with
    parents / run links / result metadata;
  * the run row is terminal ("complete") with ``_finished_at``;
  * ``lineage`` / ``run_outputs`` derived rows exist for both writes;
  * the workspace membership advanced to the edit version;
  * the result asset's current pointer is the published version.

Usage:
    python3 readback_v3.py --project <copy/typical.paleo.json> \
        --base-version ver_... --edit-version ver_... \
        --result-asset asset_... --result-version ver_... \
        --run-id run_... --result-sha256 <hex>

Exit codes: 0 verified / 1 mismatch / 2 usage / 3 unreadable input.
The script never writes: no sqlite create, no file creation, no pragma.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def fail(failures: list[str], verdict: dict) -> int:
    verdict["ok"] = False
    verdict["failures"] = failures
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--base-version", required=True)
    parser.add_argument("--edit-version", required=True)
    parser.add_argument("--result-asset", required=True)
    parser.add_argument("--result-version", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--result-sha256", required=True)
    parser.add_argument("--layer-id", default="",
                        help="rebound layer id; empty = no rebind expected")
    parser.add_argument("--edit-run-id", default="",
                        help="manual_edit run linked to the edit version")
    args = parser.parse_args()

    verdict: dict = {"project": args.project}
    failures: list[str] = []

    project = Path(args.project)
    if not project.is_file():
        print(json.dumps({"ok": False, "error": f"missing: {project}"}))
        return 3
    try:
        document = json.loads(project.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(json.dumps({"ok": False, "error": repr(error)}))
        return 3

    # 1. Legacy pydantic model still accepts the C++-written project.
    try:
        import _legacy_reference
        _legacy_reference.ensure_legacy_reference()  # archived-reference shim
        from paleo_workbench.project.models import ProjectDocument

        ProjectDocument.model_validate(document)
        verdict["pydantic_project"] = "ok"
    except Exception as error:  # ValidationError 等
        failures.append(f"pydantic validation: {type(error).__name__}: {error}")

    # 2. Workspace membership advanced to the edit version (only when the
    #    loop actually rebound a layer; fixtures may carry only bindings to
    #    unknown assets).
    memberships = (document.get("mapping_workspace") or {}).get(
        "memberships") or {}
    if args.layer_id:
        row = memberships.get(args.layer_id)
        if row is not None and str(row.get("source_version_id", "")) == \
                args.edit_version:
            verdict["binding_advanced"] = True
        else:
            failures.append(
                f"membership {args.layer_id} did not advance to the edit "
                "version")
    else:
        verdict["binding_advanced"] = "skipped-no-layer"

    # 3. Catalog rows (mode=ro — the connection cannot write).
    db_path = (project.parent / "typical.artifacts" / "metadata" /
               "catalog.sqlite")
    if not db_path.is_file():
        # Derive from the documented artifacts layout next to the project.
        candidates = sorted(project.parent.glob("*.artifacts/metadata/"
                                                "catalog.sqlite"))
        db_path = candidates[0] if candidates else db_path
    # Zero-footprint read: mode=ro still creates -shm/-wal coordination
    # files on a WAL-mode store, so the oracle demands a cleanly closed
    # database (no live WAL) and opens immutable — provably no writes.
    for suffix in ("-wal", "-shm"):
        if db_path.with_name(db_path.name + suffix).exists():
            print(json.dumps({
                "ok": False,
                "error": f"live {suffix} present — close writers before "
                "a zero-footprint readback"}))
            return 3
    try:
        connection = sqlite3.connect(
            f"file:{db_path}?immutable=1", uri=True, timeout=10)
    except sqlite3.Error as error:
        print(json.dumps({"ok": False, "error": repr(error)}))
        return 3
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT asset_id, parent_ids, run_id, sha256, metadata "
            "FROM versions WHERE id = ?", (args.edit_version,)
        ).fetchall()
        if len(rows) != 1:
            failures.append(f"edit version row missing: {args.edit_version}")
        else:
            row = rows[0]
            parents = json.loads(row["parent_ids"] or "[]")
            if parents != [args.base_version]:
                failures.append(f"edit parents {parents} != [base]")
            expected_run = args.edit_run_id or args.run_id
            if row["run_id"] != expected_run:
                failures.append(
                    f"edit version run link {row['run_id']!r} != "
                    f"{expected_run!r}")
            verdict["edit_version"] = "ok"

        rows = connection.execute(
            "SELECT asset_id, parent_ids, run_id, sha256, metadata "
            "FROM versions WHERE id = ?", (args.result_version,)
        ).fetchall()
        if len(rows) != 1:
            failures.append(
                f"result version row missing: {args.result_version}")
        else:
            row = rows[0]
            if row["asset_id"] != args.result_asset:
                failures.append("result version asset mismatch")
            parents = json.loads(row["parent_ids"] or "[]")
            if parents != [args.base_version]:
                failures.append(f"result parents {parents} != [base]")
            if row["sha256"] != args.result_sha256:
                failures.append("result sha mismatch")
            metadata = json.loads(row["metadata"] or "{}")
            if metadata.get("units") != "ms" or \
                    metadata.get("approximate") is not False:
                failures.append(f"result metadata lost: {metadata}")
            verdict["result_version"] = "ok"

        rows = connection.execute(
            "SELECT status, parameters FROM runs WHERE id = ?",
            (args.run_id,)).fetchall()
        if len(rows) != 1:
            failures.append(f"run row missing: {args.run_id}")
        else:
            status = rows[0]["status"]
            parameters = json.loads(rows[0]["parameters"] or "{}")
            if status != "complete":
                failures.append(f"run status {status!r} != 'complete'")
            if "_finished_at" not in parameters:
                failures.append("run parameters lost _finished_at")
            if parameters.get("units") != "ms":
                failures.append("run parameters lost units")
            verdict["run"] = "ok"

        linked = connection.execute(
            "SELECT 1 FROM run_outputs WHERE run_id = ? AND version_id = ?",
            (args.run_id, args.result_version)).fetchall()
        if not linked:
            failures.append("run_outputs link missing")

        for parent, child in ((args.base_version, args.edit_version),
                              (args.base_version, args.result_version)):
            rows = connection.execute(
                "SELECT 1 FROM lineage WHERE parent_version_id = ? "
                "AND child_version_id = ?", (parent, child)).fetchall()
            if not rows:
                failures.append(f"lineage row missing {parent}->{child}")

        rows = connection.execute(
            "SELECT current_version_id FROM assets WHERE id = ?",
            (args.result_asset,)).fetchall()
        if len(rows) != 1 or rows[0]["current_version_id"] != \
                args.result_version:
            failures.append("result asset current pointer mismatch")
    except sqlite3.Error as error:
        failures.append(f"sqlite: {type(error).__name__}: {error}")
    finally:
        connection.close()

    if failures:
        return fail(failures, verdict)
    verdict["ok"] = True
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
