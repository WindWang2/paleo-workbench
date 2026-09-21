# 08 — Known limitations (V14-DATA-LINEAGE)

## Frozen-oracle tests that fail on Windows (environmental, not regressions)

Seven pre-existing frozen-oracle suites fail on this machine's MSVC build:
`data.catalog_domain`, `data.catalog_service`, `data.oracle_compare`,
`data.consumer_loop`, `data.oracle_readback`, `data.catalog_gc`,
`data.ingest_plan`, `data.lifecycle_ops`.

**A/B attribution (same box, same command):** a clean `origin/main`
worktree cannot even COMPILE `libs/catalog` under MSVC (`localtime_r`,
`gmtime_r`, wchar `::stat`, `S_ISREG`/`S_ISDIR` are POSIX-only), so those
suites have never run here — consistent with the 01-ledger A12 disclosure
that this machine had no cmake/ctest and verification was g++-direct. On
this branch they compile and most pass; the residual failures are
path-form comparisons against fixtures generated on Linux:

- `recorded_path` / `path` mismatches — POSIX `/` separators and 8.3
  short names (`WANGJ~1.KEV`) vs the fixture's long form;
- `/tmp/pwb_*` literal expectations in `lifecycle_ops` (the fixture is a
  POSIX temp tree);
- `<ROOT>` placeholder substitution in `ingest_plan` (the generator's
  root marker);
- the two oracle-readback suites spawn the Python oracle as a subprocess
  and compare trees — the same path-form difference.

**Not fixed in this line** (they are frozen fixtures; regenerating them
for Windows is a separate, repo-wide decision). The new V14 suites avoid
the problem by constructing their expectations in-process.

## Accepted P3s (with rationale)

1. **`IngestPlanModel` slot key omits `entity_type`** — `(entity_id, role)`
   pairs collide only if two entity types share an id; ids are
   type-prefixed by construction (`well_…`, `svy_…`, `ent_…`). A latent
   hazard if that convention ever changes.
2. **`posix_shim::temp_file_path` constructs `std::random_device` per
   call** — may open an OS entropy source each time. The atomic-write
   frequency (working-copy placement) is low; hoisting is a trivial
   follow-up.
3. **Windows `strptime` replacement is looser than POSIX** — `sscanf`
   accepts signs/leading whitespace and does not reject trailing garbage.
   The single caller parses the fixed `%Y-%m-%dT%H:%M:%S` prefix of
   catalog-generated stamps.
4. **O(L) link scan per `well_view`** — expanding one well re-walks the
   link array. Measured: 50 expansions over 100k links ≈ 5M link scans,
   a few ms. The scale contract (no catalog reads, bounded asset
   resolution) is what the structural test pins.

## Deliberate divergences from the Python oracle

1. **`build_manual_edit_run` validates source version ids** (fail-closed)
   where `service.py` registers with `validate_versions=False` because
   "versions may legitimately not exist yet". The C++ commit path always
   has the source versions durable (working-copy commit requires them), so
   the check only rejects genuinely dangling provenance anchors. Rationale
   recorded here per the line's decision-log requirement.
2. **The production runtime-bag path registers context-free manual-edit
   runs** (empty entity_type/entity_id/business_role/actor) — this mirrors
   the Python production caller (`data_lifecycle_controller.py`). The full
   `ManualEditRequest` surface (entity context + actor) is implemented and
   tested for the entity-context caller; only the degenerate bag path is
   wired. Wiring entity context through the bag signatures is a follow-up
   that needs the controller's edit-session context plumbed first.

## Deferred / not in this line

- `InstalledCatalogClosure` composition-root wiring into
  MainWindow/AppContext (line-12 scope; the adapter remains test-installed
  and this line's product wiring goes through `PwbDataStore`, which is the
  path the Qt shell actually uses).
- QGIS map-usage rows: the workspace exposes `related_runs` /
  entity-link surfaces; QGIS-layer usage belongs to the QGIS line and can
  consume the same seam.
- Offloading the folder-ingest execute to the job runtime (currently
  synchronous under a wait cursor — honest simplicity, recorded in the
  install comment).
- Regenerating the frozen oracle fixtures for Windows (repo-wide
  decision, see above).

## Resource discipline

All builds used `-j4` (CEILING respected; `CMAKE_BUILD_PARALLEL_LEVEL=4`,
`--build … -j 4`, ctest `-j 2`). Isolated build dirs per worktree
(`build/cpp-data-v14-ta`, `build/cpp-data-v14-scale`,
`build/presets/windows-msvc`). No vendor/QGIS rebuild was triggered. The
POSIX resource gate is unavailable on this win32 host (documented exit 77);
discipline was enforced by construction.
