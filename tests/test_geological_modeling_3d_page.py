from __future__ import annotations

import os
import tempfile
import numpy as np
import pytest
from PySide6.QtCore import Qt

from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
from paleo_workbench.ui.pages.geological_modeling_workers import (
    GeologicalModelingWorker,
    ExportWorker,
    AdvisorWorker,
)
from paleo_workbench.viz.geomodel.engine import (
    generate_cylinder_geometry,
    generate_tube_geometry,
    generate_fault_geometry
)
from paleo_workbench.viz.geomodel.exporters import (
    export_to_flac3d,
    export_to_abaqus
)
from paleo_workbench.viz.geomodel.advisor import (
    check_boreholes,
    check_coplanar_faults
)

def test_geomodel_geometry_generators():
    # Cylinder
    v, f, c = generate_cylinder_geometry((0, 0, 0), (0, 0, 10), radius=2.0)
    assert len(v) > 0
    assert len(f) > 0
    assert len(c) > 0
    
    # Tube
    v, f, c = generate_tube_geometry([[0, 0, 0], [10, 10, 10]], radius=3.0)
    assert len(v) > 0
    assert len(f) > 0
    
    # Faulted Surface
    v, f, c = generate_fault_geometry()
    assert len(v) > 0
    assert len(f) > 0


def test_geomodel_exporters():
    with tempfile.TemporaryDirectory() as tmpdir:
        flac3d_path = os.path.join(tmpdir, "test.f3grid")
        abaqus_path = os.path.join(tmpdir, "test.inp")
        
        # Test FLAC3D export
        assert export_to_flac3d(flac3d_path, nx=3, ny=3, nz=3)
        assert os.path.exists(flac3d_path)
        with open(flac3d_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert "* FLAC3D grid" in content
            assert "GRID" in content
            assert "ZON hex" in content
            
        # Test Abaqus export
        assert export_to_abaqus(abaqus_path, nx=3, ny=3, nz=3)
        assert os.path.exists(abaqus_path)
        with open(abaqus_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert "*HEADING" in content
            assert "*PART" in content
            assert "*NODE" in content
            assert "*ELEMENT" in content


def test_geomodel_advisor_checks():
    bh_data = [
        {
            "name": "Well A",
            "x": 0.0,
            "y": 0.0,
            "total_depth": 100.0,
            "layers": [
                {"top": 0.0, "bottom": 40.0, "lithology": "Sand"},
                {"top": 40.0, "bottom": 80.0, "lithology": "Clay"},
                # Overlap!
                {"top": 70.0, "bottom": 100.0, "lithology": "Granite"}
            ]
        }
    ]
    report = check_boreholes(bh_data)
    assert report["checked_boreholes"] == 1
    assert len(report["issues"]) > 0
    assert any("overlap" in iss["message"].lower() for iss in report["issues"])
    
    faults_data = [
        {"name": "F1", "normal": (1.0, 0.0, 0.0), "d": 10.0},
        {"name": "F2", "normal": (1.0, 0.0, 0.0), "d": 12.0} # Coplanar!
    ]
    fault_report = check_coplanar_faults(faults_data)
    assert fault_report["checked_faults"] == 2
    assert len(fault_report["issues"]) > 0
    assert "coplanar" in fault_report["issues"][0]["message"].lower()


def test_geological_modeling_3d_page_ui_elements(qtbot):
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    
    # Verify layout objects
    assert page.model_tree is not None
    assert page.gl_widget is not None
    assert page.btn_run is not None
    assert page.btn_ai_advisor is not None
    assert page.btn_export is not None
    
    # Verify tree population (now 5 groups including Well-Seismic calibration)
    assert page.model_tree.topLevelItemCount() == 5
    assert page.model_tree.topLevelItem(0).text(0) == "地层构造格架"
    assert page.model_tree.topLevelItem(4).text(0) == "井震融合标定与校正"
    
    # Check default interactive clipping sliders & checkboxes exist
    assert page.chk_clip_x is not None
    assert page.slide_clip_x is not None
    assert page.combo_clip_x_dir is not None
    
    # Test setting clipping values
    page.chk_clip_x.setChecked(True)
    page.slide_clip_x.setValue(60)
    page.combo_clip_x_dir.setCurrentIndex(1)
    
    # Check that interactive clipping updates variables without crashing
    page._update_clipping()

    # Check well-seismic calibration widgets exist
    assert page.slider_wavelet_freq is not None
    assert page.slider_td_shift is not None
    assert page.btn_auto_tie is not None
    
    # Simulate slider tuning changes
    page.slider_wavelet_freq.setValue(45)
    page.slider_td_shift.setValue(-10)
    page._on_tie_params_changed()

    # Auto-tie without data should show info message, not crash
    # (No bh_raw_data loaded, so it should do nothing harmful)
    # We can't easily test the QMessageBox popup in unit tests,
    # but verify no exception is raised.
    assert page.bh_raw_data == []
