"""High-resolution unified renderer export and OUTPUT lineage contracts."""

from PySide6.QtGui import QImage

from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend
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
