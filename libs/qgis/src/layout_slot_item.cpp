// PwbLayoutSlotItem — implementation (see header for the design contract).
//
// Drawing follows the retired SVG composer's geometry semantics (mm layout
// space, SimSun/Arial families, ~2.4-3.6 mm font sizes) so migrated
// documents keep their visual intent while geometry/undo/export are native.
//
// Coordinate spaces inside draw():
//   - shapes: the painter is scaled so 1 unit == 1 mm (same geometry numbers
//     as the retired SVG composer viewBox);
//   - text: QgsTextRenderer on the *unscaled* painter with QgsTextFormat
//     sized in Millimeters — QGIS converts via the render context scale
//     factor, which stays correct for screen preview, PNG, PDF and SVG alike.

#include <pwb/qgis/layout_slot_item.hpp>

#include <qgsapplication.h>
#include <qgslayout.h>
#include <qgslayoutitemregistry.h>
#include <qgsrendercontext.h>
#include <qgstextformat.h>
#include <qgstextrenderer.h>

#include <QDomDocument>
#include <QDomElement>
#include <QLinearGradient>
#include <QPainter>
#include <QPainterPath>
#include <QPen>
#include <QStringList>

#include <algorithm>
#include <cmath>
#include <optional>
#include <string>
#include <vector>

namespace pwb::qgis {

namespace {

using domain::Json;

const Json& prop(const Json& properties, const char* key) {
    static const Json kNull;
    if (!properties.is_object()) return kNull;
    const auto it = properties.find(key);
    return it == properties.end() ? kNull : *it;
}

std::string prop_str(const Json& properties, const char* key,
                     const std::string& fallback = {}) {
    const Json& v = prop(properties, key);
    return v.is_string() ? v.get<std::string>() : fallback;
}

double prop_num(const Json& properties, const char* key, double fallback) {
    const Json& v = prop(properties, key);
    if (v.is_number()) return v.get<double>();
    return fallback;
}

std::vector<double> prop_nums(const Json& arr) {
    std::vector<double> out;
    if (!arr.is_array()) return out;
    for (const Json& v : arr) {
        if (v.is_number()) out.push_back(v.get<double>());
    }
    return out;
}

// [{label,value}] series → parallel vectors (composer series_entries).
void series_entries(const Json& series, std::vector<std::string>& labels,
                    std::vector<double>& values) {
    if (!series.is_array()) return;
    for (const Json& entry : series) {
        if (entry.is_object()) {
            const auto l = entry.find("label");
            const auto v = entry.find("value");
            if (v != entry.end() && v->is_number()) {
                labels.push_back(l != entry.end() && l->is_string()
                                     ? l->get<std::string>()
                                     : std::string());
                values.push_back(v->get<double>());
            }
        } else if (entry.is_array() && entry.size() >= 2 && entry[0].is_string() &&
                   entry[1].is_number()) {
            labels.push_back(entry[0].get<std::string>());
            values.push_back(entry[1].get<double>());
        } else if (entry.is_number()) {
            labels.emplace_back();
            values.push_back(entry.get<double>());
        }
    }
}

// Default categorical palette (composer renderer chart_colors default).
QColor series_color(std::size_t index) {
    static const std::vector<QColor> kPalette{
        QColor("#1f77b4"), QColor("#ff7f0e"), QColor("#2ca02c"), QColor("#d62728"),
        QColor("#9467bd"), QColor("#8c564b"), QColor("#e377c2"), QColor("#7f7f7f"),
    };
    return kPalette[index % kPalette.size()];
}

QString from_utf8(const std::string& text) {
    return QString::fromStdString(text);
}

// Draws one text run sized in millimetres via the QGIS text pipeline.
// `at` is in mm item-local coordinates; `rotation_deg` is CCW.
void text_mm(QgsRenderContext& context, const QString& text, QPointF at_mm,
             double size_mm, bool bold, const QColor& color, bool centered,
             double rotation_deg = 0.0) {
    if (text.isEmpty()) return;
    const double s = context.convertToPainterUnits(1, Qgis::RenderUnit::Millimeters);
    QgsTextFormat format;
    QFont font;
    font.setFamilies({"SimSun", "Arial"});
    font.setBold(bold);
    format.setFont(font);
    format.setSize(size_mm);
    format.setSizeUnit(Qgis::RenderUnit::Millimeters);
    format.setColor(color);
    QgsTextRenderer::drawText(
        QPointF(at_mm.x() * s, at_mm.y() * s), rotation_deg,
        centered ? Qgis::TextHorizontalAlignment::Center
                 : Qgis::TextHorizontalAlignment::Left,
        QStringList{text}, context, format);
}

// RAII: shapes drawn inside the scope run in mm coordinates.
class MmShapes {
public:
    MmShapes(QPainter& painter, double px_per_mm) : painter_(painter) {
        painter_.save();
        painter_.scale(px_per_mm, px_per_mm);
    }
    ~MmShapes() { painter_.restore(); }

private:
    QPainter& painter_;
};

}  // namespace

const char* PwbLayoutSlotItem::kind_key(Kind kind) noexcept {
    switch (kind) {
        case Kind::StatChart: return "stat_chart";
        case Kind::Colorbar: return "colorbar";
        case Kind::Timescale: return "timescale";
        case Kind::Profile: return "profile";
        case Kind::FaultSymbols: return "fault_symbols";
        case Kind::LithologyLegend: return "lithology_legend";
        case Kind::Placeholder: return "placeholder";
    }
    return "placeholder";
}

std::optional<PwbLayoutSlotItem::Kind> PwbLayoutSlotItem::kind_from_string(
    const std::string& text) {
    if (text == "stat_chart") return Kind::StatChart;
    if (text == "colorbar") return Kind::Colorbar;
    if (text == "timescale") return Kind::Timescale;
    if (text == "profile") return Kind::Profile;
    if (text == "fault_symbols") return Kind::FaultSymbols;
    if (text == "lithology_legend") return Kind::LithologyLegend;
    if (text == "placeholder") return Kind::Placeholder;
    return std::nullopt;
}

PwbLayoutSlotItem::PwbLayoutSlotItem(QgsLayout* layout)
    : QgsLayoutItem(layout) {}

PwbLayoutSlotItem::~PwbLayoutSlotItem() = default;

QgsLayoutItem* PwbLayoutSlotItem::create(QgsLayout* layout) {
    return new PwbLayoutSlotItem(layout);
}

QIcon PwbLayoutSlotItem::icon() const {
    return QgsApplication::getThemeIcon("/mActionAddBasicShape.svg");
}

std::string PwbLayoutSlotItem::kind_string() const {
    return kind_key(kind_);
}

void PwbLayoutSlotItem::set_slot_properties(domain::Json properties) {
    properties_ = properties.is_object() ? std::move(properties) : Json::object();
    refresh();
}

void PwbLayoutSlotItem::ensure_registered() {
    QgsLayoutItemRegistry* registry = QgsApplication::layoutItemRegistry();
    if (registry == nullptr) return;
    if (registry->itemMetadata(ItemTypeId) != nullptr) return;
    registry->addLayoutItemType(new QgsLayoutItemMetadata(
        ItemTypeId, QObject::tr("PWB Slot Item"),
        QObject::tr("PWB Slot Items"), &PwbLayoutSlotItem::create));
}

void PwbLayoutSlotItem::draw(QgsLayoutItemRenderContext& context) {
    QgsRenderContext render_context = context.renderContext();
    QPainter* painter = render_context.painter();
    if (painter == nullptr) return;
    const double w_mm = rect().width();
    const double h_mm = rect().height();
    if (!(w_mm > 0.0) || !(h_mm > 0.0)) return;
    const double s =
        render_context.convertToPainterUnits(1, Qgis::RenderUnit::Millimeters);
    switch (kind_) {
        case Kind::StatChart: draw_stat_chart(*painter, render_context, s, w_mm, h_mm); break;
        case Kind::Colorbar: draw_colorbar(*painter, render_context, s, w_mm, h_mm); break;
        case Kind::Timescale: draw_timescale(*painter, render_context, s, w_mm, h_mm); break;
        case Kind::Profile: draw_profile(*painter, s, w_mm, h_mm); break;
        case Kind::FaultSymbols:
        case Kind::LithologyLegend:
            draw_symbol_legend(*painter, render_context, s, w_mm, h_mm);
            break;
        case Kind::Placeholder: draw_placeholder(*painter, s, w_mm, h_mm); break;
    }
}

bool PwbLayoutSlotItem::writePropertiesToElement(
    QDomElement& element, QDomDocument& document,
    const QgsReadWriteContext& /*context*/) const {
    QDomElement props = document.createElement(QStringLiteral("PwbSlotItem"));
    props.setAttribute(QStringLiteral("kind"),
                       QString::fromStdString(kind_string()));
    props.setAttribute(QStringLiteral("slot"), QString::fromStdString(slot_name_));
    props.appendChild(document.createTextNode(QString::fromStdString(
        properties_.dump())));
    element.appendChild(props);
    return true;
}

bool PwbLayoutSlotItem::readPropertiesFromElement(
    const QDomElement& element, const QDomDocument& /*document*/,
    const QgsReadWriteContext& /*context*/) {
    const QDomElement props =
        element.firstChildElement(QStringLiteral("PwbSlotItem"));
    if (props.isNull()) return false;
    const auto parsed_kind =
        kind_from_string(props.attribute(QStringLiteral("kind")).toStdString());
    kind_ = parsed_kind.value_or(Kind::Placeholder);
    slot_name_ = props.attribute(QStringLiteral("slot")).toStdString();
    try {
        properties_ = domain::Json::parse(props.text().toStdString());
    } catch (const std::exception&) {
        properties_ = Json::object();
    }
    if (!properties_.is_object()) properties_ = Json::object();
    return true;
}

// ---------------------------------------------------------------------------
// StatChart — pie/donut/histogram/rose/line/scatter/bar/hbar, series driven.
// ---------------------------------------------------------------------------

void PwbLayoutSlotItem::draw_stat_chart(QPainter& painter,
                                        QgsRenderContext& context, double s,
                                        double w_mm, double h_mm) {
    const std::string chart_type = prop_str(properties_, "chart_type", "bar");
    const std::string title = prop_str(properties_, "title");
    const Json& series = prop(properties_, "series");
    const Json& values_json = prop(properties_, "values");
    const double title_h = title.empty() ? 0.0 : 5.0;

    if (!title.empty()) {
        text_mm(context, from_utf8(title), QPointF(w_mm / 2.0, title_h - 1.2),
                3.2, /*bold=*/true, QColor(Qt::black), /*centered=*/true);
    }

    if (chart_type == "pie" || chart_type == "donut") {
        std::vector<std::string> labels;
        std::vector<double> values;
        series_entries(series, labels, values);
        std::vector<std::size_t> keep;
        for (std::size_t i = 0; i < values.size(); ++i) {
            if (values[i] > 0.0) keep.push_back(i);
        }
        double total = 0.0;
        for (std::size_t i : keep) total += values[i];
        const double radius =
            std::min(w_mm, h_mm - title_h) / 2.0 - 2.0;
        if (keep.empty() || total <= 0.0 || radius <= 1.0) {
            draw_placeholder(painter, s, w_mm, h_mm);
            return;
        }
        const double cx = w_mm / 2.0;
        const double cy = title_h + (h_mm - title_h) / 2.0;
        QPainterPath pie;
        pie.moveTo(cx, cy);
        const QRectF rect(cx - radius, cy - radius, radius * 2.0, radius * 2.0);
        double start_angle = 90.0;  // 12 o'clock, clockwise sweep
        {
            MmShapes mm(painter, s);
            for (std::size_t k = 0; k < keep.size(); ++k) {
                const double span = values[keep[k]] / total * 360.0;
                painter.setBrush(QBrush(series_color(k)));
                painter.setPen(QPen(QColor("#ffffff"), 0.2));
                pie.arcTo(rect, start_angle, -span);
                pie.closeSubpath();
                painter.drawPath(pie);
                pie = QPainterPath();
                pie.moveTo(cx, cy);
                start_angle -= span;
            }
            if (chart_type == "donut") {
                const double hole = prop_num(properties_, "hole_ratio", 0.55);
                const QColor page = Qt::white;
                painter.setPen(Qt::NoPen);
                painter.setBrush(page);
                painter.drawEllipse(QPointF(cx, cy), radius * hole, radius * hole);
            }
        }
        return;
    }

    if (chart_type == "rose") {
        std::vector<const Json*> entries;
        if (series.is_array()) {
            for (const Json& e : series) {
                if (e.is_object()) entries.push_back(&e);
            }
        }
        double vmax = 0.0;
        for (const Json* e : entries) {
            const auto v = e->find("value");
            if (v != e->end() && v->is_number()) vmax = std::max(vmax, v->get<double>());
        }
        const double radius = std::min(w_mm, h_mm - title_h) / 2.0 - 2.0;
        if (entries.empty() || vmax <= 0.0 || radius <= 1.0) {
            draw_placeholder(painter, s, w_mm, h_mm);
            return;
        }
        const double cx = w_mm / 2.0;
        const double cy = title_h + (h_mm - title_h) / 2.0;
        const double span_deg = 360.0 / static_cast<double>(entries.size());
        {
            MmShapes mm(painter, s);
            for (std::size_t k = 0; k < entries.size(); ++k) {
                const Json* e = entries[k];
                double angle = 0.0, value = 0.0;
                const auto a = e->find("angle_deg");
                const auto v = e->find("value");
                if (a != e->end() && a->is_number()) angle = a->get<double>();
                if (v != e->end() && v->is_number()) value = v->get<double>();
                const double r = radius * std::sqrt(value / vmax);
                QPainterPath sector;
                sector.moveTo(cx, cy);
                // North = 0°, clockwise; Qt angles are CCW → mirror.
                const double start = angle - span_deg / 2.0;
                sector.arcTo(QRectF(cx - r, cy - r, r * 2.0, r * 2.0),
                             90.0 - start - span_deg, span_deg);
                sector.closeSubpath();
                painter.setBrush(QBrush(series_color(k)));
                painter.setPen(QPen(QColor("#37474f"), 0.15));
                painter.drawPath(sector);
            }
        }
        return;
    }

    if (chart_type == "line" || chart_type == "scatter") {
        std::vector<double> xs, ys;
        if (series.is_array()) {
            for (const Json& e : series) {
                if (e.is_object()) {
                    const auto x = e.find("x");
                    const auto y = e.find("y");
                    if (y != e.end() && y->is_number()) {
                        xs.push_back(x != e.end() && x->is_number()
                                         ? x->get<double>()
                                         : static_cast<double>(xs.size()));
                        ys.push_back(y->get<double>());
                    }
                }
            }
        }
        if (ys.empty()) {
            draw_placeholder(painter, s, w_mm, h_mm);
            return;
        }
        double xmin = xs.front(), xmax = xs.front(), ymin = ys.front(), ymax = ys.front();
        for (std::size_t i = 0; i < ys.size(); ++i) {
            xmin = std::min(xmin, xs[i]);
            xmax = std::max(xmax, xs[i]);
            ymin = std::min(ymin, ys[i]);
            ymax = std::max(ymax, ys[i]);
        }
        if (xmax - xmin <= 0.0) xmax = xmin + 1.0;
        if (ymax - ymin <= 0.0) ymax = ymin + 1.0;
        const double left = 8.0, bottom = 6.0;
        const double pw = std::max(2.0, w_mm - left - 2.0);
        const double ph = std::max(2.0, h_mm - title_h - bottom - 2.0);
        const double top = title_h + 2.0;
        const auto map_x = [&](double x) { return left + (x - xmin) / (xmax - xmin) * pw; };
        const auto map_y = [&](double y) {
            return top + (1.0 - (y - ymin) / (ymax - ymin)) * ph;
        };
        {
            MmShapes mm(painter, s);
            painter.setBrush(Qt::NoBrush);
            painter.setPen(QPen(QColor("#90a4ae"), 0.12));
            painter.drawRect(QRectF(left, top, pw, ph));
            if (chart_type == "scatter") {
                painter.setPen(Qt::NoPen);
                painter.setBrush(QBrush(QColor("#1f77b4")));
                for (std::size_t i = 0; i < ys.size(); ++i) {
                    painter.drawEllipse(QPointF(map_x(xs[i]), map_y(ys[i])), 0.5, 0.5);
                }
            } else {
                QPainterPath path;
                path.moveTo(map_x(xs[0]), map_y(ys[0]));
                for (std::size_t i = 1; i < ys.size(); ++i) {
                    path.lineTo(map_x(xs[i]), map_y(ys[i]));
                }
                painter.setBrush(Qt::NoBrush);
                painter.setPen(QPen(QColor("#1f77b4"), 0.3));
                painter.drawPath(path);
            }
        }
        return;
    }

    // bar / hbar / histogram share the value-bars treatment.
    std::vector<std::string> labels;
    std::vector<double> values;
    if (chart_type == "histogram") {
        values = prop_nums(values_json);
        const int bins = static_cast<int>(prop_num(properties_, "bins", 10));
        if (!values.empty() && bins > 0) {
            double vmin = values.front(), vmax2 = values.front();
            for (double v : values) {
                vmin = std::min(vmin, v);
                vmax2 = std::max(vmax2, v);
            }
            if (vmax2 - vmin <= 0.0) vmax2 = vmin + 1.0;
            std::vector<double> counts(static_cast<std::size_t>(bins), 0.0);
            for (double v : values) {
                std::size_t bin = static_cast<std::size_t>(
                    (v - vmin) / (vmax2 - vmin) * bins);
                if (bin >= counts.size()) bin = counts.size() - 1;
                counts[bin] += 1.0;
            }
            values = counts;
        }
    } else {
        series_entries(series, labels, values);
    }
    double vmax = 0.0;
    for (double v : values) vmax = std::max(vmax, v);
    if (values.empty() || vmax <= 0.0) {
        draw_placeholder(painter, s, w_mm, h_mm);
        return;
    }
    const double left = 8.0, bottom = 5.0;
    const double pw = std::max(2.0, w_mm - left - 2.0);
    const double ph = std::max(2.0, h_mm - title_h - bottom - 2.0);
    const double top = title_h + 2.0;
    {
        MmShapes mm(painter, s);
        painter.setBrush(Qt::NoBrush);
        painter.setPen(QPen(QColor("#90a4ae"), 0.12));
        painter.drawRect(QRectF(left, top, pw, ph));
        if (chart_type == "hbar") {
            const double row_h = ph / static_cast<double>(values.size());
            for (std::size_t i = 0; i < values.size(); ++i) {
                const double bw = values[i] / vmax * pw;
                painter.setPen(Qt::NoPen);
                painter.setBrush(series_color(i));
                painter.drawRect(QRectF(left, top + i * row_h, bw, row_h * 0.7));
            }
        } else {
            const double col_w = pw / static_cast<double>(values.size());
            for (std::size_t i = 0; i < values.size(); ++i) {
                const double bh = values[i] / vmax * ph;
                painter.setPen(Qt::NoPen);
                painter.setBrush(series_color(i));
                painter.drawRect(QRectF(left + i * col_w + col_w * 0.15,
                                        top + ph - bh, col_w * 0.7, bh));
            }
        }
    }
    (void)labels;
}

// ---------------------------------------------------------------------------
// Colorbar — vertical ramp (discrete swatches or continuous gradient).
// ---------------------------------------------------------------------------

void PwbLayoutSlotItem::draw_colorbar(QPainter& painter, QgsRenderContext& context,
                                      double s, double w_mm, double h_mm) {
    const std::string title = prop_str(properties_, "title");
    const double vmin = prop_num(properties_, "min", 0.0);
    const double vmax = prop_num(properties_, "max", 1.0);
    const Json& discrete_json = prop(properties_, "discrete");
    const bool discrete = discrete_json.is_boolean() && discrete_json.get<bool>();

    std::vector<std::pair<double, QColor>> stops;
    if (const Json& raw = prop(properties_, "stops"); raw.is_array()) {
        for (const Json& stop : raw) {
            if (stop.is_array() && stop.size() >= 2 && stop[0].is_number() &&
                stop[1].is_string()) {
                stops.emplace_back(stop[0].get<double>(),
                                   QColor(stop[1].get<std::string>().c_str()));
            }
        }
    }
    if (stops.empty()) {
        stops = {{0.0, QColor("#053061")}, {1.0, QColor("#67001f")}};
    }
    std::stable_sort(stops.begin(), stops.end(),
                     [](const auto& a, const auto& b) { return a.first < b.first; });

    const double bar_w = std::min(10.0, w_mm * 0.8);
    const double title_h = title.empty() ? 0.0 : 6.0;
    const double label_h = 10.0;
    const double bar_y = title_h;
    const double bar_h = std::max(4.0, h_mm - title_h - label_h);
    const double bar_x = title.empty() ? 1.0 : 5.0;

    {
        MmShapes mm(painter, s);
        if (discrete) {
            // Stop 0 sits at the BOTTOM (vmin label side), matching the
            // continuous gradient direction.
            const double seg = bar_h / static_cast<double>(stops.size());
            for (std::size_t i = 0; i < stops.size(); ++i) {
                painter.setPen(Qt::NoPen);
                painter.setBrush(stops[i].second);
                painter.drawRect(QRectF(bar_x, bar_y + bar_h - (i + 1) * seg,
                                         bar_w, seg));
            }
        } else {
            QLinearGradient gradient(bar_x, bar_y + bar_h, bar_x, bar_y);
            for (const auto& [pos, color] : stops) {
                gradient.setColorAt(std::clamp(pos, 0.0, 1.0), color);
            }
            painter.setPen(Qt::NoPen);
            painter.setBrush(QBrush(gradient));
            painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h));
        }
        painter.setBrush(Qt::NoBrush);
        painter.setPen(QPen(QColor("#333333"), 0.2));
        painter.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h));
    }

    if (!title.empty()) {
        // Rotated caption along the left edge (composer parity, -90°).
        text_mm(context, from_utf8(title),
                QPointF(bar_x - 1.2, bar_y + bar_h / 2.0), 3.2, /*bold=*/false,
                QColor(Qt::black), /*centered=*/true, /*rotation=*/-90.0);
    }
    const QString unit = from_utf8(prop_str(properties_, "units"));
    text_mm(context, QString("%1").arg(vmin, 0, 'g', 6) + unit,
            QPointF(bar_x + bar_w + 1.5, bar_y + bar_h + 2.0), 2.4, false,
            QColor(Qt::black), false);
    text_mm(context, QString("%1").arg(vmax, 0, 'g', 6) + unit,
            QPointF(bar_x + bar_w + 1.5, bar_y + 1.0), 2.4, false,
            QColor(Qt::black), false);
}

// ---------------------------------------------------------------------------
// FaultSymbols / LithologyLegend — line-style / swatch legend columns.
// ---------------------------------------------------------------------------

void PwbLayoutSlotItem::draw_symbol_legend(QPainter& painter,
                                           QgsRenderContext& context, double s,
                                           double w_mm, double h_mm) {
    const bool lithology = kind_ == Kind::LithologyLegend;
    const std::string title =
        prop_str(properties_, "title", lithology ? "岩性图例" : "断层符号");
    const Json& raw_items = prop(properties_, "items");
    std::vector<const Json*> items;
    if (raw_items.is_array()) {
        for (const Json& it : raw_items) {
            if (it.is_object()) items.push_back(&it);
        }
    }
    text_mm(context, from_utf8(title), QPointF(0.0, 4.2),
            lithology ? 3.6 : 3.4, /*bold=*/true, QColor(Qt::black), false);

    const double item_h = lithology ? 6.0 : 5.2;
    const double sample_len = std::min(12.0, w_mm * 0.35);
    for (std::size_t idx = 0; idx < items.size(); ++idx) {
        const double iy = 7.0 + static_cast<double>(idx) * item_h;
        if (iy > h_mm - 1.0) break;
        const Json* item = items[idx];
        const auto item_str = [&](const char* key, const std::string& fallback = {}) {
            const auto it = item->find(key);
            return it != item->end() && it->is_string() ? it->get<std::string>()
                                                        : fallback;
        };
        if (lithology) {
            const QColor color(item_str("color", "#cfd8dc").c_str());
            {
                MmShapes mm(painter, s);
                painter.setBrush(QBrush(color));
                painter.setPen(QPen(QColor("#333333"), 0.15));
                painter.drawRect(QRectF(3.0, iy, 9.0, 3.6));
            }
            text_mm(context, from_utf8(item_str("label")), QPointF(14.5, iy + 1.8),
                    2.8, false, QColor(Qt::black), false);
        } else {
            std::string pattern = item_str("pattern", "solid");
            std::transform(pattern.begin(), pattern.end(), pattern.begin(),
                           [](unsigned char c) {
                               return static_cast<char>(std::tolower(c));
                           });
            QVector<qreal> dash;
            if (pattern == "dash") dash = {2.4, 1.2};
            else if (pattern == "dot") dash = {0.6, 0.9};
            else if (pattern == "dashdot") dash = {2.8, 1.0, 0.6, 1.0};
            else if (pattern == "fault") dash = {3.2, 1.2};
            {
                MmShapes mm(painter, s);
                QPen pen(QColor("#1a1a1a"), 0.55);
                if (!dash.isEmpty()) pen.setDashPattern(dash);
                painter.setPen(pen);
                painter.drawLine(QPointF(2.0, iy + 0.9),
                                 QPointF(2.0 + sample_len, iy + 0.9));
            }
            text_mm(context, from_utf8(item_str("label")),
                    QPointF(2.0 + sample_len + 2.5, iy + 1.8), 2.6, false,
                    QColor(Qt::black), false);
        }
    }
}

// ---------------------------------------------------------------------------
// Timescale — weighted stratigraphic stages strip.
// ---------------------------------------------------------------------------

void PwbLayoutSlotItem::draw_timescale(QPainter& painter, QgsRenderContext& context,
                                       double s, double w_mm, double h_mm) {
    const Json& raw_stages = prop(properties_, "stages");
    std::vector<const Json*> stages;
    if (raw_stages.is_array()) {
        for (const Json& s_entry : raw_stages) {
            if (s_entry.is_object()) stages.push_back(&s_entry);
        }
    }
    if (stages.empty()) {
        draw_placeholder(painter, s, w_mm, h_mm);
        return;
    }
    std::vector<double> weights;
    weights.reserve(stages.size());
    for (const Json* stage : stages) {
        double start = 0.0, end = 0.0;
        const auto s_it = stage->find("start");
        const auto e_it = stage->find("end");
        if (s_it != stage->end() && s_it->is_number()) start = s_it->get<double>();
        if (e_it != stage->end() && e_it->is_number()) end = e_it->get<double>();
        weights.push_back(std::max(1.0, end - start));
    }
    double total = 0.0;
    for (double weight : weights) total += weight;
    const double bar_h = std::min(h_mm * 0.55, 6.0);
    const double bar_y = (h_mm - bar_h - 3.2) / 2.0;
    double cx = 0.0;
    for (std::size_t i = 0; i < stages.size(); ++i) {
        const double seg_w = w_mm * weights[i] / total;
        const auto color = stages[i]->find("color");
        const QColor fill = color != stages[i]->end() && color->is_string()
                                ? QColor(color->get<std::string>().c_str())
                                : QColor("#b0bec5");
        {
            MmShapes mm(painter, s);
            painter.setBrush(fill);
            painter.setPen(QPen(QColor("#37474f"), 0.15));
            painter.drawRect(QRectF(cx, bar_y, seg_w, bar_h));
        }
        const auto label = stages[i]->find("label");
        if (label != stages[i]->end() && label->is_string()) {
            text_mm(context, from_utf8(label->get<std::string>()),
                    QPointF(cx + seg_w / 2.0, bar_y + bar_h + 2.8), 2.4, false,
                    QColor(Qt::black), true);
        }
        cx += seg_w;
    }
}

// ---------------------------------------------------------------------------
// Profile — annotated profile frame (content bound at runtime by slots).
// ---------------------------------------------------------------------------

void PwbLayoutSlotItem::draw_profile(QPainter& painter, double s, double w_mm,
                                     double h_mm) {
    MmShapes mm(painter, s);
    painter.setBrush(Qt::NoBrush);
    painter.setPen(QPen(QColor("#37474f"), 0.2));
    painter.drawRect(QRectF(0.5, 0.5, w_mm - 1.0, h_mm - 1.0));
}

// ---------------------------------------------------------------------------
// Placeholder — honest "not bound / unknown" box (never fabricate content).
// ---------------------------------------------------------------------------

void PwbLayoutSlotItem::draw_placeholder(QPainter& painter, double s, double w_mm,
                                         double h_mm) {
    MmShapes mm(painter, s);
    painter.setBrush(QBrush(QColor("#f5f5f5")));
    QPen pen(QColor("#9e9e9e"), 0.2);
    pen.setStyle(Qt::DashLine);
    painter.setPen(pen);
    painter.drawRect(QRectF(0.5, 0.5, w_mm - 1.0, h_mm - 1.0));
}

}  // namespace pwb::qgis
