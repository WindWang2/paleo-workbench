"""Test-only spatial model provider (Stage 13).

NEVER seed into user ModelRegistry as production by default.
Register only in tests via ``register_provider`` + package manifest.
"""

from __future__ import annotations

from typing import Any

PROVIDER_TEST_SPATIAL = "test_spatial"
PROVIDER_TEST_SPATIAL_FAIL = "test_spatial_fail"
PROVIDER_TEST_SPATIAL_MALFORMED = "test_spatial_malformed"


class TestSpatialModelProvider:
    """Deterministic VECTOR_POLYGONS provider for automated tests."""

    model_id = "test-spatial-pkg-v1"
    model_version = "1"
    demo_only = False

    def run(
        self,
        inputs: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        # Real coordinates (NOT 114/22.5 demo squares).
        features = [
            {
                "type": "Feature",
                "name": "Sand",
                "facies": "Sand",
                "properties": {
                    "facies": "Sand",
                    "name": "Sand",
                    "probability": 0.82,
                    "region_id": "test_poly_1",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [120.10, 30.20],
                            [120.20, 30.20],
                            [120.20, 30.30],
                            [120.10, 30.30],
                            [120.10, 30.20],
                        ]
                    ],
                },
            },
            {
                "type": "Feature",
                "name": "Mud",
                "facies": "Mud",
                "properties": {
                    "facies": "Mud",
                    "name": "Mud",
                    "probability": 0.71,
                    "region_id": "test_poly_2",
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [120.22, 30.20],
                            [120.32, 30.20],
                            [120.32, 30.28],
                            [120.22, 30.28],
                            [120.22, 30.20],
                        ]
                    ],
                },
            },
        ]
        consumed = sorted(inputs.keys())
        return {
            "adapter_kind": "local",
            "generator_version": "test-spatial-v1",
            "demo": False,
            "source": "test_spatial_provider",
            "result_summary": {
                "predicted_regions": [
                    {
                        "region_id": "test_poly_1",
                        "facies": "Sand",
                        "probability": 0.82,
                    },
                    {
                        "region_id": "test_poly_2",
                        "facies": "Mud",
                        "probability": 0.71,
                    },
                ],
                "is_mock": False,
                "is_replaceable": False,
                "final_scientific_prediction": True,
                "demo": False,
                "model_type": "ml",
                "source": "test_spatial_provider",
                "spatial_output_type": "VECTOR_POLYGONS",
                "spatial": {
                    "type": "VECTOR_POLYGONS",
                    "spatial_output_type": "VECTOR_POLYGONS",
                    "crs": "EPSG:4326",
                    "features": features,
                },
                "consumed_input_version_ids": consumed,
            },
            "probability_summary": {"mean_probability": 0.765},
            "evidence_contribution": [],
            "review_areas": [],
            "seed": int(parameters.get("seed", 0) or 0),
        }


class TestSpatialFailProvider:
    """Provider that always fails (no fabricated output)."""

    model_id = "test-spatial-fail-v1"
    model_version = "1"
    demo_only = False

    def run(self, inputs, parameters):
        raise RuntimeError("test provider intentional failure")


class TestSpatialMalformedProvider:
    """Provider that claims VECTOR_POLYGONS but returns no geometry."""

    model_id = "test-spatial-malformed-v1"
    model_version = "1"
    demo_only = False

    def run(self, inputs, parameters):
        return {
            "adapter_kind": "local",
            "generator_version": "test-spatial-malformed-v1",
            "demo": False,
            "result_summary": {
                "predicted_regions": [{"facies": "X", "probability": 0.5}],
                "final_scientific_prediction": True,
                "spatial_output_type": "VECTOR_POLYGONS",
                "spatial": {
                    "type": "VECTOR_POLYGONS",
                    "crs": "EPSG:4326",
                    "features": [],  # malformed: empty
                },
            },
        }
