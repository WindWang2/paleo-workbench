"""Rebuildable SQLite query index over the canonical catalog (ADR 0056).

``<project>.artifacts/metadata/catalog.sqlite`` is a pure cache: the canonical
``catalog.json`` (see ``store.py``) is the single source of truth. Every write
happens inside :meth:`CatalogIndex.rebuild` — a full delete-and-rewrite of all
tables within one transaction, keyed by the document's ``catalog_revision`` and
``schema_version`` (stored in ``sync_state``). Missing, stale, or corrupt
databases never block project open: ``revision()`` returns ``None`` and query
methods fall back to empty results, after which the caller (or ``rebuild``
itself) recreates the index from the canonical document.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataStage,
    normalize_tag_name,
)
from paleo_workbench.catalog.storage import catalog_dir_for

DB_FILENAME = "catalog.sqlite"


def metadata_search_value(value: Any) -> str:
    """Canonical string form for governance-metadata search.

    Mirrors what SQLite's ``json_extract(metadata, '$.key')`` CAST to TEXT
    yields for a value round-tripped through JSON: booleans become ``"1"`` /
    ``"0"``, numbers their decimal text, strings verbatim. Both the SQLite
    index path (``db.py``) and the canonical document scan (``queries.py``)
    normalize through this same function so one query returns the same rows
    regardless of index freshness (audit #849-2).
    """
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def like_escape_literal(text: str) -> str:
    """Escape user text for inclusion in a LIKE pattern.

    ``%`` and ``_`` are LIKE wildcards in the index path but literal
    characters in the canonical scan; escaping keeps both paths' matching
    semantics identical (audit #849-2).
    """
    return (
        str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def normalize_asset_search_name(name: str) -> str:
    """Unicode-folded search copy of an asset name (#897).

    SQLite's LIKE is ASCII-only case-insensitive, while the canonical scan
    (queries.py) matches on ``casefold()``; both paths now compare against
    this NFKC+casefold form so non-ASCII names (e.g. ``Grünfeld`` vs
    ``GRÜNFELD``) hit identically with or without the index.
    """
    import unicodedata

    return unicodedata.normalize("NFKC", str(name)).casefold()

# Version of the index table layout itself (distinct from the canonical
# document's CATALOG_SCHEMA_VERSION). Bump whenever the index schema changes so
# stale databases are rebuilt from the canonical store instead of being queried
# with a missing column.
# v4: assets.name_search — Unicode-folded copy of name (NFKC + casefold) so the
# LIKE text filter matches the canonical scan's casefold semantics for
# non-ASCII names (#897); SQLite LIKE is ASCII-only case-insensitive.
INDEX_SCHEMA_VERSION = 4

# Table/DDL definitions. The index is deliberately FK-free: it is a disposable
# projection of the canonical document, and delete order must never matter.
_SCHEMA_DDL = [
    """CREATE TABLE IF NOT EXISTS assets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        name_search TEXT NOT NULL DEFAULT '',
        type TEXT NOT NULL DEFAULT 'unknown',
        description TEXT NOT NULL DEFAULT '',
        current_version_id TEXT,
        legacy_resource_id TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        trashed INTEGER NOT NULL DEFAULT 0,
        trashed_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(name)",
    "CREATE INDEX IF NOT EXISTS idx_assets_name_search ON assets(name_search)",
    "CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(type)",
    "CREATE INDEX IF NOT EXISTS idx_assets_trashed ON assets(trashed)",
    """CREATE TABLE IF NOT EXISTS versions (
        id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        stage TEXT NOT NULL,
        managed INTEGER NOT NULL DEFAULT 1,
        path TEXT NOT NULL DEFAULT '',
        source_uri TEXT,
        format TEXT NOT NULL DEFAULT '',
        size_bytes INTEGER,
        sha256 TEXT,
        run_id TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT '',
        trashed INTEGER NOT NULL DEFAULT 0,
        trashed_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_versions_asset_id ON versions(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_versions_stage ON versions(stage)",
    "CREATE INDEX IF NOT EXISTS idx_versions_trashed ON versions(trashed)",
    "CREATE INDEX IF NOT EXISTS idx_versions_source_sha ON versions(source_uri, sha256)",
    """CREATE TABLE IF NOT EXISTS tags (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        display_name TEXT,
        metadata TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS asset_tags (
        asset_id TEXT NOT NULL,
        tag_id TEXT NOT NULL,
        PRIMARY KEY (asset_id, tag_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_asset_tags_tag_id ON asset_tags(tag_id)",
    """CREATE TABLE IF NOT EXISTS version_tags (
        version_id TEXT NOT NULL,
        tag_id TEXT NOT NULL,
        PRIMARY KEY (version_id, tag_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_version_tags_tag_id ON version_tags(tag_id)",
    """CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        operation TEXT NOT NULL,
        parameters TEXT NOT NULL DEFAULT '{}',
        generator TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'completed',
        created_at TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS run_inputs (
        run_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        PRIMARY KEY (run_id, version_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_run_inputs_version_id ON run_inputs(version_id)",
    """CREATE TABLE IF NOT EXISTS run_outputs (
        run_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        PRIMARY KEY (run_id, version_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_run_outputs_version_id ON run_outputs(version_id)",
    """CREATE TABLE IF NOT EXISTS lineage (
        parent_version_id TEXT NOT NULL,
        child_version_id TEXT NOT NULL,
        PRIMARY KEY (parent_version_id, child_version_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_lineage_child ON lineage(child_version_id)",
    """CREATE TABLE IF NOT EXISTS sync_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
]

# Children first so a future PRAGMA foreign_keys=ON stays safe.
_DELETE_ORDER = [
    "lineage",
    "version_tags",
    "asset_tags",
    "run_outputs",
    "run_inputs",
    "versions",
    "runs",
    "tags",
    "assets",
    "sync_state",
]


class ThreadSafeCatalogSession:
    """Explicit context manager ensuring thread-confined SQLite connection cleanup upon exit.

    Used by worker threads (including PySide6 QThread workers and background tasks)
    to safely acquire a thread-confined connection and guarantee its disposal upon block exit.
    """

    def __init__(self, index: "CatalogIndex") -> None:
        self._index = index
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = self._index.open()
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._index._drop_current_connection()


@dataclass(frozen=True)
class _ConnEntry:
    """One pooled connection together with the OS thread that owns it.

    ``ident`` (the dict key) is only unique among *simultaneously existing*
    threads — ``threading.get_ident()`` values are recycled after exit — so
    the entry also carries the OS-native thread id used for liveness proofs
    (see :func:`native_thread_alive`).
    """

    conn: sqlite3.Connection
    native_id: int


def native_thread_alive(native_id: int) -> bool | None:
    """Best-effort proof that the OS thread *native_id* still exists.

    Returns True/False where the platform allows an exact answer and None
    when liveness cannot be determined; callers must treat None as "assume
    alive" (leak) because closing a live connection from a foreign thread is
    the one unrecoverable mistake.

    ``threading.enumerate()`` is deliberately NOT consulted: foreign threads
    (PySide QThreads executing Python slots) only appear there after someone
    calls ``threading.current_thread()``, and their ``_DummyThread.is_alive()``
    misreports — so enumerate-based pruning closed connections of *running*
    workers (#1026).
    """
    try:
        if Path("/proc/self/task").is_dir():  # Linux: exact per-thread listing
            return Path(f"/proc/self/task/{native_id}").exists()
    except OSError:
        return None
    if sys.platform == "win32":
        import ctypes

        THREAD_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_INVALID_PARAMETER = 87
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.OpenThread.restype = ctypes.c_void_p  # HANDLE is pointer-sized
        handle = kernel32.OpenThread(
            THREAD_QUERY_LIMITED_INFORMATION, False, ctypes.c_ulong(native_id)
        )
        if not handle:
            # ERROR_INVALID_PARAMETER (87) means the thread id no longer
            # exists — the provable-death signal. Anything else (e.g. access
            # denied) is indistinguishable from alive: assume alive.
            if ctypes.get_last_error() == ERROR_INVALID_PARAMETER:
                return False
            return None
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeThread(handle, ctypes.byref(exit_code)):
                return None
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    return None


class CatalogIndex:
    """Project-local SQLite query index over a :class:`CatalogDocument`.

    The index is a rebuildable cache; ``metadata/catalog.json`` remains the
    authoritative store. ``rebuild()`` (or ``sync()``) rewrites every table
    from the document in a single transaction, so corruption or manual
    deletion is never fatal — it only means the next open rebuilds.
    """

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        # One connection PER THREAD (sqlite3 connections are not shareable:
        # check_same_thread=True raises ProgrammingError on cross-thread use,
        # which used to be swallowed into a silently stale index — issue
        # #394 / C31). WAL keeps readers on other threads consistent without
        # blocking the single writer (the service serializes saves).
        # Values carry the owning OS thread id: the ident key is recyclable
        # and enumerate()-based liveness never sees foreign threads (#1026).
        self._conns: dict[int, _ConnEntry] = {}
        self._conns_lock = threading.Lock()
        # In-memory snapshot of the last-synced document rows
        # (``{table: {id: tuple-of-columns}}``), used by the incremental sync
        # to upsert only changed rows. ``None`` = unknown state (first sync in
        # this process must rebuild). Rebuild/prime always repopulate it.
        self._last_state: dict[str, dict[str, tuple]] | None = None

    # -- lifecycle ----------------------------------------------------------

    @property
    def db_path(self) -> Path:
        """Path of the SQLite index file (``metadata/catalog.sqlite``)."""
        return catalog_dir_for(self.project_path) / DB_FILENAME

    def open(self) -> sqlite3.Connection:
        """Lazily establish the SQLite connection and return it."""
        return self._connect()

    def connect(self) -> sqlite3.Connection:
        """Alias for :meth:`open` (whichever name the caller prefers)."""
        return self.open()

    def session(self) -> ThreadSafeCatalogSession:
        """Context manager yielding a thread-local connection and safely dropping it on exit."""
        return ThreadSafeCatalogSession(self)

    def prune_dead_threads(self) -> None:
        """Close and remove connections for threads that have exited."""
        self._prune_dead_threads()

    def _prune_dead_threads(self) -> None:
        """Close and remove connections whose OWNING OS thread has exited.

        Liveness is proven per entry via :func:`native_thread_alive` (the OS
        thread id recorded when the connection was created). Entries whose
        liveness cannot be proven are left in place: a leaked descriptor is
        recoverable, closing a connection while its (possibly foreign) owner
        is mid-statement is not — that is use-after-free at the sqlite3 C
        layer (#1026, #394 / C31).
        """
        provably_dead: list[_ConnEntry] = []
        with self._conns_lock:
            for tid, entry in list(self._conns.items()):
                if native_thread_alive(entry.native_id) is False:
                    provably_dead.append(self._conns.pop(tid))
        for entry in provably_dead:
            # The owner OS thread no longer exists, so nobody can be
            # executing a statement on this handle; closing it from here is
            # the documented-safe post-mortem reaping.
            try:
                entry.conn.close()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        """Close ALL cached connections (one per thread), if any.

        A connection owned by another *live* thread cannot be closed from
        here: freeing the handle under an in-flight statement in the owner
        thread is use-after-free at the sqlite3 C layer (SIGSEGV; #394 / C31,
        reproduced by the Save As rollback racing a catalog-maintenance
        rebuild). Live foreign connections are interrupted — the one
        cross-thread API sqlite3 guarantees — dropped from the pool, and
        closed by their owner (or the garbage collector); the owning thread
        reconnects lazily on its next use. Connections whose owner OS thread
        provably exited are closed outright.
        """
        tid = threading.get_ident()
        with self._conns_lock:
            mine = self._conns.pop(tid, None)
            foreign = list(self._conns.values())
            self._conns.clear()
        if mine is not None:
            try:
                mine.conn.close()
            except sqlite3.Error:
                pass
        for entry in foreign:
            try:
                if native_thread_alive(entry.native_id) is False:
                    entry.conn.close()
                else:
                    entry.conn.interrupt()
            except sqlite3.Error:
                pass

    def drop_current_connection(self) -> None:
        """Close and forget the CURRENT thread's connection."""
        self._drop_current_connection()

    def _drop_current_connection(self) -> None:
        """Close and forget the CURRENT thread's connection.

        Error-recovery path: a failed statement leaves the connection in an
        unknown state, so the next call reconnects fresh. Other threads'
        connections are never touched — closing a live foreign connection
        could interrupt an in-flight writer (issue #394 / C31).
        """
        tid = threading.get_ident()
        with self._conns_lock:
            entry = self._conns.pop(tid, None)
        if entry is not None:
            try:
                entry.conn.close()
            except sqlite3.Error:
                pass

    def reset(self) -> None:
        """Delete the database file (plus journal/WAL/SHM) so a fresh rebuild.

        Safe to call any time: the index is fully reconstructible from the
        canonical document. Used to clear a corrupt file before rebuilding.
        """
        self.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = Path(f"{self.db_path}{suffix}")
            try:
                path.unlink()
            except (FileNotFoundError, OSError):
                pass

    def _connect(self) -> sqlite3.Connection:
        """Return the CURRENT thread's cached connection (create on demand)."""
        tid = threading.get_ident()
        native_id = threading.get_native_id()
        with self._conns_lock:
            entry = self._conns.get(tid)
        if entry is not None:
            if entry.native_id == native_id:
                return entry.conn
            # The ident was recycled: this is a NEW OS thread reusing the id
            # of a previous (exited) one. Never hand the old thread's handle
            # across — that silently shares one connection between two OS
            # threads (#1026). Disown it, then connect fresh below.
            self._disown_recycled_entry(tid, entry)
        self._prune_dead_threads()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL is safe here: writes are single-writer (the service serializes
        # saves under its lock) and WAL gives readers a consistent snapshot
        # without blocking. ``reset()`` cleans up -wal/-shm files.
        try:
            # Bound contention when a foreign process/connection holds the
            # write lock mid-checkpoint (python's sqlite3 default timeout
            # already provides this; the pragma pins it against future
            # timeout=0 calls).
            conn.execute("PRAGMA busy_timeout=5000")
        except sqlite3.DatabaseError:
            pass
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass  # e.g. read-only media — DELETE journal still works
        with self._conns_lock:
            self._conns[tid] = _ConnEntry(conn=conn, native_id=native_id)
        return conn

    def _disown_recycled_entry(self, tid: int, entry: _ConnEntry) -> None:
        """Drop a pooled entry whose ident was inherited by a new thread."""
        with self._conns_lock:
            if self._conns.get(tid) is entry:
                del self._conns[tid]
        try:
            if native_thread_alive(entry.native_id) is False:
                entry.conn.close()
            else:
                # Unreachable in practice (an ident is only recycled after
                # its thread exits); if a probe ever disagrees, interrupt —
                # the guaranteed-safe cross-thread call — and abandon the
                # handle rather than risk closing it under use.
                entry.conn.interrupt()
        except sqlite3.Error:
            pass

    # -- state ----------------------------------------------------------------

    def _read_sync_state(self, key: str) -> str | None:
        """Read one sync_state value; None when missing/unreadable/corrupt."""
        if not self.db_path.is_file():
            self._drop_current_connection()
            return None
        try:
            row = self._connect().execute(
                "SELECT value FROM sync_state WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row is not None else None
        except (sqlite3.DatabaseError, OSError):
            self._drop_current_connection()
            return None

    def revision(self) -> int | None:
        """Return the indexed ``catalog_revision``, or None when stale/corrupt."""
        raw = self._read_sync_state("catalog_revision")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def is_fresh(self, document: CatalogDocument) -> bool:
        """True when the index matches *document*'s revision and schema."""
        if self.revision() != document.catalog_revision:
            return False
        raw = self._read_sync_state("schema_version")
        if raw is None:
            return False
        try:
            if int(raw) != document.schema_version:
                return False
        except ValueError:
            return False
        # Index-layout version: an older DB without the ``trashed`` columns is
        # not fresh and gets rebuilt from the canonical store.
        index_raw = self._read_sync_state("index_schema_version")
        if index_raw is None:
            return False
        try:
            return int(index_raw) == INDEX_SCHEMA_VERSION
        except ValueError:
            return False

    def sync(self, document: CatalogDocument) -> bool:
        """Bring the index up to date with *document*; True when it changed.

        Fast path: when the database is exactly one revision behind and the
        in-memory row snapshot is available, only the changed rows are
        upserted (``INSERT OR REPLACE`` keyed by primary key, deleted rows
        removed) instead of a full delete-and-rewrite. Anything else — a
        bigger gap, a missing/corrupt database, an unknown snapshot — falls
        back to :meth:`rebuild`, so the rebuildable-index guarantee and
        self-healing are unchanged.
        """
        if self.is_fresh(document):
            return False
        if self._can_incremental(document):
            self._sync_incremental(document)
            return True
        self.rebuild(document)
        return True

    # -- rebuild ---------------------------------------------------------------

    def rebuild(self, document: CatalogDocument) -> None:
        """Rewrite every table from *document* in a single transaction.

        Self-healing: a corrupt database file is deleted and recreated from
        scratch (callers may also use :meth:`reset` explicitly first). Records
        the row snapshot so subsequent single-revision saves sync
        incrementally.
        """
        self.close()
        for attempt in (0, 1):
            try:
                self._rebuild_once(document)
                break
            except sqlite3.DatabaseError:
                if attempt:
                    raise
                self.reset()
        self._last_state = self._state_of(document)

    def prime(self, document: CatalogDocument) -> "CatalogIndex":
        """Record *document*'s row snapshot WITHOUT touching the database.

        Call after confirming the index is fresh (e.g. on project open) so the
        first save of this process syncs incrementally instead of rebuilding.
        The snapshot equals the fresh database because revision + schema
        equality implies identical document content in this codebase.
        """
        self._last_state = self._state_of(document)
        return self

    def _rebuild_once(self, document: CatalogDocument) -> None:
        conn = self._connect()
        with conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(ddl)
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")

            conn.executemany(
                "INSERT INTO assets (id, name, name_search, type, description, current_version_id,"
                " legacy_resource_id, metadata, created_at, updated_at, trashed, trashed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        asset.id,
                        asset.name,
                        normalize_asset_search_name(asset.name),
                        asset.type,
                        asset.description,
                        asset.current_version_id,
                        asset.legacy_resource_id,
                        json.dumps(asset.metadata, ensure_ascii=False),
                        asset.created_at,
                        asset.updated_at,
                        int(asset.trashed),
                        asset.trashed_at,
                    )
                    for asset in document.assets
                ],
            )
            conn.executemany(
                "INSERT INTO versions (id, asset_id, version_number, stage, managed,"
                " path, source_uri, format, size_bytes, sha256, run_id, metadata,"
                " created_at, trashed, trashed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        version.id,
                        version.asset_id,
                        version.version_number,
                        version.stage.value,
                        int(version.managed),
                        version.path,
                        version.source_uri,
                        version.format,
                        version.size_bytes,
                        version.sha256,
                        version.run_id,
                        json.dumps(version.metadata, ensure_ascii=False),
                        version.created_at,
                        int(version.trashed),
                        version.trashed_at,
                    )
                    for version in document.versions
                ],
            )
            # Tag name is stored normalized so lookups are case/whitespace-safe;
            # the display form lives in display_name.
            conn.executemany(
                "INSERT OR IGNORE INTO tags (id, name, display_name, metadata)"
                " VALUES (?,?,?,?)",
                [
                    (
                        tag.id,
                        normalize_tag_name(tag.name),
                        tag.display_name,
                        json.dumps(tag.metadata, ensure_ascii=False),
                    )
                    for tag in document.tags
                ],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (?,?)",
                [
                    (asset_id, tag_id)
                    for asset_id, tag_ids in document.asset_tags.items()
                    for tag_id in tag_ids
                ],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO version_tags (version_id, tag_id) VALUES (?,?)",
                [
                    (version_id, tag_id)
                    for version_id, tag_ids in document.version_tags.items()
                    for tag_id in tag_ids
                ],
            )
            conn.executemany(
                "INSERT INTO runs (id, operation, parameters, generator, status,"
                " created_at) VALUES (?,?,?,?,?,?)",
                [
                    (
                        run.id,
                        run.operation,
                        json.dumps(run.parameters, ensure_ascii=False),
                        run.generator,
                        run.status,
                        run.created_at,
                    )
                    for run in document.runs
                ],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO run_inputs (run_id, version_id) VALUES (?,?)",
                [
                    (run.id, version_id)
                    for run in document.runs
                    for version_id in run.input_version_ids
                ],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO run_outputs (run_id, version_id) VALUES (?,?)",
                [
                    (run.id, version_id)
                    for run in document.runs
                    for version_id in run.output_version_ids
                ],
            )

            # Materialized lineage edges: explicit parents plus run input→output.
            lineage_rows: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for version in document.versions:
                for parent in version.parent_version_ids:
                    edge = (parent, version.id)
                    if edge not in seen:
                        seen.add(edge)
                        lineage_rows.append(edge)
            for run in document.runs:
                for input_id in run.input_version_ids:
                    for output_id in run.output_version_ids:
                        edge = (input_id, output_id)
                        if edge not in seen:
                            seen.add(edge)
                            lineage_rows.append(edge)
            conn.executemany(
                "INSERT OR IGNORE INTO lineage (parent_version_id, child_version_id)"
                " VALUES (?,?)",
                lineage_rows,
            )

            conn.executemany(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
                [
                    ("schema_version", str(document.schema_version)),
                    ("catalog_revision", str(document.catalog_revision)),
                    ("index_schema_version", str(INDEX_SCHEMA_VERSION)),
                ],
            )

    # -- incremental sync -------------------------------------------------------

    def _state_of(self, document: CatalogDocument) -> dict[str, dict[str, tuple]]:
        """Snapshot each row as an id→column-tuple map (the diff source).

        Tuples include derived columns (parent ids, run input/output ids, tag
        id sets) so a change in any stored column or derived join row is
        detected by tuple inequality. JSON columns are serialized with the
        same kwargs as ``_rebuild_once`` for byte-identical comparison.
        """
        assets: dict[str, tuple] = {}
        for asset in document.assets:
            assets[asset.id] = (
                asset.name,
                normalize_asset_search_name(asset.name),
                asset.type,
                asset.description,
                asset.current_version_id,
                asset.legacy_resource_id,
                json.dumps(asset.metadata, ensure_ascii=False),
                asset.created_at,
                asset.updated_at,
                int(asset.trashed),
                asset.trashed_at,
            )
        versions: dict[str, tuple] = {}
        for version in document.versions:
            versions[version.id] = (
                version.asset_id,
                version.version_number,
                version.stage.value,
                int(version.managed),
                version.path,
                version.source_uri,
                version.format,
                version.size_bytes,
                version.sha256,
                version.run_id,
                json.dumps(version.metadata, ensure_ascii=False),
                version.created_at,
                int(version.trashed),
                version.trashed_at,
                tuple(version.parent_version_ids),
            )
        runs: dict[str, tuple] = {}
        for run in document.runs:
            runs[run.id] = (
                run.operation,
                json.dumps(run.parameters, ensure_ascii=False),
                run.generator,
                run.status,
                run.created_at,
                tuple(run.input_version_ids),
                tuple(run.output_version_ids),
            )
        tags: dict[str, tuple] = {}
        for tag in document.tags:
            tags[tag.id] = (
                tag.name,
                tag.display_name,
                json.dumps(tag.metadata, ensure_ascii=False),
            )
        asset_tags = {
            asset_id: frozenset(tag_ids)
            for asset_id, tag_ids in document.asset_tags.items()
        }
        version_tags = {
            version_id: frozenset(tag_ids)
            for version_id, tag_ids in document.version_tags.items()
        }
        return {
            "assets": assets,
            "versions": versions,
            "runs": runs,
            "tags": tags,
            "asset_tags": asset_tags,
            "version_tags": version_tags,
        }

    def _can_incremental(self, document: CatalogDocument) -> bool:
        """True when the DB is exactly one revision behind and diffable."""
        if self._last_state is None:
            return False
        try:
            revision = self.revision()
            schema = self._read_sync_state("schema_version")
            layout = self._read_sync_state("index_schema_version")
        except Exception:
            return False
        if revision is None or revision != document.catalog_revision - 1:
            return False
        if schema != str(document.schema_version):
            return False
        return layout == str(INDEX_SCHEMA_VERSION)

    def _delete_entity(
        self,
        conn: sqlite3.Connection,
        table: str,
        entity_id: str,
        last_row: tuple | None,
        lineage_keep: tuple[set[tuple[str, str]], set[tuple[str, str]]] | None = None,
    ) -> None:
        """Remove one entity row plus its dependent rows (exact per-table).

        Lineage edges are the union of version-parent edges and retained-run
        edges. ``lineage_keep`` is ``(run_pairs, version_pairs)`` from the
        *current* document state; a version's old parent edges are deleted only
        when not also covered by a retained run (so purging a version never
        drops a run-derived edge a full rebuild would keep).
        """
        if table == "assets":
            conn.execute("DELETE FROM assets WHERE id = ?", (entity_id,))
            conn.execute("DELETE FROM asset_tags WHERE asset_id = ?", (entity_id,))
        elif table == "versions":
            conn.execute("DELETE FROM versions WHERE id = ?", (entity_id,))
            conn.execute("DELETE FROM version_tags WHERE version_id = ?", (entity_id,))
            # Run input/output link rows are NOT deleted here: they are owned
            # by the run record, which retains purged version ids as historical
            # provenance (service.purge_trashed keeps runs). A full rebuild
            # re-creates those rows from the run, so deleting them would make
            # the incremental index diverge from a rebuild.
            if last_row is not None and lineage_keep is not None:
                run_pairs, _version_pairs = lineage_keep
                for parent_id in last_row[-1]:
                    if (parent_id, entity_id) not in run_pairs:
                        conn.execute(
                            "DELETE FROM lineage WHERE parent_version_id = ?"
                            " AND child_version_id = ?",
                            (parent_id, entity_id),
                        )
        elif table == "runs":
            conn.execute("DELETE FROM runs WHERE id = ?", (entity_id,))
            conn.execute("DELETE FROM run_inputs WHERE run_id = ?", (entity_id,))
            conn.execute("DELETE FROM run_outputs WHERE run_id = ?", (entity_id,))
            if last_row is not None and lineage_keep is not None:
                run_pairs, version_pairs = lineage_keep
                for input_id in last_row[-2]:
                    for output_id in last_row[-1]:
                        if (input_id, output_id) not in run_pairs and (
                            input_id, output_id
                        ) not in version_pairs:
                            conn.execute(
                                "DELETE FROM lineage WHERE parent_version_id = ?"
                                " AND child_version_id = ?",
                                (input_id, output_id),
                            )
        elif table == "tags":
            conn.execute("DELETE FROM tags WHERE id = ?", (entity_id,))
            conn.execute("DELETE FROM asset_tags WHERE tag_id = ?", (entity_id,))
            conn.execute("DELETE FROM version_tags WHERE tag_id = ?", (entity_id,))

    def _sync_incremental(self, document: CatalogDocument) -> None:
        """Upsert changed rows (and remove deleted ones) in one transaction.

        The result is byte-equivalent to a full :meth:`rebuild`: only the
        write set shrinks to the actually-changed rows. Any failure raises
        inside the transaction, rolling the database back to the previous
        revision, after which ``sync`` self-heals via :meth:`rebuild`.
        """
        state = self._state_of(document)
        last = self._last_state
        assert last is not None
        conn = self._connect()
        # Lineage-affecting change detection: any version parents / run io
        # differ, or any version/run was added or removed. When nothing
        # lineage-affecting changed, the lineage table is left untouched
        # (the import-folder path adds parent-less RAW versions → O(Δ) sync).
        version_lin_changed = (
            set(last["versions"]) != set(state["versions"])
            or any(
                last["versions"].get(vid) is None
                or last["versions"][vid][-1] != row[-1]
                for vid, row in state["versions"].items()
            )
        )
        run_lin_changed = (
            set(last["runs"]) != set(state["runs"])
            or any(
                last["runs"].get(rid) is None
                or last["runs"][rid][-2:] != row[-2:]
                for rid, row in state["runs"].items()
            )
        )
        lineage_keep: tuple[set[tuple[str, str]], set[tuple[str, str]]] | None = None
        if version_lin_changed or run_lin_changed:
            # Current (post-change) edge sets: lineage deletion must keep any
            # pair still covered by a version-parent edge or a retained run.
            run_pairs = {
                (input_id, output_id)
                for rid, row in state["runs"].items()
                for input_id in row[-2]
                for output_id in row[-1]
            }
            version_pairs = {
                (parent_id, vid)
                for vid, row in state["versions"].items()
                for parent_id in row[-1]
            }
            lineage_keep = (run_pairs, version_pairs)
        with conn:
            # 1. Deletions first (ids present last sync, gone from the document).
            for table in ("assets", "versions", "runs", "tags"):
                for entity_id in set(last[table]) - set(state[table]):
                    self._delete_entity(
                        conn, table, entity_id, last[table].get(entity_id), lineage_keep
                    )

            # 2. Tag associations: full per-owner refresh on change.
            for asset_id in set(last["asset_tags"]) | set(state["asset_tags"]):
                if last["asset_tags"].get(asset_id) != state["asset_tags"].get(asset_id):
                    conn.execute(
                        "DELETE FROM asset_tags WHERE asset_id = ?", (asset_id,)
                    )
                    conn.executemany(
                        "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id)"
                        " VALUES (?,?)",
                        [(asset_id, tid) for tid in state["asset_tags"].get(asset_id, ())],
                    )
            for version_id in set(last["version_tags"]) | set(state["version_tags"]):
                if last["version_tags"].get(version_id) != state["version_tags"].get(version_id):
                    conn.execute(
                        "DELETE FROM version_tags WHERE version_id = ?", (version_id,)
                    )
                    conn.executemany(
                        "INSERT OR IGNORE INTO version_tags (version_id, tag_id)"
                        " VALUES (?,?)",
                        [(version_id, tid) for tid in state["version_tags"].get(version_id, ())],
                    )

            # 3. Row upserts + dependent join rows.
            for asset_id, row in state["assets"].items():
                if last["assets"].get(asset_id) != row:
                    conn.execute(
                        "INSERT OR REPLACE INTO assets (id, name, name_search, type, description,"
                        " current_version_id, legacy_resource_id, metadata, created_at,"
                        " updated_at, trashed, trashed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (asset_id, *row),
                    )
            for version_id, row in state["versions"].items():
                old = last["versions"].get(version_id)
                if old == row:
                    continue
                if old is None or old[-1] != row[-1]:
                    # Lineage edges owned by this version's parent ids. Old
                    # parents come from the snapshot; a pair still covered by a
                    # retained run is kept (a full rebuild would re-create it).
                    if old is not None and lineage_keep is not None:
                        run_pairs, _version_pairs = lineage_keep
                        for parent_id in old[-1]:
                            if (parent_id, version_id) not in run_pairs:
                                conn.execute(
                                    "DELETE FROM lineage WHERE parent_version_id = ?"
                                    " AND child_version_id = ?",
                                    (parent_id, version_id),
                                )
                    conn.executemany(
                        "INSERT OR IGNORE INTO lineage (parent_version_id,"
                        " child_version_id) VALUES (?,?)",
                        [(parent_id, version_id) for parent_id in row[-1]],
                    )
                conn.execute(
                    "INSERT OR REPLACE INTO versions (id, asset_id, version_number,"
                    " stage, managed, path, source_uri, format, size_bytes, sha256,"
                    " run_id, metadata, created_at, trashed, trashed_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (version_id, *row[:-1]),
                )
            for run_id, row in state["runs"].items():
                old = last["runs"].get(run_id)
                if old == row:
                    continue
                # The runs row itself must be upserted (same pattern as the
                # versions/tags loops): a run that first appears in an
                # incremental revision would otherwise never land in the
                # ``runs`` table — only a full rebuild writes it (DATA-1).
                conn.execute(
                    "INSERT OR REPLACE INTO runs (id, operation, parameters,"
                    " generator, status, created_at) VALUES (?,?,?,?,?,?)",
                    (run_id, *row[:-2]),
                )
                conn.execute("DELETE FROM run_inputs WHERE run_id = ?", (run_id,))
                conn.execute("DELETE FROM run_outputs WHERE run_id = ?", (run_id,))
                conn.executemany(
                    "INSERT OR IGNORE INTO run_inputs (run_id, version_id)"
                    " VALUES (?,?)",
                    [(run_id, vid) for vid in row[-2]],
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO run_outputs (run_id, version_id)"
                    " VALUES (?,?)",
                    [(run_id, vid) for vid in row[-1]],
                )
                # Run-derived lineage edges: remove old pairs no longer covered
                # by any source, add new pairs (deduped).
                new_pairs = [(i, o) for i in row[-2] for o in row[-1]]
                run_pairs, version_pairs = lineage_keep or (set(), set())
                if old is not None:
                    for input_id in old[-2]:
                        for output_id in old[-1]:
                            pair = (input_id, output_id)
                            if pair not in run_pairs and pair not in version_pairs:
                                conn.execute(
                                    "DELETE FROM lineage WHERE parent_version_id = ?"
                                    " AND child_version_id = ?",
                                    pair,
                                )
                    for pair in new_pairs:
                        if pair not in version_pairs:
                            conn.execute(
                                "INSERT OR IGNORE INTO lineage (parent_version_id,"
                                " child_version_id) VALUES (?,?)",
                                pair,
                            )
                else:
                    conn.executemany(
                        "INSERT OR IGNORE INTO lineage (parent_version_id,"
                        " child_version_id) VALUES (?,?)",
                        new_pairs,
                    )
            for tag_id, row in state["tags"].items():
                if last["tags"].get(tag_id) != row:
                    conn.execute(
                        "INSERT OR REPLACE INTO tags (id, name, display_name,"
                        " metadata) VALUES (?,?,?,?)",
                        (tag_id, *row),
                    )

            # 4. Sync state (revision advances with the canonical document).
            conn.executemany(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
                [
                    ("schema_version", str(document.schema_version)),
                    ("catalog_revision", str(document.catalog_revision)),
                    ("index_schema_version", str(INDEX_SCHEMA_VERSION)),
                ],
            )
        self._last_state = state

    # -- queries ----------------------------------------------------------------

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict:
        """Convert a row to a plain dict, decoding stored JSON columns."""
        data = dict(row)
        for key in ("metadata", "parameters"):
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = json.loads(data[key])
                except json.JSONDecodeError:
                    data[key] = {}
        return data

    def _safe(self, default: Any, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run *fn*, returning *default* (and dropping the connection) on trouble."""
        if not self.db_path.is_file():
            self._drop_current_connection()
            return default
        try:
            return fn(*args, **kwargs)
        except (sqlite3.DatabaseError, OSError):
            self._drop_current_connection()
            return default

    def search_assets(
        self,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tag: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        metadata: list[tuple[str, str]] | None = None,
    ) -> list[dict]:
        """Search assets by name substring, version stage, tag(s), type, and
        metadata key-value pairs.

        ``tags`` + ``tag_op`` (``"and"``/``"or"``) express multi-tag queries;
        a single ``tag`` is unioned into ``tags``. ``metadata`` pairs match
        ``json_extract(assets.metadata, '$."key"') = value`` (governance
        fields live in that JSON column — no schema change needed).
        """
        return self._safe(
            [],
            self._search_assets,
            text=text,
            stage=stage,
            tag=tag,
            tags=tags,
            tag_op=tag_op,
            type=type,
            metadata=metadata,
        )

    def _search_assets(
        self,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tag: str | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        tag_op: str = "and",
        type: str | None = None,
        metadata: list[tuple[str, str]] | None = None,
    ) -> list[dict]:
        joins: list[str] = []
        wheres: list[str] = []
        params: list[str] = []
        if stage is not None:
            joins.append("JOIN versions v ON v.asset_id = a.id")
            wheres.append("v.stage = ?")
            params.append(stage.value if isinstance(stage, DataStage) else str(stage))
        tag_list = [normalize_tag_name(t) for t in (tags or []) if str(t).strip()]
        if tag is not None and str(tag).strip():
            tag_list.append(normalize_tag_name(tag))
        if tag_list:
            # EXISTS per tag keeps AND/OR semantics without DISTINCT-fanout;
            # every branch is index-backed (idx_asset_tags_tag_id, tags.name).
            if tag_op == "or":
                placeholders = ", ".join("?" for _ in tag_list)
                wheres.append(
                    "EXISTS (SELECT 1 FROM asset_tags at_o"
                    " JOIN tags t_o ON t_o.id = at_o.tag_id"
                    f" WHERE at_o.asset_id = a.id AND t_o.name IN ({placeholders}))"
                )
                params.extend(tag_list)
            else:
                for tag_name in tag_list:
                    wheres.append(
                        "EXISTS (SELECT 1 FROM asset_tags at_a"
                        " JOIN tags t_a ON t_a.id = at_a.tag_id"
                        " WHERE at_a.asset_id = a.id AND t_a.name = ?)"
                    )
                    params.append(tag_name)
        if text:
            # Match the canonical scan's Unicode casefold semantics via the
            # normalized name_search column (#897); plain LIKE on name is
            # ASCII-only case-insensitive and diverged for non-ASCII names.
            wheres.append("a.name_search LIKE ? ESCAPE '\\'")
            params.append(
                f"%{like_escape_literal(normalize_asset_search_name(text))}%"
            )
        if type is not None:
            wheres.append("a.type = ?")
            params.append(str(type))
        for key, value in metadata or []:
            # Metadata lives as a JSON TEXT column (assets.metadata); the
            # json_extract predicate keeps governance filtering on the index
            # path at 10k+ assets without a schema change. The path is quoted
            # and the extraction CAST to TEXT so non-string values (manual
            # catalog.json edits) match like the canonical scan does. Values
            # normalize through metadata_search_value so booleans agree with
            # the scan path's Python-side str() semantics (audit #849-2).
            wheres.append("CAST(json_extract(a.metadata, ?) AS TEXT) = ?")
            params.extend([f'$."{key}"', metadata_search_value(value)])
        where = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        sql = f"SELECT DISTINCT a.* FROM assets a {' '.join(joins)} {where}"
        rows = self._connect().execute(sql, params).fetchall()
        return [self._decode(row) for row in rows]

    def list_versions(self, asset_id: str) -> list[dict]:
        """All versions of *asset_id*, ordered by ``version_number``."""
        return self._safe([], self._list_versions, asset_id)

    def _list_versions(self, asset_id: str) -> list[dict]:
        rows = self._connect().execute(
            "SELECT * FROM versions WHERE asset_id = ? ORDER BY version_number",
            (asset_id,),
        ).fetchall()
        return [self._decode(row) for row in rows]

    def lineage_edges(self, version_id: str) -> dict:
        """Direct parent and child version ids of *version_id*."""
        return self._safe(
            {"parents": [], "children": []}, self._lineage_edges, version_id
        )

    def _lineage_edges(self, version_id: str) -> dict:
        conn = self._connect()
        parents = [
            row[0]
            for row in conn.execute(
                "SELECT parent_version_id FROM lineage WHERE child_version_id = ?",
                (version_id,),
            )
        ]
        children = [
            row[0]
            for row in conn.execute(
                "SELECT child_version_id FROM lineage WHERE parent_version_id = ?",
                (version_id,),
            )
        ]
        return {"parents": parents, "children": children}

    def assets_for_tag(self, tag_name: str) -> list[str]:
        """Asset ids carrying *tag_name* (matched after normalization)."""
        return self._safe([], self._assets_for_tag, tag_name)

    def _assets_for_tag(self, tag_name: str) -> list[str]:
        rows = self._connect().execute(
            "SELECT a.id FROM assets a"
            " JOIN asset_tags at ON at.asset_id = a.id"
            " JOIN tags t ON t.id = at.tag_id"
            " WHERE t.name = ? ORDER BY a.id",
            (normalize_tag_name(tag_name),),
        ).fetchall()
        return [row[0] for row in rows]

    def versions_for_tag(self, tag_name: str) -> list[str]:
        """Version ids carrying *tag_name* (matched after normalization)."""
        return self._safe([], self._versions_for_tag, tag_name)

    def _versions_for_tag(self, tag_name: str) -> list[str]:
        rows = self._connect().execute(
            "SELECT v.id FROM versions v"
            " JOIN version_tags vt ON vt.version_id = v.id"
            " JOIN tags t ON t.id = vt.tag_id"
            " WHERE t.name = ? ORDER BY v.id",
            (normalize_tag_name(tag_name),),
        ).fetchall()
        return [row[0] for row in rows]

    def find_managed_raw(self, source_uri: str, sha256_value: str) -> str | None:
        """Version id of a managed RAW version with the exact (source, checksum).

        Powers O(log N) import dedup (P4) instead of scanning every version.
        Returns None when the database is missing/unreadable so callers fall
        back to a document scan (correctness never depends on the index).
        """
        return self._safe(None, self._find_managed_raw, source_uri, sha256_value)

    def _find_managed_raw(self, source_uri: str, sha256_value: str) -> str | None:
        row = self._connect().execute(
            "SELECT id FROM versions WHERE managed = 1 AND stage = 'raw'"
            " AND trashed = 0 AND source_uri = ? AND sha256 = ? LIMIT 1",
            (source_uri, sha256_value),
        ).fetchone()
        return row[0] if row is not None else None

    def find_external_by_path(self, path: str) -> str | None:
        """Version id of an unmanaged version linked at the exact path."""
        return self._safe(None, self._find_external_by_path, path)

    def _find_external_by_path(self, path: str) -> str | None:
        row = self._connect().execute(
            "SELECT id FROM versions WHERE managed = 0 AND trashed = 0"
            " AND path = ? LIMIT 1",
            (path,),
        ).fetchone()
        return row[0] if row is not None else None
