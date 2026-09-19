// viz_e_dat_preview.cpp — implementation half of the VIZ-E DAT preview
// parser. See viz_e_dat_preview.hpp for the frozen-source map (geoviz/
// previews/dat.py @0885195) and the documented deviations.
//
// Internal error model mirrors Python exactly:
//   * DatSchemaError          ↔ _DatSchemaError (dat.py:117-118) — carries
//     the raw detail text; the public entry points translate it into the
//     GeoVizError wording (dat.py:581-584).
//   * WellResourceLimitError  ↔ _WellResourceLimitError (dat.py:121-122) —
//     subclass whose message is thrown verbatim (RESOURCE_LIMIT,
//     dat.py:973-977).
//   * IoError                 ↔ OSError → GeoVizError(IO_ERROR,
//     "无法读取 DAT 数据", ...) (dat.py:582-583) — final message at throw
//     site, propagated unchanged.

#include "viz_e_dat_preview.hpp"

#include <QFile>
#include <QFileDevice>
#include <QRegularExpression>
#include <QString>
#include <QStringConverter>
#include <QStringDecoder>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <utility>
#include <vector>

namespace pwb::viz_e {
namespace {

// ---- frozen constants (dat.py:26-45, contracts.py:40-41) -----------------

constexpr long long kMaxPoints = 50'000;              // _MAX_POINTS
constexpr long long kMaxSurfaceAxis = 256;            // _MAX_SURFACE_AXIS
constexpr long long kDefaultSurfaceGridSize = 256;    // PreviewOptions.surface_grid_size
constexpr long long kMaxHeaderLines = 256;            // _MAX_HEADER_LINES
constexpr long long kMaxHeaderChars = 64 * 1024;      // _MAX_HEADER_CHARS

// ---- error types ----------------------------------------------------------

struct DatSchemaError : std::runtime_error {
    explicit DatSchemaError(const QString& detail)
        : std::runtime_error(detail.toStdString()), detail(detail) {}
    QString detail;  // raw Python str(error) payload
};

struct WellResourceLimitError : DatSchemaError {
    explicit WellResourceLimitError(const QString& message)
        : DatSchemaError(message) {}
};

struct IoError : std::runtime_error {
    explicit IoError(const QString& detail)
        : std::runtime_error(
              QStringLiteral("无法读取 DAT 数据: %1").arg(detail).toStdString()) {}
};

// ---- utf-8-sig text access (open(path, encoding="utf-8-sig")) -------------

QString read_text_utf8_sig(const std::string& path) {
    QFile file(QString::fromStdString(path));
    if (!file.open(QIODevice::ReadOnly)) {
        throw IoError(file.errorString());
    }
    QByteArray raw = file.readAll();
    if (file.error() != QFileDevice::NoError) {
        throw IoError(file.errorString());
    }
    if (raw.startsWith("\xEF\xBB\xBF")) {  // utf-8-sig strips a leading BOM
        raw.remove(0, 3);
    }
    QStringDecoder decoder(QStringConverter::Utf8);
    QString text = decoder(raw);
    if (decoder.hasError()) {
        // Python UnicodeDecodeError → _prepare_error → INVALID_DATA branch
        // (dat.py:972, :1109-1110); exact byte offsets are not reproduced.
        throw DatSchemaError(
            QStringLiteral("'utf-8' codec can't decode file content"));
    }
    return text;
}

// Python text-mode universal newlines: "\r\n" and "\r" terminate a line
// exactly like "\n"; a trailing terminator does not open a final empty
// line ("a\n" iterates as one line).
std::vector<QString> split_lines_universal(const QString& text) {
    std::vector<QString> lines;
    QString current;
    const auto size = text.size();
    for (qsizetype i = 0; i < size; ++i) {
        const QChar c = text.at(i);
        if (c == u'\r') {
            lines.push_back(current);
            current.clear();
            if (i + 1 < size && text.at(i + 1) == u'\n') {
                ++i;
            }
        } else if (c == u'\n') {
            lines.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    if (!current.isEmpty()) {
        lines.push_back(current);
    }
    return lines;
}

QString trimmed_line(const QString& raw) { return raw.trimmed(); }

bool is_comment(const QString& line) { return line.startsWith(u'#'); }

// ---- header collection (dat.py:135-159) ------------------------------------

long long retain_header_line(std::vector<QString>& header,
                             long long header_chars,
                             const QString& line) {
    // dat.py:155-159 — over-budget lines are dropped silently, never error.
    if (static_cast<long long>(header.size()) >= kMaxHeaderLines ||
        header_chars + static_cast<long long>(line.size()) > kMaxHeaderChars) {
        return header_chars;
    }
    header.push_back(line);
    return header_chars + static_cast<long long>(line.size());
}

// dat.py:135-146 — leading '#' lines only, stop at the first data line.
std::vector<QString> read_header(const QString& text) {
    std::vector<QString> header;
    long long header_chars = 0;
    for (const QString& raw : split_lines_universal(text)) {
        const QString line = trimmed_line(raw);
        if (line.isEmpty()) {
            continue;
        }
        if (!is_comment(line)) {
            break;
        }
        header_chars = retain_header_line(header, header_chars, line);
    }
    return header;
}

// ---- tokenization (dat.py:149-152, :446-452) -------------------------------

std::vector<QString> whitespace_split(const QString& s) {
    static const QRegularExpression sep(
        QStringLiteral("\\s+"), QRegularExpression::UseUnicodePropertiesOption);
    const QStringList parts = s.split(sep, Qt::SkipEmptyParts);
    return std::vector<QString>(parts.cbegin(), parts.cend());
}

// dat.py:149-152 `_header_tokens`.
std::vector<QString> header_tokens(const QString& line) {
    if (line.count(u'"') % 2 != 0) {
        throw DatSchemaError(QStringLiteral("unclosed double quote in header"));
    }
    qsizetype body_start = 0;
    while (body_start < line.size() && line.at(body_start) == u'#') {
        ++body_start;  // line.lstrip("#")
    }
    return whitespace_split(line.mid(body_start).trimmed());
}

// POSIX shlex.split(line) with whitespace_split=True and comments disabled —
// the dat.py:449-451 branch for data rows containing quote characters.
// State machine transcribed from CPython shlex.Shlex.read_token (posix
// mode): quotes group, backslash escapes outside quotes and — only for
// `"` — inside them, everything else joins the current word.
std::vector<QString> shlex_split(const QString& line) {
    std::vector<QString> tokens;
    enum class St { Space, Word, Quote, Escape };
    const auto is_ws = [](QChar c) {
        return c == u' ' || c == u'\t' || c == u'\r' || c == u'\n';
    };
    qsizetype pos = 0;
    const auto read_token = [&]() -> bool {
        QString token;
        bool quoted = false;
        St state = St::Space;
        St escaped_state = St::Word;
        QChar quote;
        while (true) {
            const bool at_eof = pos >= line.size();
            const QChar c = at_eof ? QChar() : line.at(pos);
            if (!at_eof) {
                ++pos;
            }
            switch (state) {
            case St::Space:
                if (at_eof) {
                    return false;  // stream end (empty unquoted token → None)
                }
                if (is_ws(c)) {
                    if (!token.isEmpty() || quoted) {
                        tokens.push_back(token);
                        return true;
                    }
                    continue;
                }
                if (c == u'\\') {
                    escaped_state = St::Word;
                    state = St::Escape;
                    continue;
                }
                if (c == u'\'' || c == u'"') {
                    quote = c;
                    state = St::Quote;
                    continue;
                }
                token = c;  // whitespace_split: any other char starts a word
                state = St::Word;
                continue;
            case St::Quote:
                quoted = true;
                if (at_eof) {
                    throw DatSchemaError(QStringLiteral("No closing quotation"));
                }
                if (c == quote) {
                    state = St::Word;
                    continue;
                }
                if (c == u'\\' && quote == u'"') {  // escapedquotes == '"'
                    escaped_state = St::Quote;
                    state = St::Escape;
                    continue;
                }
                token += c;
                continue;
            case St::Escape:
                if (at_eof) {
                    throw DatSchemaError(QStringLiteral("No escaped character"));
                }
                if (escaped_state == St::Quote && c != u'\\' && c != quote) {
                    token += u'\\';  // backslash is literal inside quotes
                }
                token += c;
                state = escaped_state;
                continue;
            case St::Word:
                if (at_eof) {
                    tokens.push_back(token);
                    return true;
                }
                if (is_ws(c)) {
                    tokens.push_back(token);
                    return true;
                }
                if (c == u'\'' || c == u'"') {
                    quote = c;
                    state = St::Quote;
                    continue;
                }
                if (c == u'\\') {
                    escaped_state = St::Word;
                    state = St::Escape;
                    continue;
                }
                token += c;
                continue;
            }
        }
    };
    while (read_token()) {
    }
    return tokens;
}

// dat.py:446-452 `_split_data_line`.
std::vector<QString> split_data_line(const QString& line) {
    if (!line.contains(u'"') && !line.contains(u'\'')) {
        return whitespace_split(line);
    }
    return shlex_split(line);
}

// ---- column vocabulary (dat.py:162-224) -------------------------------------

// dat.py:162-164 `_normalized_column`: casefold + "'"-to-"prime" + drop
// non-alphanumerics. QString::toLower stands in for casefold (they differ
// only on special fold pairs such as ß→ss — header columns are ASCII).
QString normalized_column(const QString& column) {
    QString s = column.toLower();
    s.replace(u'\'', QStringLiteral("prime"));
    QString out;
    for (const QChar c : s) {
        if (c.isLetterOrNumber()) {
            out += c;
        }
    }
    return out;
}

using ColumnAliases =
    std::vector<std::pair<QString, std::set<QString>>>;  // registered → accepted

// dat.py:197-201 `_WELL_HEAD_COLUMNS`.
const ColumnAliases& well_head_aliases() {
    static const ColumnAliases aliases = {
        {QStringLiteral("name"),
         {QStringLiteral("name"), QStringLiteral("well"),
          QStringLiteral("wellname")}},
        {QStringLiteral("x"), {QStringLiteral("x")}},
        {QStringLiteral("y"), {QStringLiteral("y")}},
    };
    return aliases;
}

// dat.py:202-215 `_WELL_HEAD_EXTRA_COLUMNS`.
const std::set<QString>& well_head_extras() {
    static const std::set<QString> extras = {
        QStringLiteral("bottomx"), QStringLiteral("bottomy"),
        QStringLiteral("datum"),   QStringLiteral("elevation"),
        QStringLiteral("gl"),      QStringLiteral("kb"),
        QStringLiteral("td"),      QStringLiteral("totaldepth"),
        QStringLiteral("uwi"),     QStringLiteral("welltype"),
    };
    return extras;
}

// dat.py:167-194 `_column_mapping`.
std::optional<std::map<QString, long long>> column_mapping(
    const std::vector<QString>& header,
    const ColumnAliases& aliases,
    const std::set<QString>& allowed_extras,
    std::optional<long long> row_width) {
    std::set<QString> allowed = allowed_extras;
    for (const auto& entry : aliases) {
        allowed.insert(entry.second.cbegin(), entry.second.cend());
    }

    std::vector<std::map<QString, long long>> candidates;
    for (const QString& line : header) {
        const std::vector<QString> tokens = header_tokens(line);
        if (row_width &&
            static_cast<long long>(tokens.size()) != *row_width) {
            continue;
        }
        std::vector<QString> normalized;
        normalized.reserve(tokens.size());
        for (const QString& token : tokens) {
            normalized.push_back(normalized_column(token));
        }
        if (normalized.empty()) {
            continue;
        }
        bool all_allowed = true;
        for (const QString& column : normalized) {
            if (allowed.count(column) == 0) {
                all_allowed = false;
                break;
            }
        }
        if (!all_allowed) {
            continue;
        }
        std::map<QString, long long> mapping;
        for (const auto& [registered, accepted] : aliases) {
            std::vector<long long> matches;
            for (long long index = 0;
                 index < static_cast<long long>(normalized.size()); ++index) {
                if (accepted.count(normalized[static_cast<size_t>(index)]) > 0) {
                    matches.push_back(index);
                }
            }
            if (matches.size() == 1) {
                mapping[registered] = matches.front();
            }
        }
        if (mapping.size() == aliases.size()) {
            std::set<long long> distinct;
            for (const auto& [field, index] : mapping) {
                distinct.insert(index);
            }
            if (distinct.size() == mapping.size()) {
                candidates.push_back(std::move(mapping));
            }
        }
    }
    if (candidates.empty()) {
        return std::nullopt;
    }
    for (size_t i = 1; i < candidates.size(); ++i) {
        if (candidates[i] != candidates.front()) {
            return std::nullopt;
        }
    }
    return candidates.front();
}

// ---- declarations (dat.py:227-295) -------------------------------------------

// dat.py:227-247 `_horizon_field_mapping`.
std::map<QString, long long> horizon_field_mapping(
    const std::vector<QString>& header, long long row_width) {
    static const std::set<QString> kFields = {
        QStringLiteral("x"), QStringLiteral("y"), QStringLiteral("z")};
    std::map<QString, long long> mapping;
    std::set<long long> used_indices;
    for (const QString& line : header) {
        const std::vector<QString> tokens = header_tokens(line);
        if (static_cast<long long>(tokens.size()) < 3 ||
            tokens.front().toLower() != QStringLiteral("field:")) {
            continue;
        }
        bool ok = false;
        const long long index = tokens[1].toLongLong(&ok) - 1;  // int() - 1
        if (!ok) {
            throw DatSchemaError(QStringLiteral("invalid horizon field index"));
        }
        const QString name = normalized_column(tokens[2]);
        if (kFields.count(name) == 0) {
            continue;
        }
        if (mapping.count(name) > 0 || used_indices.count(index) > 0 ||
            index < 0 || index >= row_width) {
            throw DatSchemaError(
                QStringLiteral("ambiguous horizon field mapping"));
        }
        mapping[name] = index;
        used_indices.insert(index);
    }
    if (mapping.size() != kFields.size()) {  // keys ⊆ {x,y,z} ⇒ == {x,y,z}
        throw DatSchemaError(QStringLiteral("missing horizon field mapping"));
    }
    return mapping;
}

// dat.py:250-261 `_unit_declarations`.
std::map<QString, QString> unit_declarations(const std::vector<QString>& header) {
    std::map<QString, QString> units;
    for (const QString& line : header) {
        const std::vector<QString> tokens = header_tokens(line);
        if (tokens.size() != 2 || !tokens[1].startsWith(u'.')) {
            continue;
        }
        const QString field = normalized_column(tokens[0]);
        qsizetype unit_start = 0;
        while (unit_start < tokens[1].size() &&
               tokens[1].at(unit_start) == u'.') {
            ++unit_start;  // tokens[1].lstrip(".")
        }
        const QString unit = normalized_column(tokens[1].mid(unit_start));
        const auto existing = units.find(field);
        if (existing != units.end() && existing->second != unit) {
            throw DatSchemaError(QStringLiteral("conflicting field units"));
        }
        units[field] = unit;
    }
    return units;
}

// dat.py:287-291 `_canonical_explicit_crs` — normalize explicit CRS syntax
// only; never infer from coordinate values.
QString canonical_explicit_crs(const QString& value) {
    // " ".join(value.casefold().split())
    static const QRegularExpression collapse(
        QStringLiteral("\\s+"), QRegularExpression::UseUnicodePropertiesOption);
    const QString normalized =
        value.toLower().split(collapse, Qt::SkipEmptyParts).join(u' ');
    static const QRegularExpression epsg(
        QStringLiteral("\\bepsg\\s*:\\s*(\\d+)\\b"));
    const QRegularExpressionMatch match = epsg.match(normalized);
    if (match.hasMatch()) {
        return QStringLiteral("epsg:%1").arg(match.captured(1));
    }
    return normalized;
}

// dat.py:294-295 `_same_explicit_crs`.
bool same_explicit_crs(const QString& left, const QString& right) {
    return canonical_explicit_crs(left) == canonical_explicit_crs(right);
}

// dat.py:264-284 `_source_crs_declaration`.
QString source_crs_declaration(const std::vector<QString>& header) {
    std::vector<QString> declarations;
    for (const QString& line : header) {
        qsizetype body_start = 0;
        while (body_start < line.size() && line.at(body_start) == u'#') {
            ++body_start;  // line.lstrip("#")
        }
        const QString body = line.mid(body_start).trimmed();
        const qsizetype colon = body.indexOf(u':');
        if (colon < 0) {
            continue;
        }
        const QString key = body.left(colon);
        const QString normalized_key = normalized_column(key);
        if (normalized_key != QStringLiteral("crs") &&
            normalized_key != QStringLiteral("sourcecrs")) {
            continue;
        }
        const QString value = body.mid(colon + 1).trimmed();
        if (value.isEmpty()) {
            throw DatSchemaError(QStringLiteral("empty SourceCRS declaration"));
        }
        declarations.push_back(value);
    }
    if (declarations.empty()) {
        return QString();
    }
    for (size_t i = 1; i < declarations.size(); ++i) {
        if (!same_explicit_crs(declarations[i], declarations.front())) {
            throw DatSchemaError(
                QStringLiteral("conflicting SourceCRS declarations"));
        }
    }
    return declarations.front();
}

// X/Y unit pair with the dat.py:644-653 conflict gate. Returns "" when the
// file declares neither axis unit.
QString declared_xy_units(const std::vector<QString>& header) {
    const std::map<QString, QString> units = unit_declarations(header);
    const auto x = units.find(QStringLiteral("x"));
    const auto y = units.find(QStringLiteral("y"));
    const QString x_unit = x == units.end() ? QString() : x->second;
    const QString y_unit = y == units.end() ? QString() : y->second;
    if (!x_unit.isEmpty() && !y_unit.isEmpty() && x_unit != y_unit) {
        throw DatSchemaError(
            QStringLiteral("conflicting X/Y coordinate units"));
    }
    return !x_unit.isEmpty() ? x_unit : y_unit;
}

// ---- row values (dat.py:560-574) ----------------------------------------------

// dat.py:560-567 `_finite_float`.
double finite_float(const QString& value) {
    bool ok = false;
    const double parsed = value.toDouble(&ok);
    if (!ok) {
        throw DatSchemaError(QStringLiteral("not numeric: %1").arg(value));
    }
    if (!std::isfinite(parsed)) {
        throw DatSchemaError(QStringLiteral("not finite: %1").arg(value));
    }
    return parsed;
}

// dat.py:570-574 `_value_at`.
QString value_at(const std::vector<QString>& row, long long index) {
    if (index < 0 || index >= static_cast<long long>(row.size())) {
        throw DatSchemaError(QStringLiteral("row has too few columns"));
    }
    return row[static_cast<size_t>(index)];
}

// ---- sampling (dat.py:125-128) ------------------------------------------------

// `representative_indices`: numpy >= 1.20 `np.linspace(0, length-1, num=limit,
// dtype=int64)` — y[i] = floor(float64(i) * ((length-1)/(limit-1))), with the
// last sample pinned to the stop value by linspace's endpoint handling.
std::vector<long long> representative_indices(long long length, long long limit) {
    if (length <= limit) {
        std::vector<long long> all(static_cast<size_t>(length));
        for (long long i = 0; i < length; ++i) {
            all[static_cast<size_t>(i)] = i;
        }
        return all;
    }
    if (limit <= 1) {
        return {0};  // linspace(..., num=1) == [start]
    }
    std::vector<long long> sampled(static_cast<size_t>(limit));
    const double step =
        static_cast<double>(length - 1) / static_cast<double>(limit - 1);
    for (long long i = 0; i < limit; ++i) {
        const double value = static_cast<double>(i) * step;
        sampled[static_cast<size_t>(i)] =
            static_cast<long long>(std::floor(value));
    }
    sampled.back() = length - 1;  // endpoint pinning
    return sampled;
}

// dat.py:577-578 `_sample_limit`.
long long sample_limit(int max_points) {
    return std::max(1LL, std::min<long long>(max_points, kMaxPoints));
}

// ---- geometry gate (dat.py:813-822) ---------------------------------------------

// numpy.linalg.matrix_rank(unique_xy - mean) < 2 for an n×2 matrix: the
// two singular values are the square roots of the 2×2 Gram eigenvalues,
// and numpy's default tol is σ1 * max(shape) * eps. rank < 2 ⟺ σ2 ≤ tol.
// (Singular values via the Gram matrix are mathematically identical to
// LAPACK's SVD; bit-level equality is not claimed for adversarially
// near-collinear inputs, where numpy's SVD and this closed form both sit
// at the eps-scale noise floor.)
bool matrix_rank_below_two(const std::set<std::pair<double, double>>& points) {
    const double n = static_cast<double>(points.size());  // ≥ 3 at call sites
    double mean_x = 0.0;
    double mean_y = 0.0;
    for (const auto& [x, y] : points) {
        mean_x += x;
        mean_y += y;
    }
    mean_x /= n;
    mean_y /= n;
    double g11 = 0.0;  // Gram matrix of the centered columns
    double g12 = 0.0;
    double g22 = 0.0;
    for (const auto& [x, y] : points) {
        const double cx = x - mean_x;
        const double cy = y - mean_y;
        g11 += cx * cx;
        g12 += cx * cy;
        g22 += cy * cy;
    }
    const double trace = g11 + g22;
    const double discriminant =
        std::sqrt((g11 - g22) * (g11 - g22) + 4.0 * g12 * g12);
    const double sigma1 = std::sqrt(std::max(0.0, (trace + discriminant) / 2.0));
    const double sigma2 = std::sqrt(std::max(0.0, (trace - discriminant) / 2.0));
    const double tol =
        sigma1 * n * std::numeric_limits<double>::epsilon();
    return !(sigma2 > tol);
}

// Python f"{value:,}" (positive values only here).
QString thousands_separated(long long value) {
    QString digits = QString::number(value);
    for (int pos = static_cast<int>(digits.size()) - 3; pos > 0; pos -= 3) {
        digits.insert(pos, u',');
    }
    return digits;
}

// ---- shared read passes --------------------------------------------------------

// dat.py:455-471 `_read_dat_data_lines`: one pass collecting the retained
// header and every raw data line.
struct HeaderAndDataLines {
    std::vector<QString> header;
    std::vector<QString> data_lines;
};

HeaderAndDataLines read_dat_data_lines(const QString& text) {
    HeaderAndDataLines result;
    long long header_chars = 0;
    for (const QString& raw : split_lines_universal(text)) {
        const QString line = trimmed_line(raw);
        if (line.isEmpty()) {
            continue;
        }
        if (is_comment(line)) {
            header_chars =
                retain_header_line(result.header, header_chars, line);
            continue;
        }
        result.data_lines.push_back(line);
    }
    if (result.data_lines.empty()) {
        throw DatSchemaError(QStringLiteral("no data rows"));
    }
    return result;
}

bool header_contains(const std::vector<QString>& header, const QString& marker) {
    for (const QString& line : header) {
        if (line.contains(marker)) {
            return true;
        }
    }
    return false;
}

// ---- well-head payload (dat.py:587-765) ------------------------------------------

WellHeadPreview well_head_payload(const QString& text, long long limit) {
    const std::vector<QString> header = read_header(text);
    if (!header_contains(header, QStringLiteral("WellHead File From SMI"))) {
        throw DatSchemaError(QStringLiteral("missing well-head marker"));
    }
    const auto mapping_opt = column_mapping(header, well_head_aliases(),
                                            well_head_extras(), std::nullopt);
    if (!mapping_opt) {
        throw DatSchemaError(
            QStringLiteral("missing required Name/X/Y columns"));
    }
    const std::map<QString, long long>& mapping = *mapping_opt;

    // dat.py:607-622 — widths of header lines whose columns are all
    // well-head vocabulary and cover every mapped index; exactly one width.
    std::set<QString> allowed_width_columns = well_head_extras();
    for (const auto& entry : well_head_aliases()) {
        allowed_width_columns.insert(entry.second.cbegin(),
                                     entry.second.cend());
    }
    std::set<long long> declaration_widths;
    for (const QString& line : header) {
        const std::vector<QString> tokens = header_tokens(line);
        if (tokens.empty()) {
            continue;
        }
        bool covers_mapping = true;
        for (const auto& [field, index] : mapping) {
            if (index >= static_cast<long long>(tokens.size())) {
                covers_mapping = false;
                break;
            }
        }
        if (!covers_mapping) {
            continue;
        }
        bool all_known = true;
        for (const QString& token : tokens) {
            if (allowed_width_columns.count(normalized_column(token)) == 0) {
                all_known = false;
                break;
            }
        }
        if (all_known) {
            declaration_widths.insert(
                static_cast<long long>(tokens.size()));
        }
    }
    if (declaration_widths.size() != 1) {
        throw DatSchemaError(
            QStringLiteral("ambiguous well-head column width"));
    }
    const long long row_width = *declaration_widths.begin();

    // dat.py:629-641 — single unambiguous `uwi` column among declared-width
    // header lines; zero or conflicting votes ⇒ no UWI.
    std::set<long long> uwi_votes;
    for (const QString& line : header) {
        const std::vector<QString> tokens = header_tokens(line);
        if (tokens.empty() ||
            static_cast<long long>(tokens.size()) != row_width) {
            continue;
        }
        std::vector<long long> matches;
        for (long long index = 0;
             index < static_cast<long long>(tokens.size()); ++index) {
            if (normalized_column(tokens[static_cast<size_t>(index)]) ==
                QStringLiteral("uwi")) {
                matches.push_back(index);
            }
        }
        if (matches.size() == 1) {
            uwi_votes.insert(matches.front());
        }
    }
    const std::optional<long long> uwi_index =
        uwi_votes.size() == 1
            ? std::optional<long long>(*uwi_votes.begin())
            : std::nullopt;

    // dat.py:643-653 — file declarations only; the C++ API carries no asset
    // metadata, which is exactly `_merge_declared_metadata("", declared)`.
    const QString declared_crs = source_crs_declaration(header);
    const QString declared_units = declared_xy_units(header);

    // dat.py:698-731 — per-row parse with issue capture (first 20, then a
    // running omission count) and the hard display cap after each append.
    WellHeadPreview preview;
    std::vector<QString> issue_reasons;
    std::vector<long long> issue_rows;
    long long omitted_issue_count = 0;
    long long row_count = 0;

    const std::vector<QString> lines = split_lines_universal(text);
    for (size_t line_index = 0; line_index < lines.size(); ++line_index) {
        const QString line = trimmed_line(lines[line_index]);
        if (line.isEmpty() || is_comment(line)) {
            continue;
        }
        const long long source_row =
            static_cast<long long>(line_index) + 1;  // enumerate(start=1)
        ++row_count;
        try {
            const std::vector<QString> row = split_data_line(line);
            if (static_cast<long long>(row.size()) != row_width) {
                throw DatSchemaError(QStringLiteral("列数与声明不一致"));
            }
            // parse_row (dat.py:672-690)
            const QString name = value_at(row, mapping.at(QStringLiteral("name")));
            if (name.isEmpty()) {
                throw DatSchemaError(QStringLiteral("井名为空"));
            }
            double x = 0.0;
            try {
                x = finite_float(
                    value_at(row, mapping.at(QStringLiteral("x"))));
            } catch (const DatSchemaError&) {
                throw DatSchemaError(QStringLiteral("X 坐标不是有限数值"));
            }
            double y = 0.0;
            try {
                y = finite_float(
                    value_at(row, mapping.at(QStringLiteral("y"))));
            } catch (const DatSchemaError&) {
                throw DatSchemaError(QStringLiteral("Y 坐标不是有限数值"));
            }
            const QString uwi =
                uwi_index
                    ? value_at(row, *uwi_index).trimmed()
                    : QString();
            WellHeadRecord record;
            record.name = name.toStdString();
            record.x = x;
            record.y = y;
            record.uwi = uwi.toStdString();
            preview.records.push_back(std::move(record));
        } catch (const DatSchemaError& error) {
            if (issue_reasons.size() < 20) {
                issue_reasons.push_back(error.detail);
                issue_rows.push_back(source_row);
            } else {
                ++omitted_issue_count;
            }
            continue;
        }
        // dat.py:715-718 — hard cap on valid records (RESOURCE_LIMIT).
        if (static_cast<long long>(preview.records.size()) > limit) {
            throw WellResourceLimitError(
                QStringLiteral("井位数据超过 %1 个有效记录的显示上限")
                    .arg(thousands_separated(limit)));
        }
    }

    if (row_count == 0) {
        throw DatSchemaError(QStringLiteral("no data rows"));
    }
    if (preview.records.empty()) {
        // dat.py:721-731 — detail carries the recorded causes verbatim.
        QString detail = QStringLiteral("no renderable well locations");
        if (!issue_reasons.empty()) {
            QStringList causes;
            for (size_t i = 0; i < issue_reasons.size(); ++i) {
                causes << QStringLiteral("source row %1: %2")
                              .arg(issue_rows[i])
                              .arg(issue_reasons[i]);
            }
            detail += QStringLiteral("; ") + causes.join(QStringLiteral("; "));
        }
        if (omitted_issue_count > 0) {
            detail += QStringLiteral("; %1 additional rows omitted")
                          .arg(omitted_issue_count);
        }
        throw DatSchemaError(detail);
    }

    preview.total_records = row_count;
    preview.valid_records = static_cast<long long>(preview.records.size());
    preview.skipped_records = preview.total_records - preview.valid_records;
    preview.source_crs = declared_crs.toStdString();
    preview.coordinate_units = declared_units.toStdString();
    preview.source_version.clear();  // asset metadata not ported (dat.py:739)
    return preview;
}

// ---- horizon payload (dat.py:792-826) ----------------------------------------------

HorizonPoints horizon_payload(const QString& text, long long limit) {
    const HeaderAndDataLines parsed = read_dat_data_lines(text);
    const std::vector<QString>& header = parsed.header;
    const std::vector<QString>& data_lines = parsed.data_lines;
    if (!header_contains(header, QStringLiteral("XYZInlineCrossline"))) {
        throw DatSchemaError(QStringLiteral("missing horizon marker"));
    }
    const std::vector<QString> first_row = split_data_line(data_lines.front());
    if (first_row.empty()) {
        throw DatSchemaError(QStringLiteral("no data rows"));
    }
    const std::map<QString, long long> mapping =
        horizon_field_mapping(header,
                              static_cast<long long>(first_row.size()));

    // dat.py:808-809 + :474-486 — sample rows, keep the sampled width
    // consistent, parse finite XYZ at the mapped indices.
    const std::vector<long long> source_indices = representative_indices(
        static_cast<long long>(data_lines.size()), limit);
    HorizonPoints points;
    long long sampled_width = 0;
    for (const long long index : source_indices) {
        const std::vector<QString> row =
            split_data_line(data_lines[static_cast<size_t>(index)]);
        if (row.empty()) {
            throw DatSchemaError(
                QStringLiteral("row count changed while reading"));
        }
        if (sampled_width == 0) {
            sampled_width = static_cast<long long>(row.size());
        } else if (static_cast<long long>(row.size()) != sampled_width) {
            throw DatSchemaError(QStringLiteral("inconsistent row width"));
        }
        points.x.push_back(
            finite_float(value_at(row, mapping.at(QStringLiteral("x")))));
        points.y.push_back(
            finite_float(value_at(row, mapping.at(QStringLiteral("y")))));
        points.z.push_back(
            finite_float(value_at(row, mapping.at(QStringLiteral("z")))));
    }

    // dat.py:813-822 — independent-geometry gate over the sampled points.
    const long long n = static_cast<long long>(points.x.size());
    std::set<std::pair<double, double>> unique_xy;
    std::set<double> unique_x;
    std::set<double> unique_y;
    for (size_t i = 0; i < points.x.size(); ++i) {
        unique_xy.emplace(points.x[i], points.y[i]);
        unique_x.insert(points.x[i]);
        unique_y.insert(points.y[i]);
    }
    const bool insufficient =
        n < 3 || static_cast<long long>(unique_xy.size()) != n ||
        static_cast<long long>(unique_x.size()) < 2 ||
        static_cast<long long>(unique_y.size()) < 2 ||
        matrix_rank_below_two(unique_xy);
    if (insufficient) {
        throw DatSchemaError(
            QStringLiteral("insufficient independent horizon geometry"));
    }

    // dat.py:823-826 — axis decision (ranges consumed by the mapping_kernel
    // IDW stage as linspace(min, max, grid_n); see viz_e_dat_preview.hpp).
    const long long axis_limit =
        std::max(1LL, std::min(kDefaultSurfaceGridSize, kMaxSurfaceAxis));
    const long long axis_size = std::min(
        axis_limit,
        std::max(2LL, static_cast<long long>(std::ceil(std::sqrt(
                          static_cast<double>(source_indices.size()))))));

    points.total_records = static_cast<long long>(data_lines.size());
    points.skipped_records =
        points.total_records - static_cast<long long>(points.x.size());
    points.x_min = *std::min_element(points.x.begin(), points.x.end());
    points.x_max = *std::max_element(points.x.begin(), points.x.end());
    points.y_min = *std::min_element(points.y.begin(), points.y.end());
    points.y_max = *std::max_element(points.y.begin(), points.y.end());
    points.grid_n = static_cast<int>(axis_size);
    // Documented additive extension (see header): surface provenance via the
    // identical declaration helpers used by the well-head path.
    points.source_crs = source_crs_declaration(header).toStdString();
    points.coordinate_units = declared_xy_units(header).toStdString();
    return points;
}

// ---- GeoVizError translation (dat.py:581-584, :973-977, :1109-1110) --------

template <typename Payload, typename Body>
Payload with_geoviz_errors(Body&& body) {
    try {
        return body();
    } catch (const WellResourceLimitError& error) {
        // RESOURCE_LIMIT carries str(error) verbatim, no schema prefix.
        throw std::runtime_error(error.what());
    } catch (const IoError&) {
        throw;  // already "无法读取 DAT 数据: …"
    } catch (const DatSchemaError& error) {
        throw std::runtime_error(
            QStringLiteral("DAT 数据结构与资源类型不匹配: %1")
                .arg(error.detail)
                .toStdString());
    }
}

}  // namespace

WellHeadPreview parse_well_head(const std::string& path, int max_points) {
    const long long limit = sample_limit(max_points);
    return with_geoviz_errors<WellHeadPreview>([&] {
        return well_head_payload(read_text_utf8_sig(path), limit);
    });
}

bool well_head_supported(const std::string& path) {
    try {
        const QString text = read_text_utf8_sig(path);
        const std::vector<QString> header = read_header(text);
        if (!header_contains(header, QStringLiteral("WellHead File From SMI"))) {
            return false;
        }
        return column_mapping(header, well_head_aliases(), well_head_extras(),
                              std::nullopt)
            .has_value();
    } catch (const std::exception&) {
        return false;  // _supports_with_header (dat.py:438-443)
    }
}

HorizonPoints parse_horizon_points(const std::string& path, int max_points) {
    const long long limit = sample_limit(max_points);
    return with_geoviz_errors<HorizonPoints>([&] {
        return horizon_payload(read_text_utf8_sig(path), limit);
    });
}

bool horizon_supported(const std::string& path) {
    try {
        const QString text = read_text_utf8_sig(path);
        const std::vector<QString> header = read_header(text);
        if (!header_contains(header, QStringLiteral("XYZInlineCrossline"))) {
            return false;
        }
        // Row width for the FIELD mapping comes from the first data line.
        std::optional<long long> row_width;
        for (const QString& raw : split_lines_universal(text)) {
            const QString line = trimmed_line(raw);
            if (line.isEmpty() || is_comment(line)) {
                continue;
            }
            row_width = static_cast<long long>(split_data_line(line).size());
            break;
        }
        if (!row_width) {
            return false;  // no data rows — parse would fail
        }
        horizon_field_mapping(header, *row_width);
        return true;
    } catch (const std::exception&) {
        return false;  // _supports_with_header (dat.py:438-443)
    }
}

int horizon_grid_resolution(const HorizonPoints& pts) { return pts.grid_n; }

}  // namespace pwb::viz_e
