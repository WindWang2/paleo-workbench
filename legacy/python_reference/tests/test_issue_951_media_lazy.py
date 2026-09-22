"""Regression for #951: QMediaPlayer must be lazy, not created at app-shell startup."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget


class FakeAudioOutput(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def setVolume(self, v):  # noqa: ARG002
        pass


class FakePlayer(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    errorOccurred = Signal(object, str)
    mediaStatusChanged = Signal(object)

    class PlaybackState:
        StoppedState = 0
        PlayingState = 1
        PausedState = 2

    class MediaStatus:
        InvalidMedia = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self._audio = None

    def setAudioOutput(self, out):
        self._audio = out

    def setVideoOutput(self, w):  # noqa: ARG002
        pass

    def setSource(self, url):  # noqa: ARG002
        pass

    def playbackState(self):
        return self.PlaybackState.StoppedState

    def play(self):
        pass

    def pause(self):
        pass

    def stop(self):
        pass

    def position(self):
        return 0

    def duration(self):
        return 0

    def setPosition(self, v):  # noqa: ARG002
        pass


class FakeVideoWidget(QWidget):
    pass


def test_media_preview_widget_does_not_create_player_on_construction(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.preview_widgets as pw

    calls: list[int] = []

    orig_player = pw.QMediaPlayer

    class CountingPlayer(FakePlayer):
        def __init__(self, *a, **kw):
            calls.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(pw, "QMediaPlayer", CountingPlayer, raising=False)
    monkeypatch.setattr(pw, "QAudioOutput", FakeAudioOutput, raising=False)
    monkeypatch.setattr(pw, "QVideoWidget", FakeVideoWidget, raising=False)

    from paleo_workbench.ui.pages.media_preview_widget import MediaPreviewWidget

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    # Construction must not have instantiated QMediaPlayer (#951 mitigation)
    assert calls == [], "MediaPreviewWidget eagerly constructed QMediaPlayer"
    assert w._player is None

    # First real media use should create the player exactly once
    w.set_media_path("/tmp/clip.wav")
    assert len(calls) == 1
    assert w._player is not None
    assert w.status_label.text() == "就绪"

    # Second call must not recreate
    w.set_media_path("/tmp/other.wav")
    assert len(calls) == 1


def test_data_reader_panel_does_not_create_player_until_media_render(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.preview_widgets as pw
    from paleo_workbench.ui.pages.preview_provider import PreviewResult

    calls: list[int] = []

    class CountingPlayer(FakePlayer):
        def __init__(self, *a, **kw):
            calls.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(pw, "QMediaPlayer", CountingPlayer, raising=False)
    monkeypatch.setattr(pw, "QAudioOutput", FakeAudioOutput, raising=False)
    monkeypatch.setattr(pw, "QVideoWidget", FakeVideoWidget, raising=False)

    from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel

    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    assert calls == [], "DataReaderPanel startup must not create QMediaPlayer"
    assert panel.media_preview is None

    # Rendering a non-media preview must still not create player
    panel.render(PreviewResult(mode="text", title="t", text="hello"))
    assert calls == []
    assert panel.media_preview is None

    # Rendering media should lazily create exactly one player
    panel.render(PreviewResult(mode="media", title="clip", media_path="/tmp/a.wav"))
    assert len(calls) == 1
    assert panel.media_preview is not None
    assert panel.stack.currentWidget() is panel.media_preview


def test_app_shell_construction_does_not_create_player(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.preview_widgets as pw

    calls: list[int] = []

    class CountingPlayer(FakePlayer):
        def __init__(self, *a, **kw):
            calls.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(pw, "QMediaPlayer", CountingPlayer, raising=False)
    monkeypatch.setattr(pw, "QAudioOutput", FakeAudioOutput, raising=False)
    monkeypatch.setattr(pw, "QVideoWidget", FakeVideoWidget, raising=False)

    from paleo_workbench.ui.app_shell import AppShell

    shell = AppShell()
    qtbot.addWidget(shell)
    assert calls == [], "AppShell construction must not create QMediaPlayer (#951)"
    # Data page's media_preview is lazy now
    panel = shell.data_page_widget()
    # panel.media_preview attribute may be None until first media render
    if hasattr(panel, "media_preview"):
        assert panel.media_preview is None or getattr(panel.media_preview, "_player", None) is None
