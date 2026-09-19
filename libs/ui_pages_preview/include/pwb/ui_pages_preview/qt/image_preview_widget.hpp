#pragma once

// Port of paleo_workbench/ui/pages/image_preview_widget.py (UI-07):
// QLabel shell — bounded decode (2048 long side), fit mode with 80ms resize
// debounce, zoom (0.1–8 ×1.25) with viewport-windowed paintEvent (#1135),
// Ctrl+wheel zoom, drag pan clamped to the virtual image.

#include <QLabel>
#include <QPoint>
#include <QPixmap>
#include <QSize>
#include <QTimer>

#include <pwb/ui_pages_preview/image_zoom.hpp>

namespace pwb::ui_pages_preview {

struct PreviewSettings;

class ImagePreviewWidget : public QLabel {
    Q_OBJECT
public:
    explicit ImagePreviewWidget(QWidget* parent = nullptr);

    QSize sizeHint() const override;
    QSize minimumSizeHint() const override;

    void apply_settings(const PreviewSettings& settings);

    // load(path, revision, image_bytes): re-decodes when the identity
    // changed (or no pixmap yet), then renders. Bytes were read off-thread;
    // the decode is bounded to IMAGE_PREVIEW_MAX_LONG_SIDE.
    void load(const QString& path, const QString& revision = QString(),
              const QByteArray& image_bytes = QByteArray());

    void render_current();

    // zoom public API
    void zoom_in();
    void zoom_out();
    void set_zoom_factor(double factor);
    void set_fit_mode(bool enabled);
    void reset_zoom();

    bool fit_mode() const { return fit_mode_; }
    double zoom_factor() const { return zoom_factor_; }
    Qt::TransformationMode transformation_mode() const { return transformation_mode_; }

signals:
    void zoom_changed(double factor);

protected:
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void paintEvent(QPaintEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    // _decode_bounded: QImageReader with setScaledSize bounded to the
    // preview long side; returns a null pixmap on undecodable input.
    static QPixmap decode_bounded(const QByteArray& bytes);
    static QPixmap decode_bounded(const QString& path);

    QString path_;
    QString revision_;
    QPixmap pixmap_;
    Qt::TransformationMode transformation_mode_ = Qt::SmoothTransformation;
    // Cache key for the fit-mode scaled pixmap (render_current early-out).
    QString scaled_key_;
    QTimer resize_timer_;
    double zoom_factor_ = 1.0;
    bool fit_mode_ = true;
    QPoint pan_offset_{0, 0};
    bool dragging_ = false;
    QPoint drag_start_pos_{0, 0};
    QPoint drag_start_offset_{0, 0};
};

}  // namespace pwb::ui_pages_preview
