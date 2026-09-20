# Task 13 — findings ledger

Base: `06211541ae1ccce22b0d5ba9258ce722170ca98b` (origin/main @ task start).
Convention: each defect = reproduction → pre-fix failure → fix → post-fix pass →
adjacent regression. "FIXED on main" entries got regression confirmation only.

## Per-issue findings

### #1380 — shared store write on SEG-Y worker thread (P1)
- **Status: FIXED on base.** Commit `3ae509d1` moved publication off the worker
  (`publish_run_result` via queued path); `bf374a79` added store movability.
- Regression evidence: `tests/cpp/viz_c/store_concurrency_test.cpp` —
  barrier-controlled 3-writer interleave (segy-import / attribute-run / gui-edit)
  with in-critical-section FaultHook probe; asserts mutual exclusion + rollback.
- Action: run the test; no code change.

### #1381 — TaskRuntime catalog publication race (P1)
- **Status: FIXED on base** (same `3ae509d1`; `CatalogResultPublisher` serializes
  store access). Same regression test covers the B-writer role.

### #1382 — CatalogRowOverview::asset dangling pointer (P2)
- **Status: FIXED on base.** `3644d562` changed the field to
  `std::shared_ptr<const catalog::DataAsset>`; `list_assets()` returns by value,
  so a raw pointer into the temporary vector dangled as soon as it returned.
- Extended `ui_data_core.asset_view_guard` covers: overview outliving service +
  returned vector, `apply_catalog_overview`, `asset_view_from_catalog_overview`,
  long-lived `CatalogEnricher`.

### #1383 — asset_view_from_object empty-variant/null deref (P2)
- **Status: FIXED on base** (`3644d562` — `get_if` chain + null guards for
  `AssetHandle`, `shared_ptr<AssetView>`, `shared_ptr<const DataAsset>`).
- Extended the same test: catalog-row variant, null `AssetView`, null
  `DataAsset`, FilterIndex path through catalog handles.

### #1384, #1385, #1388, #1392 — performance items
- Classified as **line-14 scope** (measurement + evidence-based optimization);
  recorded here as *not fixed, not ours*. No correctness defect claimed by the
  issue text beyond what is listed below.

### #1386 — well_tops `py_split` ASCII-only whitespace (P2) — FIXED
- Reproduced: `.dat` rows separated by U+3000 / U+00A0 collapsed to one token →
  too few fields → row silently skipped; Python `str.split()` splits them.
- Same defect class in `py_parse_float`/`py_strip` edge-strip (ASCII-only).
- Fix: exported `detail::cp_is_unicode_space` (already the `py_strip`
  predicate) and reused it in `py_split` + `py_parse_float` edges. Token loop
  also stopped dereferencing `nullopt->size` on ill-formed input (latent UB).
- Oracle: `generate_ingest_oracles.py` grew `unicode_space_separators` +
  `nbsp_separator` cases; fixture regenerated from real Python 3.14 —
  unrelated env-dependent churn (zip timestamps, LAS capability) reverted.
- Extra direct cases in `ingest.parsers` (`test_py_compat_unicode_space`).

### #1387 — unchecked QFile::write short writes (P2) — FIXED
- `WellLogTrackPanel::on_save_template`: open checked, write/flush not →
  silent truncation on full/RO media. Now requires `write()==size && flush()`,
  warns via QMessageBox (same pattern as `save_style_sidecar` reference).
- `MainWindow::showDiagnosticsDialog` save lambda: identical gap → identical
  fail-closed fix.
- Limitation: no real disk-full injection available offscreen; the failure
  branch is verified by code path review + the fail-closed contract
  (`write()!=size || !flush()` → warning). Honest, not claimed as simulated.

### #1389 — QObject raw-pointer captures/registry (P3) — FIXED
- Item 1 (`ShortcutRegistry`) already `QPointer` on base — verified.
- `DataWorkspace::floatable_` was `std::map<QString, QWidget*>`:
  `set_inspector_panel` deleteLater'd the old panel while the map kept the raw
  pointer → `persist_docked_sizes` (debounce timer) dereferenced dead widget.
  Fix: `QPointer<QWidget>` values; `set_inspector_panel` re-points the
  `data:inspector` entry at the live panel; `persist_docked_sizes` skips nulls.
- `floatable_panel_entries` captured raw `FloatingPanel*`/`QWidget*`/`FloatController&`
  in std::function entries that outlive the objects → UB when invoked later.
  Fix: `QPointer` captures; `toggle_float` guards a dead controller too.
- Regression: `ui_shell.qt_widgets_smoke` builds entries, destroys the
  FloatingPanel via `dock_panel`+DeferredDelete and the widget via `delete`,
  then invokes the stale callbacks — must no-op, not crash.

### #1390 — ObjectTableModel bounds + NaN sort + stale order (P3) — FIXED
- `data()` lacked a column bound (`columns_[index.column()]` unchecked) —
  foreign/proxy indexes went OOB. Fixed; `headerData` already guarded.
- `sort_key_of` produced a numeric key for NaN → `sort_key_less` always-false
  → equivalence not transitive → `std::stable_sort` strict-weak-ordering UB.
  Fix: NaN → tier 2 (absent/missing-last); ±inf stays numeric (orderable in
  both languages).
- `DataAssetTable` only listened to `modelReset`; the ObjectTableModel sort
  convention emits `layoutChanged` + persistent-index remap → visible order
  went stale and `sync_selection` could select wrong rows. Now connects
  `layoutChanged → on_model_reset` on both model_ and paged_model_.
- Regression: `ui_widgets.modelview` — foreign-model index into `data()`,
  NaN sort key stability, existing mixed-sort/persistent-index tests retained.

### #1391 — four-item punchlist (P3) — FIXED
1. **Malformed saved filters**: `filter_query_from_dict` now returns
   `std::optional`; non-object or wrong-typed stored fields → `nullopt` → the
   existing (dead) warning branch in `apply_saved` is reachable again.
   Strictness note: Python's `list(str)`/`list(dict)` corners are accepted
   there but treated as corruption here — the issue's own spec is
   "非 object/类型不符判失败". Valid app-written payloads round-trip
   identically (verified in smoke test).
2. **Unicode search fold**: `lower_ascii`/`normalize_search_text` were
   ASCII-only while Python uses `str.lower()`. Added `pwb::domain::text`
   (`lowercase_utf8`, `casefold_utf8`) backed by a generated table from real
   `str.lower()`/`str.casefold()` (`tools/oracle/generate_domain_lower_table.py`
   → `libs/domain/src/lower_table.inc`, 1460+1557 mappings, Unicode 16.0.0) —
   same generation contract as interchange's unicode_tables. Wired into
   `filter_index.cpp` (needle+haystack), `table_model.cpp`
   (`normalize_search_text`, which feeds both paged and non-paged paths), and
   `chips.cpp` saved-filter sort (casefold, matching `sorted(key=str.casefold)`).
   Other ASCII lowers left alone (stage/format vocabularies are ASCII by
   definition; Qt-layer sites already use `QString::toLower`).
3. **Ragged `any_to_grid`**: `vector<vector<double>>` and `vector<any>` paths
   both now verify row-length consistency before flattening; mismatch throws
   `PyValueError("grid_z 维数错误")` (the `np.asarray` parity). Previously
   rows*cols != data.size() made every `Grid2D::at` read OOB.
4. **`AlgorithmRunner::algorithms()`** now takes the same `mutex_` as
   `register_kernel` — unguarded iteration was UB under concurrent register.

### #1399 — version_id undeclared under CONV_30+VIEWER (build)
- **Status: FIXED on base** — `version_id` hoisted above the macros plus a
  `!CONV_30` guard in `main_window.cpp`. Confirmed by inspection; compile
  coverage comes free with the platform build.

## Cross-cutting residual notes
- No new defects found in the A–E/UI-17 interaction scan beyond what the issue
  list already enumerates; the store-concurrency test is the cross-module
  evidence carrier.
- `FilterQuery` non-string scalars on Optional fields (e.g. `node_value: 123`)
  are warned-on rather than applied — Python would construct a dead query;
  C++ can't represent a non-string node_value. Corruption corner only.

## Independent review pass (subagent, post-validation)

Reviewed the full diff + tests against the Python frozen sources. Verdict:
no high-severity defects; fixes applied for the actionable findings.

**Fixed after review:**
- `apply_saved` falsy-payload parity: Python's `if not stored: return` makes
  `{}`/[]/""/0/null a silent no-op; the first cut let `query:{}` through to
  `from_dict` → emitted an all-default query (view reset). Now falsy payloads
  return before parsing; non-falsy malformed payloads still warn. 
- `cp_is_unicode_space`/`is_py_space` were missing real `str.isspace()`
  members U+0085 (NEL) and U+001C-U+001F (FS/GS/RS/US). Added + test cases.
- `saved_filter_names_sorted` smoke coverage extended to non-ASCII names
  ("Ära"/"sigma-Σ") so an ASCII-only-fold regression would fail.

**Recorded, not fixed (documented limitations):**
- `str.lower()` final-sigma context rule: U+03A3 lowers to ς word-finally
  in Python; the per-codepoint table emits σ unconditionally. Needs
  cased/case-ignorable property tables + lookahead — disproportionate for
  this corner; affects Greek asset names ending in Σ only. `casefold`
  (used for sorting) is context-free and exact.
- Other pages keep raw `QWidget*` floatable registries
  (`visualization_page`, `correlation_page`, `review_export_page`) with the
  same latent dangle shape — no panel-replacement seam exists there today,
  so no live defect; flagged for future hardening.
- `PanelFloatButton::controller_` raw pointer: unreachable dead-controller
  path under current ownership (button is parented to the panel tree).
- `pwb::domain::casefold_utf8` duplicates `pwb::interchange::casefold_utf8`
  (same generated Unicode data) — deliberate layering: neither consumer
  links Pwb::Interchange.
- SQL paged-search `name_search` column remains ASCII-folded by design
  (D6); the non-paged path now matches Python.
