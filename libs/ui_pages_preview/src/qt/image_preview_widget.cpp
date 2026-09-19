#include <pwb/ui_pages_preview/qt/image_preview_widget.hpp>

#include <QBuffer>
#include <QImageReader>
#include <QMouseEvent>
#include <QPainter>
#include <QWheelEvent>

#include <cmath>

#include <pwb/ui_pages_preview/preview_settings.hpp>

namespace pwb::ui_pages_preview {

ImagePreviewWidget::ImagePreviewWidget(QWidget* parent)
    : QLabel(parent) {
    setAlignment(Qt::AlignCenter);
    resize_timer_.setSingleShot(true);
    resize_timer_.setInterval(IMAGE_RESIZE_DEBOUNCE_MS);
    connect(&resize_timer_, &QTimer::timeout, this,
            &ImagePreviewWidget::render_current);
}

QSize ImagePreviewWidget::sizeHint() const {
    // 缩放模式下 pixmap 远大于可视区 — the default sizeHint (= pixmap size)
    // would inflate the outer layout; panning happens inside paintEvent, so
    // the widget only needs the layout-assigned space. Fit mode keeps the
    // default (the pixmap already fits the widget).
    if (!fit_mode_) {
        return {240, 180};
    }
    return QLabel::sizeHint();
}

QSize ImagePreviewWidget::minimumSizeHint() const {
    if (!fit_mode_) {
        return {240, 180};
    }
    return QLabel::minimumSizeHint();
}

void ImagePreviewWidget::apply_settings(const PreviewSettings& settings) {
    transformation_mode_ = settings.smooth_images ? Qt::SmoothTransformation
                                                  : Qt::FastTransformation;
    render_current();
}

QPixmap ImagePreviewWidget::decode_bounded(const QByteArray& bytes) {
    QBuffer buf;
    buf.setData(bytes);
    buf.open(QIODevice::ReadOnly);
    QImageReader reader(&buf);
    reader.setAutoTransform(true);
    const QSize size = reader.size();
    if (size.isValid() &&
        std::max(size.width(), size.height()) > IMAGE_PREVIEW_MAX_LONG_SIDE) {
        reader.setScaledSize(size.scaled(IMAGE_PREVIEW_MAX_LONG_SIDE,
                                         IMAGE_PREVIEW_MAX_LONG_SIDE,
                                         Qt::KeepAspectRatio));
    }
    const QImage image = reader.read();
    if (image.isNull()) {
        return {};
    }
    return QPixmap::fromImage(image);
}

QPixmap ImagePreviewWidget::decode_bounded(const QString& path) {
    QImageReader reader(path);
    reader.setAutoTransform(true);
    const QSize size = reader.size();
    if (size.isValid() &&
        std::max(size.width(), size.height()) > IMAGE_PREVIEW_MAX_LONG_SIDE) {
        reader.setScaledSize(size.scaled(IMAGE_PREVIEW_MAX_LONG_SIDE,
                                         IMAGE_PREVIEW_MAX_LONG_SIDE,
                                         Qt::KeepAspectRatio));
    }
    const QImage image = reader.read();
    if (image.isNull()) {
        return {};
    }
    return QPixmap::fromImage(image);
}

void ImagePreviewWidget::load(const QString& path, const QString& revision,
                              const QByteArray& image_bytes) {
    if (path != path_ || revision != revision_ || pixmap_.isNull()) {
        path_ = path;
        revision_ = revision;
        // Bytes were read off-thread by the preview worker; the decode is
        // bounded to preview resolution (#530).
        pixmap_ = !image_bytes.isEmpty() ? decode_bounded(image_bytes)
                                        : decode_bounded(path);
        scaled_key_.clear();
        // new image -> back to fit mode
        zoom_factor_ = 1.0;
        fit_mode_ = true;
        pan_offset_ = {0, 0};
        dragging_ = false;
    }
    render_current();
}

void ImagePreviewWidget::render_current() {
    if (pixmap_.isNull()) {
        clear();
        setText(QStringLiteral("图片预览加载失败"));
        scaled_key_.clear();
        return;
    }
    if (fit_mode_) {
        const QSize target(std::max(width(), 240), std::max(height(), 180));
        const QString key = path_ + QLatin1Char('\x1f') + revision_ +
            QLatin1Char('\x1f') + QString::number(target.width()) +
            QLatin1Char('x') + QString::number(target.height()) +
            QLatin1Char('\x1f') +
            QString::number(static_cast<int>(transformation_mode_)) +
            QLatin1Char('\x1f') + QStringLiteral("fit");
        if (key == scaled_key_) {
            return;  // already rendered at exactly this size/mode
        }
        const QPixmap scaled = pixmap_.scaled(target, Qt::KeepAspectRatio,
                                              transformation_mode_);
        scaled_key_ = key;
        setPixmap(scaled);
        // fit 模式下居中，不需要平移
        pan_offset_ = {0, 0};
        dragging_ = false;
        update();
    } else {
        // 缩放模式不再物化「整图 × zoom」位图（#1135）— paintEvent 按可视区
        // 窗口化采样，绘制开销 O(viewport)。
        setPixmap(QPixmap());
        scaled_key_.clear();
        const PanOffset clamped = image_clamp_pan(
            pan_offset_.x(), pan_offset_.y(), pixmap_.width(), pixmap_.height(),
            zoom_factor_, width(), height());
        pan_offset_ = {clamped.x, clamped.y};
        update();
    }
}

// -- zoom public API ------------------------------------------------------

void ImagePreviewWidget::zoom_in() {
    set_zoom_factor(zoom_factor_ * IMAGE_ZOOM_STEP);
}

void ImagePreviewWidget::zoom_out() {
    set_zoom_factor(zoom_factor_ / IMAGE_ZOOM_STEP);
}

void ImagePreviewWidget::set_zoom_factor(double factor) {
    const double clamped = image_zoom_clamp(factor);
    // 已在边界且仍往边界外尝试时，不改变状态
    if (std::abs(clamped - zoom_factor_) < 1e-9 && !fit_mode_) {
        return;
    }
    zoom_factor_ = clamped;
    fit_mode_ = false;
    render_current();
    emit zoom_changed(zoom_factor_);
}

void ImagePreviewWidget::set_fit_mode(bool enabled) {
    if (enabled == fit_mode_) {
        return;
    }
    fit_mode_ = enabled;
    if (enabled) {
        zoom_factor_ = 1.0;
        pan_offset_ = {0, 0};
        dragging_ = false;
    }
    render_current();
    emit zoom_changed(zoom_factor_);
}

void ImagePreviewWidget::reset_zoom() {
    zoom_factor_ = 1.0;
    fit_mode_ = true;
    pan_offset_ = {0, 0};
    dragging_ = false;
    render_current();
    emit zoom_changed(zoom_factor_);
}

// -- events ---------------------------------------------------------------

void ImagePreviewWidget::wheelEvent(QWheelEvent* event) {
    if (event->modifiers() & Qt::ControlModifier) {
        const int delta = event->angleDelta().y();
        if (delta > 0) {
            zoom_in();
        } else if (delta < 0) {
            zoom_out();
        }
        event->accept();
        return;
    }
    QLabel::wheelEvent(event);
}

void ImagePreviewWidget::mousePressEvent(QMouseEvent* event) {
    if (!fit_mode_ && event->button() == Qt::LeftButton) {
        dragging_ = true;
        drag_start_pos_ = event->pos();
        drag_start_offset_ = pan_offset_;
        setCursor(Qt::ClosedHandCursor);
        event->accept();
        return;
    }
    QLabel::mousePressEvent(event);
}

void ImagePreviewWidget::mouseMoveEvent(QMouseEvent* event) {
    if (dragging_ && (event->buttons() & Qt::LeftButton)) {
        const QPoint delta = event->pos() - drag_start_pos_;
        const QPoint new_offset = drag_start_offset_ + delta;
        const PanOffset clamped = image_clamp_pan(
            new_offset.x(), new_offset.y(), pixmap_.width(), pixmap_.height(),
            zoom_factor_, width(), height());
        pan_offset_ = {clamped.x, clamped.y};
        update();
        event->accept();
        return;
    }
    if (!fit_mode_ && !dragging_) {
        // hover 时给出可拖拽提示
        setCursor(Qt::OpenHandCursor);
    }
    QLabel::mouseMoveEvent(event);
}

void ImagePreviewWidget::mouseReleaseEvent(QMouseEvent* event) {
    if (dragging_ && event->button() == Qt::LeftButton) {
        dragging_ = false;
        if (!fit_mode_) {
            setCursor(Qt::OpenHandCursor);
        } else {
            unsetCursor();
        }
        event->accept();
        return;
    }
    QLabel::mouseReleaseEvent(event);
}

void ImagePreviewWidget::paintEvent(QPaintEvent* event) {
    if (fit_mode_ || pixmap_.isNull()) {
        QLabel::paintEvent(event);
        return;
    }
    // 视口窗口化绘制（#1135）：把可视区矩形映射回源图坐标，仅采样该窗口。
    const QPixmap& source = pixmap_;
    const double sw = source.width();
    const double sh = source.height();
    const auto [pw, ph] = image_virtual_size(pixmap_.width(), pixmap_.height(),
                                             zoom_factor_);
    if (pw <= 0 || ph <= 0) {
        QLabel::paintEvent(event);
        return;
    }
    int ww = width();
    int wh = height();
    if (ww <= 0 || wh <= 0) {
        ww = 240;
        wh = 180;
    }
    const int x = (ww - pw) / 2 + pan_offset_.x();
    const int y = (wh - ph) / 2 + pan_offset_.y();
    // 可视区落在虚拟图上的矩形（与 widget 相交）
    const int vis_x0 = std::max(0, -x);
    const int vis_y0 = std::max(0, -y);
    const int vis_x1 = std::min(ww, pw - x);
    const int vis_y1 = std::min(wh, ph - y);
    if (vis_x1 <= vis_x0 || vis_y1 <= vis_y0) {
        return;
    }
    const double scale_x = sw / static_cast<double>(pw);
    const double scale_y = sh / static_cast<double>(ph);
    const QRectF src_rect(vis_x0 * scale_x, vis_y0 * scale_y,
                          (vis_x1 - vis_x0) * scale_x,
                          (vis_y1 - vis_y0) * scale_y);
    QPainter painter(this);
    if (transformation_mode_ == Qt::SmoothTransformation) {
        painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
    }
    painter.drawPixmap(
        QRectF(x + vis_x0, y + vis_y0, vis_x1 - vis_x0, vis_y1 - vis_y0),
        source, src_rect);
}

void ImagePreviewWidget::resizeEvent(QResizeEvent* event) {
    QLabel::resizeEvent(event);
    if (path_.isEmpty()) {
        return;
    }
    if (fit_mode_) {
        // Interactive resizes stream dozens of events; coalesce so each
        // O(source) smooth rescale runs once the user stops (#530).
        resize_timer_.start();
    } else {
        const PanOffset clamped = image_clamp_pan(
            pan_offset_.x(), pan_offset_.y(), pixmap_.width(), pixmap_.height(),
            zoom_factor_, width(), height());
        pan_offset_ = {clamped.x, clamped.y};
        update();
    }
}

}  // namespace pwb::ui_pages_preview
