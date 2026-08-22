from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover
    QAudioOutput = None
    QMediaPlayer = None

try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:  # pragma: no cover
    QVideoWidget = None

from paleo_workbench.tokens import SPACE_2


class MediaPreviewWidget(QWidget):
    """Inline audio/video player (wav/mp3/flac + mp4/mov/webm/mkv/avi). QMediaPlayer is UI-thread only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets
        player_cls = getattr(preview_widgets, "QMediaPlayer", QMediaPlayer)
        audio_cls = getattr(preview_widgets, "QAudioOutput", QAudioOutput)
        video_cls = getattr(preview_widgets, "QVideoWidget", QVideoWidget)
        self._player = player_cls(self) if player_cls is not None else None
        self._audio_out = audio_cls(self) if audio_cls is not None else None
        self._video_widget: QWidget | None = None
        self._current_path = ""
        self.autoplay = False
        if self._player is not None and self._audio_out is not None:
            self._player.setAudioOutput(self._audio_out)
            self._audio_out.setVolume(0.8)
        # Attach video surface — QVideoWidget gives aspect-correct resize for free.
        if self._player is not None and video_cls is not None:
            try:
                self._video_widget = video_cls(self)
                # setVideoOutput is available on QMediaPlayer (Qt6)
                if hasattr(self._player, "setVideoOutput"):
                    self._player.setVideoOutput(self._video_widget)
            except Exception:  # pragma: no cover
                self._video_widget = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_2)
        self.status_label = QLabel("未加载")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        if self._video_widget is not None:
            layout.addWidget(self._video_widget, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.play_btn.setObjectName("SecondaryButton")
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        controls.addWidget(self.position_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        vol = QHBoxLayout()
        self._volume_label = QLabel("音量")
        vol.addWidget(self._volume_label)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        vol.addWidget(self.volume_slider, 1)
        layout.addLayout(vol)

        self._path_label = QLabel("")
        self._path_label.setWordWrap(True)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path_label.hide()
        layout.addWidget(self._path_label)
        layout.addStretch()

        # Controls to hide on fallback (player controls)
        self._control_widgets: list[QWidget] = [
            self.play_btn,
            self.position_slider,
            self.time_label,
            self._volume_label,
            self.volume_slider,
        ]

        if self._player is None:
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            if self._video_widget is not None:
                self._video_widget.hide()
            return

        self.position_slider.sliderMoved.connect(self._player.setPosition)
        self.volume_slider.valueChanged.connect(
            lambda v: self._audio_out.setVolume(v / 100.0) if self._audio_out is not None else None
        )
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.errorOccurred.connect(self._on_error)
        # InvalidMedia is emitted via mediaStatusChanged
        if hasattr(self._player, "mediaStatusChanged"):
            self._player.mediaStatusChanged.connect(self._on_status_changed)

    def apply_settings(self, settings) -> None:
        self.autoplay = settings.media_autoplay
        self.volume_slider.setValue(settings.media_volume)

    def stop(self) -> None:
        """Stop playback when leaving the media preview (asset switch / loading)."""
        if self._player is None:
            return
        self._player.stop()
        self.play_btn.setText("播放")

    def hideEvent(self, event) -> None:  # noqa: N802
        # Stop audio when the widget is hidden (page switch / tab change) so a
        # previewed clip does not keep playing after the user navigates away.
        self.stop()
        super().hideEvent(event)

    def set_media_path(self, path: str) -> None:
        from PySide6.QtCore import QUrl

        if self._player is None:
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return
        self._current_path = str(path or "")
        self._restore_controls()
        self.stop()
        if not path:
            self.status_label.setText("未加载")
            self.play_btn.setEnabled(False)
            return
        self._player.setSource(QUrl.fromLocalFile(path))
        self.status_label.setText("就绪")
        self.play_btn.setEnabled(True)
        self.play_btn.setText("播放")
        if self.autoplay:
            self._player.play()
            self.play_btn.setText("暂停")

    def _toggle_play(self) -> None:
        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.play_btn.setText("播放")
        else:
            self._player.play()
            self.play_btn.setText("暂停")

    def _on_position(self, ms: int) -> None:
        self.position_slider.setValue(ms)
        if self._player is not None:
            self._update_time(ms, self._player.duration())

    def _on_duration(self, ms: int) -> None:
        self.position_slider.setRange(0, ms)
        if self._player is not None:
            self._update_time(self._player.position(), ms)

    def _on_error(self, _error, msg: str = "") -> None:  # noqa: ARG002
        self._show_fallback()

    def _on_status_changed(self, status) -> None:
        if self._player is None:
            return
        # Detect InvalidMedia without hard dependency on enum import.
        # Support both real Qt enum and test fakes: compare by value and identity.
        invalid_candidates: list[object] = []
        for src in (self._player, QMediaPlayer):
            if src is None:
                continue
            try:
                ms = getattr(src, "MediaStatus", None)
                if ms is not None:
                    invalid_candidates.append(getattr(ms, "InvalidMedia"))
            except Exception:
                pass
            try:
                # instance attribute (e.g. FakePlayer().MediaStatus)
                ms2 = getattr(getattr(src, "MediaStatus", None), "InvalidMedia", None)
                if ms2 is not None and ms2 not in invalid_candidates:
                    invalid_candidates.append(ms2)
            except Exception:
                pass
        # Also try via type(self._player)
        try:
            ms = getattr(type(self._player), "MediaStatus", None)
            if ms is not None:
                v = getattr(ms, "InvalidMedia", None)
                if v is not None and v not in invalid_candidates:
                    invalid_candidates.append(v)
        except Exception:
            pass
        for invalid in invalid_candidates:
            # Direct equality
            if status == invalid:
                self._show_fallback()
                return
            # Value-based equality for cross-enum fake vs real
            try:
                if int(status) == int(invalid):  # type: ignore[arg-type]
                    self._show_fallback()
                    return
            except Exception:
                pass
            try:
                sv = getattr(status, "value", status)
                iv = getattr(invalid, "value", invalid)
                if sv == iv:
                    self._show_fallback()
                    return
            except Exception:
                pass

    def _show_fallback(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass
        for w in self._control_widgets:
            w.hide()
        if self._video_widget is not None:
            self._video_widget.hide()
        filename = Path(self._current_path).name if self._current_path else ""
        if filename:
            self.status_label.setText(f"缺少系统解码器，无法播放：{filename}")
        else:
            self.status_label.setText("缺少系统解码器，无法播放")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setWordWrap(True)
        self._path_label.setText(self._current_path)
        # Full path selectable/copyable
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if self._current_path:
            self._path_label.show()
        else:
            self._path_label.hide()
        self.play_btn.setEnabled(False)
        self.play_btn.setText("播放")

    def _restore_controls(self) -> None:
        for w in self._control_widgets:
            w.show()
        if self._video_widget is not None:
            self._video_widget.show()
        self._path_label.hide()
        self._path_label.setText("")
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.status_label.setWordWrap(False)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _update_time(self, pos: int, dur: int) -> None:
        self.time_label.setText(f"{self._ms(pos)} / {self._ms(dur)}")

    @staticmethod
    def _ms(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"
