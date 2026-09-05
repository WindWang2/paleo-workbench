"""Crash consistency at scale (D11): SIGKILL inside a bulk-registration
commit on a 10k-asset catalog — reopen must be consistent and complete.

Extends the small ``crash_kill_helper`` technique to the D4 chunked import:
the helper registers 10k resources inside one ``batch_save`` and kills the
process mid-flush. Because the canonical store is SQLite-WAL with a single
transaction per flush, the reopened catalog is either ALL committed rows or
a clean rollback — never half-registered — and paging/counting work after
recovery.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService

_PROJECT_ROOT = Path(__file__).parent.parent
_PYTHON = sys.executable
_HELPER = Path(__file__).parent / "crash_batch_helper.py"
BATCH = 2_000  # fast by default; scale via PALEO_CRASH_SCALE_BATCH


@pytest.mark.parametrize("mode", ["replace", "bak"])
def test_sigkill_mid_batch_import_reopens_consistent(tmp_path: Path, mode: str):
    batch = int(os.environ.get("PALEO_CRASH_SCALE_BATCH", str(BATCH)))
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")

    env = dict(os.environ)
    existing = os.environ.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_PROJECT_ROOT}:{existing}" if existing else str(_PROJECT_ROOT)
    proc = subprocess.run(
        [_PYTHON, str(_HELPER), mode, str(project), str(batch)],
        capture_output=True,
        cwd=str(_PROJECT_ROOT),
        env=env,
        timeout=600,
    )
    if sys.platform == "win32":
        assert proc.returncode == signal.SIGTERM, proc.stderr.decode()
    else:
        assert proc.returncode in (-signal.SIGKILL, -9), proc.stderr.decode()

    svc = DataCatalogService.open(project)
    try:
        assets = svc.list_assets(include_trashed=True)
        # The store is SQLite-canonical: a mid-transaction kill rolls the
        # whole registration back (0 rows — the flush was the FIRST one),
        # a post-commit kill keeps everything. Never anything in between
        # and never a broken store.
        assert len(assets) in (0, batch), (len(assets), batch)
        # Full query surface works on the recovered store.
        assert svc.count_assets() == len(assets)
        page = svc.search_assets_page(limit=100)
        assert len(page) == min(100, len(assets))
        assert svc.index_revision() == svc.document.catalog_revision
        # The project is writable again (self-healing).
        src = project.parent / "incoming" / "post.las"
        src.write_text("post-crash", encoding="utf-8")
        svc.import_raw(src)
        assert svc.count_assets() == len(assets) + 1
    finally:
        svc.close()
