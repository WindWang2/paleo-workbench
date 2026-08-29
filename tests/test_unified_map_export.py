"""High-resolution unified renderer export and OUTPUT lineage contracts."""

from PySide6.QtGui import QImage

import sys

import pytest

from tests.qgis_support import QGIS_SKIP_REASON

from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend, QgisMapRenderBackend
from paleo_workbench.resources.export_service import export_widget_snapshot, view_export_capabilities
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
from tests.test_unified_map_canvas import _snapshot


def test_unified_canvas_exports_the_renderer_at_requested_high_resolution(tmp_path, qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    canvas.set_overlay_provider(lambda: {
        "decorations": {"title": "Map", "elements": ["标题栏", "比例尺", "指北针", "图例"], "legend_items": ["Well"]}
    })
    output = tmp_path / "map.png"

    canvas.export_png(str(output), width=640, height=480, dpi=200.0)

    image = QImage(str(output))
    assert output.is_file()
    assert (image.width(), image.height()) == (640, 480)
    assert "PNG" in view_export_capabilities(canvas)


def test_unified_export_registers_output_lineage(tmp_path, qtbot) -> None:
    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    project = ProjectDocument.new(name="Map Export")

    result = export_widget_snapshot(
        canvas,
        tmp_path / "map.png",
        project=project,
        linked_id="map-1",
        source_task_ids=["factor-1"],
    )

    assert result.success
    assert result.artifact is not None
    assert result.artifact.format == "png"
    assert result.artifact.included_map_elements[-1] == "unified_map"


@pytest.mark.qgis
def test_qgis_unified_export_cancels_interactive_work_without_a_stale_frame(tmp_path, qtbot) -> None:
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        pytest.skip(QGIS_SKIP_REASON)
    canvas = UnifiedMapCanvas(backend=backend)
    qtbot.addWidget(canvas)
    canvas.resize(320, 220)
    canvas.show()
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))

    output = tmp_path / "qgis-map.png"
    canvas.export_png(str(output), width=360, height=240, dpi=150.0)

    image = QImage(str(output))
    assert (image.width(), image.height()) == (360, 240)


def test_fallback_export_scales_title_font_with_dpi(tmp_path, qtbot) -> None:
    """Export decorations scale the title font by dpi/96 (same physical size
    as the 96-dpi screen look); the screen path is unchanged."""
    import numpy as np

    canvas = UnifiedMapCanvas(backend=FallbackMapRenderBackend())
    qtbot.addWidget(canvas)
    canvas.set_layer_snapshot(_snapshot())
    canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    canvas.set_overlay_provider(lambda: {
        "decorations": {"title": "TITLE", "elements": ["标题栏"]}
    })

    def title_height(dpi: float) -> int:
        image = canvas.render_export_image(800, 600, dpi=dpi)
        pixels = np.frombuffer(image.constBits().tobytes(), dtype=np.uint8).reshape(600, 800, 4).astype(int)
        background = np.array([0x18, 0x1C, 0x22, 0xFF], dtype=int)
        diff = np.abs(pixels - background).sum(axis=2)
        # The title is the top-most decoration; ignore map content below.
        rows = np.where((diff > 24).any(axis=1))[0]
        title_rows = rows[rows < 100]
        assert title_rows.size > 0
        return int(title_rows.max() - title_rows.min() + 1)

    height_96 = title_height(96.0)
    height_300 = title_height(300.0)
    # Glyph rasterization quantizes to integer pixels; the ratio must track
    # dpi/96 (old behavior: exactly 1.0 regardless of dpi).
    assert height_96 > 0
    # The dpi/96 ratio holds exactly on the Linux font stack; Windows'
    # default CJK fallback rasterizes the 标题栏 glyphs with different
    # metrics, so there only the contract (decorations scale with dpi,
    # never the old fixed 1.0) is asserted.
    if sys.platform == "win32":
        assert height_300 > height_96 * 1.5
    else:
        assert height_300 / height_96 == pytest.approx(300.0 / 96.0, rel=0.1)
