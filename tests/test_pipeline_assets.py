from __future__ import annotations

from paleo_workbench.pipeline.assets import (
    bind_prediction_assets,
    ensure_demo_prediction,
    suggest_assets_for_demo,
)
from paleo_workbench.project.models import (
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)


def _res(name: str, rtype: str, fmt: str, path: str = "") -> ResourceItem:
    return ResourceItem(
        name=name,
        path=path or f"/tmp/{name}",
        type=rtype,
        format=fmt,
        status="indexed",
    )


def test_suggest_assets_for_demo_stable_sort():
    doc = ProjectDocument.new("T")
    doc.resources = [
        _res("B2.Las", "well_log", "las"),
        _res("A1.Las", "well_log", "las"),
        _res("z.sgy", "seismic", "sgy"),
        _res("a.sgy", "seismic", "sgy"),
        _res("note.pdf", "document", "pdf"),
    ]
    suggestion = suggest_assets_for_demo(doc, max_wells=2)
    assert suggestion["well_log_ids"] == [
        next(r.id for r in doc.resources if r.name == "A1.Las"),
        next(r.id for r in doc.resources if r.name == "B2.Las"),
    ]
    assert suggestion["seismic_ids"] == [
        next(r.id for r in doc.resources if r.name == "a.sgy"),
    ]


def test_bind_prediction_assets_sets_input_refs():
    doc = ProjectDocument.new("T")
    w = _res("A1.Las", "well_log", "las")
    s = _res("v.sgy", "seismic", "sgy")
    doc.resources = [w, s]
    task = PredictionTask(name="t", status="complete")
    doc.prediction_tasks.append(task)

    bind_prediction_assets(doc, task, well_log_ids=[w.id], seismic_ids=[s.id])
    assert task.input_refs["well_log_resource_ids"] == [w.id]
    assert task.input_refs["seismic_resource_ids"] == [s.id]


def test_bind_ignores_unknown_ids():
    doc = ProjectDocument.new("T")
    w = _res("A1.Las", "well_log", "las")
    doc.resources = [w]
    task = PredictionTask(name="t")
    bind_prediction_assets(doc, task, well_log_ids=[w.id, "missing"], seismic_ids=["nope"])
    assert task.input_refs["well_log_resource_ids"] == [w.id]
    assert task.input_refs.get("seismic_resource_ids", []) == []


def test_ensure_demo_prediction_creates_and_binds(tmp_path):
    las = tmp_path / "A1.Las"
    las.write_text("~Version\n", encoding="utf-8")
    sgy = tmp_path / "v.sgy"
    sgy.write_bytes(b"x" * 10)
    doc = ProjectDocument.new("T")
    doc.resources = [
        _res("A1.Las", "well_log", "las", str(las)),
        _res("v.sgy", "seismic", "sgy", str(sgy)),
    ]
    task = ensure_demo_prediction(doc, seed=1)
    assert task in doc.prediction_tasks
    assert task.input_refs.get("well_log_resource_ids")
    assert task.result_summary.get("is_mock") is True
    # idempotent: second call returns same last bound task or re-binds without duplicating unbound
    n = len(doc.prediction_tasks)
    ensure_demo_prediction(doc, seed=1)
    assert len(doc.prediction_tasks) == n  # do not spam tasks
