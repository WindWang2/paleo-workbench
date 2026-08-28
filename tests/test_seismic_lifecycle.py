"""SEG-Y → Zarr data lifecycle (#1079): production scheduler + catalog paths.

Pins the lifecycle contract end to end against the REAL transcoder, the REAL
scheduler and the REAL catalog: background job, DataRun bookkeeping, DERIVED
version registration with lineage, stale marking on re-transcode, cancel
semantics, resume after crash and directory-payload trash/restore.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from geoviz_seismic import open_volume  # noqa: E402
from paleo_workbench.catalog.service import DataCatalogService  # noqa: E402
from paleo_workbench.runtime import TaskScheduler, TaskState  # noqa: E402
from paleo_workbench.seismic_lifecycle import (  # noqa: E402
    SeismicLifecycleService,
    store_work_path,
)
from paleo_workbench.seismic_transcode import TranscodeParams  # noqa: E402

NIL, NXL, NT = 40, 44, 60
PARAMS = TranscodeParams(chunk=(8, 16, 16), shard=(16, 32, 32), clevel=1)


def _write_segy(path: Path, seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.3).astype(np.float32)
    spec = segyio.spec()
    spec.ilines = list(range(1, NIL + 1))
    spec.xlines = list(range(1, NXL + 1))
    spec.samples = list(range(NT))
    spec.format = 5
    with segyio.create(str(path), spec) as f:
        for il in range(NIL):
            for xl in range(NXL):
                i = il * NXL + xl
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: il + 1,
                    segyio.TraceField.CROSSLINE_3D: xl + 1,
                    segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    return cube


@pytest.fixture()
def project(tmp_path):
    p = tmp_path / "proj" / "demo.paleo.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    return p


@pytest.fixture()
def sched():
    s = TaskScheduler(max_workers=1)
    yield s
    s.shutdown(wait=True, timeout=10.0)


@pytest.fixture()
def imported_raw(project, tmp_path):
    segy = tmp_path / "survey.segy"
    cube = _write_segy(segy)
    svc = DataCatalogService.open(project)
    version = svc.link_external(segy, name="survey", type="seismic")
    yield svc, version, cube
    svc.close()


def _wait_done(handle, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED):
            return handle.state
        time.sleep(0.02)
    raise TimeoutError(f"task still {handle.state}")


def test_full_lifecycle_registers_derived_with_lineage(imported_raw, sched):
    svc, raw, cube = imported_raw
    life = SeismicLifecycleService(svc, scheduler=sched)
    job = life.start_transcode(raw.id, params=PARAMS, workers=1)
    assert _wait_done(job.handle) == TaskState.DONE

    derived = life.derived_version_for(raw.id)
    assert derived is not None
    assert derived.stage.value == "derived"
    assert derived.format == "zarr-v3"
    assert raw.id in derived.parent_version_ids
    assert derived.run_id is not None
    # DataRun completed and links RAW -> DERIVED
    run = svc.get_run(derived.run_id)
    assert run.operation == "segy-to-zarr"
    assert run.status.lower() == "complete"
    assert raw.id in run.input_version_ids
    assert derived.id in run.output_version_ids
    # store moved into managed layout; readable through open_volume
    store = Path(svc.resolve_path(derived))
    assert store.is_dir()
    vol = open_volume(store)
    np.testing.assert_allclose(vol.read_inline(1), cube[0], atol=1e-6)
    # fingerprint recorded instead of a payload hash
    fp = derived.metadata["store_fingerprint"]
    assert fp["files"] > 0 and fp["bytes"] > 0
    assert not store_work_path(svc, raw.id).exists()


def test_browse_via_segy_fallback_while_transcode_runs(imported_raw, sched):
    """The RAW stays readable through the SEG-Y backend during the job."""
    svc, raw, cube = imported_raw
    life = SeismicLifecycleService(svc, scheduler=sched)
    job = life.start_transcode(raw.id, params=PARAMS, workers=1)
    vol = open_volume(Path(svc.resolve_path(raw)))
    np.testing.assert_allclose(vol.read_inline(2), cube[1], atol=1e-6)
    assert _wait_done(job.handle) == TaskState.DONE


def test_cancel_then_resume_completes(imported_raw, sched):
    svc, raw, _ = imported_raw
    life = SeismicLifecycleService(svc, scheduler=sched)
    job = life.start_transcode(raw.id, params=PARAMS, workers=1)
    sched.cancel(job.handle.task_id)
    state = _wait_done(job.handle)
    assert state == TaskState.CANCELLED
    # run marked cancelled; no derived version; nothing registered as complete
    assert life.derived_version_for(raw.id) is None
    run = svc.get_run(job.run_id)
    assert run.status.lower() == "cancelled"
    # resume: same RAW, fresh job; transcoder skips completed shards
    job2 = life.start_transcode(raw.id, params=PARAMS, workers=1)
    assert _wait_done(job2.handle) == TaskState.DONE
    assert life.derived_version_for(raw.id) is not None


def test_retranscode_marks_old_derived_stale(imported_raw, sched):
    svc, raw, _ = imported_raw
    life = SeismicLifecycleService(svc, scheduler=sched)
    j1 = life.start_transcode(raw.id, params=PARAMS, workers=1)
    assert _wait_done(j1.handle) == TaskState.DONE
    first = life.derived_version_for(raw.id)

    j2 = life.start_transcode(raw.id, params=PARAMS, workers=1)
    assert _wait_done(j2.handle) == TaskState.DONE
    second = life.derived_version_for(raw.id)

    assert second.id != first.id
    first = svc.get_version(first.id)  # re-read post-mutation
    assert first.metadata.get("stale") is True
    assert first.metadata.get("stale_reason") == "re-transcoded"
    # stale version is kept (not deleted, not trashed) for lineage
    assert not first.trashed
    assert svc.resolve_path(first).is_dir()


def test_trash_restore_derived_store_moves_directory(imported_raw, sched):
    svc, raw, _ = imported_raw
    life = SeismicLifecycleService(svc, scheduler=sched)
    job = life.start_transcode(raw.id, params=PARAMS, workers=1)
    assert _wait_done(job.handle) == TaskState.DONE
    derived = life.derived_version_for(raw.id)
    store = Path(svc.resolve_path(derived))

    trashed = svc.trash_version(derived.id, reason="bench")
    assert trashed.trashed
    assert not store.exists()  # payload moved into project trash
    assert life.derived_version_for(raw.id) is None  # trashed excluded

    restored = svc.restore_version(derived.id)
    assert not restored.trashed
    assert Path(svc.resolve_path(restored)).is_dir()
    vol = open_volume(Path(svc.resolve_path(restored)))
    assert vol.shape == (NIL, NXL, NT)


def test_resume_pending_requeues_orphaned_running_runs(imported_raw, sched):
    """A 'running' DataRun from a crashed session is re-queued on open."""
    svc, raw, _ = imported_raw
    orphan = svc.register_run(
        "segy-to-zarr", input_version_ids=[raw.id], status="running"
    )
    life = SeismicLifecycleService(svc, scheduler=sched)
    assert life.resume_pending() == 1
    # orphan bookkeeping closed; new job finishes the transcode
    assert svc.get_run(orphan.id).status.lower() == "cancelled"
    job = life.job_for(raw.id)
    assert job is not None
    assert _wait_done(job.handle) == TaskState.DONE
    assert life.derived_version_for(raw.id) is not None
    assert life.resume_pending() == 0  # nothing pending afterwards
