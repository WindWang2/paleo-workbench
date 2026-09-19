#include <pwb/viz/cross_well/qt/section_canvas.hpp>

#include <QApplication>
#include <QColor>
#include <QEvent>
#include <QFileInfo>
#include <QLineF>
#include <QPageLayout>
#include <QMouseEvent>
#include <QPageSize>
#include <QPaintEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPen>
#include <QPointF>
#include <QPrinter>
#include <QRectF>
#include <QSvgGenerator>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <utility>

namespace pwb::viz::cross_well::qt {

namespace {

using pwb::viz::cross_well::FormationTop;
using pwb::viz::cross_well::HorizonPick;
using pwb::viz::cross_well::WellColumnData;
using pwb::viz::cross_well::WellColumnGeometry;
using pwb::viz::cross_well::formation_color_for_name;

// Column geometry for scene painting: horizontal band per well.
struct ColumnLayout {
    std::size_t index = 0;
    double x_left = 0.0;
    double x_right = 0.0;
    WellColumnGeometry geometry;
};

std::vector<ColumnLayout> layout_columns(const SectionScene& scene,
                                         double width_px, double height_px) {
    std::vector<ColumnLayout> out;
    const std::size_t n = scene.wells.size();
    if (n == 0) return out;
    double x = kLeftMarginPx;
    for (std::size_t i = 0; i < n; ++i) {
        ColumnLayout column;
        column.index = i;
        column.x_left = x;
        column.x_right = x + kColumnWidthPx;
        column.geometry.depth_top = scene.view.depth_top;
        column.geometry.depth_bottom = scene.view.depth_bottom;
        column.geometry.header_height_px =
            pwb::viz::cross_well::kDefaultHeaderHeightPx;
        column.geometry.canvas_height_px =
            height_px - kColumnNameBandPx;
        column.geometry.canvas_left_px = column.x_left;
        column.geometry.canvas_right_px = column.x_right;
        out.push_back(column);
        x += kColumnWidthPx + kWellSpacingPx;
    }
    return out;
}

// Depth -> y in the column's content band, including the name band.
double column_depth_to_y(const ColumnLayout& column, double depth) {
    return kColumnNameBandPx + column.geometry.depth_to_y(depth);
}

std::optional<double> column_y_to_depth(const ColumnLayout& column,
                                        double y) {
    return column.geometry.y_to_depth(y - kColumnNameBandPx);
}

QColor formation_qcolor(const std::string& formation) {
    return QColor(QString::fromStdString(
        pwb::viz::cross_well::formation_color_for_name(formation)));
}

void paint_column(QPainter* painter, const SectionScene& scene,
                  const WellColumnData& well, const ColumnLayout& column) {
    // Header band (inside the column, 56 px).
    QRectF header(column.x_left, kColumnNameBandPx, kColumnWidthPx,
                  pwb::viz::cross_well::kDefaultHeaderHeightPx);
    painter->fillRect(header, QColor(0xf7, 0xfa, 0xfc));
    painter->setPen(QPen(QColor(0xe2, 0xe8, 0xf0), 1.0));
    painter->drawRect(header);
    // Well name band above the header.
    QRectF name_band(column.x_left, 0.0, kColumnWidthPx, kColumnNameBandPx);
    painter->fillRect(name_band, QColor(0xf7, 0xfa, 0xfc));
    painter->setPen(QPen(QColor(0xe2, 0xe8, 0xf0), 1.0));
    painter->drawLine(QPointF(column.x_left, kColumnNameBandPx),
                      QPointF(column.x_right, kColumnNameBandPx));
    painter->setPen(QPen(QColor(0x1a, 0x20, 0x2c), 1.0));
    QFont name_font = painter->font();
    name_font.setPointSize(10);
    name_font.setBold(true);
    painter->setFont(name_font);
    painter->drawText(name_band.adjusted(2, 0, -2, 0), Qt::AlignCenter,
                      QString::fromStdString(well.name));
    // Curve label + range in the header.
    QFont small_font = painter->font();
    small_font.setPointSize(8);
    small_font.setBold(false);
    painter->setFont(small_font);
    painter->setPen(QPen(QColor(0x31, 0x66, 0xd4), 1.0));
    painter->drawText(header.adjusted(4, 2, -4, -header.height() / 2),
                      Qt::AlignLeft | Qt::AlignVCenter,
                      QString::fromStdString(well.display_curve.name));
    const auto [lo, hi] =
        pwb::viz::cross_well::curve_display_range(well.display_curve);
    painter->drawText(header.adjusted(4, header.height() / 2, -4, -2),
                      Qt::AlignLeft | Qt::AlignVCenter,
                      QString("%1 ~ %2").arg(lo).arg(hi));

    // Curve polyline: value -> x linear over [lo, hi] inside the column.
    if (well.display_curve.depths.size() ==
        well.display_curve.values.size()) {
        const double span = hi - lo;
        painter->setPen(QPen(QColor(0x1f, 0x66, 0xd4), 1.2));
        bool pen_down = false;
        double last_x = 0.0, last_y = 0.0;
        for (std::size_t i = 0; i < well.display_curve.depths.size(); ++i) {
            const double v = well.display_curve.values[i];
            if (!std::isfinite(v)) {
                pen_down = false;
                continue;
            }
            const double depth = well.display_curve.depths[i];
            if (depth < scene.view.depth_top - span * 0.01 ||
                depth > scene.view.depth_bottom + span * 0.01) {
                continue;
            }
            double t = span > 0.0 ? (v - lo) / span : 0.5;
            t = std::clamp(t, 0.02, 0.98);
            const double x = column.x_left + 4.0 +
                             t * (kColumnWidthPx - 8.0);
            const double y = column_depth_to_y(column, depth);
            if (pen_down) {
                painter->drawLine(QPointF(last_x, last_y), QPointF(x, y));
            }
            last_x = x;
            last_y = y;
            pen_down = true;
        }
    }
}

void paint_tops(QPainter* painter, const SectionScene& scene,
                const std::vector<ColumnLayout>& columns) {
    if (!scene.show_tops) return;
    QFont label_font = painter->font();
    label_font.setPointSize(8);
    painter->setFont(label_font);
    for (const ColumnLayout& column : columns) {
        const std::string well_name =
            scene.wells[column.index].name;
        for (const FormationTop& top : scene.tops) {
            if (top.well_name != well_name) continue;
            const double y = column_depth_to_y(column, top.depth_m);
            if (y < kColumnNameBandPx || y > column.geometry.canvas_height_px +
                                                     kColumnNameBandPx) {
                continue;
            }
            QColor color(QString::fromStdString(
                top.resolved_color()));
            QPen pen(color, 1.5);
            pen.setStyle(Qt::DashLine);
            painter->setPen(pen);
            painter->drawLine(QPointF(column.x_left, y),
                              QPointF(column.x_right, y));
            painter->setPen(QPen(color.darker(130), 1.0));
            painter->drawText(QPointF(column.x_left + 4.0, y - 3.0),
                              QString::fromStdString(top.formation_name));
        }
    }
}

// CorrelationLayer port: bezier ties between adjacent connected wells +
// pick dots on each well's right edge.
void paint_ties(QPainter* painter, const SectionScene& scene,
                const std::vector<ColumnLayout>& columns) {
    if (scene.picks.empty() || columns.empty()) return;
    std::map<std::string, const ColumnLayout*> by_well;
    for (const ColumnLayout& column : columns) {
        by_well[scene.wells[column.index].name] = &column;
    }
    painter->setRenderHint(QPainter::Antialiasing, true);
    for (const HorizonPick& pick : scene.picks) {
        const std::vector<std::string> connected = pick.connected_wells();
        QColor color = formation_qcolor(pick.formation_name);
        const bool emphasized =
            pick.pick_id == scene.selected_pick ||
            pick.pick_id == scene.hover_pick;
        // Segments between adjacent entries of the connection order.
        for (std::size_t i = 0; i + 1 < connected.size(); ++i) {
            const auto src = by_well.find(connected[i]);
            const auto tgt = by_well.find(connected[i + 1]);
            if (src == by_well.end() || tgt == by_well.end()) continue;
            const std::optional<double> d1 =
                pick.depth_for_well(connected[i]);
            const std::optional<double> d2 =
                pick.depth_for_well(connected[i + 1]);
            if (!d1.has_value() || !d2.has_value()) continue;
            const double y1 = column_depth_to_y(*src->second, *d1);
            const double y2 = column_depth_to_y(*tgt->second, *d2);
            const double src_right = src->second->x_right;
            const double tgt_left = tgt->second->x_left;
            const double span = tgt_left - src_right;
            QPainterPath path;
            path.moveTo(src_right, y1);
            path.cubicTo(src_right + span / 3.0, y1,
                         src_right + 2.0 * span / 3.0, y2, tgt_left, y2);
            QPen pen(color, pick.source == "dtw" ? 1.5
                                                 : (emphasized ? 3.0 : 2.0));
            if (pick.source == "dtw") pen.setStyle(Qt::DashLine);
            painter->setPen(pen);
            painter->setBrush(Qt::NoBrush);
            painter->drawPath(path);
        }
        // Pick dots at each connected well's right edge.
        for (const std::string& well : connected) {
            const auto it = by_well.find(well);
            if (it == by_well.end()) continue;
            const std::optional<double> d = pick.depth_for_well(well);
            if (!d.has_value()) continue;
            const double y = column_depth_to_y(*it->second, *d);
            const double radius =
                pick.pick_id == scene.selected_pick ? 6.0 : 4.0;
            QColor dot_color = color;
            painter->setPen(QPen(dot_color.darker(120), 1.5));
            if (pick.source == "dtw") {
                QPen dash(dot_color.darker(120), 1.0);
                dash.setStyle(Qt::DashLine);
                painter->setPen(dash);
                dot_color.setAlpha(100);
                painter->setBrush(dot_color);
            } else {
                painter->setBrush(color);
            }
            painter->drawEllipse(
                QPointF(it->second->x_right, y), radius, radius);
        }
    }
}

void paint_depth_ruler(QPainter* painter, const SectionScene& scene,
                       const std::vector<ColumnLayout>& columns,
                       double width_px, double height_px) {
    if (columns.empty()) return;
    const double x = width_px - kDepthRulerWidthPx + 4.0;
    QFont font = painter->font();
    font.setPointSize(8);
    painter->setFont(font);
    const ColumnLayout& first = columns.front();
    const double span = scene.view.span();
    if (span <= 0.0) return;
    const int steps = 10;
    for (int i = 0; i <= steps; ++i) {
        const double depth = scene.view.depth_top +
                             span * i / static_cast<double>(steps);
        const double y = column_depth_to_y(first, depth);
        painter->setPen(QPen(QColor(0xa0, 0xae, 0xc0), 1.0));
        painter->drawLine(QPointF(x, y), QPointF(x + 6.0, y));
        painter->setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
        painter->drawText(QPointF(x + 8.0, y + 3.0),
                          QString::number(depth, 'f', 1));
    }
}

// TWT axis (canvas.py _paint_twt_axis): left of the FIRST displayed well
// that owns a calibration table; 10 evenly spaced depth ticks labelled
// with interpolate_twt, blue 7 pt.
void paint_twt_axis(QPainter* painter, const SectionScene& scene,
                    const std::vector<ColumnLayout>& columns,
                    double height_px) {
    if (scene.depth_domain != "TWT" || columns.empty()) return;
    const ColumnLayout* anchor = nullptr;
    for (const ColumnLayout& column : columns) {
        if (scene.tie.has_well(scene.wells[column.index].name)) {
            anchor = &column;
            break;
        }
    }
    if (anchor == nullptr) return;
    const std::string well_name = scene.wells[anchor->index].name;
    const double axis_x = anchor->x_left - 42.0;
    if (axis_x < 2.0) return;
    QFont font = painter->font();
    font.setPointSize(7);
    painter->setFont(font);
    const int steps = 10;
    for (int i = 0; i <= steps; ++i) {
        const double ratio = static_cast<double>(i) / steps;
        const double y = kColumnNameBandPx +
                         pwb::viz::cross_well::kDefaultHeaderHeightPx +
                         ratio * (height_px - kColumnNameBandPx -
                                  pwb::viz::cross_well::kDefaultHeaderHeightPx);
        const std::optional<double> depth = column_y_to_depth(*anchor, y);
        if (!depth.has_value()) continue;
        const std::optional<double> twt =
            scene.tie.depth_to_twt(well_name, *depth);
        if (!twt.has_value()) continue;
        painter->setPen(QPen(QColor(0, 100, 180), 1.0));
        painter->drawLine(QPointF(axis_x, y), QPointF(axis_x + 5.0, y));
        painter->drawText(QPointF(axis_x, y + 3.0),
                          QString::number(*twt, 'f', 0));
    }
    painter->drawText(QPointF(axis_x, kColumnNameBandPx - 10.0),
                      QStringLiteral("TWT(ms)"));
}

void paint_hover_and_cursor(QPainter* painter, const SectionScene& scene,
                            const std::vector<ColumnLayout>& columns,
                            double width_px) {
    // Hover snap preview: blue dashed line + curve point.
    if (scene.hover_well_index >= 0 &&
        static_cast<std::size_t>(scene.hover_well_index) < columns.size() &&
        std::isfinite(scene.hover_snap_depth)) {
        const ColumnLayout& column =
            columns[static_cast<std::size_t>(scene.hover_well_index)];
        const double y = column_depth_to_y(column, scene.hover_snap_depth);
        QColor color(31, 102, 212, 180);
        QPen pen(color, 1.0);
        pen.setStyle(Qt::DashLine);
        painter->setPen(pen);
        painter->drawLine(QPointF(kLeftMarginPx, y),
                          QPointF(width_px - kDepthRulerWidthPx, y));
        if (std::isfinite(scene.hover_snap_value)) {
            const auto [lo, hi] = pwb::viz::cross_well::curve_display_range(
                scene.wells[static_cast<std::size_t>(
                    scene.hover_well_index)]
                    .display_curve);
            const double span = hi - lo;
            double t = span > 0.0
                           ? (scene.hover_snap_value - lo) / span
                           : 0.5;
            t = std::clamp(t, 0.0, 1.0);
            const double x = column.x_left + 4.0 +
                             t * (kColumnWidthPx - 8.0);
            painter->setPen(QPen(Qt::white, 2.0));
            painter->setBrush(QBrush(QColor(31, 102, 212, 220)));
            painter->drawEllipse(QPointF(x, y), 4.5, 4.5);
        }
    }
    if (scene.show_cursor && std::isfinite(scene.cursor_depth) &&
        !columns.empty()) {
        const double y =
            column_depth_to_y(columns.front(), scene.cursor_depth);
        QPen pen(QColor(220, 38, 38), 1.0);
        pen.setStyle(Qt::DashLine);
        painter->setPen(pen);
        painter->drawLine(QPointF(kLeftMarginPx, y),
                          QPointF(width_px - kDepthRulerWidthPx, y));
    }
}

}  // namespace

void paint_section(QPainter* painter, const SectionScene& scene,
                   double width_px, double height_px) {
    painter->fillRect(QRectF(0, 0, width_px, height_px),
                      QColor(0xfa, 0xf9, 0xf5));
    if (scene.wells.empty()) {
        painter->setPen(QPen(QColor(0x2d, 0x37, 0x48), 1.0));
        painter->drawText(QRectF(0, 0, width_px, height_px),
                          Qt::AlignCenter, QStringLiteral("无井数据"));
        return;
    }
    const std::vector<ColumnLayout> columns =
        layout_columns(scene, width_px, height_px);
    for (const ColumnLayout& column : columns) {
        paint_column(painter, scene,
                     scene.wells[column.index], column);
    }
    paint_tops(painter, scene, columns);
    paint_ties(painter, scene, columns);
    paint_depth_ruler(painter, scene, columns, width_px, height_px);
    paint_twt_axis(painter, scene, columns, height_px);
    paint_hover_and_cursor(painter, scene, columns, width_px);
}

bool export_section_composite(const SectionScene& scene, const QString& path,
                              const QString& fmt, int dpi,
                              const std::optional<int>& width_px,
                              const std::optional<QString>& page_size) {
    if (scene.wells.empty()) return false;
    const double natural_w =
        kLeftMarginPx * 2.0 +
        scene.wells.size() * kColumnWidthPx +
        (scene.wells.size() - 1) * kWellSpacingPx + kDepthRulerWidthPx;
    const double natural_h = 640.0;
    double scale = 1.0;
    if (width_px.has_value() && *width_px > 0 && !page_size.has_value()) {
        scale = static_cast<double>(*width_px) / natural_w;
    }
    const int total_w =
        std::max(1, static_cast<int>(std::lround(natural_w * scale)));
    const int total_h =
        std::max(1, static_cast<int>(std::lround(natural_h * scale)));

    const std::string format = fmt.toLower().toStdString();
    if (format == "png") {
        QImage image(total_w, total_h, QImage::Format_ARGB32);
        image.fill(Qt::white);
        image.setDotsPerMeterX(static_cast<int>(dpi / 0.0254));
        image.setDotsPerMeterY(static_cast<int>(dpi / 0.0254));
        QPainter painter(&image);
        painter.scale(static_cast<double>(total_w) / natural_w,
                      static_cast<double>(total_h) / natural_h);
        paint_section(&painter, scene, natural_w, natural_h);
        painter.end();
        return image.save(path, "PNG");
    }
    if (format == "svg") {
        QSvgGenerator generator;
        generator.setFileName(path);
        generator.setSize(QSize(total_w, total_h));
        generator.setViewBox(QRectF(0, 0, total_w, total_h));
        QPainter painter(&generator);
        if (!painter.isActive()) return false;
        painter.scale(static_cast<double>(total_w) / natural_w,
                      static_cast<double>(total_h) / natural_h);
        paint_section(&painter, scene, natural_w, natural_h);
        painter.end();
        return QFileInfo::exists(path);
    }
    if (format == "pdf") {
        QPrinter printer(QPrinter::HighResolution);
        printer.setOutputFormat(QPrinter::PdfFormat);
        printer.setOutputFileName(path);
        printer.setResolution(dpi);
        double fit = static_cast<double>(total_w) / natural_w;
        if (page_size.has_value()) {
            const QString name = page_size->toUpper();
            const QPageSize::PageSizeId id =
                name == "LETTER" ? QPageSize::Letter : QPageSize::A4;
            printer.setPageSize(QPageSize(id));
            if (natural_w > natural_h) {
                printer.setPageOrientation(QPageLayout::Landscape);
            }
            const QSizeF points =
                printer.pageLayout().pageSize().size(QPageSize::Point);
            const double px_w = points.width() * dpi / 72.0;
            const double px_h = points.height() * dpi / 72.0;
            fit = std::min(px_w / natural_w, px_h / natural_h);
        } else {
            const double mm_w = total_w * 25.4 / dpi;
            const double mm_h = total_h * 25.4 / dpi;
            printer.setPageSize(
                QPageSize(QSizeF(mm_w, mm_h), QPageSize::Millimeter));
        }
        QPainter painter(&printer);
        if (!painter.isActive()) return false;
        painter.scale(fit, fit);
        paint_section(&painter, scene, natural_w, natural_h);
        painter.end();
        return QFileInfo::exists(path);
    }
    return false;
}

// ---------------------------------------------------------------------------
// Widget

struct SectionCanvas::Impl {
    std::vector<WellColumnData> wells;
    FormationTopsModel* tops_model = nullptr;
    HorizonPicksModel* picks_model = nullptr;
    SeismicTie tie;
    SectionView view;
    bool pick_mode = false;
    bool show_tops = true;
    bool panning = false;
    double pan_start_y = 0.0;
    SectionView pan_start_view;
    QString active_formation;
    std::string active_pick_id;
    std::string hover_pick_id;
    std::string active_curve = "GR";
    pwb::viz::cross_well::SnapType snap_type =
        pwb::viz::cross_well::SnapType::kNone;
    double snap_window_m = pwb::viz::cross_well::kDefaultSnapWindowM;
    int hover_well_index = -1;
    double hover_snap_depth = std::numeric_limits<double>::quiet_NaN();
    double hover_snap_value = std::numeric_limits<double>::quiet_NaN();
    std::string depth_domain = "MD";

    [[nodiscard]] std::vector<ColumnLayout>
    columns(double width_px, double height_px) const {
        SectionScene scene;
        scene.wells = wells;
        scene.view = view;
        return layout_columns(scene, width_px, height_px);
    }

    [[nodiscard]] std::optional<std::size_t> column_at(double x) const {
        for (std::size_t i = 0; i < wells.size(); ++i) {
            const double left = kLeftMarginPx +
                                static_cast<double>(i) *
                                    (kColumnWidthPx + kWellSpacingPx);
            if (x >= left && x <= left + kColumnWidthPx) return i;
        }
        return std::nullopt;
    }
};

SectionCanvas::SectionCanvas(QWidget* parent)
    : QWidget(parent), impl_(std::make_unique<Impl>()) {
    setMouseTracking(true);
    setMinimumSize(320, 240);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
}

SectionCanvas::~SectionCanvas() = default;

void SectionCanvas::set_wells(const std::vector<WellColumnData>& wells) {
    impl_->wells = wells;
    // Fill display curves via the canonical preference order.
    const std::vector<std::string> preferred = {"GR", "SP", "RT"};
    for (WellColumnData& column : impl_->wells) {
        if (column.display_curve.depths.empty()) {
            if (auto curve = pwb::viz::cross_well::extract_curve(
                    column.curves, preferred)) {
                column.display_curve = std::move(*curve);
            }
        }
    }
    if (!impl_->wells.empty()) {
        // Shared viewport: union of curve depth extents.
        double lo = std::numeric_limits<double>::infinity();
        double hi = -std::numeric_limits<double>::infinity();
        for (const WellColumnData& column : impl_->wells) {
            for (double d : column.display_curve.depths) {
                if (!std::isfinite(d)) continue;
                lo = std::min(lo, d);
                hi = std::max(hi, d);
            }
        }
        if (std::isfinite(lo) && std::isfinite(hi) && hi > lo) {
            impl_->view.depth_top = lo;
            impl_->view.depth_bottom = hi;
        } else {
            impl_->view.depth_top = 0.0;
            impl_->view.depth_bottom = 100.0;
        }
    }
    update();
}

void SectionCanvas::set_models(FormationTopsModel* tops,
                               HorizonPicksModel* picks) {
    impl_->tops_model = tops;
    impl_->picks_model = picks;
    update();
}

void SectionCanvas::set_seismic_tie(const SeismicTie& tie) {
    impl_->tie = tie;
    update();
}

void SectionCanvas::set_pick_mode(bool on) {
    impl_->pick_mode = on;
    if (!on) {
        impl_->active_pick_id.clear();
        impl_->active_formation.clear();
        setCursor(Qt::ArrowCursor);
    } else {
        setCursor(Qt::CrossCursor);
    }
    update();
}

void SectionCanvas::set_active_formation(const QString& formation) {
    impl_->active_formation = formation;
}

void SectionCanvas::set_snap(pwb::viz::cross_well::SnapType type,
                             double window_m) {
    impl_->snap_type = type;
    impl_->snap_window_m = window_m;
}

void SectionCanvas::set_show_tops(bool show) {
    impl_->show_tops = show;
    update();
}

void SectionCanvas::set_depth_domain(const QString& domain) {
    const std::string value = domain.toStdString();
    impl_->depth_domain = value == "TWT" ? "TWT" : "MD";
    update();
}

void SectionCanvas::zoom_full() {
    set_wells(impl_->wells);
}

SectionScene SectionCanvas::build_scene() const {
    SectionScene scene;
    scene.wells = impl_->wells;
    scene.view = impl_->view;
    scene.show_tops = impl_->show_tops;
    scene.depth_domain = impl_->depth_domain;
    scene.tie = impl_->tie;
    scene.selected_pick = impl_->active_pick_id;
    scene.hover_pick = impl_->hover_pick_id;
    scene.hover_well_index = impl_->hover_well_index;
    scene.hover_snap_depth = impl_->hover_snap_depth;
    scene.hover_snap_value = impl_->hover_snap_value;
    if (std::isfinite(cursor_depth_.value_or(
            std::numeric_limits<double>::quiet_NaN()))) {
        scene.show_cursor = true;
        scene.cursor_depth = *cursor_depth_;
    }
    if (impl_->tops_model != nullptr) {
        for (const FormationTop& top : impl_->tops_model->all_tops()) {
            scene.tops.push_back(top);
        }
    }
    if (impl_->picks_model != nullptr) {
        for (const HorizonPick* pick : impl_->picks_model->all_picks()) {
            scene.picks.push_back(*pick);
        }
    }
    return scene;
}

std::vector<std::string> SectionCanvas::well_names() const {
    std::vector<std::string> names;
    names.reserve(impl_->wells.size());
    for (const WellColumnData& well : impl_->wells) {
        names.push_back(well.name);
    }
    return names;
}

void SectionCanvas::paintEvent(QPaintEvent*) {
    QPainter painter(this);
    paint_section(&painter, build_scene(), static_cast<double>(width()),
                  static_cast<double>(height()));
}

void SectionCanvas::mouseMoveEvent(QMouseEvent* event) {
    const QPointF pos = event->position();
    const double x = pos.x();
    const double y = pos.y();
    if (impl_->panning) {
        const double content_h =
            static_cast<double>(height()) - kColumnNameBandPx -
            pwb::viz::cross_well::kDefaultHeaderHeightPx;
        const double span = impl_->pan_start_view.span();
        if (content_h > 0.0 && span > 0.0) {
            const double shift =
                -(y - impl_->pan_start_y) / content_h * span;
            impl_->view.depth_top = impl_->pan_start_view.depth_top + shift;
            impl_->view.depth_bottom =
                impl_->pan_start_view.depth_bottom + shift;
        }
        update();
        return;
    }
    const auto index = impl_->column_at(x);
    std::optional<double> depth;
    if (index.has_value()) {
        const auto columns =
            impl_->columns(width(), height());
        if (*index < columns.size()) {
            depth = column_y_to_depth(columns[*index], y);
        }
    }
    if (depth.has_value()) {
        cursor_depth_ = *depth;
        emit cursor_moved(*depth);
        impl_->hover_well_index =
            static_cast<int>(index.value_or(0));
        // Snap preview.
        double snapped = *depth;
        double value = std::numeric_limits<double>::quiet_NaN();
        if (*index < impl_->wells.size()) {
            const WellColumnData& well = impl_->wells[*index];
            pwb::viz::cross_well::SnapInput snap_input{
                well.display_curve.depths, well.display_curve.values};
            snapped = pwb::viz::cross_well::snapped_depth(
                snap_input, *depth, impl_->snap_type, impl_->snap_window_m);
            // Nearest sample value for the dot.
            double best = std::numeric_limits<double>::infinity();
            for (std::size_t i = 0; i < well.display_curve.depths.size();
                 ++i) {
                const double d = std::abs(well.display_curve.depths[i] -
                                          snapped);
                if (d < best) {
                    best = d;
                    value = well.display_curve.values[i];
                }
            }
        }
        impl_->hover_snap_depth = snapped;
        impl_->hover_snap_value = value;
    } else {
        impl_->hover_well_index = -1;
    }
    // Hover pick hit test.
    std::string hover;
    if (depth.has_value() && index.has_value() &&
        impl_->picks_model != nullptr) {
        const auto columns = impl_->columns(width(), height());
        std::vector<pwb::viz::cross_well::PickHitCandidate> candidates;
        for (const HorizonPick* pick :
             impl_->picks_model->picks_for_well(
                 impl_->wells[*index].name)) {
            const std::optional<double> d =
                pick->depth_for_well(impl_->wells[*index].name);
            if (d.has_value()) {
                candidates.push_back({*d, pick->pick_id});
            }
        }
        if (*index < columns.size()) {
            hover = pwb::viz::cross_well::pick_hit_test(
                        candidates, *depth, columns[*index].geometry)
                        .value_or("");
        }
    }
    if (hover != impl_->hover_pick_id) {
        impl_->hover_pick_id = hover;
    }
    update();
}

void SectionCanvas::mousePressEvent(QMouseEvent* event) {
    if (!impl_->pick_mode) {
        if (event->button() == Qt::LeftButton) {
            impl_->panning = true;
            impl_->pan_start_y = event->position().y();
            impl_->pan_start_view = impl_->view;
            setCursor(Qt::ClosedHandCursor);
        }
        return;
    }
    const QPointF pos = event->position();
    const auto index = impl_->column_at(pos.x());
    if (!index.has_value() || *index >= impl_->wells.size() ||
        impl_->picks_model == nullptr) {
        return;
    }
    const auto columns = impl_->columns(width(), height());
    if (*index >= columns.size()) return;
    const std::string well_name = impl_->wells[*index].name;
    const std::optional<double> depth =
        column_y_to_depth(columns[*index], pos.y());
    if (!depth.has_value()) return;

    if (event->button() == Qt::RightButton) {
        std::vector<pwb::viz::cross_well::PickHitCandidate> candidates;
        for (const HorizonPick* pick :
             impl_->picks_model->picks_for_well(well_name)) {
            const std::optional<double> d = pick->depth_for_well(well_name);
            if (d.has_value()) {
                candidates.push_back({*d, pick->pick_id});
            }
        }
        const auto hit = pwb::viz::cross_well::pick_hit_test(
            candidates, *depth, columns[*index].geometry);
        if (!hit.has_value()) return;
        const HorizonPick* pick = impl_->picks_model->get_pick(*hit);
        if (pick == nullptr) return;
        if (pick->source == "dtw") {
            impl_->picks_model->reject_dtw_pick(*hit);
        } else {
            impl_->picks_model->delete_pick(*hit);
        }
        if (impl_->active_pick_id == *hit) impl_->active_pick_id.clear();
        emit interaction_changed();
        update();
        return;
    }
    if (event->button() != Qt::LeftButton) return;

    // Hit an existing pick first (dtw accept).
    std::vector<pwb::viz::cross_well::PickHitCandidate> candidates;
    for (const HorizonPick* pick :
         impl_->picks_model->picks_for_well(well_name)) {
        const std::optional<double> d = pick->depth_for_well(well_name);
        if (d.has_value()) {
            candidates.push_back({*d, pick->pick_id});
        }
    }
    const auto hit = pwb::viz::cross_well::pick_hit_test(
        candidates, *depth, columns[*index].geometry);
    if (hit.has_value()) {
        const HorizonPick* pick = impl_->picks_model->get_pick(*hit);
        if (pick != nullptr && pick->source == "dtw") {
            impl_->picks_model->accept_dtw_pick(*hit);
            emit interaction_changed();
            update();
            return;
        }
    }

    // Snap on the active curve.
    double clicked = *depth;
    if (!impl_->wells[*index].display_curve.depths.empty()) {
        const pwb::viz::cross_well::SnapInput snap_input{
            impl_->wells[*index].display_curve.depths,
            impl_->wells[*index].display_curve.values};
        clicked = pwb::viz::cross_well::snapped_depth(
            snap_input, *depth, impl_->snap_type, impl_->snap_window_m);
    }

    if (event->modifiers() & Qt::ShiftModifier &&
        !impl_->active_pick_id.empty()) {
        impl_->picks_model->connect_picks(impl_->active_pick_id, well_name,
                                          clicked);
    } else {
        std::string formation =
            impl_->active_formation.toStdString();
        if (formation.empty()) {
            formation = "Horizon-" +
                        std::to_string(
                            impl_->picks_model->all_picks().size() + 1);
        }
        impl_->active_pick_id =
            impl_->picks_model->add_pick(formation, well_name, clicked);
        impl_->active_formation = QString::fromStdString(formation);
    }
    emit interaction_changed();
    update();
}

void SectionCanvas::mouseReleaseEvent(QMouseEvent*) {
    if (impl_->panning) {
        impl_->panning = false;
        setCursor(impl_->pick_mode ? Qt::CrossCursor : Qt::ArrowCursor);
    }
}

void SectionCanvas::wheelEvent(QWheelEvent* event) {
    const int delta = event->angleDelta().y();
    if (delta == 0) return;
    const double span = impl_->view.span();
    if (span <= 0.0) return;
    const double content_h =
        static_cast<double>(height()) - kColumnNameBandPx -
        pwb::viz::cross_well::kDefaultHeaderHeightPx;
    if (content_h <= 0.0) return;
    const double anchor = impl_->view.depth_top +
                          (event->position().y() - kColumnNameBandPx -
                           pwb::viz::cross_well::kDefaultHeaderHeightPx) /
                              content_h *
                              span;
    const double factor = delta > 0 ? 0.8 : 1.25;
    const double new_span = span * factor;
    const double ratio = (anchor - impl_->view.depth_top) / span;
    double lo = anchor - ratio * new_span;
    if (lo < 0.0) lo = 0.0;
    impl_->view.depth_top = lo;
    impl_->view.depth_bottom = lo + new_span;
    update();
    event->accept();
}

void SectionCanvas::leaveEvent(QEvent*) {
    impl_->hover_well_index = -1;
    impl_->hover_snap_depth = std::numeric_limits<double>::quiet_NaN();
    impl_->hover_snap_value = std::numeric_limits<double>::quiet_NaN();
    update();
}

}  // namespace pwb::viz::cross_well::qt
