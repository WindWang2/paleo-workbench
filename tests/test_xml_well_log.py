from pathlib import Path
import pytest
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider
from paleo_workbench.resources.classifier import classify_path


def test_xml_well_log_classifier():
    path = Path("/project/data/well_log_A11.xml")
    item_type, fmt, status = classify_path(path)
    assert item_type == "well_log"
    assert fmt == "xml"


def test_xml_well_log_preview_parsing(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<WITSMLComposite xmlns="http://www.witsml.org/schemas/1series">
    <log>
        <nameWell>A11</nameWell>
        <logCurveInfo>
            <mnemonic>DEPT</mnemonic>
            <unit>m</unit>
            <curveDescription>DEPTH</curveDescription>
        </logCurveInfo>
        <logCurveInfo>
            <mnemonic>GR</mnemonic>
            <unit>gAPI</unit>
            <curveDescription>Gamma Ray</curveDescription>
        </logCurveInfo>
        <logData>
            <data>1000.0, 45.2</data>
            <data>1000.125, 48.5</data>
            <data>1000.25, 52.1</data>
        </logData>
    </log>
</WITSMLComposite>
"""
    xml_file = tmp_path / "A11_well_log.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    resource = ResourceItem(
        id="res-1",
        name=xml_file.name,
        path=str(xml_file),
        format="xml",
        type="well_log",
        status="indexed",
    )

    provider = PreviewProvider()
    res = provider.preview(resource)

    assert res.mode == "well_log"
    assert res.type_label == "测井数据"
    assert res.visualization_available is True
    assert ("井名", "A11") in res.summary_rows
    assert ("曲线数", "2") in res.summary_rows
    assert ("采样点", "3") in res.summary_rows
    assert res.data_headers == ("DEPT", "GR")
    assert len(res.data_rows) == 3
    assert res.data_rows[0] == ("1000.0", "45.2")
