#include <pwb/seismic_viewer/horizon_core.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <map>
#include <stdexcept>
#include <utility>

namespace pwb::seismic_viewer::horizon {
namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
constexpr double kInf = std::numeric_limits<double>::infinity();

bool is_num_start(char c) {
    return (c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.';
}

// Oracle regex `[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?` — scanner version with the
// same left-to-right non-overlapping semantics as Python's re.findall
// (greedy digits, optional dot, at least one digit AFTER the dot, optional
// exponent glued directly onto the digit tail — so "1.e3" matches only
// "1", never "1.e3").
bool scan_number(std::string_view text, std::size_t& pos, double& out) {
    const std::size_t n = text.size();
    while (true) {
        while (pos < n && !is_num_start(text[pos])) {
            ++pos;
        }
        if (pos >= n) {
            return false;
        }
        std::size_t p = pos;
        std::string token;
        bool has_digits = false;
        if (p < n && (text[p] == '-' || text[p] == '+')) {
            token += text[p];
            ++p;
        }
        while (p < n && text[p] >= '0' && text[p] <= '9') {
            token += text[p];
            ++p;
            has_digits = true;
        }
        if (p < n && text[p] == '.') {
            std::size_t q = p + 1;
            std::string frac;
            while (q < n && text[q] >= '0' && text[q] <= '9') {
                frac += text[q];
                ++q;
            }
            if (!frac.empty()) {
                token += '.';
                token += frac;
                p = q;
                has_digits = true;
            }
            // A trailing dot without digits ends the match HERE (p stays on
            // the dot): "1." scans as "1" and "1.e3" as "1" + separately
            // "3" — the exponent never glues onto a digit-dot-dot tail
            // (regex `\d+` must sit immediately before [eE]).
        }
        if (!has_digits) {
            pos = p;
            if (pos < n && text[pos] == '.') {
                ++pos; // skip the unmatched bare dot (no infinite loop)
            }
            continue; // a bare sign/dot: rescan from after it (loop, no recursion)
        }
        // The exponent glues onto the digit tail only.
        if (p < n && (text[p] == 'e' || text[p] == 'E')) {
            std::size_t q = p + 1;
            std::string expo = "e";
            if (q < n && (text[q] == '-' || text[q] == '+')) {
                expo += text[q];
                ++q;
            }
            std::string digits;
            while (q < n && text[q] >= '0' && text[q] <= '9') {
                digits += text[q];
                ++q;
            }
            if (!digits.empty()) {
                token += expo + digits;
                p = q;
            }
        }
        pos = p;
        out = std::strtod(token.c_str(), nullptr);
        return true;
    }
}

} // namespace

std::vector<std::array<std::int64_t, 3>> horizon_quad_faces(std::int64_t n_i,
                                                            std::int64_t n_x) {
    std::vector<std::array<std::int64_t, 3>> faces;
    if (n_i < 2 || n_x < 2) {
        return faces;
    }
    faces.reserve(static_cast<std::size_t>((n_i - 1) * (n_x - 1) * 2));
    for (std::int64_t i = 0; i + 1 < n_i; ++i) {
        for (std::int64_t j = 0; j + 1 < n_x; ++j) {
            const std::int64_t p0 = i * n_x + j;
            const std::int64_t p1 = p0 + 1;
            const std::int64_t p2 = p0 + n_x;
            const std::int64_t p3 = p2 + 1;
            faces.push_back({p0, p1, p2});
            faces.push_back({p1, p3, p2});
        }
    }
    return faces;
}

ParsedHorizon parse_horizon_text(std::string_view text, const HorizonAxes& axes,
                                 double scale, std::int64_t iline_offset,
                                 std::int64_t xline_offset) {
    std::map<std::pair<std::int64_t, std::int64_t>, double> points;
    std::size_t start = 0;
    while (start < text.size()) {
        std::size_t end = text.find('\n', start);
        if (end == std::string_view::npos) {
            end = text.size();
        }
        std::string_view line = text.substr(start, end - start);
        start = end + 1;
        std::vector<double> nums;
        std::size_t pos = 0;
        while (pos < line.size()) {
            double value = 0.0;
            if (!scan_number(line, pos, value)) {
                break;
            }
            nums.push_back(value);
            if (nums.size() >= 3) {
                break; // only the first three numbers matter
            }
        }
        if (nums.size() < 3) {
            continue;
        }
        const auto il = static_cast<std::int64_t>(std::trunc(nums[0]));
        const auto xl = static_cast<std::int64_t>(std::trunc(nums[1]));
        points[{il, xl}] = nums[2] * scale;
    }
    if (points.empty()) {
        throw std::invalid_argument(
            "No valid data points found in horizon text. "
            "Expected format: inline crossline time_ms (tab-separated). "
            "Each line should have at least 3 numeric columns.");
    }
    std::map<std::int64_t, std::int64_t> il_to_i;
    for (std::size_t i = 0; i < axes.ilines.size(); ++i) {
        il_to_i[axes.ilines[i]] = static_cast<std::int64_t>(i);
    }
    std::map<std::int64_t, std::int64_t> xl_to_j;
    for (std::size_t j = 0; j < axes.xlines.size(); ++j) {
        xl_to_j[axes.xlines[j]] = static_cast<std::int64_t>(j);
    }
    ParsedHorizon parsed;
    parsed.grid = Grid2D(static_cast<std::int64_t>(axes.ilines.size()),
                         static_cast<std::int64_t>(axes.xlines.size()), kNaN);
    parsed.points_read = static_cast<int>(points.size());
    for (const auto& [key, value] : points) {
        const auto it_i = il_to_i.find(key.first + iline_offset);
        const auto it_j = xl_to_j.find(key.second + xline_offset);
        if (it_i != il_to_i.end() && it_j != xl_to_j.end()) {
            parsed.grid.at(it_i->second, it_j->second) = value;
            ++parsed.matched;
        }
    }
    return parsed;
}

Grid2D fill_nearest(const Grid2D& grid, double max_dist) {
    const std::int64_t rows = grid.rows;
    const std::int64_t cols = grid.cols;
    Grid2D out = grid;
    if (rows <= 0 || cols <= 0) {
        return out;
    }
    // Gap cells filled from the exact nearest sample. Distances are compared
    // as INTEGER squared distances (exact — no float drift). The C++ tie
    // rule on equidistant samples is deterministic min(|dr|, row, col)
    // (same-row first, then smaller row, then smaller column); scipy's EDT
    // resolves exact ties by its internal pass order, which coincides on
    // small crafted cases but NOT on every random grid — value-level tie
    // parity is therefore declared out of scope (fixtures avoid or coincide;
    // see docs/development/cpp-viz-d/v5-product-delta.md). Search expands
    // row-band by row-band from the gap (|dr| = 0, 1, …) with the column
    // window narrowed by the best distance so far —
    // O(gaps * (2d+1) * avg-window) on gap-sparse grids.
    for (std::int64_t r = 0; r < rows; ++r) {
        for (std::int64_t c = 0; c < cols; ++c) {
            if (std::isfinite(grid.at(r, c))) {
                continue;
            }
            std::int64_t best_d2 = std::numeric_limits<std::int64_t>::max();
            std::int64_t best_row = -1;
            std::int64_t best_col = -1;
            for (std::int64_t k = 0; k * k <= best_d2; ++k) {
                const bool has_up = r - k >= 0;
                const bool has_down = r + k < rows;
                if (!has_up && !has_down) {
                    break;
                }
                // Row r-k first: at equal |dr| the smaller row wins ties.
                const auto scan_row = [&](std::int64_t rr) {
                    if (rr < 0 || rr >= rows) {
                        return;
                    }
                    const std::int64_t remaining = best_d2 - k * k;
                    const std::int64_t half = static_cast<std::int64_t>(
                        std::floor(std::sqrt(static_cast<double>(remaining < 0 ? 0 : remaining))));
                    const std::int64_t c_lo = std::max<std::int64_t>(0, c - half);
                    const std::int64_t c_hi = std::min<std::int64_t>(cols - 1, c + half);
                    for (std::int64_t cc = c_lo; cc <= c_hi; ++cc) {
                        if (!std::isfinite(grid.at(rr, cc))) {
                            continue;
                        }
                        const std::int64_t dc = cc - c;
                        const std::int64_t d2 = k * k + dc * dc;
                        if (d2 < best_d2) {
                            best_d2 = d2;
                            best_row = rr;
                            best_col = cc;
                        }
                        // Ties keep the earlier (smaller row / smaller column)
                        // hit: strict < above never replaces on equality.
                    }
                };
                scan_row(r - k);
                scan_row(r + k);
            }
            if (best_row < 0) {
                continue; // no finite sample at all
            }
            if (max_dist > 0.0) {
                const double distance = std::sqrt(static_cast<double>(best_d2));
                if (distance > max_dist) {
                    continue; // beyond the cap: stays NaN
                }
            }
            out.at(r, c) = grid.at(best_row, best_col);
        }
    }
    return out;
}

Grid2D fill_rbf(const Grid2D& grid, double max_dist, int neighbors, double smoothing) {
    const std::int64_t rows = grid.rows;
    const std::int64_t cols = grid.cols;
    Grid2D out = grid;
    if (rows <= 0 || cols <= 0) {
        return out;
    }
    struct Node {
        double y;
        double x;
        double value;
    };
    std::vector<Node> nodes;
    std::vector<std::pair<std::int64_t, std::int64_t>> gaps;
    for (std::int64_t r = 0; r < rows; ++r) {
        for (std::int64_t c = 0; c < cols; ++c) {
            if (std::isfinite(grid.at(r, c))) {
                nodes.push_back({static_cast<double>(r), static_cast<double>(c),
                                 grid.at(r, c)});
            } else {
                gaps.emplace_back(r, c);
            }
        }
    }
    if (nodes.empty() || gaps.empty()) {
        return out;
    }
    const std::size_t k = std::min<std::size_t>(
        static_cast<std::size_t>(std::max(neighbors, 1)), nodes.size());

    for (const auto& [gr, gc] : gaps) {
        const double ty = static_cast<double>(gr);
        const double tx = static_cast<double>(gc);
        // k nearest known cells by Euclidean distance (stable on ties by
        // node order — fixtures avoid distance ties).
        std::vector<std::pair<double, std::size_t>> ranked;
        ranked.reserve(nodes.size());
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            ranked.emplace_back(std::hypot(nodes[i].y - ty, nodes[i].x - tx), i);
        }
        std::partial_sort(ranked.begin(), ranked.begin() + static_cast<std::ptrdiff_t>(k),
                          ranked.end());
        // Kernel block + degree-0 (constant) polynomial term.
        const std::size_t m = k + 1;
        std::vector<double> a(m * m, 0.0);
        std::vector<double> rhs(m, 0.0);
        for (std::size_t i = 0; i < k; ++i) {
            const Node& ni = nodes[ranked[i].second];
            for (std::size_t j = 0; j < k; ++j) {
                const Node& nj = nodes[ranked[j].second];
                // scipy's "linear" RBF kernel is phi(r) = -r.
                a[i * m + j] = -std::hypot(ni.y - nj.y, ni.x - nj.x);
            }
            a[i * m + k] = 1.0;
            a[k * m + i] = 1.0;
            rhs[i] = ni.value;
        }
        if (smoothing > 0.0) {
            for (std::size_t i = 0; i < k; ++i) {
                a[i * m + i] += smoothing;
            }
        }
        // Gaussian elimination with partial pivoting; singular systems get
        // a tiny diagonal nudge (declared vs scipy's lstsq).
        for (std::size_t col = 0; col < m; ++col) {
            std::size_t pivot = col;
            for (std::size_t r = col + 1; r < m; ++r) {
                if (std::abs(a[r * m + col]) > std::abs(a[pivot * m + col])) {
                    pivot = r;
                }
            }
            if (std::abs(a[pivot * m + col]) < 1e-13) {
                a[pivot * m + col] += 1e-12;
            }
            if (pivot != col) {
                for (std::size_t j = 0; j < m; ++j) {
                    std::swap(a[pivot * m + j], a[col * m + j]);
                }
                std::swap(rhs[pivot], rhs[col]);
            }
            for (std::size_t r = col + 1; r < m; ++r) {
                const double factor = a[r * m + col] / a[col * m + col];
                if (factor == 0.0) {
                    continue;
                }
                for (std::size_t j = col; j < m; ++j) {
                    a[r * m + j] -= factor * a[col * m + j];
                }
                rhs[r] -= factor * rhs[col];
            }
        }
        std::vector<double> w(m, 0.0);
        for (std::size_t ii = m; ii-- > 0;) {
            double acc = rhs[ii];
            for (std::size_t j = ii + 1; j < m; ++j) {
                acc -= a[ii * m + j] * w[j];
            }
            w[ii] = acc / a[ii * m + ii];
        }
        double value = w[k]; // constant (degree-0) term
        for (std::size_t i = 0; i < k; ++i) {
            const Node& ni = nodes[ranked[i].second];
            value += w[i] * -std::hypot(ni.y - ty, ni.x - tx);
        }
        out.at(gr, gc) = value;
    }

    if (max_dist > 0.0) {
        // Same EDT cap as fill_nearest: gaps beyond max_dist stay NaN.
        const Grid2D nearest_distances = fill_nearest(grid, max_dist);
        for (const auto& [gr, gc] : gaps) {
            if (!std::isfinite(nearest_distances.at(gr, gc))) {
                out.at(gr, gc) = kNaN;
            }
        }
    }
    return out;
}

std::vector<float> extract_along_horizon(std::span<const float> volume, std::int64_t n_i,
                                         std::int64_t n_x, std::int64_t n_s,
                                         const Grid2D& grid, double dt_ms, double t0_ms,
                                         int window) {
    std::vector<float> out(static_cast<std::size_t>(grid.rows * grid.cols), kNaN);
    if (volume.size() != static_cast<std::size_t>(n_i * n_x * n_s) || n_i <= 0 ||
        n_x <= 0 || n_s <= 0 || grid.rows != n_i || grid.cols != n_x ||
        !(dt_ms != 0.0) || !std::isfinite(dt_ms)) {
        return out; // dt_ms == 0 would inf the sample index (UB on the cast)
    }
    const auto sample = [&](std::int64_t i, std::int64_t j, std::int64_t s) -> float {
        return volume[(static_cast<std::size_t>(i) * static_cast<std::size_t>(n_x) +
                       static_cast<std::size_t>(j)) *
                          static_cast<std::size_t>(n_s) +
                      static_cast<std::size_t>(s)];
    };
    const auto idx_of = [&](double twt) -> std::int64_t {
        // (grid - t0) / dt in float64, int32 truncation, clipped to the
        // sample extent (numpy astype(int32) parity).
        const double raw = (twt - t0_ms) / dt_ms;
        const auto truncated = static_cast<std::int32_t>(raw);
        return std::clamp<std::int64_t>(truncated, 0, n_s - 1);
    };
    for (std::int64_t i = 0; i < n_i; ++i) {
        for (std::int64_t j = 0; j < n_x; ++j) {
            const double twt = grid.at(i, j);
            if (!std::isfinite(twt)) {
                continue;
            }
            const std::int64_t center = idx_of(twt);
            if (window <= 0) {
                out[static_cast<std::size_t>(i * n_x + j)] = sample(i, j, center);
                continue;
            }
            // RMS over 2*window+1 samples; out-of-bounds offsets contribute
            // nothing, an empty window stays NaN (nanmean parity).
            double acc = 0.0;
            std::int64_t count = 0;
            for (int off = -window; off <= window; ++off) {
                const std::int64_t s = center + off;
                if (s < 0 || s >= n_s) {
                    continue;
                }
                const float v = sample(i, j, s);
                if (std::isfinite(v)) {
                    acc += static_cast<double>(v) * static_cast<double>(v);
                    ++count;
                }
            }
            if (count > 0) {
                const double mean_sq = acc / static_cast<double>(count);
                out[static_cast<std::size_t>(i * n_x + j)] =
                    static_cast<float>(std::sqrt(std::max(mean_sq, 0.0)));
            }
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// Pick model + persistence
// ---------------------------------------------------------------------------

void add_pick(HorizonPickSet& set, HorizonPick pick) {
    set.picks.push_back(pick);
}

bool remove_pick_near(HorizonPickSet& set, double inline_no, double crossline_no,
                      double time_value, double tol_inline, double tol_crossline,
                      double tol_time) {
    for (auto it = set.picks.begin(); it != set.picks.end(); ++it) {
        if (std::abs(it->inline_no - inline_no) <= tol_inline &&
            std::abs(it->crossline_no - crossline_no) <= tol_crossline &&
            std::abs(it->time_value - time_value) <= tol_time) {
            set.picks.erase(it);
            return true;
        }
    }
    return false;
}

bool move_pick(HorizonPickSet& set, std::size_t index, HorizonPick pick) {
    if (index >= set.picks.size()) {
        return false;
    }
    set.picks[index] = pick;
    return true;
}

void clear_picks(HorizonPickSet& set) { set.picks.clear(); }

namespace {

void json_escape_append(std::string& out, std::string_view text) {
    for (const char c : text) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(c) < 0x20) {
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                out += buf;
            } else {
                out += c;
            }
        }
    }
}

std::string json_string(std::string_view text) {
    std::string out = "\"";
    json_escape_append(out, text);
    out += '"';
    return out;
}

std::string json_number(double v) {
    if (!std::isfinite(v)) {
        return "null"; // fail-closed: NaN/inf never serialized as numbers
    }
    char buf[64];
    const int n = std::snprintf(buf, sizeof(buf), "%.17g", v);
    return std::string(buf, static_cast<std::size_t>(n < 0 ? 0 : n));
}

// Minimal strict JSON parser for the fixed pick schema (objects, arrays,
// strings, numbers, bools, null — no comments, fail-closed on trailing
// input).
class MiniJson {
public:
    explicit MiniJson(std::string_view text) : text_(text) {}

    // Adversarial inputs (a picks file full of "[[[[…") must fail closed,
    // not overflow the stack: the pick schema nests 3 levels.
    static constexpr std::size_t kMaxDepth = 64;

    // Parses one value; `value` holds: string / number / literal / children.
    struct Value {
        enum class Kind { string, number, boolean, null, array, object } kind{Kind::null};
        std::string str;
        double number{0.0};
        bool boolean{false};
        std::vector<Value> items;               // array
        std::vector<std::pair<std::string, Value>> members; // object
    };

    [[nodiscard]] bool parse(Value& out) {
        skip_ws();
        if (!parse_value(out)) {
            return false;
        }
        skip_ws();
        return pos_ >= text_.size();
    }

    [[nodiscard]] std::string error() const { return error_; }

private:
    void skip_ws() {
        while (pos_ < text_.size() &&
               (text_[pos_] == ' ' || text_[pos_] == '\t' || text_[pos_] == '\n' ||
                text_[pos_] == '\r')) {
            ++pos_;
        }
    }

    bool fail(const char* message) {
        if (error_.empty()) {
            error_ = std::string("horizon picks JSON: ") + message + " at offset " +
                     std::to_string(pos_);
        }
        return false;
    }

    bool parse_value(Value& out) {
        skip_ws();
        if (pos_ >= text_.size()) {
            return fail("unexpected end");
        }
        const char c = text_[pos_];
        if (c == '{') {
            return parse_object(out);
        }
        if (c == '[') {
            return parse_array(out);
        }
        if (c == '"') {
            out.kind = Value::Kind::string;
            return parse_string(out.str);
        }
        if (c == 't' || c == 'f') {
            out.kind = Value::Kind::boolean;
            return parse_bool(out.boolean);
        }
        if (c == 'n') {
            if (text_.compare(pos_, 4, "null") == 0) {
                pos_ += 4;
                out.kind = Value::Kind::null;
                return true;
            }
            return fail("bad literal");
        }
        return parse_number(out);
    }

    bool parse_object(Value& out) {
        if (++depth_ > kMaxDepth) {
            return fail("nesting too deep");
        }
        out.kind = Value::Kind::object;
        ++pos_; // {
        skip_ws();
        if (pos_ < text_.size() && text_[pos_] == '}') {
            ++pos_;
            return true;
        }
        while (true) {
            skip_ws();
            if (pos_ >= text_.size() || text_[pos_] != '"') {
                return fail("expected object key");
            }
            std::string key;
            if (!parse_string(key)) {
                return false;
            }
            skip_ws();
            if (pos_ >= text_.size() || text_[pos_] != ':') {
                return fail("expected ':'");
            }
            ++pos_;
            Value value;
            if (!parse_value(value)) {
                return false;
            }
            out.members.emplace_back(std::move(key), std::move(value));
            skip_ws();
            if (pos_ < text_.size() && text_[pos_] == ',') {
                ++pos_;
                continue;
            }
            if (pos_ < text_.size() && text_[pos_] == '}') {
                ++pos_;
                return true;
            }
            return fail("expected ',' or '}'");
        }
    }

    bool parse_array(Value& out) {
        if (++depth_ > kMaxDepth) {
            return fail("nesting too deep");
        }
        out.kind = Value::Kind::array;
        ++pos_; // [
        skip_ws();
        if (pos_ < text_.size() && text_[pos_] == ']') {
            ++pos_;
            return true;
        }
        while (true) {
            Value value;
            if (!parse_value(value)) {
                return false;
            }
            out.items.push_back(std::move(value));
            skip_ws();
            if (pos_ < text_.size() && text_[pos_] == ',') {
                ++pos_;
                continue;
            }
            if (pos_ < text_.size() && text_[pos_] == ']') {
                ++pos_;
                return true;
            }
            return fail("expected ',' or ']'");
        }
    }

    bool parse_string(std::string& out) {
        ++pos_; // opening quote
        while (pos_ < text_.size()) {
            const char c = text_[pos_];
            if (c == '"') {
                ++pos_;
                return true;
            }
            if (c == '\\') {
                if (pos_ + 1 >= text_.size()) {
                    return fail("bad escape");
                }
                const char e = text_[pos_ + 1];
                switch (e) {
                case '"': out += '"'; break;
                case '\\': out += '\\'; break;
                case '/': out += '/'; break;
                case 'b': out += '\b'; break;
                case 'f': out += '\f'; break;
                case 'n': out += '\n'; break;
                case 'r': out += '\r'; break;
                case 't': out += '\t'; break;
                case 'u': {
                    if (pos_ + 5 >= text_.size()) {
                        return fail("bad \\u escape");
                    }
                    unsigned code = 0;
                    for (int i = 0; i < 4; ++i) {
                        const char h = text_[pos_ + 2 + i];
                        code <<= 4;
                        if (h >= '0' && h <= '9') {
                            code |= static_cast<unsigned>(h - '0');
                        } else if (h >= 'a' && h <= 'f') {
                            code |= static_cast<unsigned>(h - 'a' + 10);
                        } else if (h >= 'A' && h <= 'F') {
                            code |= static_cast<unsigned>(h - 'A' + 10);
                        } else {
                            return fail("bad \\u escape");
                        }
                    }
                    // The pick schema is ASCII-only; encode other code
                    // points as UTF-8 (values fit BMP assumptions here).
                    if (code < 0x80) {
                        out += static_cast<char>(code);
                    } else if (code < 0x800) {
                        out += static_cast<char>(0xC0 | (code >> 6));
                        out += static_cast<char>(0x80 | (code & 0x3F));
                    } else {
                        out += static_cast<char>(0xE0 | (code >> 12));
                        out += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
                        out += static_cast<char>(0x80 | (code & 0x3F));
                    }
                    pos_ += 4;
                    break;
                }
                default:
                    return fail("bad escape");
                }
                pos_ += 2;
                continue;
            }
            out += c;
            ++pos_;
        }
        return fail("unterminated string");
    }

    bool parse_bool(bool& out) {
        if (text_.compare(pos_, 4, "true") == 0) {
            out = true;
            pos_ += 4;
            return true;
        }
        if (text_.compare(pos_, 5, "false") == 0) {
            out = false;
            pos_ += 5;
            return true;
        }
        return fail("bad literal");
    }

    bool parse_number(Value& out) {
        const std::size_t start = pos_;
        if (pos_ < text_.size() && (text_[pos_] == '-' || text_[pos_] == '+')) {
            ++pos_;
        }
        while (pos_ < text_.size() && ((text_[pos_] >= '0' && text_[pos_] <= '9') ||
                                       text_[pos_] == '.' || text_[pos_] == 'e' ||
                                       text_[pos_] == 'E' || text_[pos_] == '-' ||
                                       text_[pos_] == '+')) {
            ++pos_;
        }
        if (pos_ == start) {
            return fail("expected value");
        }
        const std::string token(text_.substr(start, pos_ - start));
        char* end = nullptr;
        const double value = std::strtod(token.c_str(), &end);
        if (end == nullptr || *end != '\0') {
            return fail("bad number");
        }
        out.kind = Value::Kind::number;
        out.number = value;
        return true;
    }

    std::string_view text_;
    std::size_t pos_{0};
    std::size_t depth_{0};
    std::string error_;
};

const MiniJson::Value* member(const MiniJson::Value& object, const char* key) {
    for (const auto& [name, value] : object.members) {
        if (name == key) {
            return &value;
        }
    }
    return nullptr;
}

} // namespace

std::string to_json(const HorizonPickSet& set) {
    std::string out = "{\n";
    out += "  \"schema\": \"pwb.seismic_viewer.horizon_picks/";
    out += std::to_string(HorizonPickSet::kSchemaVersion);
    out += "\",\n";
    out += "  \"schema_version\": " + std::to_string(set.schema_version) + ",\n";
    out += "  \"volume\": {\n";
    out += "    \"volume_id\": " + json_string(set.volume_id) + ",\n";
    out += "    \"volume_revision\": " + std::to_string(set.volume_revision) + ",\n";
    out += "    \"axis\": " + json_string(set.axis_name) + ",\n";
    out += "    \"slice_index\": " + std::to_string(set.slice_index) + ",\n";
    out += "    \"time_unit\": " + json_string(set.time_unit) + "\n";
    out += "  },\n";
    out += "  \"picks\": [";
    for (std::size_t i = 0; i < set.picks.size(); ++i) {
        if (i != 0) {
            out += ",";
        }
        const HorizonPick& pick = set.picks[i];
        out += "\n    {\"inline\": " + json_number(pick.inline_no) +
               ", \"crossline\": " + json_number(pick.crossline_no) +
               ", \"time\": " + json_number(pick.time_value) + "}";
    }
    if (!set.picks.empty()) {
        out += "\n  ";
    }
    out += "]\n}\n";
    return out;
}

PickParseResult from_json(std::string_view text) {
    PickParseResult result;
    MiniJson json(text);
    MiniJson::Value root;
    if (!json.parse(root) || root.kind != MiniJson::Value::Kind::object) {
        result.error = json.error().empty() ? "root must be an object" : json.error();
        return result;
    }
    const MiniJson::Value* schema = member(root, "schema");
    if (schema == nullptr || schema->kind != MiniJson::Value::Kind::string ||
        schema->str != "pwb.seismic_viewer.horizon_picks/1") {
        result.error = "missing or unsupported schema (expected "
                       "pwb.seismic_viewer.horizon_picks/1)";
        return result;
    }
    HorizonPickSet set;
    if (const MiniJson::Value* v = member(root, "schema_version");
        v != nullptr && v->kind == MiniJson::Value::Kind::number) {
        if (v->number != static_cast<double>(HorizonPickSet::kSchemaVersion)) {
            result.error = "unsupported schema_version";
            return result;
        }
        set.schema_version = static_cast<std::uint32_t>(v->number);
    }
    const MiniJson::Value* volume = member(root, "volume");
    if (volume == nullptr || volume->kind != MiniJson::Value::Kind::object) {
        result.error = "missing volume binding block";
        return result;
    }
    const auto read_string = [&](const char* key, std::string& target) -> bool {
        const MiniJson::Value* v = member(*volume, key);
        if (v != nullptr && v->kind == MiniJson::Value::Kind::string) {
            target = v->str;
            return true;
        }
        return false;
    };
    const auto read_u64 = [&](const char* key, std::uint64_t& target) -> bool {
        const MiniJson::Value* v = member(*volume, key);
        if (v != nullptr && v->kind == MiniJson::Value::Kind::number &&
            std::isfinite(v->number) && v->number >= 0.0 &&
            v->number <= static_cast<double>(std::numeric_limits<std::uint64_t>::max())) {
            target = static_cast<std::uint64_t>(v->number);
            return true;
        }
        return false;
    };
    const auto read_i64 = [&](const char* key, std::int64_t& target) -> bool {
        const MiniJson::Value* v = member(*volume, key);
        if (v != nullptr && v->kind == MiniJson::Value::Kind::number &&
            std::isfinite(v->number) && v->number >= -9.2233720368547758e18 &&
            v->number <= 9.2233720368547758e18) {
            target = static_cast<std::int64_t>(v->number);
            return true;
        }
        return false;
    };
    if (!read_string("volume_id", set.volume_id) ||
        !read_u64("volume_revision", set.volume_revision) ||
        !read_string("axis", set.axis_name) || !read_i64("slice_index", set.slice_index) ||
        !read_string("time_unit", set.time_unit)) {
        result.error = "incomplete volume binding block";
        return result;
    }
    if (set.axis_name != "inline" && set.axis_name != "crossline" &&
        set.axis_name != "sample") {
        result.error = "axis must be inline, crossline or sample";
        return result;
    }
    const MiniJson::Value* picks = member(root, "picks");
    if (picks == nullptr || picks->kind != MiniJson::Value::Kind::array) {
        result.error = "missing picks array";
        return result;
    }
    for (const MiniJson::Value& item : picks->items) {
        if (item.kind != MiniJson::Value::Kind::object) {
            result.error = "pick entries must be objects";
            return result;
        }
        HorizonPick pick;
        const auto read_pick_number = [&](const char* key, double& target) -> bool {
            const MiniJson::Value* v = member(item, key);
            if (v != nullptr && v->kind == MiniJson::Value::Kind::number &&
                std::isfinite(v->number)) {
                target = v->number;
                return true;
            }
            return false;
        };
        if (!read_pick_number("inline", pick.inline_no) ||
            !read_pick_number("crossline", pick.crossline_no) ||
            !read_pick_number("time", pick.time_value)) {
            result.error = "pick entry missing inline/crossline/time";
            return result;
        }
        set.picks.push_back(pick);
    }
    result.ok = true;
    result.set = std::move(set);
    return result;
}

std::string to_csv(const HorizonPickSet& set) {
    std::string out = "inline,crossline,time_ms\n";
    char buf[96];
    for (const HorizonPick& pick : set.picks) {
        std::snprintf(buf, sizeof(buf), "%.1f,%.1f,%.1f\n", pick.inline_no,
                      pick.crossline_no, pick.time_value);
        out += buf;
    }
    return out;
}

} // namespace pwb::seismic_viewer::horizon
