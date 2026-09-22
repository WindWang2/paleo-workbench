from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from paleo_workbench.tokens import SPACE_2

# QtMultimedia is imported lazily, on first actual media preview use: the
# import itself loads the media backend plugins (ffmpeg/pipewire probing),
# the prime suspect for the #951 SIGSEGV on no-audio runners. Loading the
# preview facade must not initialize it.
_media_classes: tuple | None = None

_MEDIA_ATTRS = ("QMediaPlayer", "QAudioOutput", "QVideoWidget")


def _load_media_classes() -> tuple:
    """Return cached ``(QMediaPlayer, QAudioOutput, QVideoWidget)`` classes.

    Entries are None where PySide6 ships without the module. The failed
    lookup is cached too — same semantics as the old module-level try/except.
    """
    global _media_classes
    if _media_classes is None:
        player = audio = video = None
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            player, audio = QMediaPlayer, QAudioOutput
        except ImportError:  # pragma: no cover
            pass
        try:
            from PySide6.QtMultimediaWidgets import QVideoWidget

            video = QVideoWidget
        except ImportError:  # pragma: no cover
            pass
        _media_classes = (player, audio, video)
    return _media_classes


def __getattr__(name):
    """PEP 562 lazy re-exports: ``media_preview_widget.QMediaPlayer`` and
    friends keep working for importers without loading the backend."""
    if name in _MEDIA_ATTRS:
        return _load_media_classes()[_MEDIA_ATTRS.index(name)]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class MediaPreviewWidget(QWidget):
    """Inline audio/video player (wav/mp3/flac + mp4/mov/webm/mkv/avi). QMediaPlayer is UI-thread only.

    QMediaPlayer/QAudioOutput are lazily constructed on first media use to
    avoid initializing QtMultimedia in headless/offscreen CI (SIGSEGV under
    QMediaPlayer on no-audio runners). Construction of this widget itself is
    cheap and has no multimedia side effects.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player: object | None = None
        self._audio_out: object | None = None
        self._video_widget: QWidget | None = None
        self._current_path = ""
        self.autoplay = False
        self._player_init_attempted = False
        self._player_available: bool | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_2)
        self._main_layout = layout
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

        # Lazy: do not touch QtMultimedia backends here. The play button is
        # disabled until a real media path is provided and the player is
        # successfully created. If QtMultimedia is entirely unavailable, the
        # first ensure will show the unavailable fallback.
        self.play_btn.setEnabled(False)

    # -- lazy initialization -----------------------------------------------

    def _ensure_player(self) -> bool:
        """Create QMediaPlayer/QAudioOutput/QVideoWidget on first use.

        Returns True if a usable player exists after the call, False if the
        backend is unavailable (fallback message shown).
        """
        if self._player is not None:
            return True
        if self._player_init_attempted and self._player_available is False:
            return False
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets

        player_cls, audio_cls, video_cls = _load_media_classes()
        # Test-seam compatibility: explicit overrides on the facade win.
        player_cls = getattr(preview_widgets, "QMediaPlayer", player_cls)
        audio_cls = getattr(preview_widgets, "QAudioOutput", audio_cls)
        video_cls = getattr(preview_widgets, "QVideoWidget", video_cls)

        if player_cls is None:
            self._player_init_attempted = True
            self._player_available = False
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return False

        try:
            self._player = player_cls(self) if player_cls is not None else None
        except Exception:  # pragma: no cover
            self._player = None
        try:
            self._audio_out = audio_cls(self) if audio_cls is not None else None
        except Exception:  # pragma: no cover
            self._audio_out = None

        if self._player is None:
            self._player_init_attempted = True
            self._player_available = False
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return False

        if self._player is not None and self._audio_out is not None:
            try:
                self._player.setAudioOutput(self._audio_out)
            except Exception:
                pass
            try:
                self._audio_out.setVolume(self.volume_slider.value() / 100.0)
            except Exception:
                pass

        # Attach video surface — QVideoWidget gives aspect-correct resize for free.
        if self._player is not None and video_cls is not None:
            try:
                self._video_widget = video_cls(self)
                if hasattr(self._player, "setVideoOutput"):
                    self._player.setVideoOutput(self._video_widget)
                # Insert video widget after status label (index 1) to match
                # original eager layout order.
                self._main_layout.insertWidget(1, self._video_widget, 1)
            except Exception:  # pragma: no cover
                self._video_widget = None

        # Wire signals once
        try:
            self.position_slider.sliderMoved.connect(self._player.setPosition)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self.volume_slider.valueChanged.connect(
                lambda v: self._audio_out.setVolume(v / 100.0) if self._audio_out is not None else None  # type: ignore[union-attr]
            )
        except Exception:
            pass
        try:
            self._player.positionChanged.connect(self._on_position)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self._player.durationChanged.connect(self._on_duration)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self._player.errorOccurred.connect(self._on_error)  # type: ignore[union-attr]
        except Exception:
            pass
        try:
            if hasattr(self._player, "mediaStatusChanged"):
                self._player.mediaStatusChanged.connect(self._on_status_changed)  # type: ignore[union-attr]
        except Exception:
            pass

        self._player_init_attempted = True
        self._player_available = True
        return True

    def ensure_player(self) -> bool:
        """Public seam for tests to trigger lazy creation explicitly."""
        return self._ensure_player()

    def apply_settings(self, settings) -> None:
        self.autoplay = settings.media_autoplay
        self.volume_slider.setValue(settings.media_volume)

    def stop(self) -> None:
        """Stop playback when leaving the media preview (asset switch / loading)."""
        if self._player is None:
            return
        try:
            self._player.stop()  # type: ignore[union-attr]
        except Exception:
            pass
        self.play_btn.setText("播放")

    def hideEvent(self, event) -> None:  # noqa: N802
        # Stop audio when the widget is hidden (page switch / tab change) so a
        # previewed clip does not keep playing after the user navigates away.
        self.stop()
        super().hideEvent(event)

    def set_media_path(self, path: str) -> None:
        from PySide6.QtCore import QUrl

        if not self._ensure_player():
            # Backend unavailable — unavailable message already set by ensure.
            return
        assert self._player is not None
        self._current_path = str(path or "")
        self._restore_controls()
        self.stop()
        if not path:
            self.status_label.setText("未加载")
            self.play_btn.setEnabled(False)
            return
        try:
            self._player.setSource(QUrl.fromLocalFile(path))  # type: ignore[union-attr]
        except Exception:
            pass
        self.status_label.setText("就绪")
        self.play_btn.setEnabled(True)
        self.play_btn.setText("播放")
        if self.autoplay:
            try:
                self._player.play()  # type: ignore[union-attr]
            except Exception:
                pass
            self.play_btn.setText("暂停")

    def _toggle_play(self) -> None:
        if self._player is None:
            # If user clicks before any media was loaded, try to ensure player
            # but still no-op until a valid source exists.
            if not self._ensure_player():
                return
            if not self._current_path:
                return
        state = self._player.playbackState()  # type: ignore[union-attr]
        playback_enum = getattr(type(self._player), "PlaybackState", None)
        playing_state = getattr(playback_enum, "PlayingState", None) if playback_enum is not None else None
        if playing_state is not None:
            is_playing = state == playing_state
        else:
            # Qt enum fallback: Stopped=0, Playing=1, Paused=2.
            try:
                is_playing = int(state) == 1  # type: ignore[arg-type]
            except Exception:
                is_playing = False
        if is_playing:
            self._player.pause()  # type: ignore[union-attr]
            self.play_btn.setText("播放")
        else:
            self._player.play()  # type: ignore[union-attr]
            self.play_btn.setText("暂停")

    def _on_position(self, ms: int) -> None:
        self.position_slider.setValue(ms)
        if self._player is not None:
            try:
                self._update_time(ms, self._player.duration())  # type: ignore[union-attr]
            except Exception:
                pass

    def _on_duration(self, ms: int) -> None:
        self.position_slider.setRange(0, ms)
        if self._player is not None:
            try:
                self._update_time(self._player.position(), ms)  # type: ignore[union-attr]
            except Exception:
                pass

    def _on_error(self, _error, msg: str = "") -> None:  # noqa: ARG002
        self._show_fallback()

    def _on_status_changed(self, status) -> None:
        if self._player is None:
            return
        # Detect InvalidMedia without hard dependency on enum import.
        # Support both real Qt enum and test fakes: compare by value and identity.
        invalid_candidates: list[object] = []
        for src in (self._player, _load_media_classes()[0]):
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
                self._player.stop()  # type: ignore[union-attr]
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
