#include <pwb/ui_map/map_chrome_painter.hpp>

#include <QFileInfo>
#include <QFont>
#include <QIcon>
#include <QPainter>
#include <QPen>
#include <QPolygonF>
#include <QRectF>
#include <QSize>

#include <cmath>
#include <map>
#include <set>

namespace pwb::ui_map {

namespace {

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

std::set<std::string> element_set(const Json& decorations) {
    std::set<std::string> elements;
    const Json raw = field_value(decorations, "elements", Json::array());
    if (raw.is_array()) {
        for (const auto& item : raw) {
            if (item.is_string()) {
                elements.insert(item.get<std::string>());
            }
        }
    }
    return elements;
}

// (label, color) pairs for the legend box — dict entries carry an explicit
// color (fill fallback), str entries get the swatch fallback (#937-4).
std::vector<std::pair<QString, QString>> legend_rows(const Json& items,
                                                     int cap) {
    std::vector<std::pair<QString, QString>> rows;
    if (!items.is_array()) {
        return rows;
    }
    for (const auto& entry : items) {
        if (rows.size() >= static_cast<std::size_t>(cap)) {
            break;
        }
        if (entry.is_object()) {
            std::string label = field_value_str(entry, "label", "");
            if (label.empty()) {
                label = field_value_str(entry, "name", "");
            }
            if (label.empty()) {
                label = field_value_str(entry, "text", "");
            }
            std::string color = field_value_str(entry, "color", "");
            if (color.empty()) {
                color = field_value_str(entry, "fill", "");
            }
            if (color.empty()) {
                color = kChromeSwatchFallback;
            }
            if (label.empty()) {
                label = entry.dump();
            }
            rows.emplace_back(qstr(label), qstr(color));
        } else if (entry.is_string()) {
            rows.emplace_back(qstr(entry.get<std::string>()),
                              QString::fromLatin1(kChromeSwatchFallback));
        }
    }
    return rows;
}

void paint_scale_bar(QPainter& painter, const Extent& extent,
                     double canvas_width, double canvas_height, double scale,
                     const QString& ink) {
    const auto spec = scale_bar_spec(extent, canvas_width, scale);
    if (!spec.has_value()) {
        return;
    }
    const double target_units = spec->first;
    const double pixels = spec->second;
    const double y = canvas_height - 24.0 * scale;
    painter.save();
    painter.setPen(QPen(QColor(ink), 2.0 * scale));
    const double x0 = 16.0 * scale;
    painter.drawLine(QPointF(x0, y), QPointF(x0 + pixels, y));
    painter.drawLine(QPointF(x0, y - 4.0 * scale),
                     QPointF(x0, y + 4.0 * scale));
    painter.drawLine(QPointF(x0 + pixels, y - 4.0 * scale),
                     QPointF(x0 + pixels, y + 4.0 * scale));
    QFont font = painter.font();
    font.setPixelSize(std::max(8, static_cast<int>(std::lround(10.0 * scale))));
    painter.setFont(font);
    // f"{target_units:g}" — to_chars general matches Python %g repr.
    char buffer[64];
    const auto conv = std::to_chars(buffer, buffer + sizeof(buffer),
                                    target_units, std::chars_format::general);
    const QString label =
        QString::fromLatin1(buffer, static_cast<int>(conv.ptr - buffer)) +
        QStringLiteral(" map units");
    painter.drawText(QPointF(x0, y - 7.0 * scale), label);
    painter.restore();
}

}  // namespace

// Read-only check: decorations has no usable "elements" list — used to
// skip the whole-tree copy in the common non-empty case (#1392).
static bool map_chrome_elements_empty(const Json& decorations) {
    if (!decorations.is_object()) {
        return true;
    }
    const Json raw = field_value(decorations, "elements", Json::array());
    if (!raw.is_array() || raw.empty()) {
        return true;
    }
    for (const auto& item : raw) {
        if (item.is_string() && !item.get<std::string>().empty()) {
            return false;
        }
    }
    return true;
}

Json ensure_basic_map_chrome(const Json& decorations) {
    if (!map_chrome_elements_empty(decorations)) {
        return decorations;
    }
    Json out = decorations.is_object() ? decorations : Json::object();
    out["elements"] = Json::array({"比例尺", "指北针"});
    return out;
}

double nice_scale_units(double value) {
    if (value <= 0.0 || !std::isfinite(value)) {
        return value;
    }
    const double exponent = std::floor(std::log10(value));
    const double fraction = value / std::pow(10.0, exponent);
    for (const double nice : {5.0, 2.0, 1.0}) {
        if (fraction >= nice) {
            return nice * std::pow(10.0, exponent);
        }
    }
    return std::pow(10.0, exponent);
}

std::optional<std::pair<double, double>> scale_bar_spec(
    const Extent& extent, double canvas_width, double scale) {
    const double span = extent[2] - extent[0];
    if (span <= 0.0) {
        return std::nullopt;
    }
    const double target_units = nice_scale_units(span * 0.2);
    if (target_units <= 0.0) {
        return std::nullopt;
    }
    const double pixels = target_units / span * canvas_width;
    if (pixels < 16.0 * scale) {
        return std::nullopt;
    }
    return std::make_pair(target_units, pixels);
}

void paint_map_decorations(QPainter& painter, const Json& decorations_in,
                           double width, double height, const Extent& extent,
                           double dpi, bool dark_chrome) {
    const double scale = dpi > 0.0 ? dpi / 96.0 : 1.0;
    // #1392: only pay the decorations tree copy when the default-fill
    // actually applies; the non-empty common case reads decorations_in.
    Json defaulted;
    const Json& decorations =
        map_chrome_elements_empty(decorations_in)
            ? (defaulted = ensure_basic_map_chrome(decorations_in))
            : decorations_in;
    const QString ink = dark_chrome
                            ? QString::fromLatin1(kChromeInkOnLightBody)
                            : QString::fromLatin1(kChromeInkOnDarkBody);
    const double canvas_width = width;
    const double canvas_height = height;
    const auto elements = element_set(decorations);
    const bool open_whitelist = elements.empty();
    const auto wants = [&](const char* zh, const char* en) {
        return open_whitelist || elements.count(zh) || elements.count(en);
    };
    const QString title =
        qstr(field_value_str(decorations, "title", ""));

    if (!title.isEmpty() && wants("标题栏", "title")) {
        QFont title_font = painter.font();
        title_font.setPixelSize(
            std::max(10, static_cast<int>(std::lround(16.0 * scale))));
        title_font.setBold(true);
        painter.save();
        painter.setPen(QColor(ink));
        painter.setFont(title_font);
        painter.drawText(
            QRectF(14.0 * scale, 10.0 * scale,
                   canvas_width - 28.0 * scale,
                   canvas_height - 20.0 * scale),
            Qt::AlignHCenter | Qt::AlignTop, title);
        painter.restore();
    }

    if (wants("比例尺", "scale_bar")) {
        paint_scale_bar(painter, extent, canvas_width, canvas_height, scale,
                        ink);
    }

    if (wants("指北针", "north_arrow")) {
        painter.save();
        const QPointF center(28.0 * scale, 37.0 * scale);
        painter.setPen(QPen(QColor(ink), 1.5 * scale));
        painter.setBrush(dark_chrome
                             ? QColor(kChromeInkOnDarkBody)
                             : QColor(kChromeInkOnLightBody));
        painter.drawPolygon(QPolygonF({
            center + QPointF(0.0, -18.0 * scale),
            center + QPointF(-6.0 * scale, 10.0 * scale),
            center + QPointF(0.0, 5.0 * scale),
            center + QPointF(6.0 * scale, 10.0 * scale),
        }));
        QFont font = painter.font();
        font.setPixelSize(
            std::max(8, static_cast<int>(std::lround(10.0 * scale))));
        painter.setFont(font);
        painter.drawText(center + QPointF(-5.0 * scale, -22.0 * scale), "N");
        painter.restore();
    }

    const Json legend_items_raw =
        field_value(decorations, "legend_items", Json::array());
    if (wants("图例", "legend") && legend_items_raw.is_array() &&
        !legend_items_raw.empty()) {
        const auto items = legend_rows(legend_items_raw, 8);
        painter.save();
        const double legend_width = 164.0 * scale;
        const double row_height = 18.0 * scale;
        const double swatch = 9.0 * scale;
        const double legend_height =
            10.0 * scale + row_height * static_cast<double>(items.size());
        painter.setPen(QPen(QColor(kChromePanelBorder), 1.0 * scale));
        painter.setBrush(QColor(kChromePanelBgR, kChromePanelBgG,
                                kChromePanelBgB, kChromePanelBgA));
        const QRectF rect(
            canvas_width - legend_width - 16.0 * scale,
            canvas_height - legend_height - 16.0 * scale, legend_width,
            legend_height);
        painter.drawRect(rect);
        QFont font = painter.font();
        font.setPixelSize(
            std::max(8, static_cast<int>(std::lround(11.0 * scale))));
        int index = 0;
        for (const auto& [label, color] : items) {
            QColor swatch_color(color);
            if (!swatch_color.isValid()) {
                swatch_color = QColor(kChromeSwatchFallback);
            }
            painter.setBrush(swatch_color);
            const double y = rect.top() + 14.0 * scale + index * row_height;
            painter.drawRect(
                QRectF(rect.left() + 8.0 * scale, y - swatch, swatch, swatch));
            painter.setPen(QColor(kChromeInkOnDarkBody));
            painter.setFont(font);
            painter.drawText(QPointF(rect.left() + 23.0 * scale, y), label);
            ++index;
        }

        // Facies legend box to the left of the work-area legend.
        const Json facies =
            field_value(decorations, "facies_legend", Json::object());
        const Json facies_items_raw =
            field_value(facies, "items", Json::array());
        if (facies.is_object() && facies_items_raw.is_array() &&
            !facies_items_raw.empty()) {
            std::vector<Json> facies_items;
            for (const auto& entry : facies_items_raw) {
                if (entry.is_object() &&
                    facies_items.size() < 10) {
                    facies_items.push_back(entry);
                }
            }
            const QString f_title =
                qstr(field_value_str(facies, "title", "相图"));
            const double f_row = 18.0 * scale;
            const double f_height =
                12.0 * scale + f_row * (facies_items.size() + 1.0);
            const double f_width = 176.0 * scale;
            const QRectF f_rect(
                rect.left() - f_width - 8.0 * scale,
                rect.bottom() - f_height, f_width, f_height);
            painter.setPen(QPen(QColor(kChromePanelBorder), 1.0 * scale));
            painter.setBrush(QColor(kChromePanelBgR, kChromePanelBgG,
                                    kChromePanelBgB, kChromePanelBgA));
            painter.drawRect(f_rect);
            QFont f_title_font = painter.font();
            f_title_font.setBold(true);
            f_title_font.setPixelSize(
                std::max(8, static_cast<int>(std::lround(11.0 * scale))));
            painter.setPen(QColor(kChromeInkOnDarkBody));
            painter.setFont(f_title_font);
            painter.drawText(
                QPointF(f_rect.left() + 8.0 * scale,
                        f_rect.top() + 14.0 * scale),
                f_title);
            painter.setFont(font);
            int f_index = 0;
            for (const auto& entry : facies_items) {
                const QString f_label =
                    qstr(field_value_str(entry, "label", ""));
                const double y = f_rect.top() + 14.0 * scale +
                                 (f_index + 1.0) * f_row;
                const QRectF swatch_rect(f_rect.left() + 8.0 * scale,
                                         y - swatch, 14.0 * scale, swatch);
                QColor base(
                    qstr(field_value_str(entry, "color", "#b0bec5")));
                if (!base.isValid()) {
                    base = QColor(kChromeSwatchFallback);
                }
                painter.setPen(Qt::NoPen);
                painter.setBrush(base);
                painter.drawRect(swatch_rect);
                const QPixmap tile = facies_pattern_pixmap(
                    field_value_str(entry, "pattern", ""),
                    facies_pattern_dir());
                if (!tile.isNull()) {
                    painter.drawTiledPixmap(swatch_rect.toRect(), tile);
                }
                painter.setPen(QColor(kChromeInkOnDarkBody));
                painter.drawText(
                    QPointF(f_rect.left() + 28.0 * scale, y), f_label);
                ++f_index;
            }
        }
        painter.restore();
    }
}

std::pair<int, int> legend_chrome_size(const Json& decorations_in,
                                       double scale) {
    const Json decorations =
        decorations_in.is_object() ? decorations_in : Json::object();
    const Json items_raw =
        field_value(decorations, "legend_items", Json::array());
    const int item_count =
        items_raw.is_array()
            ? std::min<int>(8, static_cast<int>(items_raw.size()))
            : 0;
    const Json facies = field_value(decorations, "facies_legend",
                                    Json::object());
    const Json facies_items_raw =
        field_value(facies, "items", Json::array());
    int facies_n = 0;
    if (facies.is_object() && facies_items_raw.is_array()) {
        for (const auto& entry : facies_items_raw) {
            if (entry.is_object() && facies_n < 10) {
                ++facies_n;
            }
        }
    }
    if (item_count == 0 && facies_n == 0) {
        return {0, 0};
    }
    const double legend_width = 164.0 * scale;
    const double row_height = 18.0 * scale;
    const double margin = 16.0 * scale;
    const double legend_height =
        item_count > 0 ? 10.0 * scale + row_height * item_count
                       : 10.0 * scale;
    const double f_width = 176.0 * scale;
    const double f_row = 18.0 * scale;
    const double f_height =
        facies_n > 0 ? 12.0 * scale + f_row * (facies_n + 1.0) : 0.0;
    const double gap = 8.0 * scale;
    double out_width = margin + legend_width + margin;
    if (facies_n > 0) {
        out_width = margin + legend_width + gap + f_width;
    }
    const double out_height = margin + std::max(legend_height, f_height);
    return {std::max(1, static_cast<int>(std::ceil(out_width))),
            std::max(1, static_cast<int>(std::ceil(out_height)))};
}

const std::string& facies_pattern_dir() {
    // FACIES_PATTERN_DIR parity: the geo-viz-engine asset tree is not
    // vendored into the C++ build; the path stays overridable by the host
    // (a missing tile degrades to the base swatch, Python parity).
    static const std::string dir = [] {
        const char* env = std::getenv("PWB_FACIES_PATTERN_DIR");
        return env != nullptr ? std::string(env) : std::string();
    }();
    return dir;
}

QPixmap facies_pattern_pixmap(const std::string& pattern_id,
                              const std::string& pattern_dir) {
    static std::map<std::string, QPixmap> cache;
    const std::string cache_key = pattern_dir + "|" + pattern_id;
    if (const auto it = cache.find(cache_key); it != cache.end()) {
        return it->second;
    }
    QPixmap pixmap;
    if (!pattern_id.empty() && !pattern_dir.empty()) {
        const QString path =
            qstr(pattern_dir + "/" + pattern_id + ".svg");
        if (QFileInfo::exists(path)) {
            pixmap = QIcon(path).pixmap(QSize(32, 32));
        }
    }
    cache.emplace(cache_key, pixmap);
    return pixmap;
}

}  // namespace pwb::ui_map
