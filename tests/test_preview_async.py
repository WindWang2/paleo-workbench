from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController


class SlowProvider(PreviewProvider):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        self.calls.append(asset.name)
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"preview:{asset.name}",
        )


def test_rapid_selection_keeps_last_result(qtbot, tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("aaa")
    b.write_text("bbb")
    project = ProjectDocument.new("P")
    project.resources = [
        ResourceItem(name="a.txt", path=str(a), type="document", format="txt"),
        ResourceItem(name="b.txt", path=str(b), type="document", format="txt"),
    ]
    page = DataPage(project)
    qtbot.addWidget(page)
    provider = SlowProvider()
    page.reader_panel.provider = provider
    page._preview_controller.provider = provider

    page._set_selected_asset(project.resources[0])
    page._set_selected_asset(project.resources[1])

    def ready_for_b():
        return page.reader_panel.title_label.text() == "b.txt"

    qtbot.waitUntil(ready_for_b, timeout=3000)
    assert page.reader_panel.current_mode in {"message", "text"}
    assert "b.txt" in page.reader_panel.title_label.text()


def test_reader_shows_loading_or_settles_after_select(qtbot, tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * 100)
    resource = ResourceItem(name="big.txt", path=str(path), type="document", format="txt")
    project = ProjectDocument.new("P")
    project.resources = [resource]
    page = DataPage(project)
    qtbot.addWidget(page)

    page._set_selected_asset(resource)

    # Loading may flash, or the result may already be ready; either way not empty.
    qtbot.waitUntil(lambda: page.reader_panel.current_mode != "empty", timeout=3000)
    qtbot.waitUntil(
        lambda: page.reader_panel.current_mode in {"text", "message", "loading"},
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: page.reader_panel.current_mode in {"text", "message"},
        timeout=3000,
    )
    assert page.reader_panel.title_label.text() in {"big.txt", "加载中… big.txt"}


def test_stale_generation_discarded(qtbot, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    resource = ResourceItem(name="notes.txt", path=str(path), type="document", format="txt")
    controller = PreviewRequestController()
    received: list[object] = []
    controller.result_ready.connect(received.append)

    controller.request(resource)
    first_generation = controller.generation
    # Bump generation without waiting so the in-flight job is stale.
    controller._generation = first_generation + 1

    # Allow the worker to finish; stale result must not be emitted.
    qtbot.wait(200)
    assert received == []

    controller.request(None)
    assert len(received) == 1
    assert received[0].mode == "empty"
