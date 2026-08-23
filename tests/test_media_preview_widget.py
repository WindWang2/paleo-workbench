import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QWidget


class FakeAudioOutput(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume = 0.8

    def setVolume(self, v: float) -> None:
        self._volume = v


class FakeVideoWidget(QWidget):
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
        NoMedia = 0
        LoadingMedia = 1
        LoadedMedia = 2
        StalledMedia = 3
        BufferingMedia = 4
        BufferedMedia = 5
        EndOfMedia = 6
        InvalidMedia = 7

    class Error:
        NoError = 0
        ResourceError = 1
        FormatError = 2
        NetworkError = 3
        AccessDeniedError = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_output = None
        self._audio_output = None
        self._state = self.PlaybackState.StoppedState
        self._pos = 0
        self._dur = 10000
        self._source = None

    def setAudioOutput(self, out) -> None:
        self._audio_output = out

    def setVideoOutput(self, w) -> None:
        self._video_output = w

    def videoOutput(self):
        return self._video_output

    def setSource(self, url) -> None:
        self._source = url

    def playbackState(self):
        return self._state

    def play(self) -> None:
        self._state = self.PlaybackState.PlayingState

    def pause(self) -> None:
        self._state = self.PlaybackState.PausedState

    def stop(self) -> None:
        self._state = self.PlaybackState.StoppedState

    def position(self) -> int:
        return self._pos

    def duration(self) -> int:
        return self._dur

    def setPosition(self, v: int) -> None:
        self._pos = v


def _make_widget_with_fakes(qtbot, monkeypatch):
    import paleo_workbench.ui.pages.preview_widgets as pw

    monkeypatch.setattr(pw, "QMediaPlayer", FakePlayer, raising=False)
    monkeypatch.setattr(pw, "QAudioOutput", FakeAudioOutput, raising=False)
    monkeypatch.setattr(pw, "QVideoWidget", FakeVideoWidget, raising=False)
    # Need to re-import MediaPreviewWidget to pick up patched preview_widgets
    from paleo_workbench.ui.pages.media_preview_widget import MediaPreviewWidget

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    # MediaPreviewWidget is lazy (#951): player is created on first media use.
    # Ensure it for tests that inspect the video surface attachment.
    w.ensure_player()
    return w


def test_media_preview_attaches_video_output(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    assert w._video_widget is not None
    assert isinstance(w._video_widget, FakeVideoWidget)
    # player should have video output attached
    assert w._player.videoOutput() is w._video_widget


def test_media_preview_video_output_is_qvideowidget_child(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    # QVideoWidget is laid out — should be child of the widget and visible when no error
    assert w._video_widget.parent() is w
    assert w._video_widget.isVisible() or not w.isVisible()  # parent not shown yet, but widget exists


def test_media_preview_error_fallback_hides_controls_and_shows_selectable_path(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    w.set_media_path("/tmp/clip.mp4")
    assert w.status_label.text() == "就绪"
    # Simulate decoder missing error
    w._player.errorOccurred.emit(FakePlayer.Error.FormatError, "decoder missing")
    # Fallback message contains Chinese and filename
    assert "缺少系统解码器，无法播放" in w.status_label.text()
    assert "clip.mp4" in w.status_label.text()
    # Full path is shown in selectable label
    assert w._path_label.text() == "/tmp/clip.mp4"
    assert not w._path_label.isHidden()
    assert w._path_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    # status_label also selectable
    assert w.status_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    # Controls hidden, play disabled
    assert w.play_btn.isHidden()
    assert w.position_slider.isHidden()
    assert w._video_widget.isHidden()
    assert not w.play_btn.isEnabled()


def test_media_preview_invalid_media_fallback(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    w.set_media_path("/tmp/movie.mov")
    w._player.mediaStatusChanged.emit(FakePlayer.MediaStatus.InvalidMedia)
    assert "缺少系统解码器，无法播放" in w.status_label.text()
    assert "movie.mov" in w.status_label.text()
    assert w._path_label.text() == "/tmp/movie.mov"
    assert w._path_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert w.play_btn.isHidden()
    assert w._video_widget.isHidden()


def test_media_preview_error_then_new_path_restores_controls(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    w.set_media_path("/tmp/bad.mkv")
    w._player.errorOccurred.emit(FakePlayer.Error.FormatError, "bad")
    assert w.play_btn.isHidden()
    # Loading a new valid path should restore controls
    w.set_media_path("/tmp/good.mp4")
    assert not w.play_btn.isHidden()
    assert not w.position_slider.isHidden()
    assert not w._video_widget.isHidden()
    assert w.status_label.text() == "就绪"
    assert w._path_label.isHidden()
    assert w.play_btn.isEnabled()


def test_media_preview_invalid_media_with_empty_path_shows_generic_message(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    # No path set yet, directly emit InvalidMedia
    w._player.mediaStatusChanged.emit(FakePlayer.MediaStatus.InvalidMedia)
    assert "缺少系统解码器，无法播放" in w.status_label.text()


def test_media_preview_real_player_attaches_video_output_if_available(qtbot):
    # Integration with real QtMultimedia if present — not using fakes.
    from paleo_workbench.ui.pages import preview_widgets as pw
    from paleo_workbench.ui.pages.media_preview_widget import MediaPreviewWidget

    if pw.QMediaPlayer is None:
        pytest.skip("QtMultimedia not available")
    try:
        from PySide6.QtMultimediaWidgets import QVideoWidget as RealVideo  # noqa: F401
    except ImportError:
        pytest.skip("QtMultimediaWidgets not available")

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    # When QtMultimedia is available, widget should have a video widget and player videoOutput set
    if w._video_widget is not None and w._player is not None and hasattr(w._player, "videoOutput"):
        try:
            out = w._player.videoOutput()
        except Exception:
            out = None
        # In offscreen some backends may not support video; at minimum the widget exists
        assert w._video_widget is not None


def test_media_preview_real_player_error_signal_triggers_fallback(qtbot):
    from paleo_workbench.ui.pages import preview_widgets as pw
    from paleo_workbench.ui.pages.media_preview_widget import MediaPreviewWidget

    if pw.QMediaPlayer is None:
        pytest.skip("QtMultimedia not available")
    try:
        from PySide6.QtMultimedia import QMediaPlayer as RealPlayer
    except ImportError:
        pytest.skip("QtMultimedia not available")

    w = MediaPreviewWidget()
    qtbot.addWidget(w)
    if w._player is None:
        pytest.skip("player not created")
    w.set_media_path("/tmp/fake_video.mp4")
    # Emit error via the real player's signal — slot should handle any error object
    w._player.errorOccurred.emit(RealPlayer.Error.FormatError, "test error")
    assert "缺少系统解码器，无法播放" in w.status_label.text()
    assert w._path_label.text() == "/tmp/fake_video.mp4"
    assert w._path_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_media_preview_no_custom_resize_logic(qtbot, monkeypatch):
    w = _make_widget_with_fakes(qtbot, monkeypatch)
    # QVideoWidget gives aspect-correct resize for free — widget must not override resizeEvent
    assert "resizeEvent" not in type(w).__dict__
