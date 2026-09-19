#include <pwb/ui_pages_preview/qt/seismic_slice_preview_widget.hpp>

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QSlider>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/seismic_slice_spec.hpp>
#include <pwb/viz/seismic_volume.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

namespace {

QString type_label_qss() {
    return QStringLiteral("color: %1; font-weight: 500;")
        .arg(qt_internal::token("TEXT_SECONDARY"));
}

QString slider_qss() {
    return QStringLiteral(
        "QSlider::groove:horizontal {"
        " border: 1px solid %1; height: 6px; background: %2;"
        " border-radius: 3px; }"
        "QSlider::sub-page:horizontal { background: %3; border-radius: 3px; }"
        "QSlider::handle:horizontal {"
        " background: %4; border: 2px solid %3; width: 14px; height: 14px;"
        " margin-top: -5px; margin-bottom: -5px; border-radius: 7px; }"
        "QSlider::handle:horizontal:hover { background: %5; border-color: %5; }")
        .arg(qt_internal::token("BORDER"), qt_internal::token("BG_SEARCH"),
             qt_internal::token("PRIMARY"), qt_internal::token("ON_PRIMARY"),
             qt_internal::token("PRIMARY_HOVER"));
}

QString index_label_qss() {
    return QStringLiteral(
        "color: %1; font-family: monospace; font-weight: 500;")
        .arg(qt_internal::token("TEXT_SECONDARY"));
}

QString image_label_qss() {
    return QStringLiteral(
        "border: 1px solid %1; border-radius: %2px; background: %3;")
        .arg(qt_internal::token("BORDER"))
        .arg(qt_internal::RADIUS_BUTTON)
        .arg(qt_internal::token("BG_SEARCH"));
}

pwb::viz::VolumeAxis combo_axis(int combo_index) {
    // Combo index == volume axis index (0=inline, 1=crossline, 2=time/sample).
    switch (combo_index) {
        case 0: return pwb::viz::VolumeAxis::inline_;
        case 1: return pwb::viz::VolumeAxis::crossline;
        default: return pwb::viz::VolumeAxis::sample;
    }
}

}  // namespace

SeismicSlicePreviewWidget::SeismicSlicePreviewWidget(QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(qt_internal::SPACE_2);

    // Top Control Row
    auto* control_layout = new QHBoxLayout();
    control_layout->setSpacing(qt_internal::SPACE_3);

    auto* type_label = new QLabel(QStringLiteral("切片方向:"));
    type_label->setStyleSheet(type_label_qss());
    type_combo_ = new QComboBox();
    for (const std::string& label : seismic_axis_labels()) {
        type_combo_->addItem(QString::fromStdString(label));
    }
    connect(type_combo_,
            qOverload<int>(&QComboBox::currentIndexChanged), this,
            [this](int index) { on_type_changed(index); });

    slider_ = new QSlider(Qt::Horizontal);
    slider_->setMinimum(0);
    slider_->setMaximum(0);
    slider_->setStyleSheet(slider_qss());
    render_timer_.setSingleShot(true);
    render_timer_.setInterval(SEISMIC_RENDER_DEBOUNCE_MS);
    connect(&render_timer_, &QTimer::timeout, this,
            [this] { render_slice(); });
    connect(slider_, &QSlider::valueChanged, this,
            [this](int value) { on_slider_changed(value); });

    index_label_ = new QLabel(QStringLiteral("0 / 0"));
    index_label_->setStyleSheet(index_label_qss());

    control_layout->addWidget(type_label);
    control_layout->addWidget(type_combo_);
    control_layout->addWidget(slider_, 1);
    control_layout->addWidget(index_label_);

    layout->addLayout(control_layout);

    // Image display area
    image_label_ = new QLabel(QStringLiteral("请选择数据"));
    image_label_->setAlignment(Qt::AlignCenter);
    image_label_->setStyleSheet(image_label_qss());
    layout->addWidget(image_label_, 1);
}

void SeismicSlicePreviewWidget::load_seismic(
    const QString& path, const QString& revision,
    std::shared_ptr<pwb::viz::ISeismicVolume> volume,
    const QString& message) {
    path_ = path;
    revision_ = revision;
    volume_ = std::move(volume);
    stretch_range_.reset();  // recomputed for the new volume on next render

    if (volume_ == nullptr) {
        // Drop the previous asset's rendered slice: a later resizeEvent
        // would otherwise re-install the stale pixmap on top of the error
        // text (#894-4).
        last_pixmap_ = QPixmap();
        last_norm_.clear();
        image_label_->setPixmap(QPixmap());
        image_label_->setText(message.isEmpty()
                                  ? QStringLiteral("无地震数据或无法解析")
                                  : message);
        slider_->setMaximum(0);
        slider_->setEnabled(false);
        type_combo_->setEnabled(false);
        index_label_->setText(QStringLiteral("0 / 0"));
        return;
    }

    type_combo_->setEnabled(true);
    slider_->setEnabled(true);
    update_slider_range();
    render_timer_.stop();
    render_slice();
}

void SeismicSlicePreviewWidget::on_type_changed(int) {
    update_slider_range();
    render_timer_.stop();
    render_slice();
}

void SeismicSlicePreviewWidget::on_slider_changed(int value) {
    if (volume_ != nullptr) {
        index_label_->setText(QString::fromStdString(
            seismic_index_label(value, slider_->maximum())));
        render_timer_.start();
    }
}

void SeismicSlicePreviewWidget::update_slider_range() {
    if (volume_ == nullptr) {
        return;
    }
    const int idx = type_combo_->currentIndex();
    const auto& shape = volume_->geometry().shape;
    const long long axis_size =
        shape[static_cast<size_t>(std::clamp(idx, 0, 2))];
    slider_->setMaximum(static_cast<int>(seismic_slider_max(axis_size)));
    slider_->setValue(static_cast<int>(seismic_slider_value(axis_size)));
    index_label_->setText(QString::fromStdString(
        seismic_index_label(slider_->value(), slider_->maximum())));
}

std::pair<double, double> SeismicSlicePreviewWidget::volume_stretch_range() {
    // global_stretch_range parity: every element contributes (no stride
    // sampling); (0,0) for empty / all-non-finite / constant volumes.
    double v_min = std::numeric_limits<double>::infinity();
    double v_max = -std::numeric_limits<double>::infinity();
    const auto& shape = volume_->geometry().shape;
    const std::int64_t extent = pwb::viz::slice_extent(
        volume_->geometry(), pwb::viz::VolumeAxis::inline_);
    std::vector<float> slice(static_cast<size_t>(std::max<std::int64_t>(extent, 0)));
    for (std::int64_t i = 0; i < shape[0]; ++i) {
        const std::size_t got = volume_->read_slice(
            pwb::viz::VolumeAxis::inline_, i, slice);
        for (std::size_t k = 0; k < got; ++k) {
            const float v = slice[k];
            if (std::isfinite(v)) {
                v_min = std::min(v_min, static_cast<double>(v));
                v_max = std::max(v_max, static_cast<double>(v));
            }
        }
    }
    if (!std::isfinite(v_min) || !std::isfinite(v_max) || v_min >= v_max) {
        return {0.0, 0.0};
    }
    return {v_min, v_max};
}

void SeismicSlicePreviewWidget::render_slice() {
    if (volume_ == nullptr) {
        return;
    }

    const int idx = std::clamp(type_combo_->currentIndex(), 0, 2);
    const int val = slider_->value();
    const pwb::viz::VolumeAxis axis = combo_axis(idx);

    if (!stretch_range_.has_value()) {
        stretch_range_ = volume_stretch_range();
    }
    const std::int64_t extent =
        pwb::viz::slice_extent(volume_->geometry(), axis);
    if (extent <= 0) {
        return;
    }
    std::vector<float> slice(static_cast<size_t>(extent));
    const std::size_t got = volume_->read_slice(axis, val, slice);
    if (got != static_cast<std::size_t>(extent)) {
        return;
    }
    const pwb::viz::IndexedSlice mapped = pwb::viz::map_slice_to_indexed8(
        std::span<const float>(slice.data(), slice.size()), stretch_range_);

    // Plane shape in canonical order (rows, cols over the two remaining
    // axes in declared order).
    const auto& shape = volume_->geometry().shape;
    int rows = 0;
    int cols = 0;
    switch (idx) {
        case 0:  // inline: rows=crossline, cols=sample
            rows = static_cast<int>(shape[1]);
            cols = static_cast<int>(shape[2]);
            break;
        case 1:  // crossline: rows=inline, cols=sample
            rows = static_cast<int>(shape[0]);
            cols = static_cast<int>(shape[2]);
            break;
        default:  // time/sample: rows=inline, cols=crossline
            rows = static_cast<int>(shape[0]);
            cols = static_cast<int>(shape[1]);
            break;
    }
    if (rows <= 0 || cols <= 0) {
        return;
    }

    // Python: `if idx in (0, 1): norm = norm.T` — inline/crossline planes
    // are transposed so the sample axis runs vertically.
    last_norm_.assign(mapped.pixels.begin(), mapped.pixels.end());
    if (idx == 0 || idx == 1) {
        std::vector<std::uint8_t> transposed(last_norm_.size());
        for (int r = 0; r < rows; ++r) {
            for (int c = 0; c < cols; ++c) {
                transposed[static_cast<size_t>(c) * rows + r] =
                    last_norm_[static_cast<size_t>(r) * cols + c];
            }
        }
        last_norm_.swap(transposed);
        std::swap(rows, cols);
    }

    QImage qimg(last_norm_.data(), cols, rows, cols,
                QImage::Format_Indexed8);
    if (color_table_.empty()) {
        const std::vector<std::uint32_t> table = seismic_color_table();
        color_table_.reserve(static_cast<qsizetype>(table.size()));
        for (const std::uint32_t rgba : table) {
            color_table_.append(static_cast<QRgb>(rgba));
        }
    }
    qimg.setColorTable(color_table_);

    const QPixmap pixmap = QPixmap::fromImage(qimg);
    last_pixmap_ = pixmap;
    image_label_->setPixmap(pixmap.scaled(
        std::max(image_label_->width() - 4, 10),
        std::max(image_label_->height() - 4, 10),
        Qt::KeepAspectRatio,
        slider_->isSliderDown() ? Qt::FastTransformation
                                : Qt::SmoothTransformation));
}

void SeismicSlicePreviewWidget::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    // Re-scaling only makes sense while a volume is actually loaded; with
    // the volume cleared the message text must survive resizes (#894-4).
    if (volume_ == nullptr) {
        return;
    }
    if (!last_pixmap_.isNull()) {
        image_label_->setPixmap(last_pixmap_.scaled(
            std::max(image_label_->width() - 4, 10),
            std::max(image_label_->height() - 4, 10),
            Qt::KeepAspectRatio, Qt::SmoothTransformation));
    }
}

void SeismicSlicePreviewWidget::apply_settings(const PreviewSettings& settings) {
    QFont font = this->font();
    font.setPointSize(settings.font_size);
    setFont(font);
}

}  // namespace pwb::ui_pages_preview
