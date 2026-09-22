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


def test_spreadsheetml_xml_well_log_preview_parsing(tmp_path):
    xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
    <Worksheet ss:Name="测井曲线">
        <Table>
            <Row>
                <Cell><Data ss:Type="String">井号</Data></Cell>
                <Cell><Data ss:Type="String">深度</Data></Cell>
                <Cell><Data ss:Type="String">GR</Data></Cell>
                <Cell><Data ss:Type="String">DT</Data></Cell>
            </Row>
            <Row>
                <Cell><Data ss:Type="String">HZ19-1-1A</Data></Cell>
                <Cell><Data ss:Type="String">99.25</Data></Cell>
                <Cell><Data ss:Type="String">45.2</Data></Cell>
                <Cell><Data ss:Type="String">120.5</Data></Cell>
            </Row>
            <Row>
                <Cell><Data ss:Type="String">HZ19-1-1A</Data></Cell>
                <Cell><Data ss:Type="String">99.375</Data></Cell>
                <Cell><Data ss:Type="String">48.1</Data></Cell>
                <Cell><Data ss:Type="String">121.2</Data></Cell>
            </Row>
        </Table>
    </Worksheet>
</Workbook>
"""
    xml_file = tmp_path / "01-HZ19-1-1A_well_log.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    resource = ResourceItem(
        id="res-2",
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
    assert ("井名", "HZ19-1-1A") in res.summary_rows
    assert ("曲线数", "4") in res.summary_rows
    assert ("采样点", "2") in res.summary_rows
    assert res.data_headers == ("井号", "深度", "GR", "DT")
    assert len(res.data_rows) == 2
    assert res.data_rows[0] == ("HZ19-1-1A", "99.25", "45.2", "120.5")
