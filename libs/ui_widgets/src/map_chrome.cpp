#include "pwb/ui_widgets/map_chrome.hpp"

#include <pwb/platform_services/resource_locator.hpp>

#include <QFont>
#include <QIcon>
#include <QPen>
#include <QPointF>
#include <QPolygonF>

#include <cmath>
#include <map>

namespace pwb::ui_widgets {
namespace {

bool elements_contain(const QStringList& elements, const char* cn,
                      const char* en) {
    return elements.contains(QString::fromUtf8(cn)) ||
           elements.contains(QString::fromUtf8(en));
}

}  // namespace

QVariantMap ensure_basic_map_chrome(const QVariantMap& decorations) {
    QVariantMap out = decorations;
    QStringList elements = out.value(QStringLiteral("elements"))
                               .toStringList();
    if (elements.isEmpty()) {
        elements = kBasicMapChrome;
    }
    out.insert(QStringLiteral("elements"), elements);
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
    const std::array<double, 4>& extent, int canvas_width, double scale) {
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
    return std::pair{target_units, pixels};
}

void paint_scale_bar(QPainter& painter,
                     const std::array<double, 4>& extent,
                     int canvas_width, int canvas_height, double scale,
                     const QColor& ink) {
    const auto spec = scale_bar_spec(extent, canvas_width, scale);
    if (!spec.has_value()) {
        return;
    }
    const auto [target_units, pixels] = *spec;
    const double y = canvas_height - 24.0 * scale;
    painter.save();
    painter.setPen(QPen(ink, 2.0 * scale));
    painter.drawLine(QPointF(16 * scale, y),
                     QPointF(16 * scale + pixels, y));
    painter.drawLine(QPointF(16 * scale, y - 4 * scale),
                     QPointF(16 * scale, y + 4 * scale));
    painter.drawLine(QPointF(16 * scale + pixels, y - 4 * scale),
                     QPointF(16 * scale + pixels, y + 4 * scale));
    QFont font = painter.font();
    font.setPixelSize(std::max(8, int(std::lround(10 * scale))));
    painter.setFont(font);
    // Python f"{target_units:g} map units" — 'g' 6 significant digits.
    const QString label =
        QString::number(target_units, 'g', 6) + QStringLiteral(" map units");
    painter.drawText(QPointF(16 * scale, y - 7 * scale), label);
    painter.restore();
}

void paint_map_decorations(QPainter& painter,
                           const QVariantMap& decorations_in,
                           int width, int height,
                           const std::array<double, 4>& extent,
                           double scale, bool dark_chrome) {
    const QVariantMap decorations = ensure_basic_map_chrome(decorations_in);
    const QColor ink =
        dark_chrome ? kChromeInkOnLightBody : kChromeInkOnDarkBody;
    const int canvas_width = width;
    const int canvas_height = height;
    const QStringList elements =
        decorations.value(QStringLiteral("elements")).toStringList();
    const bool all_elements = elements.isEmpty();
    const QString title =
        decorations.value(QStringLiteral("title")).toString();

    QFont title_font = painter.font();
    title_font.setPixelSize(std::max(10, int(std::lround(16 * scale))));
    title_font.setBold(true);
    if (!title.isEmpty() &&
        (all_elements || elements_contain(elements, "标题栏", "title"))) {
        painter.save();
        painter.setPen(ink);
        painter.setFont(title_font);
        painter.drawText(
            QRectF(14 * scale, 10 * scale, canvas_width - 28 * scale,
                   canvas_height - 20 * scale),
            Qt::AlignHCenter | Qt::AlignTop, title);
        painter.restore();
    }
    if (all_elements || elements_contain(elements, "比例尺", "scale_bar")) {
        paint_scale_bar(painter, extent, canvas_width, canvas_height,
                        scale, ink);
    }
    if (all_elements ||
        elements_contain(elements, "指北针", "north_arrow")) {
        painter.save();
        const QPointF center(28 * scale, 37 * scale);
        painter.setPen(QPen(ink, 1.5 * scale));
        painter.setBrush(dark_chrome ? QColor(kChromeInkOnDarkBody)
                                     : QColor(kChromeInkOnLightBody));
        painter.drawPolygon(QPolygonF(
            {center + QPointF(0, -18 * scale),
             center + QPointF(-6 * scale, 10 * scale),
             center + QPointF(0, 5 * scale),
             center + QPointF(6 * scale, 10 * scale)}));
        QFont font = painter.font();
        font.setPixelSize(std::max(8, int(std::lround(10 * scale))));
        painter.setFont(font);
        painter.drawText(center + QPointF(-5 * scale, -22 * scale), "N");
        painter.restore();
    }

    const QVariantList raw_legend =
        decorations.value(QStringLiteral("legend_items")).toList();
    if ((all_elements || elements_contain(elements, "图例", "legend")) &&
        !raw_legend.isEmpty()) {
        // Both legacy string items and dicts with explicit color (#937-4).
        std::vector<std::pair<QString, QString>> items;
        for (const QVariant& entry : raw_legend) {
            if (items.size() >= 8) break;
            if (entry.typeId() == QMetaType::QVariantMap) {
                const QVariantMap m = entry.toMap();
                QString label =
                    m.value(QStringLiteral("label")).toString();
                if (label.isEmpty())
                    label = m.value(QStringLiteral("name")).toString();
                if (label.isEmpty())
                    label = m.value(QStringLiteral("text")).toString();
                QString color =
                    m.value(QStringLiteral("color")).toString();
                if (color.isEmpty())
                    color = m.value(QStringLiteral("fill")).toString();
                if (color.isEmpty()) color = kSwatchFallback;
                if (label.isEmpty()) {
                    // Python: label or str(entry) — the dict repr. The
                    // honest C++ equivalent uses the first value.
                    label = m.isEmpty() ? QStringLiteral("{}")
                                        : m.constBegin().value().toString();
                }
                items.emplace_back(label, color);
            } else {
                items.emplace_back(entry.toString(), kSwatchFallback);
            }
        }
        painter.save();
        const double legend_width = 164 * scale;
        const double row_height = 18 * scale;
        const double swatch = 9 * scale;
        const double legend_height =
            10 * scale + row_height * double(items.size());
        painter.setPen(QPen(QColor(kChromePanelBorder), 1.0 * scale));
        painter.setBrush(kChromePanelBg);
        const QRectF rect(canvas_width - legend_width - 16 * scale,
                          canvas_height - legend_height - 16 * scale,
                          legend_width, legend_height);
        painter.drawRect(rect);
        QFont font = painter.font();
        font.setPixelSize(std::max(8, int(std::lround(11 * scale))));
        int index = 0;
        for (const auto& [label, color] : items) {
            QColor swatch_color(color);
            if (!swatch_color.isValid()) {
                swatch_color = QColor(kSwatchFallback);
            }
            painter.setBrush(swatch_color);
            const double y = rect.top() + 14 * scale + index * row_height;
            painter.drawRect(QRectF(rect.left() + 8 * scale, y - swatch,
                                    swatch, swatch));
            painter.setPen(QColor(kChromeInkOnDarkBody));
            painter.setFont(font);
            painter.drawText(QPointF(rect.left() + 23 * scale, y), label);
            ++index;
        }

        // Facies-category legend: when the top layer is a categorized
        // facies map, a second box beside the work legend (base swatch +
        // SVG pattern tile + class name — same construction as the
        // canvas fill).
        const QVariantMap facies =
            decorations.value(QStringLiteral("facies_legend")).toMap();
        const QVariantList facies_raw =
            facies.value(QStringLiteral("items")).toList();
        std::vector<QVariantMap> facies_items;
        for (const QVariant& entry : facies_raw) {
            if (facies_items.size() >= 10) break;
            if (entry.typeId() == QMetaType::QVariantMap) {
                facies_items.push_back(entry.toMap());
            }
        }
        if (!facies_items.empty()) {
            const QString f_title =
                facies.value(QStringLiteral("title")).toString().isEmpty()
                    ? QStringLiteral("相图")
                    : facies.value(QStringLiteral("title")).toString();
            const double f_row = 18 * scale;
            const double f_height =
                12 * scale + f_row * (double(facies_items.size()) + 1);
            const double f_width = 176 * scale;
            const QRectF f_rect(rect.left() - f_width - 8 * scale,
                                rect.bottom() - f_height, f_width, f_height);
            painter.setPen(QPen(QColor(kChromePanelBorder), 1.0 * scale));
            painter.setBrush(kChromePanelBg);
            painter.drawRect(f_rect);
            QFont f_title_font = painter.font();
            f_title_font.setBold(true);
            f_title_font.setPixelSize(
                std::max(8, int(std::lround(11 * scale))));
            painter.setPen(QColor(kChromeInkOnDarkBody));
            painter.setFont(f_title_font);
            painter.drawText(
                QPointF(f_rect.left() + 8 * scale, f_rect.top() + 14 * scale),
                f_title);
            painter.setFont(font);
            int f_index = 0;
            for (const QVariantMap& entry : facies_items) {
                const QString label =
                    entry.value(QStringLiteral("label")).toString();
                const double y =
                    f_rect.top() + 14 * scale + (f_index + 1) * f_row;
                const QRectF swatch_rect(f_rect.left() + 8 * scale,
                                         y - swatch, 14 * scale, swatch);
                QColor base(
                    entry.value(QStringLiteral("color"))
                        .toString()
                        .isEmpty()
                        ? QStringLiteral("#b0bec5")
                        : entry.value(QStringLiteral("color")).toString());
                if (!base.isValid()) {
                    base = QColor(kSwatchFallback);
                }
                painter.setPen(Qt::NoPen);
                painter.setBrush(base);
                painter.drawRect(swatch_rect);
                const QPixmap pattern_pixmap = facies_pattern_pixmap(
                    entry.value(QStringLiteral("pattern")).toString());
                if (!pattern_pixmap.isNull()) {
                    painter.drawTiledPixmap(swatch_rect.toRect(),
                                            pattern_pixmap);
                }
                painter.setPen(QColor(kChromeInkOnDarkBody));
                painter.drawText(
                    QPointF(f_rect.left() + 28 * scale, y), label);
                ++f_index;
            }
        }
        painter.restore();
    }
}

QSize legend_chrome_size(const QVariantMap& decorations, double scale) {
    const int items_n = std::min(
        8, int(decorations.value(QStringLiteral("legend_items"))
                   .toList()
                   .size()));
    int facies_n = 0;
    const QVariantMap facies =
        decorations.value(QStringLiteral("facies_legend")).toMap();
    if (!facies.isEmpty()) {
        const QVariantList raw =
            facies.value(QStringLiteral("items")).toList();
        int count = 0;
        for (const QVariant& entry : raw) {
            if (entry.typeId() == QMetaType::QVariantMap && count < 10) {
                ++count;
            }
        }
        facies_n = count;
    }
    if (items_n == 0 && facies_n == 0) {
        return {0, 0};
    }
    const double legend_width = 164 * scale;
    const double row_height = 18 * scale;
    const double margin = 16 * scale;
    const double legend_height =
        items_n ? 10 * scale + row_height * items_n : 10 * scale;
    const double f_width = 176 * scale;
    const double f_row = 18 * scale;
    const double f_height =
        facies_n ? 12 * scale + f_row * (facies_n + 1) : 0.0;
    const double gap = 8 * scale;
    double width = margin + legend_width + margin;
    if (facies_n) {
        width = margin + legend_width + gap + f_width;
    }
    const double height = margin + std::max(legend_height, f_height);
    return {std::max(1, int(std::ceil(width))),
            std::max(1, int(std::ceil(height)))};
}

QPixmap facies_pattern_pixmap(const QString& pattern_id) {
    if (pattern_id.isEmpty()) {
        return {};
    }
    static std::map<QString, QPixmap> cache;
    const auto it = cache.find(pattern_id);
    if (it != cache.end()) {
        return it->second;
    }
    // Native resolution: bundled resources layout
    // (<resources>/patterns/facies/<id>.svg) — the Python path points
    // into the vendored geo-viz-engine tree, which is absent in this
    // checkout; the honest miss (null pixmap) matches Python's is_file
    // miss exactly.
    const QString path = platform_services::resource_file(
        QStringLiteral("patterns/facies/%1.svg").arg(pattern_id));
    if (path.isEmpty()) {
        cache[pattern_id] = QPixmap();
        return {};
    }
    const QPixmap pixmap = QIcon(path).pixmap(QSize(32, 32));
    cache[pattern_id] = pixmap;
    return pixmap;
}

}  // namespace pwb::ui_widgets
