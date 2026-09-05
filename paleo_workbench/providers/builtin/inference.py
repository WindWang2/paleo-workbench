"""Built-in inference provider — capability view of tiled ONNX (P2-B).

The production inference stack already has a complete provider lifecycle in
:mod:`paleo_workbench.prediction` (``ModelProvider`` protocol, model
registry, package manifests, promote gates). This built-in does NOT
duplicate it: it exposes the tiled-ONNX engine as a *capability* provider so
algorithm-style consumers (harness actions, recompute plans) can execute it
through the same guarded pipeline as every other family, delegating to
``TiledOnnxProvider`` for the actual run.

Model trust chain (#1176, provider half): ``model_path`` is verified before
execution — the artifact's real sha256 is computed, resolved against the
catalog's model registry (``ModelVersion`` by ``artifact_uri`` or registered
``checksum``) and recorded in provenance. An unregistered model — or a file
whose checksum disagrees with its registration — is refused: this provider's
semantics is *trusted* inference, so it fails closed instead of running an
anonymous artifact.
"""
from __future__ import annotations

import hashlib
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

_INFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model_path": {"type": "string", "description": "ONNX 模型文件路径"},
        "registered_model_id": {
            "type": "string",
            "description": "期望的注册模型标识（model_id 或 model_id@version）；提供时解析结果必须与之匹配",
        },
        "classes": {"type": "integer", "minimum": 2, "maximum": 64},
        "work_root": {"type": "string", "description": "推理工作目录（缺省 context.work_dir）"},
        "overlap": {"type": "integer", "minimum": 0, "maximum": 64},
        "batch": {"type": "integer", "minimum": 1, "maximum": 64},
        "prefer_gpu": {"type": "boolean"},
    },
    "required": ["model_path"],
    "additionalProperties": False,
}


def _resolve_model_trust(
    provider_id: str,
    model_path: str | Path,
    catalog: Any,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    """Verify the model artifact against the catalog's model registry (#1176).

    Computes the artifact's real sha256, then resolves it to a registered
    ``ModelVersion`` by ``artifact_uri`` or registered ``checksum``
    (client-side scan of ``list_model_versions`` — the registry has no
    by-path lookup). Read-only: this provider never registers models.

    Raises :class:`ProviderRejectedInputError` (fail closed) when the file
    is missing, no registry is reachable, the model is not registered, its
    checksum disagrees with the registration, or an explicit
    ``expected_model_id`` does not match.
    """
    path = Path(str(model_path)).expanduser()
    if not path.is_file():
        raise ProviderRejectedInputError(provider_id, f"model file not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    sha256 = digest.hexdigest()

    service = getattr(catalog, "service", None)
    if service is None:
        try:  # global fallback when the context carries a bare CatalogPort
            from paleo_workbench.catalog.runtime import get_catalog_service

            service = get_catalog_service()
        except Exception:
            service = None
    list_versions = getattr(service, "list_model_versions", None)
    if not callable(list_versions):
        raise ProviderRejectedInputError(
            provider_id,
            "no reachable model registry (catalog model service unavailable); "
            "refusing to run inference whose model cannot be proven registered",
        )

    want_id: str | None = None
    want_version: str | None = None
    if expected_model_id:
        want_id, _, want_version = str(expected_model_id).partition("@")
    resolved_path = path.resolve()
    for version in list_versions():
        if want_id is not None and str(getattr(version, "model_id", "")) != want_id:
            continue
        if want_version and str(getattr(version, "model_version", "")) != want_version:
            continue
        uri = str(getattr(version, "artifact_uri", "") or "")
        uri_match = bool(uri) and Path(uri).expanduser().resolve() == resolved_path
        registered_checksum = getattr(version, "checksum", None)
        checksum_match = bool(registered_checksum) and registered_checksum == sha256
        if not (uri_match or checksum_match):
            continue
        if uri_match and registered_checksum and registered_checksum != sha256:
            raise ProviderRejectedInputError(
                provider_id,
                "model artifact checksum mismatch for registered version "
                f"{getattr(version, 'model_id', '')}@{getattr(version, 'model_version', '')}: "
                f"registered={registered_checksum} file={sha256}",
            )
        return {
            "sha256": sha256,
            "model_id": getattr(version, "model_id", None),
            "model_version": getattr(version, "model_version", None),
            "matched_by": "artifact_uri" if uri_match else "checksum",
        }
    raise ProviderRejectedInputError(
        provider_id,
        f"model {str(path)} (sha256 {sha256[:12]}…) is not registered in the model "
        "registry (no ModelVersion matches its artifact path or checksum); this "
        "provider runs trusted inference only — register the model package first",
    )


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
            # The delegate lives in prediction.tiled_onnx (prediction.providers
            # only registers it in PROVIDER_BY_NAME — it is not a module attr).
            from paleo_workbench.prediction.tiled_onnx import TiledOnnxProvider
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
        model_path = str(model_ref.path) if model_ref is not None else parameters.get("model_path")
        if not model_path:
            raise ProviderRejectedInputError(
                self.descriptor.provider_id, "model_path parameter required"
            )
        # #1176: prove the model artifact before anything runs — real sha256,
        # registry-resolved identity, fail closed on anything unprovable.
        trust = _resolve_model_trust(
            self.descriptor.provider_id,
            model_path,
            context.catalog if context is not None else None,
            expected_model_id=parameters.get("registered_model_id"),
        )

        payload_parameters = dict(parameters)
        payload_parameters["volume_path"] = volume.path
        payload_parameters["model_path"] = model_path
        work_root = payload_parameters.get("work_root") or context.work_dir
        if work_root:
            payload_parameters["work_root"] = work_root

        delegate = TiledOnnxProvider()
        try:
            payload = delegate.run({volume.path: {"path": volume.path}}, payload_parameters)
        except TaskCancelled:
            # #1137: cancellation propagates unwrapped (run → "cancelled").
            raise
        except Exception as exc:
            raise ProviderExecutionError(self.descriptor.provider_id, exc) from exc

        artifacts = []
        outputs = payload.get("volume_outputs") or {}
        if isinstance(outputs, dict):
            output_items = list(outputs.items())
        else:
            # TiledOnnxProvider.run returns volume_outputs as a list of
            # {name, path, kind, dtype} records — honor both shapes.
            output_items = [
                (str(out.get("name", "volume_output")), out)
                for out in outputs
                if isinstance(out, dict)
            ]
        for name, out in output_items:
            store = out.get("store") if isinstance(out, dict) else out.get("path")
            artifacts.append(
                ArtifactRef(
                    name=name,
                    kind=out.get("kind") or "derived_store",
                    path=str(store) if store else None,
                    metadata={k: v for k, v in (out or {}).items() if k not in ("store", "path")} if isinstance(out, dict) else {},
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
                # Verified identity (#1176): the registry-resolved ModelVersion
                # plus the artifact's real checksum — not a static label.
                "model_id": trust["model_id"],
                "model_version": trust["model_version"],
                "model_path": str(model_path),
                "model_checksum_sha256": trust["sha256"],
                "registered": True,
                "registered_match": trust["matched_by"],
                "generator_version": payload.get("generator_version"),
            },
        )
