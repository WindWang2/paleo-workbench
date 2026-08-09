"""P2 ModelRegistry: catalog Model/ModelVersion entities + service APIs.

Covers registration CRUD, artifact checksum, ``find_production_model``
(returns None when no production model exists — drives the honest
"未配置生产模型" unavailable state), and additive loading of pre-registry
catalog documents.
"""

from __future__ import annotations

import json

import pytest

from paleo_workbench.catalog.models import CatalogDocument, Model, ModelVersion
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.store import catalog_file_for


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


# --- registration ----------------------------------------------------------


def test_register_model_and_version(service):
    model = service.register_model(
        model_id="demo-facies-v1",
        model_name="演示相带预测",
        model_type="demo",
        capability="facies_prediction",
        provider="demo",
        status="demo",
        metadata={"source": "synthetic/demo"},
    )
    assert isinstance(model, Model)
    assert model.model_id == "demo-facies-v1"
    assert model.status == "demo"

    version = service.register_model_version(
        "demo-facies-v1",
        model_version="1",
        deterministic=True,
        demo_only=True,
        status="demo",
    )
    assert isinstance(version, ModelVersion)
    assert version.demo_only is True
    assert version.status == "demo"

    assert service.get_model("demo-facies-v1").model_id == "demo-facies-v1"
    assert service.get_model_version("demo-facies-v1", "1").id == version.id
    assert service.get_model_version_by_id(version.id).model_version == "1"


def test_register_model_is_idempotent_on_model_id(service):
    service.register_model(
        model_id="m1", model_name="A", capability="cap", provider="p", status="demo"
    )
    updated = service.register_model(
        model_id="m1", model_name="A2", capability="cap2", provider="p", status="demo"
    )
    assert len(service.list_models()) == 1
    assert updated.model_name == "A2"
    assert updated.capability == "cap2"


def test_duplicate_model_version_raises(service):
    service.register_model(model_id="m1", model_name="A")
    service.register_model_version("m1", model_version="1")
    with pytest.raises(Exception):
        service.register_model_version("m1", model_version="1")


def test_register_model_version_hashes_artifact(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    try:
        artifact = tmp_path / "model.onnx"
        artifact.write_bytes(b"fake-artifact-bytes")
        svc.register_model(model_id="m1", model_name="A")
        version = svc.register_model_version("m1", artifact_uri=str(artifact))
        assert version.checksum is not None
        from paleo_workbench.catalog.checksum import sha256_file

        assert version.checksum == sha256_file(artifact)
    finally:
        svc.close()


# --- find_production_model -------------------------------------------------


def test_find_production_model_none_when_empty(service):
    assert service.find_production_model("facies_prediction") is None


def test_find_production_model_skips_demo_and_wrong_capability(service):
    service.register_model(
        model_id="demo-facies-v1",
        model_name="Demo",
        capability="facies_prediction",
        provider="demo",
        status="demo",
    )
    service.register_model_version(
        "demo-facies-v1", model_version="1", demo_only=True, status="demo"
    )
    # Another capability: not found either.
    service.register_model(
        model_id="other-v1",
        model_name="Other",
        capability="seismic_facies",
        provider="demo",
        status="production",
    )
    service.register_model_version(
        "other-v1", model_version="1", demo_only=False, status="production"
    )
    assert service.find_production_model("facies_prediction") is None


def test_find_production_model_returns_newest_production(service):
    service.register_model(
        model_id="heur-v1",
        model_name="Heuristic",
        capability="facies_prediction",
        provider="local_asset",
        status="production",
    )
    service.register_model_version(
        "heur-v1", model_version="1", demo_only=False, status="production"
    )
    version = service.find_production_model("facies_prediction")
    assert version is not None
    assert version.model_id == "heur-v1"
    assert version.status == "production"
    assert version.demo_only is False


def test_find_production_model_requires_version_production(service):
    service.register_model(
        model_id="heur-v1",
        model_name="Heuristic",
        capability="facies_prediction",
        provider="local_asset",
        status="production",
    )
    # Model is production but the version is archived/demo → not found.
    service.register_model_version(
        "heur-v1", model_version="1", demo_only=False, status="archived"
    )
    assert service.find_production_model("facies_prediction") is None


def test_find_production_model_skips_demo_only_version(service):
    service.register_model(
        model_id="demo-prod",
        model_name="Demo",
        capability="facies_prediction",
        provider="demo",
        status="production",
    )
    # demo_only=True must never be returned as a production model.
    service.register_model_version(
        "demo-prod", model_version="1", demo_only=True, status="production"
    )
    assert service.find_production_model("facies_prediction") is None


# --- persistence / backward compatibility ----------------------------------


def test_model_registry_persists_and_reloads(service):
    service.register_model(
        model_id="m1", model_name="A", capability="cap", provider="p", status="demo"
    )
    service.register_model_version("m1", model_version="1", demo_only=True)
    store_path = catalog_file_for(service.project_path)
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(raw["models"]) == 1
    assert len(raw["model_versions"]) == 1
    assert raw["model_versions"][0]["demo_only"] is True


def test_old_catalog_document_without_models_loads(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    store_path = catalog_file_for(project_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "catalog_revision": 3,
                "assets": [],
                "versions": [],
                "runs": [],
                "tags": [],
            }
        ),
        encoding="utf-8",
    )
    svc = DataCatalogService.open(project_path)
    try:
        doc: CatalogDocument = svc.document
        assert doc.catalog_revision == 3
        assert doc.models == []
        assert doc.model_versions == []
        # New API still works on the migrated document.
        svc.register_model(model_id="m1", model_name="A")
        assert svc.get_model("m1").model_name == "A"
    finally:
        svc.close()


def test_data_run_model_ref_is_optional(service):
    run = service.register_run("inference", status="running")
    assert run.model_ref is None
    run2 = service.register_run(
        "inference",
        status="running",
        model_ref={"model_id": "m1", "model_version": "1", "model_version_id": "mver1"},
    )
    assert run2.model_ref["model_id"] == "m1"
