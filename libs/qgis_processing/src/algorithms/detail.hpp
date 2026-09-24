#pragma once

// Shared implementation helpers for the Paleo Processing algorithm adapters
// (CSV curve IO common to the well family). Header-only on purpose: the
// algorithm translation units are listed individually in CMakeLists.txt and
// this header is an internal detail, not a public seam.

#include <QFile>
#include <QRegularExpression>
#include <QString>
#include <QStringList>
#include <QTextStream>

#include <algorithm>
#include <cstring>
#include <vector>

namespace pwb::qgis_processing::detail {

// depth/value pairs read from a two-column CSV. Lines that do not parse as
// two numbers (header, comments, blank lines) are skipped.
struct CurveCsv {
    std::vector<double> depth;
    std::vector<double> value;
};

// Round-trip double formatting for CSV cells (17 significant digits keeps
// the value bit-exact through a read-back).
[[nodiscard]] inline QString format_csv_double(double value) {
    return QString::number(value, 'g', 17);
}

[[nodiscard]] inline CurveCsv read_curve_csv(const QString& path, QString& error) {
    CurveCsv curve;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        error = QStringLiteral("cannot open %1").arg(path);
        return curve;
    }
    QTextStream stream(&file);
    stream.setEncoding(QStringConverter::Utf8);
    QString line;
    while (stream.readLineInto(&line)) {
        const QString trimmed = line.trimmed();
        if (trimmed.isEmpty()) continue;
        QStringList tokens = trimmed.split(QLatin1Char(','));
        if (tokens.size() < 2) {
            tokens = trimmed.split(QRegularExpression(QStringLiteral("\\s+")),
                                   Qt::SkipEmptyParts);
        }
        if (tokens.size() < 2) continue;
        bool depth_ok = false;
        bool value_ok = false;
        const double depth = tokens.at(0).trimmed().toDouble(&depth_ok);
        const double value = tokens.at(1).trimmed().toDouble(&value_ok);
        if (!depth_ok || !value_ok) continue;  // header / non-numeric row
        curve.depth.push_back(depth);
        curve.value.push_back(value);
    }
    return curve;
}

// Writes `header` then one "depth,value" row per sample. `header` may be
// empty (no header line).
[[nodiscard]] inline bool write_curve_csv(const QString& path,
                                          const std::vector<double>& depth,
                                          const std::vector<double>& value,
                                          const QString& header, QString& error) {
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        error = QStringLiteral("cannot write %1").arg(path);
        return false;
    }
    QTextStream stream(&file);
    stream.setEncoding(QStringConverter::Utf8);
    if (!header.isEmpty()) stream << header << '\n';
    const std::size_t rows = std::min(depth.size(), value.size());
    for (std::size_t i = 0; i < rows; ++i) {
        stream << format_csv_double(depth[i]) << QLatin1Char(',')
               << format_csv_double(value[i]) << '\n';
    }
    return true;
}

}  // namespace pwb::qgis_processing::detail
