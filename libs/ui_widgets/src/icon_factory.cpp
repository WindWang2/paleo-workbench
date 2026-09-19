#include "pwb/ui_widgets/icon_factory.hpp"

#include "pwb/ui_widgets/ui_context.hpp"

#include <pwb/platform_services/resource_locator.hpp>

#include <QFile>
#include <QFileInfo>
#include <QScreen>
#include <QGuiApplication>
#include <QHash>
#include <QPainter>
#include <QRegularExpression>
#include <QTextStream>

namespace pwb::ui_widgets {

namespace {

// Process icon cache (Python _ICON_CACHE equivalent; assets immutable).
QHash<QString, QIcon>& icon_cache() {
    static QHash<QString, QIcon> cache;
    return cache;
}

// Achromatic verdicts keyed by file name (Python _MONO_SUFFIX_CACHE).
QHash<QString, bool>& mono_cache() {
    static QHash<QString, bool> cache;
    return cache;
}

double device_pixel_ratio() {
    double ratio = 1.0;
    if (QGuiApplication::instance() != nullptr &&
        QGuiApplication::primaryScreen() != nullptr) {
        ratio = qMax(1.0, QGuiApplication::primaryScreen()->devicePixelRatio());
    }
    return ratio;
}

QString icon_path(const QString& name) {
    return pwb::platform_services::resource_file(
        QStringLiteral("ui/assets/icons/") + name);
}

bool is_achromatic_hex(const QString& hex_color) {
    QString value = hex_color;
    if (value.startsWith('#')) value = value.mid(1);
    if (value.size() == 3) {
        QString expanded;
        for (const QChar ch : value) {
            expanded.append(ch).append(ch);
        }
        value = expanded;
    }
    if (value.size() != 6 && value.size() != 8) {
        return true;  // 非法定长不参与判定
    }
    const QString rgb = value.size() == 8 ? value.right(6) : value;
    bool ok = false;
    const int r = rgb.mid(0, 2).toInt(&ok, 16);
    const int g = rgb.mid(2, 2).toInt(&ok, 16);
    const int b = rgb.mid(4, 2).toInt(&ok, 16);
    const int mx = qMax(r, qMax(g, b)), mn = qMin(r, qMin(g, b));
    return (mx - mn) <= 0.12 * 255;
}

// True when the SVG only bakes achromatic (gray) colors — safe to recolor.
bool is_achromatic_svg(const QString& path) {
    const QString name = QFileInfo(path).fileName();
    const auto cached = mono_cache().constFind(name);
    if (cached != mono_cache().constEnd()) return cached.value();
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) return false;
    const QString text = QTextStream(&file).readAll();
    static const QRegularExpression hex_re(
        QStringLiteral("#[0-9a-fA-F]{3,8}\\b"));
    bool achromatic = true;
    auto it = hex_re.globalMatch(text);
    while (it.hasNext()) {
        if (!is_achromatic_hex(it.next().captured(0))) {
            achromatic = false;
            break;
        }
    }
    mono_cache().insert(name, achromatic);
    return achromatic;
}

QIcon render_tinted(const QString& path, const QString& tint, double ratio) {
    const QIcon source(path);
    const QSize base(48, 48);
    QPixmap pixmap = source.pixmap(base);
    pixmap.setDevicePixelRatio(ratio);
    QPainter painter(&pixmap);
    painter.setCompositionMode(QPainter::CompositionMode_SourceIn);
    painter.fillRect(pixmap.rect(), QColor(tint));
    painter.end();
    return QIcon(pixmap);
}

QString resolve_map_icon(QString stem) {
    if (stem.endsWith(QStringLiteral(".svg"))) stem.chop(4);
    const QString map_path = icon_path(QStringLiteral("map/") + stem + ".svg");
    if (!map_path.isEmpty()) return map_path;
    return icon_path(stem + QStringLiteral(".svg"));
}

}  // namespace

QString default_icon_color() {
    const QString color = palette_token("TEXT_SECONDARY");
    return color.isEmpty() ? QStringLiteral("#6c757d") : color;
}

QIcon workstation_icon(const QString& name, const QString& color) {
    const QString tint = color.isEmpty() ? default_icon_color() : color;
    const double ratio = device_pixel_ratio();
    const QString key = name + QLatin1Char('|') + tint + QLatin1Char('|') +
                        QString::number(ratio);
    const auto cached = icon_cache().constFind(key);
    if (cached != icon_cache().constEnd()) return cached.value();
    const QString path = icon_path(name);
    const QIcon icon =
        path.isEmpty() ? QIcon() : render_tinted(path, tint, ratio);
    icon_cache().insert(key, icon);
    return icon;
}

QIcon tinted_map_icon(const QString& name, const QString& color) {
    QString stem = name;
    if (stem.endsWith(QStringLiteral(".svg"))) stem.chop(4);
    const QString tint = color.isEmpty() ? default_icon_color() : color;
    const double ratio = device_pixel_ratio();
    const QString key = QStringLiteral("map/") + stem + QLatin1Char('|') +
                        tint + QLatin1Char('|') + QString::number(ratio);
    const auto cached = icon_cache().constFind(key);
    if (cached != icon_cache().constEnd()) return cached.value();
    const QString path = resolve_map_icon(stem);
    QIcon icon;
    if (!path.isEmpty()) {
        icon = is_achromatic_svg(path) ? render_tinted(path, tint, ratio)
                                       : QIcon(path);
    }
    icon_cache().insert(key, icon);
    return icon;
}

QPixmap tinted_pixmap(const QString& icon_name, const QString& color_token,
                    int size, double dpr) {
    const QString color = palette_token(color_token.toUtf8().constData());
    const QIcon icon = workstation_icon(icon_name, color);
    return icon.pixmap(QSize(size, size), qMax(1.0, dpr));
}

}  // namespace pwb::ui_widgets
