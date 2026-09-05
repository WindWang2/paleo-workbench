"""Example capability provider (Harness 2.0, H7): pure geological compute.

``geology.factor_stats`` computes real summary statistics over a real
:class:`~paleo_workbench.mapping.geological_pipeline.models.GeologicalFactorDataset`
(the typed input the mapping pipeline produces) and writes a JSON report
artifact into the execution work dir. When a catalog run is bound, the
report is registered as an INTERMEDIATE data version — data outputs always
enter the catalog through the port, never around it.

The provider demonstrates the V2 contract surface:

- frozen descriptor with ``build_identity``;
- typed input/output declarations (no anonymous dicts);
- a post-execution ``verify`` hook (fail-closed: a stats report whose mean
  falls outside [min, max] is a contract violation, not a warning).

Register it explicitly::

    from paleo_workbench.providers import get_provider_registry
    from geology_factor_stats import FactorStatsProvider

    get_provider_registry().register(FactorStatsProvider())
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paleo_workbench.providers.base import ProviderContext
from paleo_workbench.providers.contracts import (
    ProviderDescriptor,
    ProviderFamily,
    ResourceProfile,
)
from paleo_workbench.providers.errors import ProviderRejectedInputError
from paleo_workbench.providers.refs import ArtifactRef, ProviderResult


class FactorStatsProvider:
    """INTERPOLATION-family adjacent compute: factor dataset summary stats."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="geology.factor_stats",
            family=ProviderFamily.INTERPOLATION,
            version="1.0.0",
            build_identity="examples/provider-plugins@2026-09-06",
            display_name="地质因子统计摘要",
            description=(
                "Compute count/finite/min/max/mean/stdev over a "
                "GeologicalFactorDataset's valid points and emit a JSON "
                "report artifact (catalog-registered when a run is bound)."
            ),
            capabilities=("factor_stats",),
            input_types=("GeologicalFactorDataset", "FactorDatasetRef"),
            output_types=("PathRef",),
            parameters_schema={
                "type": "object",
                "properties": {
                    "report_name": {
                        "type": "string",
                        "description": "报告工件名（不含扩展名）",
                        "pattern": "^[a-z0-9._-]+$",
                    },
                },
                "additionalProperties": False,
            },
            resource_profile=ResourceProfile(
                estimated_cpu_cores=0.5,
                estimated_ram_bytes=64 * 1024**2,
                io_weight=0.2,
                category="background.compute",
            ),
            supports_cancel=False,
            deterministic=True,
        )

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        dataset = inputs.get("dataset")
        if dataset is None:
            ref = inputs.get("factor_dataset")
            if ref is not None:
                dataset = (context.extras or {}).get("factor_datasets", {}).get(
                    getattr(ref, "factor_name", "")
                )
        if dataset is None or not hasattr(dataset, "valid_points"):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                "input 'dataset' must be a GeologicalFactorDataset",
            )

        points = dataset.valid_points
        values = [float(p.value) for p in points]
        context.report_progress(0.3, "统计计算")
        if values:
            stats = {
                "count": len(values),
                "finite": len(values),
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "stdev": _stdev(values),
            }
        else:
            stats = {
                "count": 0,
                "finite": 0,
                "min": None,
                "max": None,
                "mean": None,
                "stdev": None,
            }
        stats["factor_name"] = getattr(dataset, "factor_name", "")
        stats["unit"] = getattr(dataset, "unit", "")
        stats["target_horizon"] = getattr(dataset, "target_horizon", "")
        context.report_progress(0.7, "写报告")

        report_name = str(parameters.get("report_name") or "factor-stats")
        work_dir = Path(context.work_dir) if context.work_dir else Path.cwd()
        work_dir.mkdir(parents=True, exist_ok=True)
        report_path = work_dir / f"{report_name}.json"
        report_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
        )

        version = None
        catalog = context.catalog
        if catalog is not None and context.run_id:
            try:
                version = catalog.register_intermediate(
                    run_id=context.run_id,
                    name=f"{report_name}",
                    path=str(report_path),
                    kind="factor_stats_report",
                    format="json",
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "factor stats report registration failed (file kept on disk)"
                )

        return ProviderResult(
            artifacts=[
                ArtifactRef(
                    name=report_path.name,
                    kind="file",
                    version=version,
                    path=str(report_path),
                    metadata={"factor": stats["factor_name"]},
                )
            ],
            metrics={k: v for k, v in stats.items() if isinstance(v, (int, float))},
        )

    def verify(self, result: ProviderResult, context: ProviderContext) -> dict[str, Any]:
        """Fail-closed check: mean must sit within [min, max] when present."""
        metrics = result.metrics
        if metrics.get("count", 0) == 0:
            return {"verdict": "fail", "reasons": ["no valid points — empty statistics"]}
        mean, vmin, vmax = metrics.get("mean"), metrics.get("min"), metrics.get("max")
        if None in (mean, vmin, vmax) and None not in (mean, vmin, vmax):
            return {"verdict": "fail", "reasons": ["incomplete statistics"]}
        if mean is not None and not (vmin <= mean <= vmax):
            return {
                "verdict": "fail",
                "reasons": [f"mean {mean} outside [{vmin}, {vmax}]"],
            }
        return {"verdict": "pass", "reasons": []}


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5
