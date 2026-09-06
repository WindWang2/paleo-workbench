"""Provider Contract V2 (H7): verify hook, build_identity, and the two
example plugins executing through real interfaces (no mock data)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from paleo_workbench.providers import ProviderContext, execute_provider
from paleo_workbench.providers.registry import ProviderRegistry
from paleo_workbench.providers.contracts import ProviderDescriptor, ProviderFamily
from paleo_workbench.providers.errors import ProviderVerificationError
from paleo_workbench.providers.refs import ArtifactRef, ProviderResult

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "provider_plugins"
sys.path.insert(0, str(_EXAMPLES))

from geology_factor_stats import FactorStatsProvider  # noqa: E402
from export_map_thumbnail import MapThumbnailProvider  # noqa: E402


class TestContractV2:
    def test_build_identity_recorded(self):
        descriptor = FactorStatsProvider().descriptor
        assert descriptor.build_identity
        d = descriptor.to_dict()
        assert d["build_identity"] == descriptor.build_identity

    def test_descriptor_validation_accepts_build_identity(self):
        from paleo_workbench.providers.contracts import validate_descriptor

        assert validate_descriptor(FactorStatsProvider().descriptor) == []
        base = FactorStatsProvider().descriptor
        bad = ProviderDescriptor(
            provider_id=base.provider_id,
            family=base.family,
            version=base.version,
            display_name=base.display_name,
            build_identity=123,  # type: ignore[arg-type]
        )
        assert any("build_identity" in p for p in validate_descriptor(bad))

    def test_verify_hook_passes_warnings_through(self, tmp_path):
        class _Provider(FactorStatsProvider):
            def verify(self, result, context):
                return {"verdict": "pass", "reasons": ["thin coverage"]}

        registry = ProviderRegistry()
        registry.register(_Provider())
        dataset = _real_dataset(5)
        result = execute_provider(
            registry,
            "geology.factor_stats",
            inputs={"dataset": dataset},
            parameters={},
            context=ProviderContext(work_dir=str(tmp_path)),
        )
        assert any("thin coverage" in w for w in result.warnings)

    def test_verify_failure_fails_closed(self, tmp_path):
        class _Bad(FactorStatsProvider):
            def verify(self, result, context):
                return {"verdict": "fail", "reasons": ["stats not plausible"]}

        registry = ProviderRegistry()
        registry.register(_Bad())
        with pytest.raises(ProviderVerificationError, match="stats not plausible"):
            execute_provider(
                registry,
                "geology.factor_stats",
                inputs={"dataset": _real_dataset(5)},
                parameters={},
                context=ProviderContext(work_dir=str(tmp_path)),
            )

    def test_verify_crash_fails_closed(self, tmp_path):
        class _Crash(FactorStatsProvider):
            def verify(self, result, context):
                raise RuntimeError("verifier bug")

        registry = ProviderRegistry()
        registry.register(_Crash())
        with pytest.raises(ProviderVerificationError, match="verifier crashed"):
            execute_provider(
                registry,
                "geology.factor_stats",
                inputs={"dataset": _real_dataset(5)},
                parameters={},
                context=ProviderContext(work_dir=str(tmp_path)),
            )


class TestFactorStatsExample:
    def test_real_statistics_and_catalog_registration(self, tmp_path):
        sys.path.insert(0, str(Path(__file__).parent / "fakes"))
        from inmemory_catalog import InMemoryCatalog

        catalog = InMemoryCatalog()
        registry = ProviderRegistry()
        registry.register(FactorStatsProvider())
        run_ref = catalog.begin_run(operation="provider.test", input_version_ids=[], generator_version="t")
        run_id = getattr(run_ref, "run_id", None) or getattr(run_ref, "id", None)

        context = ProviderContext(
            catalog=catalog, run_id=run_id, work_dir=str(tmp_path / "work")
        )
        result = execute_provider(
            registry,
            "geology.factor_stats",
            inputs={"dataset": _real_dataset(12)},
            parameters={"report_name": "gr-stats"},
            context=context,
        )
        # Real statistics over the real dataset values.
        assert result.metrics["count"] == 12
        assert result.metrics["min"] == pytest.approx(min(FACTOR_VALUES))
        assert result.metrics["mean"] == pytest.approx(sum(FACTOR_VALUES) / len(FACTOR_VALUES))
        # The report artifact exists and is catalog-registered.
        artifact = result.artifacts[0]
        report = json.loads(Path(artifact.path).read_text(encoding="utf-8"))
        assert report["factor_name"] == "GR"
        assert artifact.version is not None
        assert catalog.resolve_version(artifact.version.version_id) is not None

    def test_empty_dataset_fails_verification(self, tmp_path):
        registry = ProviderRegistry()
        registry.register(FactorStatsProvider())
        with pytest.raises(ProviderVerificationError, match="no valid points"):
            execute_provider(
                registry,
                "geology.factor_stats",
                inputs={"dataset": _real_dataset(0)},
                parameters={},
                context=ProviderContext(work_dir=str(tmp_path)),
            )


class TestMapThumbnailExample:
    def test_real_render_to_contained_png(self, tmp_path):
        pytest.importorskip("PySide6")
        from paleo_workbench.mapping.layers import MapDocument, VectorMapLayer

        document = MapDocument(
            id="doc-1",
            title="示例图",
            layers=[VectorMapLayer(name="wells", features=({"x": 500000.0, "y": 4400000.0, "name": "W1"},))],
            extent=(499000.0, 4399000.0, 501000.0, 4401000.0),
        )
        registry = ProviderRegistry()
        registry.register(MapThumbnailProvider())
        context = ProviderContext(workspace_root=str(tmp_path))
        result = execute_provider(
            registry,
            "export.map_thumbnail",
            inputs={"document": document},
            parameters={"output_path": "thumbs/overview.png"},
            context=context,
        )
        out = Path(result.artifacts[0].path)
        assert out.exists()
        assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert "thumbs" in str(out) and tmp_path in out.parents or out.parent.parent == tmp_path

    def test_output_outside_workspace_refused(self, tmp_path):
        pytest.importorskip("PySide6")
        from paleo_workbench.mapping.layers import MapDocument

        document = MapDocument(id="doc-2", title="x", layers=[])
        registry = ProviderRegistry()
        registry.register(MapThumbnailProvider())
        from paleo_workbench.providers.errors import ProviderExecutionError

        with pytest.raises((ProviderExecutionError, ProviderVerificationError)) as excinfo:
            execute_provider(
                registry,
                "export.map_thumbnail",
                inputs={"document": document},
                parameters={"output_path": "/tmp/elsewhere/escape.png"},
                context=ProviderContext(workspace_root=str(tmp_path)),
            )
        assert "/tmp/elsewhere/escape.png" in str(excinfo.value)
        assert not Path("/tmp/elsewhere/escape.png").exists()


FACTOR_VALUES = [58.0, 62.0, 61.5, 70.2, 55.1, 64.0, 59.9, 66.3, 71.0, 57.7, 63.3, 60.4]


def _real_dataset(n: int):
    from paleo_workbench.mapping.geological_pipeline.models import (
        GeologicalFactor,
        GeologicalFactorDataset,
    )

    dataset = GeologicalFactorDataset(factor_name="GR", unit="GAPI", target_horizon="H2")
    for i in range(n):
        dataset.add_point(
            GeologicalFactor(
                name="GR",
                value=FACTOR_VALUES[i % len(FACTOR_VALUES)],
                unit="GAPI",
                well_id=f"W{i}",
                x=500000.0 + i * 100.0,
                y=4400000.0 + i * 50.0,
            )
        )
    return dataset
