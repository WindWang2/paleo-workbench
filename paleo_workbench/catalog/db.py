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
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataStage,
    normalize_tag_name,
)
from paleo_workbench.catalog.storage import catalog_dir_for

DB_FILENAME = "catalog.sqlite"

# Table/DDL definitions. The index is deliberately FK-free: it is a disposable
# projection of the canonical document, and delete order must never matter.
_SCHEMA_DDL = [
    """CREATE TABLE IF NOT EXISTS assets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'unknown',
        description TEXT NOT NULL DEFAULT '',
        current_version_id TEXT,
        legacy_resource_id TEXT,
        metadata TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_assets_name ON assets(name)",
    "CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(type)",
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
        created_at TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_versions_asset_id ON versions(asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_versions_stage ON versions(stage)",
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


class CatalogIndex:
    """Project-local SQLite query index over a :class:`CatalogDocument`.

    The index is a rebuildable cache; ``metadata/catalog.json`` remains the
    authoritative store. ``rebuild()`` (or ``sync()``) rewrites every table
    from the document in a single transaction, so corruption or manual
    deletion is never fatal — it only means the next open rebuilds.
    """

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)
        self._conn: sqlite3.Connection | None = None

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

    def close(self) -> None:
        """Close the cached connection, if any."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

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
            except FileNotFoundError:
                pass

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            self._conn = conn
        return self._conn

    # -- state ----------------------------------------------------------------

    def _read_sync_state(self, key: str) -> str | None:
        """Read one sync_state value; None when missing/unreadable/corrupt."""
        if not self.db_path.is_file():
            self.close()
            return None
        try:
            row = self._connect().execute(
                "SELECT value FROM sync_state WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row is not None else None
        except (sqlite3.DatabaseError, OSError):
            self.close()
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
            return int(raw) == document.schema_version
        except ValueError:
            return False

    def sync(self, document: CatalogDocument) -> bool:
        """Rebuild iff the index is stale; returns True when a rebuild ran."""
        if self.is_fresh(document):
            return False
        self.rebuild(document)
        return True

    # -- rebuild ---------------------------------------------------------------

    def rebuild(self, document: CatalogDocument) -> None:
        """Rewrite every table from *document* in a single transaction.

        Self-healing: a corrupt database file is deleted and recreated from
        scratch (callers may also use :meth:`reset` explicitly first).
        """
        self.close()
        for attempt in (0, 1):
            try:
                self._rebuild_once(document)
                return
            except sqlite3.DatabaseError:
                if attempt:
                    raise
                self.reset()

    def _rebuild_once(self, document: CatalogDocument) -> None:
        conn = self._connect()
        with conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(ddl)
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")

            conn.executemany(
                "INSERT INTO assets (id, name, type, description, current_version_id,"
                " legacy_resource_id, metadata, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                [
                    (
                        asset.id,
                        asset.name,
                        asset.type,
                        asset.description,
                        asset.current_version_id,
                        asset.legacy_resource_id,
                        json.dumps(asset.metadata, ensure_ascii=False),
                        asset.created_at,
                        asset.updated_at,
                    )
                    for asset in document.assets
                ],
            )
            conn.executemany(
                "INSERT INTO versions (id, asset_id, version_number, stage, managed,"
                " path, source_uri, format, size_bytes, sha256, run_id, metadata,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            self.close()
            return default
        try:
            return fn(*args, **kwargs)
        except (sqlite3.DatabaseError, OSError):
            self.close()
            return default

    def search_assets(
        self,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tag: str | None = None,
        type: str | None = None,
    ) -> list[dict]:
        """Search assets by name substring, version stage, tag, and asset type."""
        return self._safe(
            [], self._search_assets, text=text, stage=stage, tag=tag, type=type
        )

    def _search_assets(
        self,
        text: str | None = None,
        stage: DataStage | str | None = None,
        tag: str | None = None,
        type: str | None = None,
    ) -> list[dict]:
        joins: list[str] = []
        wheres: list[str] = []
        params: list[str] = []
        if stage is not None:
            joins.append("JOIN versions v ON v.asset_id = a.id")
            wheres.append("v.stage = ?")
            params.append(stage.value if isinstance(stage, DataStage) else str(stage))
        if tag is not None:
            joins.append("JOIN asset_tags at ON at.asset_id = a.id")
            joins.append("JOIN tags t ON t.id = at.tag_id")
            wheres.append("t.name = ?")
            params.append(normalize_tag_name(tag))
        if text:
            wheres.append("a.name LIKE ?")
            params.append(f"%{text}%")
        if type is not None:
            wheres.append("a.type = ?")
            params.append(str(type))
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
