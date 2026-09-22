"""V8 M8 — honest cancellation in the well-log load pipeline (#1224).

The engine's LAS/XML parse is a single non-interruptible call; cancellation
is cooperative at phase boundaries only. These tests pin the contract:

* before-parse cancel → WellLogLoadCancelled, no parse performed;
* between-phases cancel → cancelled without completing the wrap phase;
* mid-parse cancel → honest `cancelling` signal + late result discarded;
* `finished` never fires for a cancelled request.
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.viz.well_log_load import (
    WellLogLoadCancelled,
    load_well_log_from_path,
)


@pytest.fixture()
def las_path(tmp_path):
    path = tmp_path / "well.las"
    rows = "\n".join(
        f"1000.{i:04d} 45.5 220.1" for i in range(50)
    )
    path.write_text(
        "~VERSION INFORMATION\nVERS. 2.0\nWRAP. NO\n"
        "~WELL INFORMATION\n#STRT.M 1000.0\n#STOP.M 1000.05\n"
        "~CURVE INFORMATION\nDEPT.M : depth\nGR.GAPI : gamma\nDT.US/M : sonic\n"
        f"~ASCII\n{rows}\n",
        encoding="utf-8",
    )
    return str(path)


class TestLoaderCheckpoints:
    def test_cancel_before_parse_raises_without_parsing(self, las_path, monkeypatch):
        from paleo_workbench.viz import well_log_load

        called = {"parse": 0}

        def _no_parse(*a, **k):
            called["parse"] += 1
            raise AssertionError("parse must not run for a cancelled request")

        monkeypatch.setattr(well_log_load, "is_well_log_cached", lambda p: False)
        monkeypatch.setattr(well_log_load, "load_well_log_from_path", _no_parse)
        # Direct loader-level check on the private entry
        with pytest.raises(WellLogLoadCancelled):
            well_log_load._load_well_log(
                las_path,
                max_samples=100,
                cache=well_log_load._las_cache,
                loader_label="preview",
                cancel=lambda: True,
            )

    def test_uncancelled_load_still_works(self, las_path):
        result = load_well_log_from_path(las_path)
        assert result is not None


class TestWorkerHonestPhases:
    def _make_worker(self, adapter):
        from paleo_workbench.ui.pages.well_log_load_worker import WellLogLoadWorker

        class Ref:
            kind = "well_log"
            id = "r1"
            path = ""
            label = "W1"
            source = ""

        return WellLogLoadWorker(Ref(), None, adapter=adapter)

    def test_cancel_during_parse_emits_cancelling_and_discards(self):
        emitted = {"finished": 0, "failed": 0, "cancelled": 0, "cancelling": 0}

        worker_holder = {}

        class SlowAdapter:
            def resolve(self, ref, project, cancel=None):
                # simulate the non-interruptible parse: cancel fires MID-way
                # (same thread — direct signal delivery, no event loop
                # needed), the parse itself runs to completion
                worker_holder["worker"].cancel()
                return object()  # late result nobody may accept

        worker = self._make_worker(SlowAdapter())
        worker_holder["worker"] = worker
        worker.finished.connect(lambda _p: emitted.__setitem__("finished", emitted["finished"] + 1))
        worker.failed.connect(lambda _m: emitted.__setitem__("failed", emitted["failed"] + 1))
        worker.cancelled.connect(lambda: emitted.__setitem__("cancelled", emitted["cancelled"] + 1))
        worker.cancelling.connect(lambda: emitted.__setitem__("cancelling", emitted["cancelling"] + 1))

        worker.run()
        assert emitted["cancelling"] == 1  # honest "ending now" hint
        assert emitted["cancelled"] == 1
        assert emitted["finished"] == 0  # late result discarded
        assert emitted["failed"] == 0

    def test_cancel_before_start_no_cancelling_signal(self):
        emitted = {"cancelled": 0, "cancelling": 0}
        worker = self._make_worker(None)
        worker.cancelled.connect(lambda: emitted.__setitem__("cancelled", emitted["cancelled"] + 1))
        worker.cancelling.connect(lambda: emitted.__setitem__("cancelling", emitted["cancelling"] + 1))
        worker.cancel()
        worker.run()
        assert emitted["cancelled"] == 1
        assert emitted["cancelling"] == 0  # nothing was running — no hint needed

    def test_successful_resolve_emits_finished(self):
        emitted = {"finished": 0, "cancelled": 0}

        class OkAdapter:
            def resolve(self, ref, project, cancel=None):
                return "payload"

        worker = self._make_worker(OkAdapter())
        worker.finished.connect(lambda _p: emitted.__setitem__("finished", emitted["finished"] + 1))
        worker.cancelled.connect(lambda: emitted.__setitem__("cancelled", emitted["cancelled"] + 1))
        worker.run()
        assert emitted["finished"] == 1
        assert emitted["cancelled"] == 0

    def test_checkpoint_cancel_propagates_from_adapter(self, las_path):
        from paleo_workbench.viz.adapter import VizAdapter

        class Ref:
            kind = "well_log"
            id = "r1"
            path = las_path
            label = "W1"
            source = ""

        # pre-cancelled token: adapter must raise the typed cancellation at
        # the loader checkpoint, never a soft-fail "message" payload
        adapter = VizAdapter()
        with pytest.raises(WellLogLoadCancelled):
            adapter.resolve(Ref(), None, cancel=lambda: True)
