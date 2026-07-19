# Lightweight File Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make data-page imports create persistent, suffix-classified project resources without opening files, parsing contents, or computing checksums.

**Architecture:** Preserve DataPage's QThread worker and its one-batch refresh. Replace import-service calls to the full scanner with an import-only collector that builds ResourceItem records from selected paths or recursive directory enumeration, stat metadata, and the existing classifier. Bootstrap and manual rescan continue using the full scanner.

**Tech Stack:** Python 3, PySide6, Pydantic, pytest, pytest-qt.

## Global Constraints

- Limit this work to data-page file, folder, and drag/drop imports; bootstrap and manual rescan retain full-scan semantics.
- Preserve current extension and .dat path-based initial classification rules.
- Imported ResourceItems persist in ProjectDocument.resources with checksum=None and parsed_summary["size_bytes"].
- Never open imported files or calculate content checksums during import.
- Deduplicate only normalized paths. Equal-content files at distinct paths may both be added.
- Preserve unrelated dirty-worktree changes and stage only files named in each task.

---

### Task 1: Build and test the import-only resource collector

**Files:**

- Modify: paleo_workbench/resources/import_service.py:1-126
- Modify: tests/test_data_import_service.py:1-96

**Interfaces:**

- Consumes: classify_path(path: Path) -> tuple[str, str, str] and relativize_path(path: str, project_path: Path) -> tuple[str, bool].
- Produces: _collect_resource(path: Path, project_path: Path | None) -> ResourceItem and _collect_folder(root: Path, project_path: Path | None) -> tuple[list[ResourceItem], list[str]].

- [ ] **Step 1: Write failing lightweight-import tests**

In tests/test_data_import_service.py, remove the content-checksum duplicate test and the import checksum-threshold test. Add:

~~~python
def test_import_files_never_opens_file_or_calculates_checksum(tmp_path: Path, monkeypatch):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")

    def fail_open(*_args, **_kwargs):
        raise AssertionError("import must not open file content")

    monkeypatch.setattr(Path, "open", fail_open)
    report = import_files([well], existing=[])

    assert report.added_count == 1
    assert report.added[0].checksum is None
    assert report.added[0].parsed_summary == {"size_bytes": len(b"~Version\n")}


def test_import_files_processes_only_requested_paths(tmp_path: Path, monkeypatch):
    selected = tmp_path / "selected.las"
    unselected = tmp_path / "unselected.sgy"
    selected.write_text("~Version\n", encoding="utf-8")
    unselected.write_bytes(b"cube")

    def fail_rglob(*_args, **_kwargs):
        raise AssertionError("single-file import must not enumerate a directory")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    report = import_files([selected], existing=[])

    assert [resource.name for resource in report.added] == ["selected.las"]


def test_import_files_keeps_same_content_at_distinct_paths(tmp_path: Path):
    first = tmp_path / "first.las"
    second = tmp_path / "second.las"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")

    first_report = import_files([first], existing=[])
    second_report = import_files([second], existing=first_report.added)

    assert second_report.added_count == 1
    assert second_report.skipped_checksum == []
~~~

Rename the folder test to test_import_folder_collects_recursively_by_initial_classification. Add a nested .dat file under a directory named 层位 and assert its type is horizon, retaining the existing .sgy assertion.

- [ ] **Step 2: Run the targeted tests to verify failure**

Run: QT_QPA_PLATFORM=offscreen pytest tests/test_data_import_service.py -q

Expected: FAIL because the current service calls scan_resources, which reads files for checksums and scans the selected file's parent directory.

- [ ] **Step 3: Implement the collector**

In paleo_workbench/resources/import_service.py:

1. Replace the scanner import with imports for paleo_workbench.project.paths.relativize_path and paleo_workbench.resources.classifier.classify_path.
2. Remove DEFAULT_IMPORT_SKIP_CHECKSUM and _existing_checksums.
3. Add this helper, which uses only stat metadata and does not handle errors internally:

~~~python
def _collect_resource(path: Path, project_path: Path | None = None) -> ResourceItem:
    resource_type, resource_format, status = classify_path(path)
    resolved_path = path.resolve()
    size_bytes = resolved_path.stat().st_size
    stored_path = resolved_path.as_posix()
    external = False
    if project_path is not None:
        stored_path, external = relativize_path(str(path), project_path)
    return ResourceItem(
        name=path.name,
        path=stored_path,
        type=resource_type,
        format=resource_format,
        status=status,
        source="import",
        parsed_summary={"size_bytes": size_bytes},
        checksum=None,
        external=external,
    )
~~~

4. Add _collect_folder. It sorts root.rglob("*"), keeps is_file() entries except names beginning ._, then calls _collect_resource. Catch OSError per child and append "{path}: {exc}" to warnings. If traversal raises OSError, return an empty candidate list and a single "{root}: {exc}" warning.
5. Rewrite import_files to call _collect_resource once per requested path and accumulate an OSError warning. Never scan a selected file's parent directory.
6. Rewrite import_folder to call _collect_folder, then _filter_new.
7. Keep ImportReport.skipped_checksum only as an empty compatibility field. Simplify _filter_new to use and update path_keys only; it must not inspect checksums.

- [ ] **Step 4: Run import-service tests to verify pass**

Run: QT_QPA_PLATFORM=offscreen pytest tests/test_data_import_service.py -q

Expected: PASS. Records have no checksum; a selected file has no siblings imported; folder import retains the existing initial classification rules.

- [ ] **Step 5: Commit the collector**

~~~bash
git add paleo_workbench/resources/import_service.py tests/test_data_import_service.py
git commit -m "perf: collect import resources without content reads"
~~~

### Task 2: Isolate full scans and clarify data-page copy

**Files:**

- Modify: paleo_workbench/pipeline/bootstrap.py:12
- Modify: paleo_workbench/ui/pages/data_page.py:230-258,564-567
- Modify: tests/test_pipeline_bootstrap.py
- Modify: tests/test_data_page.py:365-455

**Interfaces:**

- Consumes: the existing full scan_resources default checksum behavior and DataPage._start_import_job(task: Callable[[], ImportReport]) -> bool.
- Produces: bootstrap's full-scan default and status messages accurately describing an archive-only import.

- [ ] **Step 1: Write failing regression tests**

Add to tests/test_pipeline_bootstrap.py:

~~~python
def test_bootstrap_default_keeps_full_scan_checksums(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "well.las"
    source.write_text("~Version\n", encoding="utf-8")

    result = bootstrap_sample_project(data_root)

    assert result.document.resources[0].checksum is not None
~~~

Add a test to tests/test_data_page.py that starts an import using a controlled worker, asserts the operation label contains 正在归档文件 after start, releases the worker, and after qtbot.waitSignal(page.import_finished, timeout=1000) asserts the completion label starts with 已归档. Follow the existing worker-thread import tests for monkeypatching and signal synchronization.

- [ ] **Step 2: Run scope and UI tests to verify failure**

Run: QT_QPA_PLATFORM=offscreen pytest tests/test_pipeline_bootstrap.py tests/test_data_page.py -q

Expected: FAIL because the current dirty bootstrap default skips every checksum and current status copy says 正在导入 / 新增.

- [ ] **Step 3: Restore bootstrap policy and change only import wording**

In paleo_workbench/pipeline/bootstrap.py set:

~~~python
DEFAULT_SKIP_CHECKSUM = 50 * 1024 * 1024
~~~

In paleo_workbench/ui/pages/data_page.py set the initial worker message to:

~~~python
self._set_action_status("正在归档文件...")
~~~

Replace _set_import_status with:

~~~python
def _set_import_status(self, report: ImportReport) -> None:
    self._set_action_status(
        f"已归档 {report.added_count} · 重复路径 {len(report.skipped_path)} · 警告 {len(report.warnings)}"
    )
~~~

Do not change the worker lifecycle, the re-entrant-import guard, _apply_import_report, or manual rescan. _apply_import_report remains the single operation that appends report.added to project.resources and refreshes the table.

- [ ] **Step 4: Run scope and UI tests to verify pass**

Run: QT_QPA_PLATFORM=offscreen pytest tests/test_pipeline_bootstrap.py tests/test_data_page.py -q

Expected: PASS. Bootstrap records retain checksums, import status describes lightweight archiving, and one import completion batch adds resources to the project.

- [ ] **Step 5: Commit scope protection and status copy**

~~~bash
git add paleo_workbench/pipeline/bootstrap.py paleo_workbench/ui/pages/data_page.py tests/test_pipeline_bootstrap.py tests/test_data_page.py
git commit -m "fix: keep full scans separate from lightweight imports"
~~~

### Task 3: Verify the complete boundary and record completion

**Files:**

- Modify: docs/superpowers/specs/2026-07-15-lightweight-import-design.md:3
- Modify: tests/test_project_manager.py
- Test: tests/test_data_import_service.py
- Test: tests/test_data_page.py
- Test: tests/test_pipeline_bootstrap.py
- Test: tests/test_resource_scanner.py

**Interfaces:**

- Consumes: public import_files, import_folder, DataPage import entry points, and bootstrap_sample_project.
- Produces: verified data-page imports whose classification is persistent project content and isolated full scans.

- [ ] **Step 1: Run focused end-to-end regression tests**

First add this persistence test to tests/test_project_manager.py:

~~~python
def test_lightweight_import_classification_round_trips_as_project_content(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    source = tmp_path / "data" / "well.las"
    source.parent.mkdir()
    source.write_text("~Version\n", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.resources.extend(
        import_files([source], existing=[], project_path=project_path).added
    )
    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    assert loaded.resources[0].type == "well_log"
    assert loaded.resources[0].format == "las"
    assert loaded.resources[0].checksum is None
    assert loaded.resources[0].parsed_summary["size_bytes"] == len(b"~Version\n")
~~~

Add import_files to the test module import. Then run: QT_QPA_PLATFORM=offscreen pytest tests/test_data_import_service.py tests/test_data_page.py tests/test_pipeline_bootstrap.py tests/test_project_manager.py tests/test_resource_scanner.py -q

Expected: PASS. Scanner tests still prove default full scans compute checksums; import-service tests prove imports do not.

- [ ] **Step 2: Inspect the final diff for scope leakage**

Run: git diff HEAD~2..HEAD -- paleo_workbench/resources/import_service.py paleo_workbench/pipeline/bootstrap.py paleo_workbench/ui/pages/data_page.py tests/test_data_import_service.py tests/test_pipeline_bootstrap.py tests/test_data_page.py

Expected: only the import collector, import status copy, bootstrap-default restoration, and matching tests changed. No classifier rule or manual-rescan implementation changed.

- [ ] **Step 3: Mark the approved design implemented**

In docs/superpowers/specs/2026-07-15-lightweight-import-design.md, change only:

~~~markdown
**状态：** 已实施并验证
~~~

- [ ] **Step 4: Re-run the focused end-to-end regression tests**

Run: QT_QPA_PLATFORM=offscreen pytest tests/test_data_import_service.py tests/test_data_page.py tests/test_pipeline_bootstrap.py tests/test_project_manager.py tests/test_resource_scanner.py -q

Expected: PASS.

- [ ] **Step 5: Commit verification documentation**

~~~bash
git add docs/superpowers/specs/2026-07-15-lightweight-import-design.md tests/test_project_manager.py
git commit -m "docs: mark lightweight import implementation verified"
~~~
