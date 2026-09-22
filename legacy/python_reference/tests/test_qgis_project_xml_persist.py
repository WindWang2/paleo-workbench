# -*- coding: utf-8 -*-
"""M5: map_qgis_project_xml 进入工程文件；composite save/load 接线。"""
import pytest

pytest.importorskip("PySide6")
from tests.qgis_support import QGIS_SKIP_REASON


def test_project_document_roundtrips_map_qgis_project_xml():
    from paleo_workbench.project.models import ProjectDocument

    doc = ProjectDocument.new("demo")
    assert doc.map_qgis_project_xml == ""
    doc.map_qgis_project_xml = "<qgis>ok</qgis>"
    loaded = ProjectDocument.model_validate(doc.model_dump())
    assert loaded.map_qgis_project_xml == "<qgis>ok</qgis>"


@pytest.mark.qgis
def test_sync_composition_writes_xml_onto_project(qapp, qtbot, tmp_path):
    pytest.importorskip("qgis_render_bridge.mapstack", reason=QGIS_SKIP_REASON)
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    project = ProjectDocument.new("demo")
    project.meta.project_root = str(tmp_path)
    page = CompositeDocument(project)
    qtbot.addWidget(page)
    assert "<qgis" in (project.map_qgis_project_xml or "")
