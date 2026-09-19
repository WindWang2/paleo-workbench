#include <pwb/viz/cross_well/qt/report_export.hpp>

#include <QColor>
#include <QFileInfo>
#include <QFont>
#include <QImage>
#include <QPageSize>
#include <QPainter>
#include <QPen>
#include <QPrinter>
#include <QRectF>
#include <QSvgGenerator>

#include <algorithm>
#include <cmath>
#include <string>
#include <utility>
#include <vector>

namespace pwb::viz::cross_well::qt {

namespace {

// mm -> px at the report dpi.
double mm_to_px(double mm, int dpi) { return mm / 25.4 * dpi; }

// _PAGE_SIZES_MM is width x height LANDSCAPE (report_export.py).
std::pair<double, double> page_size_mm(const QString& name) {
    const QString key = name.toUpper();
    if (key == "A3") return {420.0, 297.0};
    if (key == "A2") return {594.0, 420.0};
    return {297.0, 210.0};  // A4 fallback
}

// The section's natural aspect; scale to fit the content rect.
void paint_content(QPainter* painter, const SectionScene& scene,
                   const QRectF& content_px) {
    const double natural_w =
        kLeftMarginPx * 2.0 + scene.wells.size() * kColumnWidthPx +
        (scene.wells.size() - 1) * kWellSpacingPx + kDepthRulerWidthPx;
    const double natural_h = 640.0;
    const double fit = std::min(content_px.width() / natural_w,
                                content_px.height() / natural_h);
    painter->save();
    painter->translate(content_px.left(), content_px.top());
    painter->scale(fit, fit);
    // Centre horizontally when the fit leaves slack.
    const double slack_x =
        content_px.width() - natural_w * fit;
    const double slack_y =
        content_px.height() - natural_h * fit;
    painter->translate(slack_x / 2.0 / fit, slack_y / 2.0 / fit);
    paint_section(painter, scene, natural_w, natural_h);
    painter->restore();
}

void paint_grid_frame(QPainter* painter, const QRectF& rect_px) {
    QPen pen(QColor(0xa0, 0xae, 0xc0), 1.5);
    pen.setCosmetic(true);
    painter->setPen(pen);
    painter->setBrush(Qt::NoBrush);
    painter->drawRect(rect_px);
    for (int i = 1; i <= 9; ++i) {
        const double t = static_cast<double>(i) / 10.0;
        const double x = rect_px.left() + rect_px.width() * t;
        const double y = rect_px.top() + rect_px.height() * t;
        painter->drawLine(QPointF(x, rect_px.bottom()),
                          QPointF(x, rect_px.bottom() - 6.0));
        painter->drawLine(QPointF(x, rect_px.top()),
                          QPointF(x, rect_px.top() + 6.0));
        painter->drawLine(QPointF(rect_px.left(), y),
                          QPointF(rect_px.left() + 6.0, y));
        painter->drawLine(QPointF(rect_px.right(), y),
                          QPointF(rect_px.right() - 6.0, y));
    }
}

void paint_title(QPainter* painter, const QString& title,
                 const QRectF& title_px) {
    painter->setPen(QPen(QColor(0x1a, 0x20, 0x2c), 1.0));
    QFont font = painter->font();
    font.setFamily("Arial");
    font.setPointSize(16);
    font.setBold(true);
    painter->setFont(font);
    painter->drawText(title_px, Qt::AlignCenter, title);
}

void paint_legend(QPainter* painter, const SectionScene& scene,
                  const QRectF& legend_px, int dpi) {
    painter->setPen(QPen(QColor(0xe2, 0xe8, 0xf0), 1.0));
    painter->setBrush(Qt::NoBrush);
    painter->drawRect(legend_px);
    // formation -> colour, later wells override earlier ones
    // (report_export.py collects in _well_names order).
    std::vector<std::pair<std::string, std::string>> legend;
    for (const WellColumnData& well : scene.wells) {
        for (const FormationTop& top : scene.tops) {
            if (top.well_name != well.name) continue;
            bool found = false;
            for (auto& [name, color] : legend) {
                if (name == top.formation_name) {
                    color = top.resolved_color();
                    found = true;
                    break;
                }
            }
            if (!found) {
                legend.emplace_back(top.formation_name,
                                    top.resolved_color());
            }
        }
    }
    QFont font = painter->font();
    font.setFamily("Arial");
    font.setPointSize(9);
    painter->setFont(font);
    const double swatch_w = mm_to_px(12.0, dpi);
    const double swatch_h = mm_to_px(6.0, dpi);
    const double gap = mm_to_px(4.0, dpi);
    const double step_name = mm_to_px(15.0, dpi);
    double x = legend_px.left() + mm_to_px(4.0, dpi);
    const double y = legend_px.top() + mm_to_px(4.5, dpi);
    for (const auto& [name, color] : legend) {
        const double name_px = mm_to_px(
            static_cast<double>(name.size()) * 6.0, dpi);
        if (x + swatch_w + mm_to_px(80.0, dpi) >
            legend_px.right()) {
            x = legend_px.left() + mm_to_px(4.0, dpi);
        }
        painter->setBrush(QColor(QString::fromStdString(color)));
        painter->setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
        painter->drawRect(QRectF(x, y, swatch_w, swatch_h));
        painter->setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
        painter->drawText(
            QPointF(x + swatch_w + gap, y + swatch_h),
            QString::fromStdString(name));
        x += swatch_w + gap + name_px + step_name;
    }
}

void render_report_page(QPainter* painter, const SectionScene& scene,
                        const CrossWellReportOptions& options,
                        double page_w_px, double page_h_px) {
    painter->fillRect(QRectF(0, 0, page_w_px, page_h_px), Qt::white);
    const double margin = mm_to_px(15.0, options.dpi);
    const double title_h = mm_to_px(12.0, options.dpi);
    const double legend_h = mm_to_px(15.0, options.dpi);
    const QRectF title_px(margin, margin, page_w_px - 2 * margin, title_h);
    paint_title(painter, options.title, title_px);
    double content_bottom = page_h_px - margin;
    QRectF legend_px;
    if (options.include_legend && !scene.tops.empty()) {
        legend_px = QRectF(margin, page_h_px - margin - legend_h,
                           page_w_px - 2 * margin, legend_h);
        content_bottom = legend_px.top() - mm_to_px(3.0, options.dpi);
    }
    QRectF content(margin, title_px.bottom() + mm_to_px(3.0, options.dpi),
                   page_w_px - 2 * margin,
                   content_bottom - title_px.bottom() -
                       mm_to_px(3.0, options.dpi));
    paint_content(painter, scene, content);
    if (options.include_grid_frame) {
        paint_grid_frame(painter, content);
    }
    if (!legend_px.isNull()) {
        paint_legend(painter, scene, legend_px, options.dpi);
    }
}

}  // namespace

bool export_cross_well_report(const SectionScene& scene,
                              const QString& output_path,
                              const CrossWellReportOptions& options) {
    if (scene.wells.empty()) return false;
    auto [w_mm, h_mm] = page_size_mm(options.page_size);
    if (options.portrait) std::swap(w_mm, h_mm);
    const QString suffix =
        output_path.section('.', -1).toLower();
    if (suffix == "svg") {
        const int w_px = static_cast<int>(std::lround(mm_to_px(w_mm, options.dpi)));
        const int h_px = static_cast<int>(std::lround(mm_to_px(h_mm, options.dpi)));
        QSvgGenerator generator;
        generator.setFileName(output_path);
        generator.setSize(QSize(w_px, h_px));
        generator.setViewBox(QRectF(0, 0, w_px, h_px));
        QPainter painter(&generator);
        if (!painter.isActive()) return false;
        render_report_page(&painter, scene, options, w_px, h_px);
        painter.end();
        return QFileInfo::exists(output_path);
    }
    if (suffix == "png") {
        const int w_px = static_cast<int>(std::lround(mm_to_px(w_mm, options.dpi)));
        const int h_px = static_cast<int>(std::lround(mm_to_px(h_mm, options.dpi)));
        QImage image(w_px, h_px, QImage::Format_ARGB32);
        image.fill(Qt::white);
        QPainter painter(&image);
        render_report_page(&painter, scene, options,
                           static_cast<double>(w_px),
                           static_cast<double>(h_px));
        painter.end();
        return image.save(output_path, "PNG");
    }
    // Default: PDF.
    QPrinter printer(QPrinter::HighResolution);
    printer.setOutputFormat(QPrinter::PdfFormat);
    printer.setOutputFileName(output_path);
    printer.setResolution(options.dpi);
    printer.setPageSize(QPageSize(
        QSizeF(w_mm, h_mm), QPageSize::Millimeter));
    QPainter painter(&printer);
    if (!painter.isActive()) return false;
    const double w_px = mm_to_px(w_mm, options.dpi);
    const double h_px = mm_to_px(h_mm, options.dpi);
    render_report_page(&painter, scene, options, w_px, h_px);
    painter.end();
    return QFileInfo::exists(output_path);
}

}  // namespace pwb::viz::cross_well::qt
