# ISSUE-011: Catalog SQLite Multi-Thread Connection Orphan Leak & Inode Desync

- **Severity**: High
- **Subproject**: `paleo_workbench` (`paleo_workbench/catalog`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/catalog/db.py#L239-L266`
  - `file:///home/kevin/projects/paleo_project/main/paleo_workbench/catalog/db.py#L284-L297`

---

## Defect Description & Root Cause Analysis

In `paleo_workbench/catalog/db.py`, `CatalogIndex` maintains per-thread SQLite connections in `self._conns: dict[int, sqlite3.Connection]`.

When `CatalogIndex.close()` is called:
```python
def close(self) -> None:
    tid = threading.get_ident()
    with self._conns_lock:
        mine = self._conns.pop(tid, None)
        foreign = list(self._conns.values())
        self._conns.clear()
    if mine is not None:
        try:
            mine.close()
        except (sqlite3.Error, Exception):
            pass
    for conn in foreign:
        try:
            conn.interrupt()
        except (sqlite3.Error, Exception):
            pass
```

1. Foreign thread connections are only interrupted via `conn.interrupt()`, but never closed (`conn.close()` is omitted).
2. Because `self._conns.clear()` is executed immediately, `_prune_dead_threads()` can no longer track or close these connections when foreign worker threads terminate. The open SQLite database handles and file descriptors leak until Python garbage collection runs.
3. If `reset()` is invoked immediately after `close()`:
```python
def reset(self) -> None:
    self.close()
    for suffix in ("", "-journal", "-wal", "-shm"):
        path = Path(f"{self.db_path}{suffix}")
        try:
            path.unlink()
        except (FileNotFoundError, OSError):
            pass
```
On Windows, `path.unlink()` fails with `PermissionError` because foreign handles hold the file open. On Linux, unlinking the file removes the directory entry but leaves the inode open in the kernel. If a background worker executes further statements on that open connection, it writes to an unlinked zombie inode, causing silent desynchronization from the newly recreated database file.

---

## Impact Analysis

- **Resource Leakage**: Unbounded accumulation of unclosed SQLite connection handles and file descriptors during heavy multi-threaded catalog indexing.
- **Windows Crashes**: `CatalogIndex.reset()` crashes with `PermissionError` when background workers hold open locks.
- **Data Desynchronization**: Background workers commit records to phantom unlinked database inodes.

---

## Reproduction Scenario & Execution Proof

### Code Trace
1. Worker thread A accesses `catalog.get_db()`, creating connection $C_A$.
2. Main thread calls `catalog.close()`.
3. $C_A$ is interrupted but not closed, and is removed from `_conns`.
4. Main thread calls `catalog.reset()`, unlinking `catalog.db`.
5. Worker thread A executes an `INSERT` statement on $C_A$. The statement succeeds on Linux against the unlinked inode, but the record never appears in the new `catalog.db`.

---

## Concrete Suggested Fix

Explicitly close all foreign connections in `close()`:

### Patch (`paleo_workbench/catalog/db.py`)
```python
def close(self) -> None:
    """Close all connections managed by this index."""
    with self._conns_lock:
        conns_to_close = list(self._conns.values())
        self._conns.clear()
    for conn in conns_to_close:
        try:
            conn.interrupt()
            conn.close()
        except (sqlite3.Error, Exception):
            pass
```
