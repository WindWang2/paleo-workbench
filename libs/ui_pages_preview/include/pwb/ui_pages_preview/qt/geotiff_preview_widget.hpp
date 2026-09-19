#pragma once

// Port of paleo_workbench/ui/pages/geotiff_preview_widget.py (UI-07):
// GeoTIFF thumbnail (decoded on the UI thread from off-thread PNG bytes)
// + geographic metadata summary table reusing TablePreviewWidget.

#include <QByteArray>
#include <QPixmap>
#include <QString>
#include <QWidget>
#include <utility>
#include <vector>

class QLabel;

#include <pwb/ui_pages_preview/qt/table_preview_widget.hpp>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class GeoTiffPreviewWidget : public QWidget {
    Q_OBJECT
public:
    explicit GeoTiffPreviewWidget(QWidget* parent = nullptr);

    void apply_settings(const PreviewSettings& settings);

    // load(path, revision, image_bytes, geo_metadata)
    void load(const QString& path, const QString& revision,
              const QByteArray& image_bytes,
              const std::vector<std::pair<std::string, std::string>>&
                  geo_metadata);

    // Expose the decoded thumbnail pixmap (mirrors QLabel.pixmap).
    QPixmap pixmap() const { return pixmap_; }

    TablePreviewWidget* summary_table() const { return summary_table_; }

protected:
    void resizeEvent(QResizeEvent* event) override;

private:
    void render_thumbnail();

    QLabel* image_label_ = nullptr;
    TablePreviewWidget* summary_table_ = nullptr;
    QPixmap pixmap_;
    Qt::TransformationMode transformation_mode_ = Qt::SmoothTransformation;
};

}  // namespace pwb::ui_pages_preview
