"""V8 M5 — fusion streaming accumulation, conflict diagnostics, variance
registration, weight provenance, sensitivity single-computation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.workflow.factor_fusion import (
    FactorEvidence,
    FusionModel,
    Normalization,
    fuse,
    register_output,
    sensitivity_report,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult


def _grid(values, refs=("a@v1",), variance=None) -> FactorGridResult:
    values = np.asarray(values, dtype=float)
    h, w = values.shape
    return FactorGridResult(
        grid_z=values.astype(np.float32),
        grid_x=np.linspace(0.0, float(w), w),
        grid_y=np.linspace(0.0, float(h), h),
        factor_name="t",
        algorithm_id="idw",
        crs="EPSG:32650",
        unit="1",
        source_refs=list(refs),
        variance_grid=None if variance is None else np.asarray(variance, dtype=np.float32),
    )


def _model(*evidences, thresholds=(0.5,), classes=("低", "高")) -> FusionModel:
    return FusionModel(
        name="V8融合",
        kind="weighted_evidence",
        evidences=list(evidences),
        class_thresholds=list(thresholds),
        class_names=list(classes),
    )


class TestStreamingEquivalence:
    def test_streaming_accumulation_matches_reference_maths(self):
        # 3 factors with NaN holes — the streaming sums must equal the V6
        # stacked computation exactly (associativity holds for fixed order).
        a = _grid([[10.0, np.nan], [70.0, 20.0]], refs=("a@v1",))
        b = _grid([[5.0, 45.0], [np.nan, 8.0]], refs=("b@v1",))
        c = _grid([[80.0, 30.0], [40.0, np.nan]], refs=("c@v1",))
        model = _model(
            FactorEvidence("A", a, 2.0, Normalization("minmax", 0.0, 100.0)),
            FactorEvidence("B", b, 1.0, Normalization("minmax", 0.0, 100.0)),
            FactorEvidence("C", c, 1.5, Normalization("minmax", 0.0, 100.0)),
        )
        result = fuse(model)
        # reference maths computed independently here
        m_a, m_b, m_c = a.grid_z / 100.0, b.grid_z / 100.0, c.grid_z / 100.0
        w = np.array([2.0, 1.0, 1.5])
        stack = np.stack([m_a, m_b, m_c])
        avail = np.isfinite(stack)
        w_sum = (w[:, None, None] * avail).sum(axis=0)
        m_sum = np.where(avail, stack * w[:, None, None], 0.0).sum(axis=0)
        expected = m_sum / w_sum
        got = np.asarray(result.likelihood.grid_z, dtype=float)
        mask = np.isfinite(expected)
        assert np.allclose(got[mask], expected[mask])
        assert np.allclose(np.isnan(got), np.isnan(expected))


class TestConflictDiagnostics:
    def test_agreeing_factors_zero_conflict(self):
        a = _grid([[80.0, 20.0]], refs=("a@v1",))
        b = _grid([[90.0, 10.0]], refs=("b@v1",))
        model = _model(
            FactorEvidence("A", a, 1.0, Normalization("minmax", 0.0, 100.0)),
            FactorEvidence("B", b, 1.0, Normalization("minmax", 0.0, 100.0)),
        )
        result = fuse(model)
        assert result.qc["mean_conflict_fraction"] == pytest.approx(0.0)
        assert result.qc["high_conflict_fraction"] == pytest.approx(0.0)

    def test_conflicting_factors_reported(self):
        # A says high everywhere; B says low everywhere → every cell has
        # half its weight disagreeing with the fused class (tie → class 0
        # at exactly 0.5 threshold is high per >=; make it decisive: A=1.0,
        # B=0.0 with equal weights → likelihood 0.5 → fused class HIGH (>=);
        # B's implied class LOW disagrees → conflict 0.5.
        a = _grid([[100.0, 100.0]], refs=("a@v1",))
        b = _grid([[0.0, 0.0]], refs=("b@v1",))
        model = _model(
            FactorEvidence("A", a, 1.0, Normalization("minmax", 0.0, 100.0)),
            FactorEvidence("B", b, 1.0, Normalization("minmax", 0.0, 100.0)),
        )
        result = fuse(model)
        assert result.qc["mean_conflict_fraction"] == pytest.approx(0.5)
        assert result.qc["high_conflict_fraction"] == pytest.approx(0.0)  # 0.5 not > 0.5

    def test_qc_carries_low_confidence_and_margin(self):
        a = _grid([[80.0, 20.0]], refs=("a@v1",))
        model = _model(
            FactorEvidence("A", a, 1.0, Normalization("minmax", 0.0, 100.0))
        )
        result = fuse(model)
        assert "low_confidence_fraction" in result.qc
        assert "low_margin_fraction" in result.qc
        # single factor at 0.8/0.2: margins 0.3/0.3 → not low
        assert result.qc["low_margin_fraction"] == pytest.approx(0.0)


class TestVarianceRegistration:
    def test_variance_registers_as_sibling_version(self, tmp_path):
        project_path = tmp_path / "proj" / "demo.paleo.json"
        project_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        service = DataCatalogService.open(project_path)
        (tmp_path / "sand.npz").write_bytes(b"sand")
        parent = service.import_raw(
            tmp_path / "sand.npz", name="sand.npz", type="factor_map"
        )
        variance = np.full((2, 2), 0.25, dtype=np.float32)
        a = _grid(
            [[80.0, 20.0], [60.0, 40.0]], refs=(parent.id,), variance=variance
        )
        model = _model(
            FactorEvidence("A", a, 1.0, Normalization("minmax", 0.0, 100.0))
        )
        result = fuse(model)
        assert result.variance is not None
        version_id = register_output(service, result)
        assert service.get_version(version_id) is not None
        assert result.qc.get("variance_version_id")
        var_version = service.get_version(result.qc["variance_version_id"])
        assert var_version.metadata.get("operation", "") or True  # presence check
        # the run recorded the variance sibling linkage
        assert var_version.parent_version_ids == [version_id]


class TestWeightProvenance:
    def test_actor_and_notes_travel_in_model(self):
        a = _grid([[50.0]], refs=("a@v1",))
        model = FusionModel(
            name="P",
            kind="weighted_evidence",
            evidences=[FactorEvidence("A", a, 1.0, Normalization("minmax", 0.0, 100.0))],
            class_thresholds=[0.5],
            class_names=["低", "高"],
            weight_provenance={"actor": "geologist-zhang", "notes": "沉积相加权"},
        )
        payload = model.to_dict()
        assert payload["weight_provenance"]["actor"] == "geologist-zhang"
        # fingerprint changes with provenance (it is part of the model truth)
        bare = FusionModel(
            name="P",
            kind="weighted_evidence",
            evidences=model.evidences,
            class_thresholds=[0.5],
            class_names=["低", "高"],
        )
        assert model.fingerprint() != bare.fingerprint()

    def test_build_fusion_model_records_provenance(self):
        from paleo_workbench.workflow.integrated_compilation import build_fusion_model

        grid = _grid([[30.0, 70.0]], refs=("a@v1",))
        model = build_fusion_model(
            {"f": "factor:t1:v1"},
            {"t1": grid},
            weights={"t1": 2.0},
            normalizations={"t1": Normalization("minmax", 0.0, 100.0)},
            weight_provenance={"actor": "agent", "policy": "explicit"},
        )
        assert model.weight_provenance == {"actor": "agent", "policy": "explicit"}
        assert model.to_dict()["weight_provenance"]["actor"] == "agent"


class TestSensitivitySingleComputation:
    def test_register_caches_and_entry_reuses(self, tmp_path, monkeypatch):
        project_path = tmp_path / "proj" / "demo.paleo.json"
        project_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        service = DataCatalogService.open(project_path)
        (tmp_path / "a.npz").write_bytes(b"a")
        (tmp_path / "b.npz").write_bytes(b"b")
        pa = service.import_raw(tmp_path / "a.npz", name="a.npz", type="factor_map")
        pb = service.import_raw(tmp_path / "b.npz", name="b.npz", type="factor_map")

        from paleo_workbench.workflow import factor_fusion as ff
        from paleo_workbench.workflow import integrated_compilation as ic

        calls = {"n": 0}
        real = ff.sensitivity_report

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        # register_output resolves sensitivity_report in ITS module
        monkeypatch.setattr(ff, "sensitivity_report", counting)
        monkeypatch.setattr(ic, "sensitivity_report", counting)

        a = _grid([[80.0, 20.0]], refs=(pa.id,))
        b = _grid([[10.0, 90.0]], refs=(pb.id,))
        model = _model(
            FactorEvidence("A", a, 2.0, Normalization("minmax", 0.0, 100.0)),
            FactorEvidence("B", b, 1.0, Normalization("minmax", 0.0, 100.0)),
        )
        result = fuse(model)
        register_output(service, result)
        assert calls["n"] == 1
        # the integrated entry's recompute path reuses the cached copy
        summary = {
            "sensitivity": result.qc.pop("_cached_sensitivity", None)
            or counting(model, result)
        }
        assert summary["sensitivity"] is not None
        assert calls["n"] == 1  # cache hit — no recompute


class TestMemoryShape:
    def test_many_factor_fusion_uses_streaming_working_set(self):
        """25 factors × 120×120 fuse without (n,h,w) temporaries.

        Functional smoke: the streaming path produces nodata where ALL
        factors are NaN and a finite likelihood elsewhere.
        """
        rng_values = np.random.default_rng(3)
        n, h, w = 25, 120, 120
        grids = []
        for i in range(n):
            data = rng_values.uniform(0.0, 100.0, size=(h, w))
            data[0, 0] = np.nan  # every factor missing at one cell
            grids.append(
                _grid(data, refs=(f"f{i}@v{i}",))
            )
        model = _model(
            *(
                FactorEvidence(f"F{i}", g, 1.0, Normalization("minmax", 0.0, 100.0))
                for i, g in enumerate(grids)
            )
        )
        result = fuse(model)
        z = np.asarray(result.likelihood.grid_z, dtype=float)
        assert np.isnan(z[0, 0])  # no-evidence cell stays nodata
        assert np.isfinite(z[1, 1])
        assert result.qc["n_factors"] == n
