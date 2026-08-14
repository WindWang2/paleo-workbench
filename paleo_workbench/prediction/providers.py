"""ModelRegistry-backed inference providers (P2, no ML-framework binding).

A :class:`ModelProvider` is a thin protocol: ``model_id`` / ``model_version``
identity plus ``run(inputs, parameters) -> dict``. Providers are pure Python
and Qt-free; the result dict is JSON-serializable and is what the
:mod:`paleo_workbench.prediction.inference_service` persists as the run's
DERIVED output version.

The registry ships TWO providers — both are honest about what they are:

- :class:`DemoModelProvider` — ``demo_only=True``. Deterministic synthetic
  facies regions. NEVER presented as production output.
- :class:`LocalAssetProvider` — the real GR-median / window heuristic
  (:func:`paleo_workbench.prediction.adapters.run_heuristic_facies`). Output is
  ``final_scientific_prediction=False`` + ``model_type="heuristic"`` with
  uncalibrated probabilities; random template output is ``is_mock=True``.

:func:`ensure_default_models` registers both models in the catalog with
``status="demo"`` — the repo ships NO production model, so
``find_production_model`` returns None and the UI surfaces an honest
"未配置生产模型" state instead of auto-running a mock.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from paleo_workbench.catalog.models import Model, ModelVersion
from paleo_workbench.prediction.adapters import run_heuristic_facies

DEMO_GENERATOR_VERSION = "demo-facies-v1"
HEURISTIC_GENERATOR_VERSION = "local-asset-heuristic-v1"

# Stable logical model ids.
MODEL_ID_DEMO = "demo-facies-v1"
MODEL_ID_HEURISTIC = "facies-heuristic-v1"

# Capability shared by the seismic / well-log facies prediction pages.
CAPABILITY_FACIES = "facies_prediction"

# Provider names stored on ``Model.provider`` and used for dispatch.
PROVIDER_DEMO = "demo"
PROVIDER_LOCAL_ASSET = "local_asset"


class InferenceInputError(RuntimeError):
    """Raised when an inference has no usable input data.

    The honest substitute for the old silent random fallback: a production run
    with no readable inputs fails loudly instead of fabricating output.
    """


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


def _is_file(path: Any) -> bool:
    try:
        from pathlib import Path

        return Path(str(path)).is_file()
    except (TypeError, OSError):
        return False


PROVIDER_BY_NAME: dict[str, type[ModelProvider]] = {
    PROVIDER_DEMO: DemoModelProvider,
    PROVIDER_LOCAL_ASSET: LocalAssetProvider,
}


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
