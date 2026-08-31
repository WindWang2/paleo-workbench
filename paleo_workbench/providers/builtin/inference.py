"""Built-in inference provider — capability view of tiled ONNX (P2-B).

The production inference stack already has a complete provider lifecycle in
:mod:`paleo_workbench.prediction` (``ModelProvider`` protocol, model
registry, package manifests, promote gates). This built-in does NOT
duplicate it: it exposes the tiled-ONNX engine as a *capability* provider so
algorithm-style consumers (harness actions, recompute plans) can execute it
through the same guarded pipeline as every other family, delegating to
``TiledOnnxProvider`` for the actual run.
"""
from __future__ import annotations

from collections.abc import Mapping
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

_INFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model_path": {"type": "string", "description": "ONNX 模型文件路径"},
        "classes": {"type": "integer", "minimum": 2, "maximum": 64},
        "work_root": {"type": "string", "description": "推理工作目录（缺省 context.work_dir）"},
        "overlap": {"type": "integer", "minimum": 0, "maximum": 64},
        "batch": {"type": "integer", "minimum": 1, "maximum": 64},
        "prefer_gpu": {"type": "boolean"},
    },
    "required": ["model_path"],
    "additionalProperties": False,
}


class TiledOnnxCapabilityProvider:
    """Capability wrapper delegating to prediction.providers.TiledOnnxProvider."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="inference.tiled_onnx",
            family=ProviderFamily.INFERENCE,
            version="1.0.0",
            display_name="分块 ONNX 地震相推理",
            description=(
                "Tiled ONNX inference over a seismic volume (64×128×128 tiles, "
                "receptive-field overlap, center-crop fusion, resumable classmap/"
                "probmap zarr outputs). Delegates to the production TiledOnnxProvider."
            ),
            capabilities=("facies_prediction", "tiled_inference"),
            input_types=("SeismicVolumeRef", "PathRef"),
            output_types=("DataVersionRef",),
            parameters_schema=_INFERENCE_SCHEMA,
            resource_profile=ResourceProfile(
                estimated_cpu_cores=4.0,
                estimated_ram_bytes=2 * 1024**3,
                estimated_vram_bytes=512 * 1024**2,
                io_weight=1.5,
                category="prediction.inference",
            ),
            supports_cancel=True,
            supports_resume=True,
            deterministic=True,
            threading_model="worker_thread",
        )

    def execute(
        self,
        inputs: Mapping[str, Any],
        parameters: Mapping[str, Any],
        context: ProviderContext,
    ) -> ProviderResult:
        try:
            from paleo_workbench.prediction.providers import TiledOnnxProvider
        except Exception as exc:  # onnxruntime missing → honest unavailability
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, f"tiled ONNX stack unavailable: {exc}"
            ) from exc

        volume = inputs.get("volume")
        model_ref = inputs.get("model_file")
        if model_ref is not None and not isinstance(model_ref, PathRef):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'model_file' must be a PathRef, got {type(model_ref).__name__}",
            )
        if not isinstance(volume, (SeismicVolumeRef, PathRef)):
            raise ProviderRejectedInputError(
                self.descriptor.provider_id,
                f"input 'volume' must be a SeismicVolumeRef or PathRef, got {type(volume).__name__}",
            )

        payload_parameters = dict(parameters)
        payload_parameters["volume_path"] = volume.path
        if model_ref is not None:
            payload_parameters["model_path"] = model_ref.path
        work_root = payload_parameters.get("work_root") or context.work_dir
        if work_root:
            payload_parameters["work_root"] = work_root

        delegate = TiledOnnxProvider()
        try:
            payload = delegate.run({volume.path: {"path": volume.path}}, payload_parameters)
        except Exception as exc:
            raise ProviderExecutionError(self.descriptor.provider_id, exc) from exc

        artifacts = []
        outputs = payload.get("volume_outputs") or {}
        for name, out in outputs.items():
            store = out.get("store") if isinstance(out, dict) else None
            artifacts.append(
                ArtifactRef(
                    name=name,
                    kind="derived_store",
                    path=str(store) if store else None,
                    metadata={k: v for k, v in (out or {}).items() if k != "store"} if isinstance(out, dict) else {},
                )
            )
        return ProviderResult(
            artifacts=artifacts,
            warnings=list(payload.get("warnings", [])),
            diagnostics={
                "result_summary": payload.get("result_summary"),
                "mode": (payload.get("runtime") or {}).get("mode") if isinstance(payload.get("runtime"), dict) else None,
            },
            provenance={
                "model_id": delegate.model_id,
                "model_version": delegate.model_version,
                "generator_version": payload.get("generator_version"),
            },
        )
