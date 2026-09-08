"""Catalog lifecycle telemetry events (V8 M9).

GC sweeps, working-copy recovery and lease expiry used to live only in
in-memory return values — after a crash or a UI restart there was NO record
that maintenance ever ran, what it deleted, or what it recovered. This
module appends durable, append-only JSONL events under the project's
artifacts tree:

``<project>.artifacts/catalog/events.jsonl``

One JSON object per line: ``{"event", "at", "kind_counts", "detail"}``.
The file is a TELEMETRY aid, never an authority — the catalog document and
the store remain the only truths. Writes are best-effort: a telemetry
failure must never fail the maintenance operation it describes.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVENTS_FILENAME = "events.jsonl"
_LOCK = threading.Lock()


def _events_path(project_path: str | Path) -> Path:
    from paleo_workbench.project.paths import artifact_dir_for

    return artifact_dir_for(Path(project_path)) / "catalog" / _EVENTS_FILENAME


def record_catalog_event(
    project_path: str | Path,
    event: str,
    *,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Append one lifecycle event; returns True when persisted.

    Best-effort: filesystem problems are logged and swallowed — telemetry
    must not break the caller (a GC sweep is still correct without it).
    """
    payload = {
        "event": str(event),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "detail": dict(detail or {}),
    }
    try:
        path = _events_path(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return True
    except Exception:  # noqa: BLE001 — telemetry is best-effort by contract
        logger.debug("catalog telemetry event %r not persisted", event, exc_info=True)
        return False


def read_catalog_events(
    project_path: str | Path,
    *,
    event: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read telemetry events (newest last; optional filter + tail limit)."""
    try:
        path = _events_path(project_path)
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn append (crash mid-write) is skipped, not fatal
        if event is None or str(entry.get("event")) == event:
            events.append(entry)
    if limit is not None:
        events = events[-limit:]
    return events
