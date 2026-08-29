"""Canonical SQLite store for the catalog (ADR 0056, amended by #1027).

``<project>.artifacts/metadata/catalog.sqlite`` (WAL) is the canonical
metadata store: mutations commit row-level changes in one transaction
(:meth:`apply_changes`, driven by the service's dirty sets), the legacy
``catalog.json`` project migrates via a single transactional import
(:meth:`write_all`), and reopening reconstructs the document directly
(:meth:`load_document`). ``catalog.json`` (see ``store.py``) is demoted to a
checkpoint/export manifest. A corrupt database is still recoverable: the
manifest checkpoint plus :meth:`rebuild` recreate the store, and
:meth:`reconcile` repairs drift between the store and the in-memory document.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from dataclasses import dataclass, field
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

# Version of the store's table layout itself (distinct from the canonical
# document's CATALOG_SCHEMA_VERSION). Bump whenever the schema changes so
# stale databases are rebuilt instead of being queried with a missing column.
# v4: assets.name_search — Unicode-folded copy of name (NFKC + casefold) so the
# LIKE text filter matches the canonical scan's casefold semantics for
# non-ASCII names (#897); SQLite LIKE is ASCII-only case-insensitive.
# v5: SQLite becomes the CANONICAL store (#1027): models + model_versions
# tables were added (the registry previously lived only in catalog.json) and
# sync_state gains a manifest_mtime_ns bookkeeping key. A v4 database is a
# legacy rebuildable index and is migrated by a full transactional re-import
# from catalog.json on first open.
INDEX_SCHEMA_VERSION = 5
STORE_SCHEMA_VERSION = 5  # first version with canonical semantics

# Table/DDL definitions. Deliberately FK-free: the store is a projection of
# the in-memory document, and delete order must never matter.
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
        trashed_at TEXT,
        parent_ids TEXT NOT NULL DEFAULT '[]'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_versions_asset_id ON versions(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_versions_stage ON versions(stage)",
    "CREATE INDEX IF NOT EXISTS idx_versions_trashed ON versions(trashed)",
    "CREATE INDEX IF NOT EXISTS idx_versions_source_sha ON versions(source_uri, sha256)",
    # #1043: find_external_by_path dedups every external registration with
    # ``managed = 0 AND trashed = 0 AND path = ?``; the partial index matches
    # the exact predicate (planner proves coverage without statistics) and
    # managed versions skip index maintenance on insert.
    "CREATE INDEX IF NOT EXISTS idx_versions_external_path ON versions(path) WHERE managed = 0 AND trashed = 0",
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
        model_ref TEXT,
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
    """CREATE TABLE IF NOT EXISTS models (
        id TEXT PRIMARY KEY,
        model_id TEXT NOT NULL,
        model_name TEXT NOT NULL,
        model_type TEXT NOT NULL DEFAULT 'unknown',
        capability TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'demo',
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT '',
        provenance TEXT NOT NULL DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_models_model_id ON models(model_id)",
    """CREATE TABLE IF NOT EXISTS model_versions (
        id TEXT PRIMARY KEY,
        model_id TEXT NOT NULL,
        model_version TEXT NOT NULL DEFAULT '1',
        artifact_uri TEXT NOT NULL DEFAULT '',
        checksum TEXT,
        input_schema TEXT NOT NULL DEFAULT '{}',
        output_schema TEXT NOT NULL DEFAULT '{}',
        preprocessing_version TEXT NOT NULL DEFAULT '',
        runtime TEXT NOT NULL DEFAULT '',
        deterministic INTEGER NOT NULL DEFAULT 1,
        demo_only INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'production',
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT '',
        provenance TEXT NOT NULL DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_model_versions_model_id ON model_versions(model_id)",
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
    "model_versions",
    "models",
    "sync_state",
]


# ---------------------------------------------------------------------------
# Row builders — ONE serialization per table shared by rebuild / load /
# incremental write so all three agree by construction.
# ---------------------------------------------------------------------------


def _asset_row(asset) -> tuple:
    return (
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


# Upserts use ON CONFLICT DO UPDATE (not INSERT OR REPLACE): REPLACE
# reassigns the rowid, floating updated rows to the table tail and breaking
# the rowid == document-insertion-order invariant load_document relies on.
_ASSET_UPSERT_SQL = (
    "INSERT INTO assets (id, name, name_search, type, description,"
    " current_version_id, legacy_resource_id, metadata, created_at, updated_at,"
    " trashed, trashed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
    " name_search=excluded.name_search, type=excluded.type,"
    " description=excluded.description,"
    " current_version_id=excluded.current_version_id,"
    " legacy_resource_id=excluded.legacy_resource_id,"
    " metadata=excluded.metadata, created_at=excluded.created_at,"
    " updated_at=excluded.updated_at, trashed=excluded.trashed,"
    " trashed_at=excluded.trashed_at"
)


def _version_row(version) -> tuple:
    return (
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
        json.dumps(list(version.parent_version_ids)),
    )


_VERSION_UPSERT_SQL = (
    "INSERT INTO versions (id, asset_id, version_number, stage,"
    " managed, path, source_uri, format, size_bytes, sha256, run_id, metadata,"
    " created_at, trashed, trashed_at, parent_ids)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET asset_id=excluded.asset_id,"
    " version_number=excluded.version_number, stage=excluded.stage,"
    " managed=excluded.managed, path=excluded.path,"
    " source_uri=excluded.source_uri, format=excluded.format,"
    " size_bytes=excluded.size_bytes, sha256=excluded.sha256,"
    " run_id=excluded.run_id, metadata=excluded.metadata,"
    " created_at=excluded.created_at, trashed=excluded.trashed,"
    " trashed_at=excluded.trashed_at, parent_ids=excluded.parent_ids"
)


def _run_row(run) -> tuple:
    return (
        run.operation,
        json.dumps(run.parameters, ensure_ascii=False),
        run.generator,
        run.status,
        json.dumps(run.model_ref, ensure_ascii=False) if run.model_ref else None,
        run.created_at,
    )


_RUN_UPSERT_SQL = (
    "INSERT INTO runs (id, operation, parameters, generator, status,"
    " model_ref, created_at) VALUES (?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET operation=excluded.operation,"
    " parameters=excluded.parameters, generator=excluded.generator,"
    " status=excluded.status, model_ref=excluded.model_ref,"
    " created_at=excluded.created_at"
)


def _tag_row(tag) -> tuple:
    return (
        normalize_tag_name(tag.name),
        tag.display_name,
        json.dumps(tag.metadata, ensure_ascii=False),
    )


_TAG_UPSERT_SQL = (
    "INSERT INTO tags (id, name, display_name, metadata)"
    " VALUES (?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
    " display_name=excluded.display_name, metadata=excluded.metadata"
)


def _model_row(model) -> tuple:
    return (
        model.model_id,
        model.model_name,
        model.model_type,
        model.capability,
        model.provider,
        model.status,
        json.dumps(model.metadata, ensure_ascii=False),
        model.created_at,
        json.dumps(model.provenance, ensure_ascii=False),
    )


_MODEL_UPSERT_SQL = (
    "INSERT INTO models (id, model_id, model_name, model_type,"
    " capability, provider, status, metadata, created_at, provenance)"
    " VALUES (?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id,"
    " model_name=excluded.model_name, model_type=excluded.model_type,"
    " capability=excluded.capability, provider=excluded.provider,"
    " status=excluded.status, metadata=excluded.metadata,"
    " created_at=excluded.created_at, provenance=excluded.provenance"
)


def _model_version_row(mv) -> tuple:
    return (
        mv.model_id,
        mv.model_version,
        mv.artifact_uri,
        mv.checksum,
        json.dumps(mv.input_schema, ensure_ascii=False),
        json.dumps(mv.output_schema, ensure_ascii=False),
        mv.preprocessing_version,
        mv.runtime,
        int(mv.deterministic),
        int(mv.demo_only),
        mv.status,
        json.dumps(mv.metadata, ensure_ascii=False),
        mv.created_at,
        json.dumps(mv.provenance, ensure_ascii=False),
    )


_MODEL_VERSION_UPSERT_SQL = (
    "INSERT INTO model_versions (id, model_id, model_version,"
    " artifact_uri, checksum, input_schema, output_schema, preprocessing_version,"
    " runtime, deterministic, demo_only, status, metadata, created_at, provenance)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    " ON CONFLICT(id) DO UPDATE SET model_id=excluded.model_id,"
    " model_version=excluded.model_version, artifact_uri=excluded.artifact_uri,"
    " checksum=excluded.checksum, input_schema=excluded.input_schema,"
    " output_schema=excluded.output_schema,"
    " preprocessing_version=excluded.preprocessing_version,"
    " runtime=excluded.runtime, deterministic=excluded.deterministic,"
    " demo_only=excluded.demo_only, status=excluded.status,"
    " metadata=excluded.metadata, created_at=excluded.created_at,"
    " provenance=excluded.provenance"
)


def _symmetric_diff(
    db_rows: dict[str, tuple], doc_rows: dict[str, tuple]
) -> dict[str, None]:
    """Ids whose row differs between the store and the document.

    Document-ordered (doc_rows is built in document order): re-inserted rows
    keep the rowid == document-order invariant ``_ordered`` relies on.
    """
    changed: dict[str, None] = {}
    for entity_id, row in doc_rows.items():
        if db_rows.get(entity_id) != row:
            changed[entity_id] = None
    for entity_id in set(db_rows) - set(doc_rows):
        changed[entity_id] = None
    return changed


@dataclass
class DirtySet:
    """Entity ids touched by a mutation batch (drives :meth:`apply_changes`).

    Collections are insertion-ordered dicts: ids are marked in document
    mutation order, which ``apply_changes`` relies on so rows inserted in one
    transaction keep document order. ``asset_tags`` / ``version_tags`` hold
    OWNER ids whose tag association changed. An id absent from the document
    means "delete".
    """

    assets: dict[str, None] = field(default_factory=dict)
    versions: dict[str, None] = field(default_factory=dict)
    runs: dict[str, None] = field(default_factory=dict)
    tags: dict[str, None] = field(default_factory=dict)
    models: dict[str, None] = field(default_factory=dict)
    model_versions: dict[str, None] = field(default_factory=dict)
    asset_tags: dict[str, None] = field(default_factory=dict)
    version_tags: dict[str, None] = field(default_factory=dict)

    def mark_assets(self, entity_id: str) -> None:
        self.assets[entity_id] = None

    def mark_versions(self, entity_id: str) -> None:
        self.versions[entity_id] = None

    def mark_runs(self, entity_id: str) -> None:
        self.runs[entity_id] = None

    def mark_tags(self, entity_id: str) -> None:
        self.tags[entity_id] = None

    def mark_models(self, entity_id: str) -> None:
        self.models[entity_id] = None

    def mark_model_versions(self, entity_id: str) -> None:
        self.model_versions[entity_id] = None

    def mark_asset_tags(self, entity_id: str) -> None:
        self.asset_tags[entity_id] = None

    def mark_version_tags(self, entity_id: str) -> None:
        self.version_tags[entity_id] = None

    def merge(self, other: "DirtySet") -> None:
        for field_name in (
            "assets",
            "versions",
            "runs",
            "tags",
            "models",
            "model_versions",
            "asset_tags",
            "version_tags",
        ):
            incoming = getattr(other, field_name)
            # Callers may hand a plain set of ids; normalize so dict.update
            # never misreads an id string as a (key, value) pair.
            if not isinstance(incoming, dict):
                incoming = dict.fromkeys(incoming)
            getattr(self, field_name).update(incoming)

    def is_empty(self) -> bool:
        return not any(
            (
                self.assets,
                self.versions,
                self.runs,
                self.tags,
                self.models,
                self.model_versions,
                self.asset_tags,
                self.version_tags,
            )
        )


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

    def _schema_present(self, conn: sqlite3.Connection) -> bool:
        """True when the canonical schema exists in the connected database.

        ``_connect`` recreates an empty file when the store was deleted
        mid-session (and a failed flush can leave a zero-byte one behind),
        so callers that read or write tables must gate on this — the
        rebuildable-store guarantee is ``write_all`` from the document,
        never a query against tables that are not there.
        """
        row = conn.execute(
            "SELECT 1 FROM sqlite_master"
            " WHERE type = 'table' AND name = 'sync_state'"
        ).fetchone()
        return row is not None

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
        """Bring the store up to date with *document*; True when it changed.

        Reconciliation path (fallback for callers without dirty-set
        knowledge): compares the store's rows against the document and
        applies exactly the difference through :meth:`apply_changes`, so the
        result always equals :meth:`write_all`. The canonical hot path is
        :meth:`apply_changes` driven by the service's dirty sets (#1027).
        """
        if self.is_fresh(document):
            return False
        try:
            self.reconcile(document)
        except sqlite3.DatabaseError:
            # Self-healing: a corrupt database file is recreated from the
            # document (the rebuildable-store guarantee is unchanged).
            self.reset()
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

    def prime(self, document: CatalogDocument) -> "CatalogIndex":
        """Compatibility no-op retained for the pre-canonical API surface.

        The row-snapshot fast path this used to feed was removed with the
        legacy incremental sync; :meth:`sync` now reconciles against the
        store itself, which needs no primed snapshot.
        """
        return self

    # -- canonical store (#1027) ----------------------------------------------

    def store_version(self) -> int | None:
        """The store's layout version, or None when absent/unreadable."""
        raw = self._read_sync_state("index_schema_version")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def store_health(self) -> str:
        """Classify the store: "absent" | "legacy" | "canonical" | "corrupt"
        | "error".

        "corrupt" is DETERMINISTIC damage (torn page, malformed image): the
        file provably cannot yield its committed rows, so rebuilding from
        the manifest checkpoint loses nothing readable — the bytes are kept
        aside for forensics by the caller. "error" is a TRANSIENT read
        failure (busy/locked): overwriting in that state is the silent
        last-writer-wins #1027/#411 exist to prevent, so callers refuse.
        "legacy" means safe-to-(re)initialize: no schema yet, a pre-canonical
        layout, or zero bytes from a crashed first open.
        """
        if not self.db_path.is_file():
            return "absent"
        try:
            if self.db_path.stat().st_size == 0:
                return "legacy"  # crashed first-open: nothing to lose
        except OSError:
            return "error"
        try:
            conn = self._connect()
            # Force a DATA-PAGE read: count(*) is answerable from the PK
            # autoindex alone and would miss a smashed table page.
            conn.execute("SELECT count(metadata) FROM assets").fetchone()
            conn.execute("SELECT count(path) FROM versions").fetchone()
        except sqlite3.OperationalError as exc:
            self._drop_current_connection()
            if "no such table" in str(exc).lower():
                return "legacy"  # schema never initialized
            return "error"  # busy/locked: transient, refuse to overwrite
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
            self._drop_current_connection()
            return "corrupt"
        # sync_state must be STRICTLY readable on a healthy store: a damaged
        # page here used to classify as "legacy" and silently rebuild from a
        # possibly-stale manifest (#1027 review, path A).
        try:
            row = conn.execute(
                "SELECT value FROM sync_state WHERE key = 'index_schema_version'"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            self._drop_current_connection()
            if "no such table" in str(exc).lower():
                # An UNINITIALIZED store has no tables at all; one holding
                # populated assets but no sync_state is damaged/tampered —
                # rebuilding it from the manifest must go through the
                # forensics-preserving corrupt flow, not silent legacy.
                try:
                    probe = self._connect()
                    n = probe.execute(
                        "SELECT count(metadata) FROM assets"
                    ).fetchone()[0]
                    return "legacy" if n == 0 else "corrupt"
                except sqlite3.Error:
                    return "corrupt"
            return "error"
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
            self._drop_current_connection()
            return "corrupt"
        if row is None:
            return "legacy"
        try:
            version = int(row[0])
        except ValueError:
            return "corrupt"
        return "canonical" if version == STORE_SCHEMA_VERSION else "legacy"

    def write_all(self, document: CatalogDocument) -> None:
        """Transactionally (re)initialize the store from *document*.

        Used by the legacy-JSON migration and by recovery: one atomic
        delete-and-rewrite, so a crash mid-write leaves the previous database
        contents intact (SQLite rollback) and the legacy ``catalog.json``
        untouched — the source project stays recoverable (#1027).
        """
        self.rebuild(document)

    def load_document(self) -> CatalogDocument | None:
        """Reconstruct the :class:`CatalogDocument` from the store.

        Returns None when the database is missing, not yet migrated to
        canonical layout (``STORE_SCHEMA_VERSION``), or unreadable — callers
        fall back to the legacy JSON load/migration path.
        """
        if not self.db_path.is_file():
            return None
        if self.store_version() != STORE_SCHEMA_VERSION:
            return None
        try:
            return self._load_document_once()
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError):
            return None

    def _load_document_once(self) -> CatalogDocument:
        from paleo_workbench.catalog.models import (
            DataAsset,
            DataRun,
            DataStage,
            DataVersion,
            Model,
            ModelVersion,
            Tag,
        )

        conn = self._connect()
        conn.execute("BEGIN")
        try:
            assets = [
                DataAsset(
                    id=row["id"],
                    name=row["name"],
                    type=row["type"],
                    description=row["description"],
                    current_version_id=row["current_version_id"],
                    legacy_resource_id=row["legacy_resource_id"],
                    metadata=json.loads(row["metadata"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    trashed=bool(row["trashed"]),
                    trashed_at=row["trashed_at"],
                )
                for row in conn.execute(
                    "SELECT * FROM assets"
                )
            ]
            versions = [
                DataVersion(
                    id=row["id"],
                    asset_id=row["asset_id"],
                    version_number=row["version_number"],
                    stage=DataStage(row["stage"]),
                    managed=bool(row["managed"]),
                    path=row["path"],
                    source_uri=row["source_uri"],
                    format=row["format"],
                    size_bytes=row["size_bytes"],
                    sha256=row["sha256"],
                    run_id=row["run_id"],
                    metadata=json.loads(row["metadata"]),
                    created_at=row["created_at"],
                    trashed=bool(row["trashed"]),
                    trashed_at=row["trashed_at"],
                    parent_version_ids=json.loads(row["parent_ids"]),
                )
                for row in conn.execute("SELECT * FROM versions ORDER BY rowid")
            ]
            inputs_by_run: dict[str, list[str]] = {}
            outputs_by_run: dict[str, list[str]] = {}
            for row in conn.execute("SELECT run_id, version_id FROM run_inputs"):
                inputs_by_run.setdefault(row["run_id"], []).append(row["version_id"])
            for row in conn.execute("SELECT run_id, version_id FROM run_outputs"):
                outputs_by_run.setdefault(row["run_id"], []).append(row["version_id"])
            runs = [
                DataRun(
                    id=row["id"],
                    operation=row["operation"],
                    parameters=json.loads(row["parameters"]),
                    generator=row["generator"],
                    status=row["status"],
                    model_ref=json.loads(row["model_ref"])
                    if row["model_ref"]
                    else None,
                    created_at=row["created_at"],
                )
                for row in conn.execute("SELECT * FROM runs ORDER BY rowid")
            ]
            for run in runs:
                run.input_version_ids = inputs_by_run.get(run.id, [])
                run.output_version_ids = outputs_by_run.get(run.id, [])
            tags = [
                Tag(
                    id=row["id"],
                    name=row["name"],
                    display_name=row["display_name"],
                    metadata=json.loads(row["metadata"]),
                )
                for row in conn.execute("SELECT * FROM tags ORDER BY rowid")
            ]
            asset_tags: dict[str, list[str]] = {}
            for row in conn.execute("SELECT asset_id, tag_id FROM asset_tags"):
                asset_tags.setdefault(row["asset_id"], []).append(row["tag_id"])
            version_tags: dict[str, list[str]] = {}
            for row in conn.execute("SELECT version_id, tag_id FROM version_tags"):
                version_tags.setdefault(row["version_id"], []).append(row["tag_id"])
            models = [
                Model(
                    id=row["id"],
                    model_id=row["model_id"],
                    model_name=row["model_name"],
                    model_type=row["model_type"],
                    capability=row["capability"],
                    provider=row["provider"],
                    status=row["status"],
                    metadata=json.loads(row["metadata"]),
                    created_at=row["created_at"],
                    provenance=json.loads(row["provenance"]),
                )
                for row in conn.execute("SELECT * FROM models ORDER BY rowid")
            ]
            model_versions = [
                ModelVersion(
                    id=row["id"],
                    model_id=row["model_id"],
                    model_version=row["model_version"],
                    artifact_uri=row["artifact_uri"],
                    checksum=row["checksum"],
                    input_schema=json.loads(row["input_schema"]),
                    output_schema=json.loads(row["output_schema"]),
                    preprocessing_version=row["preprocessing_version"],
                    runtime=row["runtime"],
                    deterministic=bool(row["deterministic"]),
                    demo_only=bool(row["demo_only"]),
                    status=row["status"],
                    metadata=json.loads(row["metadata"]),
                    created_at=row["created_at"],
                    provenance=json.loads(row["provenance"]),
                )
                for row in conn.execute("SELECT * FROM model_versions ORDER BY rowid")
            ]
            revision = self.revision()
            document = CatalogDocument(
                catalog_revision=revision if revision is not None else 0,
                assets=assets,
                versions=versions,
                runs=runs,
                tags=tags,
                models=models,
                model_versions=model_versions,
                asset_tags=asset_tags,
                version_tags=version_tags,
            )
            conn.execute("ROLLBACK")  # read-only snapshot; release it
            return document
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise

    def apply_changes(
        self,
        document: CatalogDocument,
        dirty: "DirtySet",
        *,
        lookups: dict[str, dict] | None = None,
    ) -> None:
        """Persist *dirty*'s entities in ONE transaction (#1027).

        For every id in *dirty*: present in *document* → upsert its row;
        absent → delete it plus its dependents. Lineage edges are reconciled
        per touched version/run with the same keep-rules a full rebuild
        encodes (run-derived edges survive version purges). The result is
        identical to :meth:`write_all` restricted to the dirty set.
        """
        conn = self._connect()
        if not self._schema_present(conn):
            # The store file was deleted (or left schema-less by an earlier
            # failed flush) mid-session; ``_connect`` has just recreated an
            # empty database, so the tables below do not exist. Fall back to
            # a full rewrite from the document — the canonical truth.
            self.write_all(document)
            return
        # O(Δ) lookups: the caller (the service) passes its incrementally
        # maintained id→object maps for the large collections; tags and the
        # model registry are small enough to scan. Building full-document
        # dicts here would put an O(N) cost on every single-row mutation —
        # exactly what #1027 removes.
        lookups = lookups or {}
        asset_by_id = lookups.get("assets") or {
            a.id: a for a in document.assets
        }
        version_by_id = lookups.get("versions") or {
            v.id: v for v in document.versions
        }
        run_by_id = lookups.get("runs") or {r.id: r for r in document.runs}
        tag_by_id = {t.id: t for t in document.tags}
        model_by_id = {m.id: m for m in document.models}
        mver_by_id = {mv.id: mv for mv in document.model_versions}

        def _ordered(ids, table: str) -> list[str]:
            """Document-order iteration for one table's dirty ids.

            Existing rows keep their rowid (== document insertion order);
            ids not yet in the store are NEW appends and stay in mark order
            after the existing ones — both match how load_document restores
            list order from rowid order.
            """
            marks = list(ids)
            if not marks:
                return []
            rowid_of: dict[str, int] = {}
            for chunk_start in range(0, len(marks), 500):
                chunk = marks[chunk_start : chunk_start + 500]
                placeholders = ",".join("?" * len(chunk))
                rowid_of.update(
                    conn.execute(
                        f"SELECT id, rowid FROM {table} WHERE id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            existing = sorted(
                (rowid_of[e], e) for e in marks if e in rowid_of
            )
            appended = [e for e in marks if e not in rowid_of]
            return [e for _, e in existing] + appended

        with conn:
            for asset_id in _ordered(dirty.assets, "assets"):
                asset = asset_by_id.get(asset_id)
                if asset is None:
                    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
                    conn.execute(
                        "DELETE FROM asset_tags WHERE asset_id = ?", (asset_id,)
                    )
                else:
                    conn.execute(
                        _ASSET_UPSERT_SQL, (asset_id, *_asset_row(asset))
                    )
            for version_id in _ordered(dirty.versions, "versions"):
                version = version_by_id.get(version_id)
                if version is None:
                    self._delete_version_keep_run_edges(conn, version_id)
                else:
                    conn.execute(
                        _VERSION_UPSERT_SQL, (version_id, *_version_row(version))
                    )
                    self._reconcile_version_parents(conn, version)
            for run_id in _ordered(dirty.runs, "runs"):
                run = run_by_id.get(run_id)
                if run is None:
                    self._delete_run_keep_version_edges(conn, run_id)
                else:
                    conn.execute(_RUN_UPSERT_SQL, (run_id, *_run_row(run)))
                    conn.execute(
                        "DELETE FROM run_inputs WHERE run_id = ?", (run_id,)
                    )
                    conn.execute(
                        "DELETE FROM run_outputs WHERE run_id = ?", (run_id,)
                    )
                    conn.executemany(
                        "INSERT OR IGNORE INTO run_inputs (run_id, version_id)"
                        " VALUES (?,?)",
                        [(run_id, vid) for vid in run.input_version_ids],
                    )
                    conn.executemany(
                        "INSERT OR IGNORE INTO run_outputs (run_id, version_id)"
                        " VALUES (?,?)",
                        [(run_id, vid) for vid in run.output_version_ids],
                    )
                    self._reconcile_run_edges(conn, run)
            for tag_id in _ordered(dirty.tags, "tags"):
                tag = tag_by_id.get(tag_id)
                if tag is None:
                    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
                    conn.execute(
                        "DELETE FROM asset_tags WHERE tag_id = ?", (tag_id,)
                    )
                    conn.execute(
                        "DELETE FROM version_tags WHERE tag_id = ?", (tag_id,)
                    )
                else:
                    normalized = normalize_tag_name(tag.name)
                    # A legacy document can carry two tags colliding under
                    # the current normalizer (pre-#884); the plain upsert
                    # would violate tags.name UNIQUE. The document's object
                    # is the survivor — drop the stale colliding row first.
                    conn.execute(
                        "DELETE FROM tags WHERE name = ? AND id <> ?",
                        (normalized, tag_id),
                    )
                    conn.execute(
                        _TAG_UPSERT_SQL,
                        (
                            tag_id,
                            normalized,
                            tag.display_name,
                            json.dumps(tag.metadata, ensure_ascii=False),
                        ),
                    )
            for asset_id in dirty.asset_tags:
                conn.execute("DELETE FROM asset_tags WHERE asset_id = ?", (asset_id,))
                conn.executemany(
                    "INSERT OR IGNORE INTO asset_tags (asset_id, tag_id) VALUES (?,?)",
                    [
                        (asset_id, tid)
                        for tid in document.asset_tags.get(asset_id, ())
                    ],
                )
            for version_id in dirty.version_tags:
                conn.execute(
                    "DELETE FROM version_tags WHERE version_id = ?", (version_id,)
                )
                conn.executemany(
                    "INSERT OR IGNORE INTO version_tags (version_id, tag_id)"
                    " VALUES (?,?)",
                    [
                        (version_id, tid)
                        for tid in document.version_tags.get(version_id, ())
                    ],
                )
            for model_id in _ordered(dirty.models, "models"):
                model = model_by_id.get(model_id)
                if model is None:
                    conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
                else:
                    conn.execute(_MODEL_UPSERT_SQL, (model_id, *_model_row(model)))
            for mv_id in _ordered(dirty.model_versions, "model_versions"):
                mv = mver_by_id.get(mv_id)
                if mv is None:
                    conn.execute(
                        "DELETE FROM model_versions WHERE id = ?", (mv_id,)
                    )
                else:
                    conn.execute(
                        _MODEL_VERSION_UPSERT_SQL, (mv_id, *_model_version_row(mv))
                    )
            conn.executemany(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
                [
                    ("schema_version", str(document.schema_version)),
                    ("catalog_revision", str(document.catalog_revision)),
                    ("index_schema_version", str(INDEX_SCHEMA_VERSION)),
                ],
            )

    def _reconcile_version_parents(
        self, conn: sqlite3.Connection, version
    ) -> None:
        """Make the lineage rows for *version* equal its parent_version_ids.

        Old parent edges are dropped unless a retained run also produces them
        (the purge-keeps-provenance rule shared with :meth:`_delete_entity`).
        """
        old_parents = {
            row[0]
            for row in conn.execute(
                "SELECT parent_version_id FROM lineage WHERE child_version_id = ?",
                (version.id,),
            )
        }
        new_parents = set(version.parent_version_ids)
        for parent in old_parents - new_parents:
            if self._run_covers_edge(conn, parent, version.id):
                continue
            conn.execute(
                "DELETE FROM lineage WHERE parent_version_id = ?"
                " AND child_version_id = ?",
                (parent, version.id),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO lineage (parent_version_id, child_version_id)"
            " VALUES (?,?)",
            [(parent, version.id) for parent in new_parents],
        )

    def _delete_version_keep_run_edges(
        self, conn: sqlite3.Connection, version_id: str
    ) -> None:
        conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))
        conn.execute("DELETE FROM version_tags WHERE version_id = ?", (version_id,))
        # Run input/output link rows are NOT deleted: they are owned by the
        # run record, which retains purged version ids as historical
        # provenance (service.purge_trashed keeps runs) — a full rebuild
        # re-creates them from the run.
        for (parent,) in conn.execute(
            "SELECT parent_version_id FROM lineage WHERE child_version_id = ?",
            (version_id,),
        ).fetchall():
            if not self._run_covers_edge(conn, parent, version_id):
                conn.execute(
                    "DELETE FROM lineage WHERE parent_version_id = ?"
                    " AND child_version_id = ?",
                    (parent, version_id),
                )

    def _reconcile_run_edges(self, conn: sqlite3.Connection, run) -> None:
        """Make run-derived lineage rows equal the run's io product.

        Dropped io pairs survive when a version-owned parent edge still
        covers them (the union rule a rebuild encodes).
        """
        new_pairs = {
            (i, o) for i in run.input_version_ids for o in run.output_version_ids
        }
        old_pairs = {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT ri.version_id, ro.version_id FROM run_inputs ri"
                " JOIN run_outputs ro ON ro.run_id = ri.run_id WHERE ri.run_id = ?",
                (run.id,),
            )
        }
        for parent, child in old_pairs - new_pairs:
            if self._version_owns_edge(conn, parent, child):
                continue
            conn.execute(
                "DELETE FROM lineage WHERE parent_version_id = ?"
                " AND child_version_id = ?",
                (parent, child),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO lineage (parent_version_id, child_version_id)"
            " VALUES (?,?)",
            list(new_pairs),
        )

    def _delete_run_keep_version_edges(
        self, conn: sqlite3.Connection, run_id: str
    ) -> None:
        io_pairs = [
            (row[0], row[1])
            for row in conn.execute(
                "SELECT ri.version_id, ro.version_id FROM run_inputs ri"
                " JOIN run_outputs ro ON ro.run_id = ri.run_id WHERE ri.run_id = ?",
                (run_id,),
            )
        ]
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.execute("DELETE FROM run_inputs WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM run_outputs WHERE run_id = ?", (run_id,))
        for parent, child in io_pairs:
            if self._version_owns_edge(conn, parent, child):
                continue
            conn.execute(
                "DELETE FROM lineage WHERE parent_version_id = ?"
                " AND child_version_id = ?",
                (parent, child),
            )

    def _version_owns_edge(
        self, conn: sqlite3.Connection, parent: str, child: str
    ) -> bool:
        """True when *child*'s own parent_ids list contains *parent*."""
        row = conn.execute(
            "SELECT parent_ids FROM versions WHERE id = ?", (child,)
        ).fetchone()
        if row is None:
            return False
        try:
            return parent in json.loads(row[0])
        except (ValueError, TypeError):
            return False

    def _run_covers_edge(
        self, conn: sqlite3.Connection, parent: str, child: str
    ) -> bool:
        row = conn.execute(
            "SELECT 1 FROM run_inputs ri JOIN run_outputs ro ON ro.run_id = ri.run_id"
            " WHERE ri.version_id = ? AND ro.version_id = ? LIMIT 1",
            (parent, child),
        ).fetchone()
        return row is not None

    def reconcile(self, document: CatalogDocument) -> None:
        """Full compare-and-repair against the document (safe fallback).

        O(N) read of the store, then applies exactly the differing entities
        through :meth:`apply_changes` — the same writer the dirty-set path
        uses, so unmarked mutations stay correct (only slower).
        """
        dirty = DirtySet()
        conn = self._connect()
        if not self._schema_present(conn):
            # Deleted mid-session, or present but schema-less (an earlier
            # failed flush already recreated the path): either way the
            # full-compare below has no tables to read.
            self.write_all(document)
            return

        def rows(table: str) -> dict[str, tuple]:
            return {
                row[0]: tuple(row[1:])
                for row in conn.execute(f"SELECT * FROM {table}")
            }

        db_assets = rows("assets")
        doc_assets = {a.id: _asset_row(a) for a in document.assets}
        dirty.assets = _symmetric_diff(db_assets, doc_assets)
        db_versions = rows("versions")
        doc_versions = {v.id: _version_row(v) for v in document.versions}
        dirty.versions = _symmetric_diff(db_versions, doc_versions)
        db_runs = rows("runs")
        doc_runs = {r.id: _run_row(r) for r in document.runs}
        dirty.runs = _symmetric_diff(db_runs, doc_runs)
        db_tags = rows("tags")
        doc_tags = {t.id: _tag_row(t) for t in document.tags}
        dirty.tags = _symmetric_diff(db_tags, doc_tags)
        db_models = rows("models")
        doc_models = {m.id: _model_row(m) for m in document.models}
        dirty.models = _symmetric_diff(db_models, doc_models)
        db_mvers = rows("model_versions")
        doc_mvers = {mv.id: _model_version_row(mv) for mv in document.model_versions}
        dirty.model_versions = _symmetric_diff(db_mvers, doc_mvers)

        db_asset_tags = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT asset_id, group_concat(tag_id) FROM asset_tags"
                " GROUP BY asset_id"
            )
        }
        for asset_id in set(db_asset_tags) | set(document.asset_tags):
            db_set = set((db_asset_tags.get(asset_id) or "").split(","))
            db_set.discard("")
            if db_set != set(document.asset_tags.get(asset_id, [])):
                dirty.mark_asset_tags(asset_id)
        db_version_tags = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT version_id, group_concat(tag_id) FROM version_tags"
                " GROUP BY version_id"
            )
        }
        for version_id in set(db_version_tags) | set(document.version_tags):
            db_set = set((db_version_tags.get(version_id) or "").split(","))
            db_set.discard("")
            if db_set != set(document.version_tags.get(version_id, [])):
                dirty.mark_version_tags(version_id)

        # Run io drift: one grouped join read, compared per run.
        # Known limit: the lineage table itself is not diffed — edges are
        # re-derived from parent_ids/run-io, so externally-injected lineage
        # rows that neither source covers are not repaired here
        # (apply_changes maintains the table for all service flows).
        db_run_io: dict[str, set[tuple[str, str]]] = {}
        for run_id, i, o in conn.execute(
            "SELECT ri.run_id, ri.version_id, ro.version_id FROM run_inputs ri"
            " JOIN run_outputs ro ON ro.run_id = ri.run_id"
        ):
            db_run_io.setdefault(run_id, set()).add((i, o))
        for run in document.runs:
            expected = {
                (i, o) for i in run.input_version_ids for o in run.output_version_ids
            }
            if db_run_io.get(run.id, set()) != expected:
                dirty.mark_runs(run.id)

        if dirty.is_empty():
            # Still refresh the revision stamp (the caller bumped it).
            conn.execute("BEGIN")
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
                    [
                        ("schema_version", str(document.schema_version)),
                        ("catalog_revision", str(document.catalog_revision)),
                        ("index_schema_version", str(INDEX_SCHEMA_VERSION)),
                    ],
                )
                conn.commit()
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
            return
        self.apply_changes(document, dirty)

    def _rebuild_once(self, document: CatalogDocument) -> None:
        conn = self._connect()
        with conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(ddl)
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")

            conn.executemany(
                _ASSET_UPSERT_SQL,
                [(asset.id, *_asset_row(asset)) for asset in document.assets],
            )
            conn.executemany(
                _VERSION_UPSERT_SQL,
                [(version.id, *_version_row(version)) for version in document.versions],
            )
            # Tag name is stored normalized so lookups are case/whitespace-safe;
            # the display form lives in display_name.
            # INSERT OR IGNORE (not the upsert): a legacy document can hold
            # two tags colliding under the current normalizer (pre-#884);
            # migration must tolerate them instead of bricking project open.
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
                _RUN_UPSERT_SQL,
                [(run.id, *_run_row(run)) for run in document.runs],
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
            conn.executemany(
                _MODEL_UPSERT_SQL,
                [(model.id, *_model_row(model)) for model in document.models],
            )
            conn.executemany(
                _MODEL_VERSION_UPSERT_SQL,
                [
                    (mv.id, *_model_version_row(mv))
                    for mv in document.model_versions
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
        # INDEXED BY pins the partial covering index (#1043): without it the
        # planner prefers idx_versions_trashed (matching ~all rows → an
        # effective full scan, 7-9 ms at 100k versions). The schema-version
        # bump guarantees the index exists on any database this code opens.
        row = self._connect().execute(
            "SELECT id FROM versions INDEXED BY idx_versions_external_path"
            " WHERE managed = 0 AND trashed = 0 AND path = ? LIMIT 1",
            (path,),
        ).fetchone()
        return row[0] if row is not None else None
