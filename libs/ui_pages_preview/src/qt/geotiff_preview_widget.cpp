#include <pwb/ui_pages_preview/qt/geotiff_preview_widget.hpp>

#include <QLabel>
#include <QVBoxLayout>

#include <pwb/ui_pages_preview/preview_settings.hpp>

#include "../qt/style_util.hpp"

namespace pwb::ui_pages_preview {

GeoTiffPreviewWidget::GeoTiffPreviewWidget(QWidget* parent)
    : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(qt_internal::SPACE_2);
    image_label_ = new QLabel();
    image_label_->setAlignment(Qt::AlignCenter);
    image_label_->setMinimumHeight(160);
    layout->addWidget(image_label_, 1);
    summary_table_ = new TablePreviewWidget();
    layout->addWidget(summary_table_);
}

void GeoTiffPreviewWidget::apply_settings(const PreviewSettings& settings) {
    summary_table_->setVisible(settings.show_geo_metadata);
    summary_table_->apply_settings(settings);
    transformation_mode_ = settings.smooth_images ? Qt::SmoothTransformation
                                                  : Qt::FastTransformation;
    render_thumbnail();
}

void GeoTiffPreviewWidget::load(
    const QString& path, const QString& revision,
    const QByteArray& image_bytes,
    const std::vector<std::pair<std::string, std::string>>& geo_metadata) {
    Q_UNUSED(path);
    Q_UNUSED(revision);
    std::vector<std::vector<std::string>> rows;
    rows.reserve(geo_metadata.size());
    for (const auto& [k, v] : geo_metadata) {
        rows.push_back({k, v});
    }
    summary_table_->load_table(std::vector<std::string>{"属性", "值"}, rows);
    pixmap_ = QPixmap();
    if (!image_bytes.isEmpty()) {
        pixmap_.loadFromData(image_bytes);
    }
    render_thumbnail();
}

void GeoTiffPreviewWidget::render_thumbnail() {
    if (pixmap_.isNull()) {
        image_label_->setText(QStringLiteral("缩略图不可用"));
        return;
    }
    image_label_->setPixmap(pixmap_.scaled(
        std::max(image_label_->width(), 240),
        std::max(image_label_->height(), 160), Qt::KeepAspectRatio,
        transformation_mode_));
}

void GeoTiffPreviewWidget::resizeEvent(QResizeEvent* event) {
    QWidget::resizeEvent(event);
    render_thumbnail();
}

}  // namespace pwb::ui_pages_preview
