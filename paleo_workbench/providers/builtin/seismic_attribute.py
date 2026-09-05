"""Built-in seismic attribute providers (P2-B).

Wraps the production out-of-core attribute kernels
(:mod:`paleo_workbench.seismic_attributes`) — the banded, resumable zarr
writer for full volumes and the halo-aware ROI kernel for interactive
queries. One provider per kernel in the ``KERNELS`` table is registered
dynamically, so adding a kernel to the table automatically exposes it here.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paleo_workbench.providers.base import ProviderContext
from paleo_workbench.providers.contracts import (
    ProviderDescriptor,
    ProviderFamily,
    ResourceProfile,
)
from paleo_workbench.providers.errors import ProviderExecutionError, ProviderRejectedInputError
from paleo_workbench.providers.refs import (
    ArtifactRef,
    PathRef,
    ProviderResult,
    SeismicVolumeRef,
)
from paleo_workbench.runtime.task_scheduler import TaskCancelled

_ATTRIBUTE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "output_dir": {
            "type": "string",
            "description": "写入派生 zarr store 的目录（缺省使用 context.work_dir）",
        },
        "roi": {
            "type": "object",
            "description": "交互式 ROI（inline/crossline/time 范围）；提供时走 roi_attribute 内存路径",
            "properties": {
                "il0": {"type": "integer"},
                "il1": {"type": "integer"},
                "xl0": {"type": "integer"},
                "xl1": {"type": "integer"},
                "t0": {"type": "integer"},
                "t1": {"type": "integer"},
            },
        },
    },
    "additionalProperties": False,
}


class SeismicAttributeProvider:
    """One named kernel (e.g. ``c3`` coherence) over one volume."""

    def __init__(self, kernel_name: str, defaults: Mapping[str, Any]):
        self._kernel = kernel_name
        self._defaults = dict(defaults)

    @property
    def descriptor(self) -> ProviderDescriptor:
        label = "相干体 C3" if self._kernel == "c3" else self._kernel
        return ProviderDescriptor(
            provider_id=f"seismic.attribute.{self._kernel}",
            family=ProviderFamily.SEISMIC_ATTRIBUTE,
            version="1.0.0",
            display_name=f"地震属性: {label}",
            description=(
                f"Out-of-core {self._kernel} attribute computation over a seismic volume "
                "(banded resumable zarr output, or in-memory for ROI queries)."
            ),
            capabilities=("seismic_attribute", self._kernel),
            input_types=("SeismicVolumeRef",),
            output_types=("DataVersionRef",),
            parameters_schema=_ATTRIBUTE_SCHEMA,
            resource_profile=ResourceProfile(
                estimated_cpu_cores=2.0,
                # #1146: same order as a budget-derived band peak (the job
                # caps bands at streaming_buffer_bytes; the old 1 GiB was
                # 10-20x under measured 12-20 GB peaks, blinding admission).
                estimated_ram_bytes=5 * 1024**3,
                io_weight=1.0,
                category="seismic.attribute",
            ),
            supports_cancel=True,
            supports_resume=True,
            deterministic=True,
        )

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        volume = inputs.get("volume")
        if not isinstance(volume, (SeismicVolumeRef, PathRef)):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'volume' must be a SeismicVolumeRef or PathRef, got {type(volume).__name__}",
            )
        from geoviz_seismic import open_volume

        path = volume.path
        try:
            reader = open_volume(path)
        except Exception as exc:
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, f"cannot open volume {path!r}: {exc}"
            ) from exc

        from paleo_workbench.seismic_attributes import VolumeAttributeJob, roi_attribute

        roi = parameters.get("roi")
        if roi:
            # #1132: roi_attribute takes ONE bounds tuple (base-index,
            # half-open); the old il0=/xl0= keywords never existed. A zero
            # bound is a legitimate index and must survive (no `or None`).
            bounds = (
                int(roi.get("il0", 0)),
                int(roi.get("il1", 0)),
                int(roi.get("xl0", 0)),
                int(roi.get("xl1", 0)),
                int(roi.get("t0", 0)),
                int(roi.get("t1", 0)),
            )
            result_array = roi_attribute(reader, bounds, name=self._kernel)
            diagnostics = {
                "mode": "roi",
                "shape": list(result_array.shape),
                "finite_ratio": float(
                    (result_array.size - int((~result_array.astype(bool)).sum())) / max(1, result_array.size)
                ),
            }
            return ProviderResult(
                artifacts=[
                    ArtifactRef(
                        name=f"{self._kernel}-roi",
                        kind="array",
                        value=result_array,
                        metadata={"volume": str(path)},
                    )
                ],
                diagnostics=diagnostics,
            )

        output_dir = parameters.get("output_dir")
        if output_dir:
            dst = Path(output_dir)
        elif context.work_dir:
            dst = Path(context.work_dir) / f"attr-{self._kernel}.zarr"
        else:
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, "no output_dir and no context work_dir for full-volume output"
            )
        dst.parent.mkdir(parents=True, exist_ok=True)

        job = VolumeAttributeJob(reader, dst, self._kernel)
        try:
            stats = job.run(_TaskContextAdapter(context))
        except (TaskCancelled, KeyboardInterrupt, SystemExit):
            # #1137: cancellation and interpreter exits propagate unwrapped —
            # wrapping them in ProviderExecutionError would wash cancelled
            # runs into failed statistics and swallow Ctrl-C.
            raise
        except Exception as exc:
            raise ProviderExecutionError(self.descriptor.provider_id, exc) from exc

        # Verification BEFORE commit (invalid output must not register a
        # successful run / derived version — ADR 0066 guard): probe the first
        # band's finite ratio through the same reader contract.
        try:
            probe = open_volume(dst)
            sample = probe.read_inline(probe.geometry.iline_start)
            import numpy as np

            if sample.size and not bool(np.isfinite(sample).any()):
                raise ProviderExecutionError(
                    self.descriptor.provider_id,
                    ValueError("attribute output is entirely non-finite; refusing to register"),
                )
        except ProviderExecutionError:
            raise
        except Exception as exc:
            raise ProviderExecutionError(
                self.descriptor.provider_id,
                ValueError(f"attribute output unreadable after compute: {exc}"),
            ) from exc

        # Register the derived store in the catalog when one is bound; the
        # catalog stays the single write authority for data artifacts.
        version = None
        registered_path = str(dst)
        catalog = context.catalog
        run_id = context.run_id
        if catalog is not None and run_id:
            try:
                version = catalog.register_derived(
                    run_id=run_id,
                    name=f"{self._kernel} attribute",
                    path=str(dst),
                    kind="seismic_attribute",
                    format="zarr",
                )
                # The catalog may relocate the store into managed storage;
                # report the authoritative path.
                managed = getattr(version, "path", None)
                if managed:
                    registered_path = str(managed)
            except Exception:  # catalog registration must not lose the compute
                import logging

                logging.getLogger(__name__).exception(
                    "attribute store catalog registration failed (artifact kept on disk)"
                )

        return ProviderResult(
            artifacts=[
                ArtifactRef(
                    name=f"{self._kernel}-volume",
                    kind="derived_store",
                    version=version,
                    path=registered_path,
                    metadata={"kernel": self._kernel},
                )
            ],
            diagnostics={
                "mode": "full_volume",
                "kernel": self._kernel,
                "bands": getattr(stats, "bands", None),
                "elapsed_s": getattr(stats, "elapsed_s", None),
            },
        )


class _TaskContextAdapter:
    """Adapt ProviderContext to the TaskContext-shaped contract VolumeAttributeJob.run expects."""

    def __init__(self, context: ProviderContext):
        self._context = context

    def check_cancelled(self) -> None:
        self._context.check_cancelled()

    def report_progress(self, done: float, total: float | None = None, message: str = "") -> None:
        ratio = (done / total) if total else done
        self._context.report_progress(ratio, message)

    def sleep_interruptible(self, seconds: float) -> None:
        import time

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._context.check_cancelled()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def make_attribute_providers() -> list[SeismicAttributeProvider]:
    """One provider per kernel currently in the production KERNELS table."""
    from paleo_workbench.seismic_attributes import KERNELS

    return [SeismicAttributeProvider(name, defaults) for name, (_, defaults, _) in KERNELS.items()]
