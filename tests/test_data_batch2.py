"""Unit tests for Batch 2: Data Management (WellTable array exports, DataFrame interoperability)."""

import numpy as np
import pytest

from paleo_workbench.project.models import WellTable, WellTableRow
from paleo_workbench.workflow.well_table import well_table_to_arrays, well_table_to_dataframe


def test_well_table_to_arrays_empty():
    table = WellTable(name="EmptyTable", rows=[])
    arrays = well_table_to_arrays(table, value_key="z")
    assert len(arrays["names"]) == 0
    assert len(arrays["x"]) == 0
    assert len(arrays["y"]) == 0
    assert len(arrays["z"]) == 0


def test_well_table_to_arrays_and_df():
    rows = [
        WellTableRow(
            well_id="w1",
            name="Well-01",
            x=500000.0,
            y=3400000.0,
            z=15.5,
            qc_flag="ok",
        ),
        WellTableRow(
            well_id="w2",
            name="Well-02",
            x=505000.0,
            y=3405000.0,
            z=22.8,
            qc_flag="ok",
        ),
        WellTableRow(
            well_id="w3",
            name="Well-03",
            x=510000.0,
            y=3410000.0,
            z=999.0,
            qc_flag="outlier",
        ),
    ]
    table = WellTable(name="TestTable", rows=rows)

    # Export ok only
    arrays = well_table_to_arrays(table, include_flagged=False, value_key="z")
    assert len(arrays["names"]) == 2
    assert list(arrays["names"]) == ["Well-01", "Well-02"]
    np.testing.assert_allclose(arrays["x"], [500000.0, 505000.0])
    np.testing.assert_allclose(arrays["z"], [15.5, 22.8])

    # Export all
    arrays_all = well_table_to_arrays(table, include_flagged=True, value_key="z")
    assert len(arrays_all["names"]) == 3

    # To DataFrame
    df = well_table_to_dataframe(table, include_flagged=True, value_key="z")
    assert len(df) == 3
    assert "name" in df.columns
    assert "value" in df.columns
