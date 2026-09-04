"""ModelRegistry-backed inference providers (P2, no ML-framework binding).

A :class:`ModelProvider` is a thin protocol: ``model_id`` / ``model_version``
identity plus ``run(inputs, parameters) -> dict``. Providers are pure Python
and Qt-free; the result dict is JSON-serializable and is what the
:mod:`paleo_workbench.prediction.inference_service` persists as the run's
DERIVED output version.

The registry ships local/demo providers plus an explicit GeoVizEngine online
single-well provider:

- :class:`DemoModelProvider` — ``demo_only=True``. Deterministic synthetic
  facies regions. NEVER presented as production output.
- :class:`LocalAssetProvider` — the real GR-median / window heuristic
  (:func:`paleo_workbench.prediction.adapters.run_heuristic_facies`). Output is
  ``final_scientific_prediction=False`` + ``model_type="heuristic"`` with
  uncalibrated probabilities; random template output is ``is_mock=True``.

:func:`ensure_default_models` registers the two local models in the catalog with
``status="demo"`` — the repo ships NO production model, so
``find_production_model`` returns None and the UI surfaces an honest
"未配置生产模型" state instead of auto-running a mock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from paleo_workbench.catalog.models import Model, ModelVersion
from paleo_workbench.prediction.adapters import run_heuristic_facies

DEMO_GENERATOR_VERSION = "demo-facies-v1"
HEURISTIC_GENERATOR_VERSION = "local-asset-heuristic-v1"
GEOVIZ_ONLINE_GENERATOR_VERSION = "inference-api-single-well-v1"

# Stable logical model ids.
MODEL_ID_DEMO = "demo-facies-v1"
MODEL_ID_HEURISTIC = "facies-heuristic-v1"
MODEL_ID_GEOVIZ_ONLINE = "geoviz-online-single-well"
MODEL_VERSION_GEOVIZ_ONLINE = "inference-api-v20260823"

# Capability shared by the seismic / well-log facies prediction pages.
CAPABILITY_FACIES = "facies_prediction"

# Provider names stored on ``Model.provider`` and used for dispatch.
PROVIDER_DEMO = "demo"
PROVIDER_LOCAL_ASSET = "local_asset"
PROVIDER_GEOVIZ_ONLINE = "geoviz_online"


class InferenceInputError(RuntimeError):
    """Raised when an inference has no usable input data.

    The honest substitute for the old silent random fallback: a production run
    with no readable inputs fails loudly instead of fabricating output.
    """


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Clamp a persisted/UI parameter to the env path's hard bounds (#1144)."""
    try:
        number = int(value) if value is not None else int(default)
    except (TypeError, ValueError):
        return int(default)
    return max(minimum, min(maximum, number))


@runtime_checkable
class ModelProvider(Protocol):
    """A runnable model registered in the catalog's ModelRegistry."""

    model_id: str
    model_version: str
    demo_only: bool

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Run inference.

        ``inputs`` maps version_id → ``{"path", "name", "asset_type",
        "format"}`` (payload locations of the run's declared input versions).
        ``parameters`` carries reproducibility metadata (``seed``, ``workflow``,
        ...). Returns a JSON-serializable result dict.
        """
        ...


class DemoModelProvider:
    """Deterministic synthetic facies prediction (demo_only).

    The math is a seeded template — it is a DEMO, never a scientific
    prediction. ``demo_only=True`` keeps :meth:`find_production_model` from
    ever returning it, and every result is flagged ``demo=True`` with
    ``source="synthetic/demo"``.
    """

    model_id = MODEL_ID_DEMO
    model_version = "1"
    demo_only = True

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        import random

        from paleo_workbench.prediction.adapters import _FACIES_MUD, _FACIES_SAND

        seed = int(parameters.get("seed", 0) or 0)
        rng = random.Random(seed)
        facies = list(_FACIES_SAND) + list(_FACIES_MUD)
        predicted = [
            {
                "region_id": f"demo_region_{i + 1}",
                "facies": facies[i % len(facies)],
                "probability": round(0.55 + rng.random() * 0.35, 3),
            }
            for i in range(4)
        ]
        mean_p = round(
            sum(item["probability"] for item in predicted) / len(predicted), 3
        )
        return {
            "adapter_kind": "mock",
            "generator_version": DEMO_GENERATOR_VERSION,
            "demo": True,
            "source": "synthetic/demo",
            "result_summary": {
                "predicted_regions": predicted,
                "is_mock": True,
                "is_replaceable": True,
                "final_scientific_prediction": False,
                "demo": True,
                "source": "synthetic/demo",
                "model_type": "demo",
                "probabilities_uncalibrated": True,
            },
            "probability_summary": {"mean_probability": mean_p},
            "evidence_contribution": [
                {"name": "sand_thickness", "weight": 0.45},
                {"name": "target_horizon", "weight": 0.30},
                {"name": "neighbor_wells", "weight": 0.25},
            ],
            "review_areas": [item for item in predicted if item["probability"] < 0.7],
            "seed": seed,
        }


class LocalAssetProvider:
    """GR-median / window heuristic facies prediction (honest, uncalibrated).

    Reuses the exact computation from
    :func:`paleo_workbench.prediction.adapters.run_heuristic_facies` — this is
    NOT an ML model and its output must never be presented as a scientific
    prediction (``final_scientific_prediction=False``).
    """

    model_id = MODEL_ID_HEURISTIC
    model_version = "1"
    demo_only = False

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        seed = int(parameters.get("seed", 0) or 0)
        wells = [
            {"name": i.get("name", ""), "path": i.get("path", ""),
             "readable": bool(i.get("path")) and _is_file(i.get("path")),
             "format": i.get("format", "")}
            for i in inputs.values()
            if i.get("asset_type") == "well_log"
        ]
        seismics = [
            {"name": i.get("name", ""), "path": i.get("path", ""),
             "readable": bool(i.get("path")) and _is_file(i.get("path")),
             "format": i.get("format", ""), "parsed_summary": i.get("parsed_summary") or {}}
            for i in inputs.values()
            if i.get("asset_type") == "seismic"
        ]
        factor_map_ids = [str(i.get("name", "")) for i in inputs.values()
                          if i.get("asset_type") == "factor_map"]
        core = run_heuristic_facies(
            wells, seismics, seed=seed, factor_map_ids=factor_map_ids
        )
        if core["source_kind"] == "mock" and not core["regions"]:
            # No usable inputs: fail loudly — never fabricate output silently.
            raise InferenceInputError(
                "无可用输入数据：未找到可读的测井（LAS）或地震数据，无法运行启发式预测"
            )
        regions = core["regions"]
        mean_p = round(
            sum(float(r.get("probability", 0) or 0) for r in regions)
            / max(len(regions), 1),
            3,
        )
        evidence = [
            {"name": "bound_well_log", "weight": 0.5 if core["well_meta"] else 0.1},
            {"name": "bound_seismic", "weight": 0.3 if core["seismic_meta"] else 0.1},
            {"name": "factor_maps", "weight": 0.2 if factor_map_ids else 0.1},
        ]
        total_w = sum(e["weight"] for e in evidence) or 1.0
        for e in evidence:
            e["weight"] = round(e["weight"] / total_w, 3)
        return {
            "adapter_kind": "local",
            "generator_version": HEURISTIC_GENERATOR_VERSION,
            "demo": False,
            "result_summary": {
                "predicted_regions": regions,
                "is_mock": core["template"],
                "is_replaceable": True,
                "final_scientific_prediction": False,
                "model_type": "heuristic",
                "probabilities_uncalibrated": True,
                "source_kind": core["source_kind"],
                "well_meta": core["well_meta"],
                "seismic_meta": core["seismic_meta"],
                "demo": core["template"],
                "source": "synthetic/demo" if core["template"] else "bound_assets",
            },
            "probability_summary": {"mean_probability": mean_p},
            "evidence_contribution": evidence,
            "review_areas": [
                item for item in regions if float(item.get("probability", 1)) < 0.7
            ],
            "seed": seed,
        }


class GeoVizOnlineProvider:
    """Authenticated external single-well facies service.

    This is intentionally not a default production model: the user explicitly
    invokes it from the well-log prediction page, which is also the point at
    which the selected well's curve rows leave the workstation.  The provider
    still runs through DataRun so success and failure are fully catalogued.
    """

    model_id = MODEL_ID_GEOVIZ_ONLINE
    model_version = MODEL_VERSION_GEOVIZ_ONLINE
    demo_only = False

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        well_inputs = [
            info
            for info in inputs.values()
            if str(info.get("asset_type") or "") == "well_log"
        ]
        if len(well_inputs) != 1:
            raise InferenceInputError(
                "线上测井预测一次只能接收一口已纳管的测井数据"
            )
        info = well_inputs[0]
        path = Path(str(info.get("path") or ""))
        if not path.is_file():
            raise InferenceInputError("所选测井文件不可读取，无法发送线上测井预测")

        from paleo_workbench.prediction.geoviz_online import (
            online_api_key,
            online_endpoint,
            online_model_version_id,
            online_poll_timeout_seconds,
            run_single_well_prediction,
            online_timeout_seconds,
            online_wait_timeout_seconds,
        )
        from paleo_workbench.viz.well_log_load import load_well_log_from_path

        well_log = load_well_log_from_path(str(path))
        if well_log is None:
            raise InferenceInputError("无法解析所选测井文件，无法发送线上测井预测")
        well_name = str(getattr(well_log, "well_name", "") or path.stem)
        # #1144: the connection endpoint is never taken from persisted
        # run/project parameters (a shared project file could carry an
        # attacker's URL) — only the operator environment decides where
        # well curves and the API key are sent. The UI still snapshots the
        # endpoint into parameters as a provenance record (display only).
        endpoint = online_endpoint()
        model_version_id = str(
            parameters.get("online_model_version_id") or online_model_version_id()
        )
        remote = run_single_well_prediction(
            well_name,
            well_log,
            api_key=online_api_key(),
            base_url=endpoint,
            model_version_id=model_version_id,
            wait_timeout_seconds=_clamp_int(
                parameters.get("online_wait_timeout_seconds"),
                online_wait_timeout_seconds(), 1, 120,
            ),
            request_timeout_seconds=_clamp_int(
                parameters.get("online_request_timeout_seconds"),
                online_timeout_seconds(), 1, 600,
            ),
            poll_timeout_seconds=_clamp_int(
                parameters.get("online_poll_timeout_seconds"),
                online_poll_timeout_seconds(), 1, 3600,
            ),
        )
        from paleo_workbench.prediction.postprocess import (
            postprocess_prediction_regions,
            resolve_formation_boundaries,
        )

        formation_boundaries, postprocess_diagnostics = resolve_formation_boundaries(
            well_name,
            well_log=well_log,
            inputs=inputs,
        )
        regions, postprocess_summary = postprocess_prediction_regions(
            list(remote["predicted_regions"]),
            formation_boundaries=formation_boundaries,
        )
        postprocess_summary["formation_boundaries"] = formation_boundaries
        if postprocess_diagnostics:
            postprocess_summary["diagnostics"] = postprocess_diagnostics
        api_summary = dict(remote.get("api_summary") or {})
        class_counts = api_summary.get("classCounts")
        if not isinstance(class_counts, dict):
            class_counts = {}
        remote_summary = {
            "meanConfidence": api_summary.get("meanConfidence"),
            "formationGroup": api_summary.get("formationGroup"),
            "classCounts": {
                str(name): int(count)
                for name, count in class_counts.items()
                if isinstance(name, str) and isinstance(count, (int, float))
            },
        }
        # Consolidated intervals represent unequal depths. Preserve the
        # probability summary's physical meaning rather than averaging a few
        # long merged bands as though each were one original sample.
        weighted_probabilities = []
        for item in regions:
            try:
                thickness = max(
                    0.0, float(item.get("bottom")) - float(item.get("top"))
                )
                probability = float(item.get("probability", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if thickness > 0.0:
                weighted_probabilities.append((probability, thickness))
        total_thickness = sum(thickness for _probability, thickness in weighted_probabilities)
        mean_probability = round(
            sum(
                probability * thickness
                for probability, thickness in weighted_probabilities
            )
            / total_thickness,
            3,
        ) if total_thickness else 0.0
        return {
            # ``PredictionTask``'s persisted adapter vocabulary calls all
            # network-backed providers ``http``.
            "adapter_kind": "http",
            "generator_version": GEOVIZ_ONLINE_GENERATOR_VERSION,
            "demo": False,
            "source": "inference_service_online",
            "result_summary": {
                "predicted_regions": regions,
                "is_mock": False,
                "is_replaceable": False,
                "final_scientific_prediction": False,
                "demo": False,
                "source": "inference_service_online",
                "model_type": "inference_api_online",
                "online_endpoint": remote["endpoint"],
                "remote_model_version": remote["remote_model_version"],
                "remote_model_name": remote.get("remote_model_name", ""),
                "remote_model_display_version": remote.get(
                    "remote_model_display_version", ""
                ),
                "remote_job_id": remote.get("job_id", ""),
                "request_row_count": remote["request_row_count"],
                "remote_summary": remote_summary,
                "postprocess": postprocess_summary,
            },
            "probability_summary": {"mean_probability": mean_probability},
            "evidence_contribution": [
                {"name": "认证线上单井模型", "weight": 1.0},
            ],
            "review_areas": [
                item for item in regions if float(item.get("probability", 1.0)) < 0.7
            ],
            "seed": int(parameters.get("seed", 0) or 0),
        }


def _is_file(path: Any) -> bool:
    try:
        from pathlib import Path

        return Path(str(path)).is_file()
    except (TypeError, OSError):
        return False


PROVIDER_BY_NAME: dict[str, type[ModelProvider]] = {
    PROVIDER_DEMO: DemoModelProvider,
    PROVIDER_LOCAL_ASSET: LocalAssetProvider,
    PROVIDER_GEOVIZ_ONLINE: GeoVizOnlineProvider,
}


def _install_bundled_providers() -> None:
    """Register in-tree providers that need optional dependencies (#1085).

    Imported lazily so a missing onnxruntime never breaks provider module
    import; registration failures surface at get_provider() time instead.
    """
    try:
        from paleo_workbench.prediction.tiled_onnx import (
            PROVIDER_TILED_ONNX,
            TiledOnnxProvider,
        )

        PROVIDER_BY_NAME.setdefault(PROVIDER_TILED_ONNX, TiledOnnxProvider)
    except Exception:  # pragma: no cover - optional dependency path
        pass


_install_bundled_providers()


def register_provider(name: str, provider_cls: type[ModelProvider]) -> None:
    """Plugin seam: register a provider class under *name* (e.g. tests/fakes).

    Does not seed the ModelRegistry. Production UI only finds models that are
    explicitly registered and promoted; test providers must never be installed
    as default production models.
    """
    if not name:
        raise KeyError("provider name required")
    PROVIDER_BY_NAME[str(name)] = provider_cls


def get_provider(name: str) -> ModelProvider:
    """Instantiate a provider by its registry name (raises on unknown)."""
    if not name:
        raise KeyError("No provider name given for model")
    provider_cls = PROVIDER_BY_NAME.get(name)
    if provider_cls is None:
        raise KeyError(f"Unknown model provider: {name!r}")
    return provider_cls()


def _ensure_model_version(service, model_id: str, model_version: str, **kwargs) -> ModelVersion:
    """Idempotent register_model_version (defaults re-registration-safe)."""
    try:
        return service.get_model_version(model_id, model_version)
    except Exception:
        return service.register_model_version(
            model_id, model_version=model_version, **kwargs
        )


def _existing_model(service, model_id: str) -> Model | None:
    """Return the registered model or None. Never creates or rewrites."""
    try:
        return service.get_model(model_id)
    except Exception:
        return None


def ensure_geoviz_online_model(service) -> ModelVersion:
    """Register the explicitly-invoked authenticated online model if needed.

    This is deliberately not promoted to the generic production-model slot:
    no background workflow can send data remotely, and the well-log page
    supplies an explicit action before a selected well is submitted.
    """
    from paleo_workbench.prediction.geoviz_online import (
        DEFAULT_MODEL_VERSION_ID,
        INFERENCE_API_BASE_URL,
    )

    model = _existing_model(service, MODEL_ID_GEOVIZ_ONLINE)
    if model is None:
        # Catalog only distinguishes demo and production states.  Keep this
        # externally hosted test endpoint out of automatic production lookup;
        # its explicit well-log action is still a real remote provider.
        service.register_model(
            model_id=MODEL_ID_GEOVIZ_ONLINE,
            model_name="单井线上沉积相预测",
            model_type="remote",
            capability=CAPABILITY_FACIES,
            provider=PROVIDER_GEOVIZ_ONLINE,
            status="demo",
            metadata={
                "source": "inference_service_online",
                "online": True,
                "endpoint": INFERENCE_API_BASE_URL,
                "explicit_only": True,
            },
        )
    return _ensure_model_version(
        service,
        MODEL_ID_GEOVIZ_ONLINE,
        MODEL_VERSION_GEOVIZ_ONLINE,
        artifact_uri=INFERENCE_API_BASE_URL,
        input_schema={
            "required_asset_types": ["well_log"],
            "required_curves": ["GR"],
            "min_wells": 1,
        },
        runtime="http",
        deterministic=False,
        demo_only=False,
        status="demo",
        metadata={
            "source": "inference_service_online",
            "online": True,
            "remote_model_version": DEFAULT_MODEL_VERSION_ID,
        },
    )


def ensure_default_models(service) -> tuple[Model, Model, ModelVersion, ModelVersion]:
    """Idempotently register the demo + heuristic models (both status=demo).

    The repo ships NO production model: both entries are ``status="demo"`` so
    ``find_production_model`` returns None and the UI shows the honest
    "未配置生产模型" state. Promoting a model to production is an explicit act:
    ``DataCatalogService.promote_model(model_id, model_version)`` sets BOTH
    the model and version status and clears ``demo_only`` atomically.

    Existing models are never rewritten here: if a model was explicitly
    promoted or had its identity changed, this seed call leaves name / type /
    provider / capability / status / metadata untouched and only fills a
    missing version. Callers that want to repair identity must use
    :meth:`DataCatalogService.register_model` directly."""
    demo_model = _existing_model(service, MODEL_ID_DEMO)
    if demo_model is None:
        demo_model = service.register_model(
            model_id=MODEL_ID_DEMO,
            model_name="演示相带预测（Demo）",
            model_type="demo",
            capability=CAPABILITY_FACIES,
            provider=PROVIDER_DEMO,
            status="demo",
            metadata={"source": "synthetic/demo", "demo_only": True},
        )
    demo_version = _ensure_model_version(
        service,
        MODEL_ID_DEMO,
        "1",
        deterministic=True,
        demo_only=True,
        status="demo",
        metadata={"source": "synthetic/demo"},
    )
    heuristic_model = _existing_model(service, MODEL_ID_HEURISTIC)
    if heuristic_model is None:
        heuristic_model = service.register_model(
            model_id=MODEL_ID_HEURISTIC,
            model_name="GR 中值启发式相带估计（非科学预测）",
            model_type="heuristic",
            capability=CAPABILITY_FACIES,
            provider=PROVIDER_LOCAL_ASSET,
            status="demo",
            metadata={
                "scientific": False,
                "probabilities_uncalibrated": True,
                "note": "GR median/window rule — real computation, not a trained model",
            },
        )
    heuristic_version = _ensure_model_version(
        service,
        MODEL_ID_HEURISTIC,
        "1",
        deterministic=True,
        demo_only=False,
        status="demo",
        metadata={"scientific": False, "probabilities_uncalibrated": True},
    )
    return demo_model, heuristic_model, demo_version, heuristic_version
