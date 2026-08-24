"""Tests for GL context cleanup and deferred queueing (Issue #974)."""

import numpy as np
import pytest
from PySide6 import QtGui
import geoviz_seismic.renderer_3d as r3d


def test_dual_gl_volume_item_clean_without_context_queues_deletions(monkeypatch):
    """DualGLVolumeItem.clean() must queue texture and program IDs when currentContext is None."""
    item = r3d.DualGLVolumeItem(np.zeros((4, 4, 4), dtype=np.float32))
    item.texture = 1001
    item._primary_cmap_tex = 1002
    item._overlay_cmap_tex = 1003
    item._sculpt_horizon_tex = 1004
    item._normal_tex = 1005
    item._customShaderProgram = 2001

    # Simulate context being None (e.g. during page close or teardown)
    monkeypatch.setattr(QtGui.QOpenGLContext, "currentContext", lambda: None)

    r3d._PENDING_GL_TEXTURE_DELETES.clear()
    r3d._PENDING_GL_PROGRAM_DELETES.clear()

    item.clean()

    assert 1001 in r3d._PENDING_GL_TEXTURE_DELETES
    assert 1002 in r3d._PENDING_GL_TEXTURE_DELETES
    assert 1003 in r3d._PENDING_GL_TEXTURE_DELETES
    assert 1004 in r3d._PENDING_GL_TEXTURE_DELETES
    assert 1005 in r3d._PENDING_GL_TEXTURE_DELETES
    assert 2001 in r3d._PENDING_GL_PROGRAM_DELETES

    assert item.texture is None
    assert item._primary_cmap_tex is None
    assert item._customShaderProgram is None
