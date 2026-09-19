#include <pwb/ui_pages_preview/qt/media_preview_widget.hpp>

#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSlider>
#include <QUrl>
#include <QVBoxLayout>

#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
#include <QAudioOutput>
#include <QMediaPlayer>
#endif
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIAWIDGETS)
#include <QVideoWidget>
#endif

#include <pwb/ui_pages_preview/media_time.hpp>
#include <pwb/ui_pages_preview/preview_settings.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

MediaPreviewWidget::MediaPreviewWidget(QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(qt_internal::SPACE_2);
    main_layout_ = layout;
    status_label_ = new QLabel(QStringLiteral("未加载"));
    status_label_->setAlignment(Qt::AlignCenter);
    layout->addWidget(status_label_);

    auto* controls = new QHBoxLayout();
    play_btn_ = new QPushButton(QStringLiteral("播放"));
    play_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(play_btn_, &QPushButton::clicked, this,
            [this] { toggle_play(); });
    controls->addWidget(play_btn_);
    position_slider_ = new QSlider(Qt::Horizontal);
    controls->addWidget(position_slider_, 1);
    time_label_ = new QLabel(QStringLiteral("00:00 / 00:00"));
    controls->addWidget(time_label_);
    layout->addLayout(controls);

    auto* vol = new QHBoxLayout();
    volume_label_ = new QLabel(QStringLiteral("音量"));
    vol->addWidget(volume_label_);
    volume_slider_ = new QSlider(Qt::Horizontal);
    volume_slider_->setRange(0, 100);
    volume_slider_->setValue(80);
    vol->addWidget(volume_slider_, 1);
    layout->addLayout(vol);

    path_label_ = new QLabel(QString());
    path_label_->setWordWrap(true);
    path_label_->setTextInteractionFlags(Qt::TextSelectableByMouse);
    path_label_->hide();
    layout->addWidget(path_label_);
    layout->addStretch();

    // Controls to hide on fallback (player controls)
    control_widgets_ = {play_btn_, position_slider_, time_label_,
                        volume_label_, volume_slider_};

    // Lazy: do not touch QtMultimedia backends here. The play button is
    // disabled until a real media path is provided and the player is
    // successfully created. If QtMultimedia is entirely unavailable, the
    // first ensure shows the unavailable fallback.
    play_btn_->setEnabled(false);
}

// -- lazy initialization ----------------------------------------------------

bool MediaPreviewWidget::ensure_player() {
    // Create QMediaPlayer/QAudioOutput/QVideoWidget on first use.
    if (player_ != nullptr) {
        return true;
    }
    if (player_init_attempted_ &&
        player_available_ == PlayerAvailability::unavailable) {
        return false;
    }
#if !defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
    // Backend unavailable — same fallback as Python's player_cls None path.
    player_init_attempted_ = true;
    player_available_ = PlayerAvailability::unavailable;
    status_label_->setText(QStringLiteral("音频预览不可用"));
    play_btn_->setEnabled(false);
    return false;
#else
    player_ = new QMediaPlayer(this);
    audio_out_ = new QAudioOutput(this);

    player_->setAudioOutput(audio_out_);
    audio_out_->setVolume(volume_slider_->value() / 100.0);

    // Attach video surface — QVideoWidget gives aspect-correct resize.
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIAWIDGETS)
    auto* video = new QVideoWidget(this);
    player_->setVideoOutput(video);
    video_widget_ = video;
    // Insert video widget after status label (index 1) to match the
    // original eager layout order.
    main_layout_->insertWidget(1, video_widget_, 1);
#endif

    // Wire signals once
    connect(position_slider_, &QSlider::sliderMoved, player_,
            &QMediaPlayer::setPosition);
    connect(volume_slider_, &QSlider::valueChanged, audio_out_,
            [this](int v) {
                if (audio_out_ != nullptr) {
                    audio_out_->setVolume(v / 100.0);
                }
            });
    connect(player_, &QMediaPlayer::positionChanged, this,
            [this](qint64 ms) { on_position(ms); });
    connect(player_, &QMediaPlayer::durationChanged, this,
            [this](qint64 ms) { on_duration(ms); });
    connect(player_, &QMediaPlayer::errorOccurred, this,
            [this](QMediaPlayer::Error, const QString&) { on_error(); });
    connect(player_, &QMediaPlayer::mediaStatusChanged, this,
            [this](QMediaPlayer::MediaStatus status) {
                on_status_changed(static_cast<int>(status));
            });

    player_init_attempted_ = true;
    player_available_ = PlayerAvailability::available;
    return true;
#endif
}

void MediaPreviewWidget::apply_settings(const PreviewSettings& settings) {
    autoplay_ = settings.media_autoplay;
    volume_slider_->setValue(settings.media_volume);
}

void MediaPreviewWidget::stop() {
    if (player_ == nullptr) {
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
    player_->stop();
#endif
    play_btn_->setText(QStringLiteral("播放"));
}

void MediaPreviewWidget::hideEvent(QHideEvent* event) {
    // Stop audio when the widget is hidden (page switch / tab change) so a
    // previewed clip does not keep playing after the user navigates away.
    stop();
    QWidget::hideEvent(event);
}

void MediaPreviewWidget::set_media_path(const QString& path) {
    if (!ensure_player()) {
        // Backend unavailable — unavailable message already set by ensure.
        return;
    }
    current_path_ = path;
    restore_controls();
    stop();
    if (path.isEmpty()) {
        status_label_->setText(QStringLiteral("未加载"));
        play_btn_->setEnabled(false);
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
    player_->setSource(QUrl::fromLocalFile(path));
#endif
    status_label_->setText(QStringLiteral("就绪"));
    play_btn_->setEnabled(true);
    play_btn_->setText(QStringLiteral("播放"));
    if (autoplay_) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
        player_->play();
#endif
        play_btn_->setText(QStringLiteral("暂停"));
    }
}

void MediaPreviewWidget::toggle_play() {
    if (player_ == nullptr) {
        // If user clicks before any media was loaded, try to ensure player
        // but still no-op until a valid source exists.
        if (!ensure_player()) {
            return;
        }
        if (current_path_.isEmpty()) {
            return;
        }
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
    const bool is_playing =
        player_->playbackState() == QMediaPlayer::PlayingState;
    if (is_playing) {
        player_->pause();
        play_btn_->setText(QStringLiteral("播放"));
    } else {
        player_->play();
        play_btn_->setText(QStringLiteral("暂停"));
    }
#endif
}

void MediaPreviewWidget::on_position(qint64 ms) {
    position_slider_->setValue(static_cast<int>(ms));
    if (player_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
        update_time(ms, player_->duration());
#else
        update_time(ms, 0);
#endif
    }
}

void MediaPreviewWidget::on_duration(qint64 ms) {
    position_slider_->setRange(0, static_cast<int>(ms));
    if (player_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
        update_time(player_->position(), ms);
#else
        update_time(0, ms);
#endif
    }
}

void MediaPreviewWidget::on_error() {
    show_fallback();
}

void MediaPreviewWidget::on_status_changed(int status) {
    if (player_ == nullptr) {
        return;
    }
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
    if (status == static_cast<int>(QMediaPlayer::InvalidMedia)) {
        show_fallback();
    }
#else
    Q_UNUSED(status);
#endif
}

void MediaPreviewWidget::show_fallback() {
    if (player_ != nullptr) {
#if defined(PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA)
        player_->stop();
#endif
    }
    for (QWidget* w : control_widgets_) {
        w->hide();
    }
    if (video_widget_ != nullptr) {
        video_widget_->hide();
    }
    const QString filename =
        current_path_.isEmpty() ? QString() : QFileInfo(current_path_).fileName();
    if (!filename.isEmpty()) {
        status_label_->setText(
            QStringLiteral("缺少系统解码器，无法播放：%1").arg(filename));
    } else {
        status_label_->setText(QStringLiteral("缺少系统解码器，无法播放"));
    }
    status_label_->setTextInteractionFlags(Qt::TextSelectableByMouse);
    status_label_->setWordWrap(true);
    path_label_->setText(current_path_);
    // Full path selectable/copyable
    path_label_->setTextInteractionFlags(Qt::TextSelectableByMouse);
    if (!current_path_.isEmpty()) {
        path_label_->show();
    } else {
        path_label_->hide();
    }
    play_btn_->setEnabled(false);
    play_btn_->setText(QStringLiteral("播放"));
}

void MediaPreviewWidget::restore_controls() {
    for (QWidget* w : control_widgets_) {
        w->show();
    }
    if (video_widget_ != nullptr) {
        video_widget_->show();
    }
    path_label_->hide();
    path_label_->setText(QString());
    status_label_->setTextInteractionFlags(Qt::NoTextInteraction);
    status_label_->setWordWrap(false);
    status_label_->setAlignment(Qt::AlignCenter);
}

void MediaPreviewWidget::update_time(qint64 pos, qint64 dur) {
    time_label_->setText(QString::fromStdString(
        media_time_label(pos, dur)));
}

}  // namespace pwb::ui_pages_preview
