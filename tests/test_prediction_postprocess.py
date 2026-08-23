from __future__ import annotations

from pathlib import Path

from paleo_workbench.prediction.postprocess import (
    postprocess_prediction_regions,
    resolve_formation_boundaries,
)


def _region(top: float, bottom: float, facies: str, probability: float) -> dict:
    return {
        "region_id": f"raw-{top}",
        "top": top,
        "bottom": bottom,
        "facies": facies,
        "probability": probability,
    }


def test_postprocess_merges_matching_display_probability_but_not_across_a_top():
    records, summary = postprocess_prediction_regions(
        [
            _region(0.0, 1.0, "分流间湾", 0.531),
            _region(1.0, 2.0, "分流间湾", 0.534),
            _region(2.0, 3.0, "分流间湾", 0.532),
            _region(3.0, 4.0, "分流间湾", 0.531),
        ],
        formation_boundaries=[{"name": "珠海组", "depth": 2.0}],
    )

    assert [(item["top"], item["bottom"]) for item in records] == [
        (0.0, 2.0),
        (2.0, 4.0),
    ]
    assert [item["probability"] for item in records] == [0.53, 0.53]
    assert [item["stratigraphic_unit"] for item in records] == [
        "未标定层位",
        "珠海组",
    ]
    assert [item["merged_sample_count"] for item in records] == [2, 2]
    assert summary == {
        "applied": True,
        "confidence_display_precision": "1%",
        "raw_region_count": 4,
        "split_region_count": 4,
        "postprocessed_region_count": 2,
        "formation_boundary_count": 1,
    }


def test_postprocess_splits_a_sample_cell_when_a_formation_top_falls_inside_it():
    records, summary = postprocess_prediction_regions(
        [_region(1000.0, 1001.0, "分流河道", 0.627)],
        formation_boundaries=[{"name": "下段", "depth": 1000.5}],
    )

    assert [(item["top"], item["bottom"]) for item in records] == [
        (1000.0, 1000.5),
        (1000.5, 1001.0),
    ]
    assert [item["stratigraphic_unit"] for item in records] == [
        "未标定层位",
        "下段",
    ]
    assert summary["split_region_count"] == 2
    assert summary["postprocessed_region_count"] == 2


def test_postprocess_keeps_different_facies_or_display_probability_separate():
    records, _summary = postprocess_prediction_regions(
        [
            _region(0.0, 1.0, "分流间湾", 0.53),
            _region(1.0, 2.0, "分流河道", 0.53),
            _region(2.0, 3.0, "分流河道", 0.54),
        ]
    )

    assert [(item["facies"], item["probability"]) for item in records] == [
        ("分流间湾", 0.53),
        ("分流河道", 0.53),
        ("分流河道", 0.54),
    ]


def test_boundary_resolver_matches_catalogued_tops_to_the_selected_well(tmp_path: Path):
    tops = tmp_path / "DC.dat"
    tops.write_text(
        "\n".join(
            [
                "#WellName Name MD X Y Z TVD Time(ms)",
                "A17 珠海组 1589.00 0 0 0 1589.00 0",
                "A17 恩平组 1623.00 0 0 0 1623.00 0",
                "A18 珠海组 900.00 0 0 0 900.00 0",
            ]
        ),
        encoding="utf-8",
    )

    boundaries, diagnostics = resolve_formation_boundaries(
        "A17.las",
        inputs={
            "tops-v1": {
                "asset_type": "well_stratification",
                "name": "DC.dat",
                "path": str(tops),
            }
        },
    )

    assert diagnostics == []
    assert boundaries == [
        {"name": "珠海组", "depth": 1589.0, "source": "well_stratification"},
        {"name": "恩平组", "depth": 1623.0, "source": "well_stratification"},
    ]
