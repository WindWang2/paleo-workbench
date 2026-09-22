"""Verify that blocking __del__ finalizers are removed from UI and viz classes."""

from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
from geoviz_seismic.seismic_view import SeismicView


def test_geological_modeling_page_has_no_del():
    """GeologicalModeling3DPage must not define __del__ (issue #967)."""
    assert "__del__" not in GeologicalModeling3DPage.__dict__


def test_seismic_view_has_no_del():
    """SeismicView must not define __del__ (issue #967)."""
    assert "__del__" not in SeismicView.__dict__
