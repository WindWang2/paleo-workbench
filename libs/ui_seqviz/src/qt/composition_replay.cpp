#include <pwb/ui_seqviz/qt/composition_replay.hpp>

#include <QByteArray>
#include <QImage>
#include <QMarginsF>
#include <QPageLayout>
#include <QPageSize>
#include <QPainter>
#include <QPdfWriter>
#include <QRectF>
#include <QSizeF>
#include <QSvgRenderer>

#include <cmath>
#include <cstdio>
#include <string>

namespace pwb::ui_seqviz::qt {
namespace {

// export.py: page pixels at the effective DPI (banker's rounding parity
// lives in the kernel's composition_page_pixels).
std::pair<long long, long long> page_pixels(double width_mm, double height_mm,
                                            double dpi) {
    const double w = std::llround(width_mm / 25.4 * dpi);
    const double h = std::llround(height_mm / 25.4 * dpi);
    return {std::max<long long>(1, w), std::max<long long>(1, h)};
}

bool replay_png(const std::string& svg, const std::string& path, double dpi,
                double width_mm, double height_mm, std::string& message) {
    QSvgRenderer renderer(QByteArray::fromStdString(svg));
    if (!renderer.isValid()) {
        // Python: RuntimeError "composition SVG did not parse; refusing to
        // export PNG" — refuse, never rasterize garbage.
        message = "composition SVG did not parse; refusing to export PNG";
        return false;
    }
    const auto [width_px, height_px] = page_pixels(width_mm, height_mm, dpi);
    QImage image(static_cast<int>(width_px), static_cast<int>(height_px),
                 QImage::Format_ARGB32_Premultiplied);
    image.fill(0xFFFFFFFF);
    QPainter painter(&image);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::TextAntialiasing, true);
    renderer.render(&painter);
    painter.end();
    const int dots_per_meter = static_cast<int>(std::lround(dpi / 0.0254));
    image.setDotsPerMeterX(dots_per_meter);
    image.setDotsPerMeterY(dots_per_meter);
    if (!image.save(QString::fromStdString(path), "PNG")) {
        // Python: RuntimeError "could not save composition PNG".
        message = "could not save composition PNG";
        return false;
    }
    return true;
}

bool replay_pdf(const std::string& svg, const std::string& path, double dpi,
                double width_mm, double height_mm, std::string& message) {
    QPdfWriter writer(QString::fromStdString(path));
    writer.setResolution(static_cast<int>(std::lround(dpi)));
    const QPageSize page_size(QSizeF(width_mm, height_mm), QPageSize::Millimeter,
                              "Composition", QPageSize::ExactMatch);
    writer.setPageLayout(QPageLayout(page_size, QPageLayout::Portrait,
                                     QMarginsF(0, 0, 0, 0)));
    QPainter painter;
    if (!painter.begin(&writer)) {
        // Python: RuntimeError "could not open PDF writer for composition
        // export".
        message = "could not open PDF writer for composition export";
        return false;
    }
    QSvgRenderer renderer(QByteArray::fromStdString(svg));
    if (!renderer.isValid()) {
        painter.end();
        message = "composition SVG did not parse; refusing to export PDF";
        return false;
    }
    QRectF page_rect = writer.pageLayout().paintRectPixels(writer.resolution());
    if (page_rect.width() <= 0 || page_rect.height() <= 0) {
        // Python fallback: compute from the physical size at the writer
        // resolution.
        page_rect = QRectF(0, 0, width_mm / 25.4 * writer.resolution(),
                           height_mm / 25.4 * writer.resolution());
    }
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setRenderHint(QPainter::TextAntialiasing, true);
    renderer.render(&painter, page_rect);
    painter.end();
    return true;
}

}  // namespace

pwb::mapping_document::ComposerReplaySeams make_composition_replay_seams() {
    pwb::mapping_document::ComposerReplaySeams seams;
    seams.replay = [](const std::string& svg, const std::string& path,
                      const std::string& format, double dpi, double width_mm,
                      double height_mm, std::string& message) -> bool {
        if (format == "png") {
            return replay_png(svg, path, dpi, width_mm, height_mm, message);
        }
        if (format == "pdf") {
            return replay_pdf(svg, path, dpi, width_mm, height_mm, message);
        }
        message = "no composition replay device for format '" + format + "'";
        return false;
    };
    return seams;
}

}  // namespace pwb::ui_seqviz::qt
