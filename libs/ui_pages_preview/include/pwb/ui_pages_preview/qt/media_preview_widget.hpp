#pragma once

// Port of paleo_workbench/ui/pages/media_preview_widget.py (UI-07):
// inline audio/video player. QMediaPlayer/QAudioOutput/QVideoWidget are
// lazily constructed on first media use — the widget itself is cheap and
// has no multimedia side effects (SIGSEGV-avoidance discipline #951).
// When Qt6::Multimedia is absent the first ensure shows the
// "音频预览不可用" fallback — same degraded path as Python.
//
// The multimedia members are forward-declared so this header is identical
// across build configurations; the .cpp compiles them under
// PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA / _HAVE_MULTIMEDIAWIDGETS.

#include <QString>
#include <QWidget>
#include <vector>

class QAudioOutput;
class QHBoxLayout;
class QVBoxLayout;
class QLabel;
class QMediaPlayer;
class QPushButton;
class QSlider;
class QVideoWidget;

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class MediaPreviewWidget : public QWidget {
    Q_OBJECT
public:
    explicit MediaPreviewWidget(QWidget* parent = nullptr);

    void apply_settings(const PreviewSettings& settings);

    // Stop playback when leaving the media preview (asset switch/loading).
    void stop();

    // set_media_path(path): lazy-ensures the player, then sets the source.
    void set_media_path(const QString& path);

    // Public seam for tests to trigger lazy creation explicitly.
    bool ensure_player();

    bool autoplay() const { return autoplay_; }
    void set_autoplay(bool enabled) { autoplay_ = enabled; }

    QLabel* status_label() const { return status_label_; }
    QPushButton* play_button() const { return play_btn_; }
    QSlider* position_slider() const { return position_slider_; }
    QSlider* volume_slider() const { return volume_slider_; }
    QLabel* time_label() const { return time_label_; }
    QLabel* path_label() const { return path_label_; }
    QString current_path() const { return current_path_; }
    bool player_created() const { return player_ != nullptr; }

protected:
    void hideEvent(QHideEvent* event) override;

private:
    void toggle_play();
    void on_position(qint64 ms);
    void on_duration(qint64 ms);
    void on_error();
    void on_status_changed(int status);
    void show_fallback();
    void restore_controls();
    void update_time(qint64 pos, qint64 dur);

    QMediaPlayer* player_ = nullptr;
    QAudioOutput* audio_out_ = nullptr;
    QWidget* video_widget_ = nullptr;
    QString current_path_;
    bool autoplay_ = false;
    bool player_init_attempted_ = false;
    // tri-state: unknown / available / unavailable (nullopt semantics).
    enum class PlayerAvailability : int { unknown, available, unavailable };
    PlayerAvailability player_available_ = PlayerAvailability::unknown;

    QVBoxLayout* main_layout_ = nullptr;
    QLabel* status_label_ = nullptr;
    QPushButton* play_btn_ = nullptr;
    QSlider* position_slider_ = nullptr;
    QLabel* time_label_ = nullptr;
    QLabel* volume_label_ = nullptr;
    QSlider* volume_slider_ = nullptr;
    QLabel* path_label_ = nullptr;
    std::vector<QWidget*> control_widgets_;
};

}  // namespace pwb::ui_pages_preview
