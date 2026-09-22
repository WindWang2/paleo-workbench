"""#1152 / #1184 / #1167 — inference service envelope + registry + cancel.

#1152: the persisted payload's envelope keys (model identity, seed,
provenance hash, run linkage, parameters) are SERVICE-owned. A provider
result dict is merged in, but its reserved keys are dropped — a malicious
or buggy provider cannot relabel a run after execution.

#1184: duplicate provider registration raises instead of silently
overwriting a live provider.

#1167: a cooperatively cancelled run ends in the terminal ``cancelled``
state (not ``failed``), with no output version.
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.prediction.inference_service import execute_run, start_inference
from paleo_workbench.prediction.providers import (
    register_provider,
    unregister_provider,
)

PROVIDER_EVIL = "evil_envelope_provider"
PROVIDER_CANCELLABLE = "cancellable_provider"
PROVIDER_RAISES_TASK_CANCELLED = "raises_task_cancelled_provider"
PROVIDER_DUP = "duplicate_name_provider"


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "envelope.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _register_model_version(service, provider_name: str, model_id: str):
    service.register_model(
        model_id=model_id,
        model_name=f"model-{provider_name}",
        model_type="ml",
        capability="facies_prediction",
        provider=provider_name,
        status="demo",
        metadata={},
    )
    return service.register_model_version(
        model_id,
        model_version="1",
        artifact_uri="",
        input_schema={},
        output_schema={},
        deterministic=True,
        demo_only=False,
        status="demo",
        metadata={},
    )


class _EvilEnvelopeProvider:
    """Returns a result dict that tries to overwrite every envelope key."""

    model_id = "evil-envelope"
    model_version = "1"
    demo_only = False

    def run(self, inputs, parameters):
        return {
            "run_id": "run_forged",
            "model": {"model_id": "forged-model", "checksum": "deadbeef"},
            "seed": 1337,
            "schema_version": "9.9-forged",
            "input_snapshot_hash": "forgedhash",
            "input_version_ids": ["forged-input"],
            "generator_version": "forged-gen",
            "parameters": {"forged": True},
            "output_version_id": "forged-output",
            "result_summary": {
                "predicted_regions": [],
                "is_mock": False,
                "final_scientific_prediction": True,
                "model_type": "ml",
            },
            "adapter_kind": "local",
            "seed_note": "provider seed must NOT win",
        }


def test_provider_cannot_overwrite_payload_envelope(service):
    register_provider(PROVIDER_EVIL, _EvilEnvelopeProvider, replace=True)
    version = _register_model_version(service, PROVIDER_EVIL, "evil-envelope-model")
    run = start_inference(
        service,
        model_version_id=version.id,
        parameters={"seed": 7, "workflow": "test"},
    )
    out = execute_run(service, run.id)

    assert out["run"].status == "complete"
    payload = out["result"]
    # Server-owned envelope values survive the **result merge.
    assert payload["run_id"] == run.id
    assert payload["seed"] == 7
    assert payload["schema_version"] == "1.0"
    assert payload["model"]["model_id"] == "evil-envelope-model"
    assert payload["model"]["checksum"] == (version.checksum or "")
    assert payload["input_snapshot_hash"] == run.parameters["_input_snapshot_hash"]
    assert payload["input_version_ids"] == list(run.input_version_ids)
    assert payload["parameters"] == {"seed": 7, "workflow": "test", "preprocessing_version": ""}
    assert "forged" not in payload["parameters"]
    assert payload.get("output_version_id") != "forged-output"
    # Provider-owned content still lands.
    assert payload["adapter_kind"] == "local"
    assert payload["seed_note"] == "provider seed must NOT win"

    # And the persisted output version carries the same protected envelope.
    output_id = out["run"].output_version_ids[0]
    persisted = json.loads(service.resolve_path(service.get_version(output_id)).read_text("utf-8"))
    assert persisted["run_id"] == run.id
    assert persisted["seed"] == 7
    assert persisted["model"]["model_id"] == "evil-envelope-model"
    assert persisted["input_version_ids"] == list(run.input_version_ids)
    assert persisted["parameters"] == {"seed": 7, "workflow": "test", "preprocessing_version": ""}

    unregister_provider(PROVIDER_EVIL)


# --------------------------------------------------------------------- B2 --

def test_provider_generator_version_is_service_owned(service):
    """B2: the provider result is never read back for generator_version.

    ``generator_version`` is a reserved envelope key — the persisted payload
    and the DataRun carry the service-owned start-time value; a provider
    that wants to declare its own generator uses the non-reserved
    ``provider_generator`` key.
    """

    class _GeneratorForgingProvider:
        model_id = "gen-forge"
        model_version = "1"
        demo_only = False

        def run(self, inputs, parameters):
            return {
                "generator_version": "forged-gen",
                "provider_generator": "provider-says-v9",
                "result_summary": {"is_mock": False, "model_type": "ml"},
            }

    from paleo_workbench.prediction.inference_service import INFERENCE_GENERATOR

    register_provider("generator_forging_provider", _GeneratorForgingProvider, replace=True)
    version = _register_model_version(
        service, "generator_forging_provider", "gen-forge-model"
    )
    run = start_inference(service, model_version_id=version.id)
    out = execute_run(service, run.id)

    assert out["run"].status == "complete"
    # Service value on every surface; the forged label never lands.
    assert run.generator == INFERENCE_GENERATOR
    assert out["run"].generator == INFERENCE_GENERATOR
    assert out["result"]["generator_version"] == INFERENCE_GENERATOR
    # The non-reserved provider-owned key still travels through the merge.
    assert out["result"]["provider_generator"] == "provider-says-v9"
    unregister_provider("generator_forging_provider")


# ---------------------------------------------------------------------- B1 --

class _VolumeStealerProvider:
    """Returns volume_outputs pointing at a host directory of its choosing."""

    model_id = "volume-stealer"
    model_version = "1"
    demo_only = False
    store_path: str = ""

    def run(self, inputs, parameters):
        return {
            "volume_outputs": [
                {"name": "stolen", "path": self.store_path, "kind": "classmap", "dtype": "uint8"}
            ],
            "result_summary": {"is_mock": False, "model_type": "ml"},
        }


def test_volume_store_outside_run_workspace_fails_run_and_moves_nothing(
    service, tmp_path
):
    """B1: register_derived_store MOVES directories — an uncontained provider
    store path must fail the run honestly instead of relocating user data."""
    register_provider("volume_stealer_provider", _VolumeStealerProvider, replace=True)
    version = _register_model_version(
        service, "volume_stealer_provider", "stealer-model"
    )

    victim = tmp_path / "important-user-dir"
    victim.mkdir()
    (victim / "keep.txt").write_text("do not move me", encoding="utf-8")
    _VolumeStealerProvider.store_path = str(victim)

    run = start_inference(service, model_version_id=version.id)
    out = execute_run(service, run.id)

    finished = out["run"]
    assert finished.status == "failed"
    assert "outside this run's workspace" in str(finished.parameters.get("error"))
    # Honest failure: nothing was registered, nothing was moved.
    assert finished.output_version_ids == []
    assert victim.is_dir()
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "do not move me"

    unregister_provider("volume_stealer_provider")


def test_volume_store_inside_project_artifacts_registers_and_moves(service, tmp_path):
    """B1 positive: a store genuinely inside the run workspace registers."""
    register_provider("volume_stealer_provider", _VolumeStealerProvider, replace=True)
    version = _register_model_version(
        service, "volume_stealer_provider", "stealer-model"
    )

    # The service fixture's project file is proj/envelope.paleo.json → the
    # artifacts tree is proj/envelope.artifacts.
    artifacts_root = tmp_path / "proj" / "envelope.artifacts"
    store = artifacts_root / "inference" / "classmap"
    store.mkdir(parents=True)
    (store / "zarr.json").write_text("{}", encoding="utf-8")
    _VolumeStealerProvider.store_path = str(store)

    run = start_inference(service, model_version_id=version.id)
    out = execute_run(service, run.id)

    assert out["run"].status == "complete"
    # Result JSON version + the moved volume store version.
    assert len(out["run"].output_version_ids) == 2
    assert not store.exists()  # moved into the managed derived layout
    unregister_provider("volume_stealer_provider")


def test_volume_store_inside_explicit_run_work_root_is_allowed(service, tmp_path):
    """B1: an explicitly declared run work_root is a valid containment root."""
    register_provider("volume_stealer_provider", _VolumeStealerProvider, replace=True)
    version = _register_model_version(
        service, "volume_stealer_provider", "stealer-model"
    )

    work_root = tmp_path / "explicit-work"
    store = work_root / "classmap"
    store.mkdir(parents=True)
    (store / "zarr.json").write_text("{}", encoding="utf-8")
    _VolumeStealerProvider.store_path = str(store)

    run = start_inference(
        service, model_version_id=version.id, parameters={"work_root": str(work_root)}
    )
    out = execute_run(service, run.id)

    assert out["run"].status == "complete"
    assert len(out["run"].output_version_ids) == 2
    unregister_provider("volume_stealer_provider")


# --------------------------------------------------------------------- #1184


class _ProviderA:
    model_id = "a"
    model_version = "1"
    demo_only = True

    def run(self, inputs, parameters):  # pragma: no cover - registration only
        return {}


class _ProviderB(_ProviderA):
    model_id = "b"


def test_duplicate_provider_registration_raises():
    register_provider(PROVIDER_DUP, _ProviderA, replace=True)
    with pytest.raises(ValueError, match=PROVIDER_DUP):
        register_provider(PROVIDER_DUP, _ProviderB)
    # The failed registration did NOT overwrite the live provider.
    from paleo_workbench.prediction.providers import get_provider

    assert isinstance(get_provider(PROVIDER_DUP), _ProviderA)

    # Explicit seams still work.
    register_provider(PROVIDER_DUP, _ProviderB, replace=True)
    assert isinstance(get_provider(PROVIDER_DUP), _ProviderB)
    assert unregister_provider(PROVIDER_DUP) is True
    assert unregister_provider(PROVIDER_DUP) is False
    register_provider(PROVIDER_DUP, _ProviderA, replace=True)
    unregister_provider(PROVIDER_DUP)


# --------------------------------------------------------------------- #1167


class _CancellableProvider:
    """Accepts the cancel seam and reports a cooperative cancellation."""

    model_id = "cancellable"
    model_version = "1"
    demo_only = False

    def run(self, inputs, parameters, *, cancel=None):
        # Simulate one tile of work, then the cancel channel fires.
        if cancel is not None:
            for _ in range(10):
                if cancel():
                    return {
                        "cancelled": True,
                        "tiles": 3,
                        "elapsed_s": 0.01,
                        "shape": [4, 4, 4],
                        "classes": 2,
                    }
        return {
            "cancelled": False,
            "tiles": 10,
            "shape": [4, 4, 4],
            "classes": 2,
            "result_summary": {
                "predicted_regions": [],
                "is_mock": False,
                "final_scientific_prediction": False,
                "model_type": "ml",
            },
        }


class _TaskCancelledRaisingProvider:
    model_id = "raises-cancelled"
    model_version = "1"
    demo_only = False

    def run(self, inputs, parameters):
        from paleo_workbench.runtime.task_scheduler import TaskCancelled

        raise TaskCancelled("provider aborted")


def test_cancelled_provider_result_ends_run_as_cancelled(service):
    register_provider(PROVIDER_CANCELLABLE, _CancellableProvider, replace=True)
    version = _register_model_version(service, PROVIDER_CANCELLABLE, "cancellable-model")
    run = start_inference(service, model_version_id=version.id, parameters={"seed": 1})

    out = execute_run(service, run.id, cancel=lambda: True)

    finished = out["run"]
    assert finished.status == "cancelled"
    assert out["cancelled"] is True
    assert out["result"] is None
    # Cancelled ≠ failed ≠ complete: no error label, no consumable output.
    assert "error" not in finished.parameters
    assert finished.output_version_ids == []
    unregister_provider(PROVIDER_CANCELLABLE)


def test_task_cancelled_exception_ends_run_as_cancelled(service):
    register_provider(
        PROVIDER_RAISES_TASK_CANCELLED, _TaskCancelledRaisingProvider, replace=True
    )
    version = _register_model_version(
        service, PROVIDER_RAISES_TASK_CANCELLED, "raises-cancelled-model"
    )
    run = start_inference(service, model_version_id=version.id)

    out = execute_run(service, run.id)

    assert out["run"].status == "cancelled"
    assert out["run"].output_version_ids == []
    unregister_provider(PROVIDER_RAISES_TASK_CANCELLED)


def test_cancel_channel_not_offered_to_providers_without_the_seam(service):
    """A provider whose run() has no cancel parameter still executes
    normally when execute_run is given a cancel callable (#1167)."""
    register_provider(PROVIDER_EVIL, _EvilEnvelopeProvider, replace=True)
    version = _register_model_version(service, PROVIDER_EVIL, "evil-envelope-model")
    run = start_inference(service, model_version_id=version.id)
    out = execute_run(service, run.id, cancel=lambda: True)
    assert out["run"].status == "complete"
    unregister_provider(PROVIDER_EVIL)
