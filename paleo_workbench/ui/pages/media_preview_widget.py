from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover
    QAudioOutput = None
    QMediaPlayer = None

from paleo_workbench.tokens import SPACE_2


class MediaPreviewWidget(QWidget):
    """Inline audio player (wav/mp3/flac). QMediaPlayer is UI-thread only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets
        player_cls = getattr(preview_widgets, "QMediaPlayer", QMediaPlayer)
        audio_cls = getattr(preview_widgets, "QAudioOutput", QAudioOutput)
        self._player = player_cls(self) if player_cls is not None else None
        self._audio_out = audio_cls(self) if audio_cls is not None else None
        self.autoplay = False
        if self._player is not None and self._audio_out is not None:
            self._player.setAudioOutput(self._audio_out)
            self._audio_out.setVolume(0.8)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_2)
        self.status_label = QLabel("未加载")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

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
        vol.addWidget(QLabel("音量"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        vol.addWidget(self.volume_slider, 1)
        layout.addLayout(vol)
        layout.addStretch()

        if self._player is None:
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return

        self.position_slider.sliderMoved.connect(self._player.setPosition)
        self.volume_slider.valueChanged.connect(
            lambda v: self._audio_out.setVolume(v / 100.0)
        )
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.errorOccurred.connect(self._on_error)

    def apply_settings(self, settings) -> None:
        self.autoplay = settings.media_autoplay
        self.volume_slider.setValue(settings.media_volume)

    def stop(self) -> None:
        """Stop playback when leaving the media preview (asset switch / loading)."""
        if self._player is None:
            return
        self._player.stop()
        self.play_btn.setText("播放")

    def set_media_path(self, path: str) -> None:
        from PySide6.QtCore import QUrl

        if self._player is None:
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return
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
        self._update_time(ms, self._player.duration())

    def _on_duration(self, ms: int) -> None:
        self.position_slider.setRange(0, ms)
        self._update_time(self._player.position(), ms)

    def _on_error(self, _error, msg: str) -> None:
        self.status_label.setText("无法播放此格式（缺少解码器）")
        self.play_btn.setEnabled(False)

    def _update_time(self, pos: int, dur: int) -> None:
        self.time_label.setText(f"{self._ms(pos)} / {self._ms(dur)}")

    @staticmethod
    def _ms(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"
