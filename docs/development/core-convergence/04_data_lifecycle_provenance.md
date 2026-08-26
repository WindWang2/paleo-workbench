# Project Data Lifecycle & Provenance Architecture

**Document ID**: `CORE-CONV-04`  
**Version**: `1.0.0`  
**Status**: `Production / Complete`  
**Author**: Paleo Workbench Engineering Team  
**Scope**: Features F19, F20, F21, F22 (Raw Dataset Immutability, Asset Hierarchy, Lineage Graph & Provenance, Project Persistence & Recovery)

---

## 1. Overview & Data Integrity Architecture

In computational geology, scientific defensibility requires that all derived interpretations, grids, and maps remain fully reproducible from their source borehole and seismic data.

The Project Data Lifecycle & Provenance subsystem implements:
1. **Physical & Logical Raw Immutability**: Hardware-level filesystem permission enforcement (`0o444`) and software exception barriers (`ImmutableVersionError`) preventing in-place alteration of imported raw datasets.
2. **Structured Asset Taxonomy**: Standardized asset staging under `<project>.artifacts/` across `RAW`, `DERIVED`, `INTERMEDIATE`, `OUTPUT`, `WORKING`, and `TRASH`.
3. **Dual-Tier Catalog Architecture**: Canonical atomic document storage (`catalog.json`) coupled with a high-performance SQLite query cache (`catalog.sqlite`) operating in WAL mode with self-healing rebuild capabilities.
4. **Cycle-Safe Directed Lineage Graphs**: Provenance tracking attaching `input_version_ids` and `run_id` to all scientific outputs, evaluated via bounded BFS and iterative DFS traversal algorithms.
5. **Crash-Safe Atomic Persistence**: Multi-stage atomic file swap with disk synchronization barriers and automatic backup restoration (`*.paleo.json.bak`).

```
+----------------------------------------------------------------------------------------------------+
|                                      DATA STORAGE & CATALOG TIER                                   |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|  <Project Root>/                                                                                   |
|  ├── project_name.paleo.json         <--- Canonical Project Manifest (Atomic os.replace + fsync)  |
|  ├── project_name.paleo.json.bak     <--- Disaster Recovery Backup                                 |
|  └── project_name.artifacts/                                                                       |
|      ├── raw/                        <--- Read-Only Raw Borehole/Seismic Files (chmod 0o444)        |
|      ├── derived/                    <--- Processed Well Curves, Stratigraphic Interpretations     |
|      ├── intermediate/               <--- Kriging Variograms, Temporary Meshes                     |
|      ├── outputs/                    <--- Exported Maps, Factor Grids, GeoJSON Layers              |
|      ├── working/                    <--- Isolated Copy-on-Write Buffers (Writable)                |
|      ├── trash/                      <--- Soft-Deleted Asset Versions                              |
|      └── metadata/                                                                                 |
|          ├── catalog.json            <--- Canonical Catalog Document Store (Atomic Swap + .bak)    |
|          └── catalog.sqlite          <--- High-Speed Query Cache (WAL Mode, Thread-Local Pools)    |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
|                                     LINEAGE & PROVENANCE DAG                                       |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   +--------------------------+          +--------------------------+                               |
|   |  RAW Well Log Dataset    |          |  RAW Tops Interpretation |                               |
|   |  (version_id: "v-raw-1") |          |  (version_id: "v-raw-2") |                               |
|   +-------------+------------+          +-------------+------------+                               |
|                 \                                    /                                             |
|                  \                                  /                                              |
|                   v                                v                                               |
|               +----------------------------------------+                                           |
|               | DataRun: Well Factor Extraction        |                                           |
|               | (run_id: "run-extract-01")             |                                           |
|               +-------------------+--------------------+                                           |
|                                   |                                                                |
|                                   v                                                                |
|               +----------------------------------------+                                           |
|               | DERIVED Factor Points                  |                                           |
|               | (version_id: "v-factor-01")            |                                           |
|               +-------------------+--------------------+                                           |
|                                   |                                                                |
|                                   v                                                                |
|               +----------------------------------------+                                           |
|               | DataRun: Kriging Spatial Interpolation |                                           |
|               | (run_id: "run-kriging-02")             |                                           |
|               +-------------------+--------------------+                                           |
|                                   |                                                                |
|                                   v                                                                |
|               +----------------------------------------+                                           |
|               | OUTPUT FactorGridResult                |                                           |
|               | (input_version_ids: ["v-factor-01"])   |                                           |
|               +-------------------+--------------------+                                           |
|                                   |                                                                |
|                                   v                                                                |
|               +----------------------------------------+                                           |
|               | OUTPUT Compiled MapDocument            |                                           |
|               | (input_version_ids: ["v-factor-01",    |                                           |
|               |                      "v-grid-02"])     |                                           |
|               +----------------------------------------+                                           |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Raw Dataset Immutability & Working Copies (Feature F19)

### 2.1 Filesystem Immutability Enforcement
When raw datasets (e.g. LAS well logs, SEGY seismic files, CSV production tables) are imported into the catalog:
- `paleo_workbench/catalog/storage.py` invokes `_make_readonly(path)`:
  ```python
  def _make_readonly(path: Path) -> None:
      current = stat.S_IMODE(path.stat().st_mode)
      readonly = current & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
      path.chmod(readonly)
  ```
- Any subsequent attempt to overwrite or append to managed raw files fails at the operating system level with `PermissionError`.

### 2.2 Logical Collision Prevention
- `paleo_workbench/catalog/models.py` defines `ImmutableVersionError`.
- If an operation attempts to re-register an existing committed version ID with modified content or payload hashes, `DataCatalogService` raises `ImmutableVersionError` rather than updating in place.

### 2.3 Copy-on-Write Working Copies
When an analyst edits an asset:
1. `storage.create_working_copy(version_id)` creates a physical byte copy (never a hardlink) in `artifacts/working/{version_id}/{filename}` and applies `_make_writable(target)`.
2. The user modifies the working copy in isolation.
3. Upon save, `service.commit_working_copy()` registers a new `DataVersion` with incremented `version_number = N + 1`, records `parent_version_ids = [source_version_id]`, and moves the file into read-only storage.

---

## 3. Asset Hierarchy & Dual-Tier Storage (Feature F20)

### 3.1 DataStage Classification
- **`RAW` (`"raw"`)**: Unprocessed external source data imported into the project.
- **`DERIVED` (`"derived"`)**: Cleaned, standardized, or unit-converted data products.
- **`INTERMEDIATE` (`"intermediate"`)**: Transient compute artifacts (variogram tables, Delaunay meshes).
- **`OUTPUT` (`"output"`)**: Publication-ready scientific results (factor grids, compiled MapDocuments, final vector contour sets).
- **`WORKING` (`"working"`)**: Active copy-on-write workspace buffers.
- **`TRASH` (`"trash"`)**: Soft-deleted versions preserved for recovery.

### 3.2 Dual-Tier Catalog Architecture
The data catalog employs a dual-tier storage strategy balancing atomic durability with instant multi-criteria querying:
1. **Canonical Document Store (`metadata/catalog.json`)**:
   - Managed by `CatalogStore` (`paleo_workbench/catalog/store.py`).
   - Writes are executed using an atomic tempfile write (`.catalog.json.<pid>.tmp`), followed by `os.fsync`, backup copy creation (`catalog.json.bak`), atomic `os.replace`, and directory `fsync`.
   - Stale write detection (`_disk_mtime_ns`) prevents race conditions between concurrent worker processes by raising `CatalogStaleWriteError`.
2. **High-Performance Query Cache (`metadata/catalog.sqlite`)**:
   - Managed by `CatalogIndex` (`paleo_workbench/catalog/db.py`).
   - Operates in Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and `PRAGMA synchronous=NORMAL` mode for non-blocking concurrent reads during background updates.
   - Connections are managed in thread-local storage (`_conns: dict[int, sqlite3.Connection]`), automatically pruned via `_prune_dead_threads` when worker threads terminate.
   - **Self-Healing Rebuild**: If `catalog.sqlite` is absent or corrupted, `CatalogIndex.rebuild()` reads `catalog.json` and reconstructs all relational tables in $< 100\text{ ms}$.

---

## 4. Directed Lineage Graph & Provenance (Feature F21)

### 4.1 Provenance Contract Alignment
Every computational asset produced by Paleo Workbench explicitly records its execution lineage:
- **`FactorGridResult`**: Exposes `input_version_ids: list[str]` and `run_id: str | None`, serialized into JSON descriptors.
- **`MapDocument`**: Exposes `input_version_ids: list[str]` (aggregating document metadata and constituent layer sources) and `run_id: str | None`.
- **`build_factor_map_document`**: Automatically binds execution `run_id` and upstream well dataset version IDs to all generated layers.

### 4.2 Cycle-Safe Traversal Algorithms
Lineage traversal algorithms (`paleo_workbench/catalog/lineage_graph.py`) are mathematically hardened against cyclic references and deep graphs:
1. **`build_lineage_chain` (Breadth-First Search)**:
   - Uses a `seen: set[str]` tracking visited version IDs.
   - Enforces configurable `max_depth` limits (default $50$), truncating graph walks if excessive depth is reached.
   - Categorizes edges into `PARENT` (direct version evolution) and `INPUT` (computational run inputs).
2. **`compute_summaries` (Iterative Depth-First Search)**:
   - Evaluates total ancestor counts, root raw source IDs, and maximum hops-to-raw metrics.
   - Employs an explicit call stack with `on_path: set[str]` cycle detection and memoization to guarantee bounded $O(V + E)$ execution time.

---

## 5. Atomic Project Persistence & Disaster Recovery (Feature F22)

### 5.1 Atomic Project Save Protocol
`ProjectManager` (`paleo_workbench/project/manager.py`) coordinates project manifest persistence:
1. **JSON Serialization**: The complete project state (well collections, horizons, seismic references, map documents, factor tasks) is serialized to JSON.
2. **Staged Temporary Write**: The payload is written to `.{name}.paleo.json.tmp`.
3. **Flushing & Disk Sync**: `file.flush()` and `os.fsync(file.fileno())` force dirty buffer pages to non-volatile storage.
4. **Backup Preservation**: If an existing `{name}.paleo.json` exists, it is copied to `{name}.paleo.json.bak`.
5. **Atomic Rename**: `os.replace(".{name}.paleo.json.tmp", "{name}.paleo.json")` atomically swaps the file.
6. **Directory Fsync**: The parent directory file descriptor is synced to guarantee directory entry persistence.

### 5.2 Disaster Recovery Fallback
If the workstation experiences power failure or sudden termination mid-operation:
- Upon opening, `ProjectManager._load_data` attempts to read and parse `{name}.paleo.json`.
- If JSON parsing fails due to truncation or corruption, it logs a warning, falls back to `{name}.paleo.json.bak`, restores the project state, and creates a recovery notification for the user.

### 5.3 Clean Session Teardown
When switching or closing projects:
- `ProjectController._end_current_session` increments session generation numbers.
- Background catalog maintenance threads are signaled and joined.
- Worker threads (`OwnedWorkerJob`) are safely terminated and joined (`shutdown_workers`).
- Thread-local SQLite connections are closed and pruned.
- Memory caches (`_LIVE_FACTOR_GRIDS`, `_GEOMETRY_POOL`, plan caches) are cleared to prevent cross-session memory leaks.

---

## 6. Verification Summary

The Data Lifecycle & Provenance architecture is verified by:
- `tests/test_catalog_storage.py`: Read-only permissions (`0o444`), working copy isolation, byte copying.
- `tests/test_catalog_store.py`: Canonical JSON atomic swaps, stale write conflict detection, `.bak` creation.
- `tests/test_catalog_db.py`: SQLite WAL mode, thread-local connection pruning, full index rebuilds.
- `tests/test_catalog_lineage_chain.py`: End-to-end geological pipeline lineage traversal, cycle safety, hops-to-raw calculation.
- `tests/test_catalog_crash_safety.py`: SIGKILL and power-cut simulation mid-save verifying zero data loss.
- `tests/test_project_manager.py`: Project save, close, reopen, and backup disaster recovery.
- `tests/e2e/test_tier1_features.py` (F19–F22) & `tests/e2e/test_tier4_scenarios.py` (Scenario 6: Project Lifecycle & Provenance).
