#include <pwb/geomodel/domain_contract.hpp>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <set>

namespace pwb::geomodel {

namespace {

// ---------------------------------------------------------------------------
// UTF-8 / codepoint helpers (well-formed input only — the oracle feeds
// valid UTF-8, matching Python str semantics)
// ---------------------------------------------------------------------------

std::u32string to_cps(std::string_view s) {
    std::u32string out;
    for (std::size_t i = 0; i < s.size();) {
        const auto c = static_cast<unsigned char>(s[i]);
        if (c < 0x80) {
            out.push_back(c);
            ++i;
        } else {
            int len = c >= 0xF0 ? 4 : c >= 0xE0 ? 3 : 2;
            char32_t cp = c & (len == 2 ? 0x1F : len == 3 ? 0x0F : 0x07);
            for (int k = 1; k < len && i + k < s.size(); ++k)
                cp = (cp << 6) | (static_cast<unsigned char>(s[i + k]) & 0x3F);
            out.push_back(cp);
            i += static_cast<std::size_t>(len);
        }
    }
    return out;
}

std::string from_cps(std::u32string_view cps) {
    std::string out;
    for (char32_t cp : cps) {
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else if (cp < 0x10000) {
            out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        }
    }
    return out;
}

bool is_py_space(char32_t cp) {
    if (cp == 0x20 || cp == 0x09 || cp == 0x0A || cp == 0x0B || cp == 0x0C ||
        cp == 0x0D)
        return true;
    if (cp >= 0x1C && cp <= 0x1F) return true;  // Python-only whitespace
    if (cp == 0x85 || cp == 0xA0) return true;
    switch (cp) {
        case 0x1680: case 0x2000: case 0x2001: case 0x2002: case 0x2003:
        case 0x2004: case 0x2005: case 0x2006: case 0x2007: case 0x2008:
        case 0x2009: case 0x200A: case 0x2028: case 0x2029: case 0x202F:
        case 0x205F: case 0x3000:
            return true;
        default:
            return false;
    }
}

struct LowerEnt {
    char32_t cp;
    const char* to;  // utf-8
};
const LowerEnt kLowerMap[] = {
#include "lower_map.inc"
};

std::string lower_cp(char32_t cp) {
    // binary search in the generated table
    std::size_t lo = 0, hi = std::size(kLowerMap);
    while (lo < hi) {
        const std::size_t mid = (lo + hi) / 2;
        if (kLowerMap[mid].cp < cp)
            lo = mid + 1;
        else
            hi = mid;
    }
    if (lo < std::size(kLowerMap) && kLowerMap[lo].cp == cp)
        return kLowerMap[lo].to;
    return from_cps(std::u32string_view(&cp, 1));
}

std::string fmt_double(double v) {
    // str(float): repr-shortest is what Python emits; nlohmann dump does the
    // same (shortest round-trip), so reuse it for scalar formatting.
    return Json(v).dump();
}

}  // namespace

std::string py_str(const Json& v) {
    if (v.is_null()) return "None";
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_integer() || v.is_number_unsigned())
        return std::to_string(v.get<long long>());
    if (v.is_number_float()) return fmt_double(v.get<double>());
    if (v.is_string()) return v.get_ref<const std::string&>();
    return v.dump();
}

std::string py_repr(const Json& v) {
    if (v.is_string()) {
        const std::string& s = v.get_ref<const std::string&>();
        std::string out = "'";
        for (const char ch : s) {
            switch (ch) {
                case '\'': out += "\\'"; break;
                case '\\': out += "\\\\"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (static_cast<unsigned char>(ch) < 0x20 ||
                        static_cast<unsigned char>(ch) == 0x7F) {
                        char buf[8];
                        std::snprintf(buf, sizeof buf, "\\x%02x",
                                      static_cast<unsigned char>(ch));
                        out += buf;
                    } else {
                        out += ch;
                    }
            }
        }
        return out + "'";
    }
    return py_str(v);
}

std::string py_strip(std::string_view s) {
    const std::u32string cps = to_cps(s);
    std::size_t a = 0, b = cps.size();
    while (a < b && is_py_space(cps[a])) ++a;
    while (b > a && is_py_space(cps[b - 1])) --b;
    return from_cps(cps.substr(a, b - a));
}

std::string py_lower(std::string_view s) {
    std::string out;
    for (char32_t cp : to_cps(s)) out += lower_cp(cp);
    return out;
}

std::string slugify(const Json& text, const std::string& fallback) {
    const std::string lowered = py_lower(py_strip(py_str(text)));
    std::string slug;
    bool in_dash = false;
    for (char32_t cp : to_cps(lowered)) {
        const bool word =
            (cp >= 'a' && cp <= 'z') || (cp >= '0' && cp <= '9') ||
            cp == '_' || cp == '.' || cp == '-';
        if (word) {
            slug += from_cps(std::u32string_view(&cp, 1));
            in_dash = false;
        } else if (!in_dash) {
            slug += '-';
            in_dash = true;
        }
    }
    // .strip("-.") — any mix of '-' and '.' from both ends
    std::size_t a = 0, b = slug.size();
    while (a < b && (slug[a] == '-' || slug[a] == '.')) ++a;
    while (b > a && (slug[b - 1] == '-' || slug[b - 1] == '.')) --b;
    slug = slug.substr(a, b - a);
    return slug.empty() ? fallback : slug;
}

bool py_truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_string()) return !v.get_ref<const std::string&>().empty();
    if (v.is_array() || v.is_object()) return !v.empty();
    return true;
}

long long py_int(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1 : 0;
    if (v.is_number_integer() || v.is_number_unsigned())
        return v.get<long long>();
    if (v.is_number_float()) return static_cast<long long>(v.get<double>());
    if (v.is_string()) {
        const std::string s = py_strip(v.get_ref<const std::string&>());
        const char* p = s.c_str();
        bool neg = false;
        if (*p == '+' || *p == '-') neg = (*p++ == '-');
        if (!*p) {
            // fall through to error
        } else {
            long long n = 0;
            bool ok = true;
            for (const char* q = p; *q; ++q) {
                if (*q < '0' || *q > '9') { ok = false; break; }
                n = n * 10 + (*q - '0');
            }
            if (ok) return neg ? -n : n;
        }
        throw ValueError("invalid literal for int() with base 10: " +
                         py_repr(v));
    }
    throw TypeError(
        "int() argument must be a string, a bytes-like object or a "
        "real number");
}

double py_float(const Json& v) {
    if (v.is_boolean()) return v.get<bool>() ? 1.0 : 0.0;
    if (v.is_number()) return v.get<double>();
    if (v.is_string()) {
        const std::string s = py_strip(v.get_ref<const std::string&>());
        if (s == "inf" || s == "Infinity" || s == "+inf" ||
            s == "+Infinity" || s == "infinity" || s == "INF" ||
            s == "Infinity" || s == "INFINITY")
            return std::numeric_limits<double>::infinity();
        if (s == "-inf" || s == "-Infinity" || s == "-infinity" ||
            s == "-INF" || s == "-INFINITY")
            return -std::numeric_limits<double>::infinity();
        if (s == "nan" || s == "NaN" || s == "NAN")
            return std::numeric_limits<double>::quiet_NaN();
        char* end = nullptr;
        const double d = std::strtod(s.c_str(), &end);
        if (end != s.c_str() && *end == '\0' && !s.empty()) return d;
        throw ValueError("could not convert string to float: " +
                         py_repr(v));
    }
    throw TypeError(
        "float() argument must be a string or a real number");
}

std::vector<std::string> clean_ids(const Json& ids) {
    std::vector<std::string> out;
    if (!py_truthy(ids)) return out;  // falsy -> ()
    if (ids.is_array()) {
        for (const auto& el : ids) out.push_back(py_str(el));
        return out;
    }
    if (ids.is_object()) {
        for (auto it = ids.begin(); it != ids.end(); ++it)
            out.push_back(it.key());
        return out;
    }
    if (ids.is_string()) {
        for (char32_t cp : to_cps(ids.get_ref<const std::string&>()))
            out.push_back(from_cps(std::u32string_view(&cp, 1)));
        return out;
    }
    const char* tn = "object";
    if (ids.is_boolean()) tn = "bool";
    else if (ids.is_number_float()) tn = "float";
    else if (ids.is_number()) tn = "int";
    throw TypeError("'" + std::string(tn) + "' object is not iterable");
}

// ---------------------------------------------------------------------------
// spec helpers: JSON -> typed arrays with numpy shape semantics
// ---------------------------------------------------------------------------

namespace {

// Python tuple-of-shape formatting: (0,) / (2, 4) / (3,)
std::string shape_str(std::initializer_list<long long> dims) {
    std::string s = "(";
    bool first = true;
    for (long long d : dims) {
        if (!first) s += ", ";
        s += std::to_string(d);
        first = false;
    }
    if (dims.size() == 1) s += ",";
    return s + ")";
}

// 2-D array from JSON: list-of-lists -> rows x cols; flat/non-list element
// -> 1-D (rows,) which callers reject with the matching DomainError text.
struct Arr2 {
    long long rows = 0, cols = -1;  // cols==-1 => 1-D
    std::vector<std::vector<double>> data;
};

Arr2 arr2d(const Json& v, const std::string& /*name*/) {
    Arr2 out;
    if (!v.is_array()) {
        out.rows = 1;
        out.cols = -1;
        return out;  // scalar -> shape (1,)? np.asarray(scalar) is 0-d; treat
                     // as (1,) for the error message (oracle has no such case)
    }
    out.rows = static_cast<long long>(v.size());
    if (out.rows == 0) {
        out.cols = -1;  // np.asarray([]) -> shape (0,)
        return out;
    }
    long long cols = -1;
    for (const auto& row : v) {
        if (!row.is_array()) {
            out.cols = -1;
            return out;  // mixed -> object array; reject as 1-D
        }
        const long long n = static_cast<long long>(row.size());
        if (cols < 0) cols = n;
        if (n != cols) {
            throw ValueError(
                "setting an array element with a sequence. The requested "
                "array has an inhomogeneous shape after 1 dimensions. The "
                "detected shape was (" + std::to_string(out.rows) +
                ",) + inhomogeneous part.");
        }
    }
    out.cols = cols;
    out.data.resize(static_cast<std::size_t>(out.rows));
    for (std::size_t i = 0; i < v.size(); ++i) {
        auto& dst = out.data[i];
        dst.reserve(static_cast<std::size_t>(cols));
        for (const auto& el : v[i]) {
            if (el.is_null()) {
                dst.push_back(std::numeric_limits<double>::quiet_NaN());
            } else if (el.is_number()) {
                dst.push_back(el.get<double>());
            } else if (el.is_string()) {
                const std::string& sv = el.get_ref<const std::string&>();
                if (sv == "inf")
                    dst.push_back(std::numeric_limits<double>::infinity());
                else if (sv == "-inf")
                    dst.push_back(-std::numeric_limits<double>::infinity());
                else if (sv == "nan")
                    dst.push_back(
                        std::numeric_limits<double>::quiet_NaN());
                else
                    throw ValueError("could not convert string to float: '" +
                                     sv + "'");
            } else {
                throw TypeError("float() argument must be a string or a "
                                "real number");
            }
        }
    }
    return out;
}

// spec shorthand: {"zeros2d": [r, c]} -> zeros((r, c)) (an explicit 2-D
// empty — the only way to express np.zeros((0,4)) in the fixture protocol)
Arr2 arr2d_spec(const Json& v, const std::string& name) {
    if (v.is_object() && v.contains("zeros2d")) {
        Arr2 out;
        const auto& z = v["zeros2d"];
        out.rows = z[0].get<long long>();
        out.cols = z[1].get<long long>();
        out.data.assign(static_cast<std::size_t>(out.rows),
                        std::vector<double>(static_cast<std::size_t>(
                                                out.cols),
                                            0.0));
        return out;
    }
    return arr2d(v, name);
}

std::vector<Vec3> to_vec3(const Arr2& a) {
    std::vector<Vec3> out;
    out.reserve(a.data.size());
    for (const auto& r : a.data)
        out.push_back(Vec3{r[0], r[1], r[2]});
    return out;
}

std::vector<std::array<double, 4>> to_vec4(const Arr2& a) {
    std::vector<std::array<double, 4>> out;
    out.reserve(a.data.size());
    for (const auto& r : a.data)
        out.push_back({r[0], r[1], r[2], r[3]});
    return out;
}

std::vector<std::array<std::int64_t, 3>> to_faces(const Arr2& a) {
    std::vector<std::array<std::int64_t, 3>> out;
    out.reserve(a.data.size());
    for (const auto& r : a.data)
        out.push_back({static_cast<std::int64_t>(r[0]),
                       static_cast<std::int64_t>(r[1]),
                       static_cast<std::int64_t>(r[2])});
    return out;
}

std::vector<std::array<double, 2>> to_vec2(const Arr2& a) {
    std::vector<std::array<double, 2>> out;
    out.reserve(a.data.size());
    for (const auto& r : a.data) out.push_back({r[0], r[1]});
    return out;
}

bool any_nonfinite(const std::vector<Vec3>& v) {
    for (const auto& p : v)
        for (double c : {p[0], p[1], p[2]})
            if (!std::isfinite(c)) return true;
    return false;
}

bool any_nonfinite(const std::vector<std::array<double, 4>>& v) {
    for (const auto& r : v)
        for (double c : r)
            if (!std::isfinite(c)) return true;
    return false;
}

bool any_nonfinite2d(const std::vector<std::vector<double>>& g) {
    for (const auto& r : g)
        for (double c : r)
            if (!std::isfinite(c)) return true;
    return false;
}

bool any_inf2d(const std::vector<std::vector<double>>& g) {
    for (const auto& r : g)
        for (double c : r)
            if (std::isinf(c)) return true;
    return false;
}

std::string req_str(const Json& m, const char* key) {
    if (!m.contains(key)) throw KeyError(py_repr(Json(key)));
    return py_str(m[key]);
}

}  // namespace

// ---------------------------------------------------------------------------
// Provenance
// ---------------------------------------------------------------------------

Json Provenance::to_meta() const {
    return Json{{"source_kind", source_kind},
                {"source_version_ids", source_version_ids},
                {"created_from", created_from},
                {"demo", demo}};
}

Provenance Provenance::from_meta(const Json& meta) {
    Provenance p;
    const Json m = meta.is_null() ? Json::object() : meta;
    if (m.contains("source_kind")) p.source_kind = py_str(m["source_kind"]);
    if (m.contains("source_version_ids"))
        p.source_version_ids = clean_ids(m["source_version_ids"]);
    if (m.contains("created_from")) p.created_from = py_str(m["created_from"]);
    if (m.contains("demo")) p.demo = py_truthy(m["demo"]);
    return p;
}

// ---------------------------------------------------------------------------
// DomainObject
// ---------------------------------------------------------------------------

std::string DomainObject::kind() const {
    const auto pos = object_id.find(':');
    return pos == std::string::npos ? object_id : object_id.substr(0, pos);
}

namespace {

void check_header(const DomainObject& o) {
    if (o.object_id.empty() || o.object_id.find(':') == std::string::npos)
        throw DomainError("object_id must be '<kind>:<slug>', got " +
                          py_repr(Json(o.object_id)));
    if (o.name.empty())
        throw DomainError(o.object_id + ": name must be non-empty");
}

void check_prefix(const DomainObject& o, const char* want) {
    if (o.object_id.rfind(std::string(want) + ":", 0) != 0)
        throw DomainError(std::string(want) +
                          " object_id must start with '" + want + ":'");
}

void require_finite(const std::string& name,
                    const std::vector<Vec3>& v) {
    if (!v.empty() && any_nonfinite(v))
        throw DomainError(name + ": array contains non-finite values");
}

void require_finite4(const std::string& name,
                     const std::vector<std::array<double, 4>>& v) {
    if (!v.empty() && any_nonfinite(v))
        throw DomainError(name + ": array contains non-finite values");
}

void check_mesh(const DomainObject& o) {
    require_finite(o.object_id + ".verts", o.verts);
    if (!o.faces.empty()) {
        std::int64_t lo = o.faces[0][0], hi = o.faces[0][0];
        for (const auto& f : o.faces)
            for (auto i : f) {
                lo = std::min(lo, i);
                hi = std::max(hi, i);
            }
        if (lo < 0 || hi >= std::max<std::int64_t>(
                                static_cast<std::int64_t>(o.verts.size()), 1))
            throw DomainError(o.object_id + ": face indices out of range");
    }
}

}  // namespace

void DomainObject::validate() const {
    check_header(*this);
    const std::string k = kind();
    if (k == "well") {
        check_prefix(*this, "well");
        require_finite4(object_id + ".stations", stations);
        if (representation != "measured" &&
            representation != "simplified_vertical")
            throw DomainError(object_id + ": unknown representation " +
                              py_repr(Json(representation)));
        if (representation == "measured" && stations.size() >= 2)
            for (std::size_t i = 1; i < stations.size(); ++i)
                if (stations[i][0] <= stations[i - 1][0])
                    throw DomainError(
                        object_id +
                        ": measured stations need strictly increasing MD "
                        "(QC rejects duplicates/non-monotonic input)");
    } else if (k == "horizon") {
        check_prefix(*this, "horizon");
        // structured grids may carry NaN holes; other non-finites are bugs
        if (any_inf2d(z_grid))
            throw DomainError(
                object_id +
                ".z_grid: contains +/-inf (NaN is the only allowed hole)");
        const std::size_t r = z_grid.size(),
                          c = z_grid.empty() ? 0 : z_grid[0].size();
        if (confidence && (confidence->size() != r ||
                           (!confidence->empty() &&
                            (*confidence)[0].size() != c)))
            throw DomainError(object_id + ": confidence shape (" +
                              std::to_string(confidence->size()) + ", " +
                              std::to_string(confidence->empty() ? 0
                                              : (*confidence)[0].size()) +
                              ") != grid (" + std::to_string(r) + ", " +
                              std::to_string(c) + ")");
        for (const auto& [an, arr] : attributes) {
            if (arr.size() != r ||
                (!arr.empty() && arr[0].size() != c))
                throw DomainError(
                    object_id + ": attribute " + py_repr(Json(an)) +
                    " shape (" + std::to_string(arr.size()) + ", " +
                    std::to_string(arr.empty() ? 0 : arr[0].size()) +
                    ") != grid (" + std::to_string(r) + ", " +
                    std::to_string(c) + ")");
        }
    } else if (k == "fault") {
        check_prefix(*this, "fault");
        check_mesh(*this);
        if (representation != "triangulated_3d" &&
            representation != "curtain_2p5d")
            throw DomainError(object_id + ": unknown representation " +
                              py_repr(Json(representation)));
        if (representation == "curtain_2p5d" && !z_extent)
            throw DomainError(object_id +
                              ": curtain representation requires z_extent");
    } else if (k == "volume") {
        check_prefix(*this, "volume");
        check_mesh(*this);
        if (facies && facies->size() != verts.size())
            throw DomainError(object_id +
                              ": facies length must match verts");
        for (const auto& [pn, arr] : properties)
            if (arr.size() != verts.size())
                throw DomainError(object_id + ": property " +
                                  py_repr(Json(pn)) +
                                  " length must match verts");
    } else if (k == "tunnel") {
        check_prefix(*this, "tunnel");
        require_finite(object_id + ".path", path);
        if (!(radius > 0.0))
            throw DomainError(object_id + ": radius must be positive");
    } else if (k == "measure") {
        check_prefix(*this, "measure");
        static const std::set<std::string> allowed = {
            "point", "distance", "polyline", "vertical_difference",
            "thickness", "plane_orientation"};
        if (!allowed.count(measurement_kind))
            throw DomainError(object_id + ": unknown measurement kind " +
                              py_repr(Json(measurement_kind)));
        require_finite(object_id + ".points", points);
    }
}

namespace {

// Shape validation shared by spec-construction: require (rows, want_cols)
// 2-D; emits "<oid>: <field> must be (N, C) <hint>, got <shape>" — or the
// simpler "<field> must be (N, C)" when no hint applies.
void require_shape(const std::string& oid, const std::string& field,
                   const Arr2& a, long long want_cols,
                   const std::string& hint = "") {
    if (a.cols < 0 || (a.rows && a.cols != want_cols)) {
        const std::string shape = a.cols < 0
                                      ? shape_str({a.rows})
                                      : shape_str({a.rows, a.cols});
        throw DomainError(oid + ": " + field + " must be (N, " +
                          std::to_string(want_cols) + ")" + hint +
                          ", got " + shape);
    }
}

}  // namespace

DomainObject object_from_spec(const Json& spec) {
    const std::string kind = spec.value("kind", std::string{});
    DomainObject o;
    o.object_id = py_str(spec.at("object_id"));
    o.name = py_str(spec.at("name"));
    o.crs = py_str(spec.value("crs", Json("unknown")));
    o.vertical_domain = py_str(spec.value("vertical_domain", Json("depth")));
    o.unit = py_str(spec.value("unit", Json("m")));
    o.provenance = Provenance::from_meta(spec.value("provenance",
                                                  Json::object()));
    o.version = spec.value("version", Json(1)).get<long long>();

    // header validation happens BEFORE subclass checks (Python order:
    // DomainObject.__post_init__ first), then the DECLARED class prefix
    // gate — kind=well with object_id "fault:x" fails 'well:' like Python's
    // WellTrajectory.__post_init__, not the prefix-derived dispatch.
    check_header(o);
    if (kind == "well" || kind == "horizon" || kind == "fault" ||
        kind == "volume" || kind == "tunnel" || kind == "measure")
        check_prefix(o, kind.c_str());

    if (kind == "well") {
        const Arr2 a = arr2d_spec(spec.value("stations", Json::array()),
                                  "stations");
        if (a.cols < 0 || (a.rows && a.cols != 4)) {
            const std::string shape = a.cols < 0
                                          ? shape_str({a.rows})
                                          : shape_str({a.rows, a.cols});
            throw DomainError(
                o.object_id +
                ": stations must be (N, 4) [md,x,y,z], got " + shape);
        }
        o.stations = to_vec4(a);
        o.representation = py_str(
            spec.value("representation", Json("measured")));
        if (spec.contains("z_unit") && !spec["z_unit"].is_null())
            o.z_unit = py_str(spec["z_unit"]);
        else if (spec.contains("z_unit"))
            o.z_unit = std::nullopt;
        else
            o.z_unit = std::nullopt;
        o.well_asset_id = py_str(spec.value("well_asset_id", Json("")));
        for (const auto& t : spec.value("formation_tops", Json::array()))
            o.formation_tops.emplace_back(py_str(t[0]), t[1].get<double>());
    } else if (kind == "horizon") {
        const Arr2 a = arr2d_spec(spec.value("z_grid", Json::array()),
                                  "z_grid");
        if (a.cols < 0)
            throw DomainError(o.object_id + ": z_grid must be 2-D");
        o.z_grid = std::move(a.data);
        const Json& org = spec.value("origin", Json::array({0.0, 0.0}));
        o.origin = {org[0].get<double>(), org[1].get<double>()};
        const Json& sp = spec.value("spacing", Json::array({1.0, 1.0}));
        o.spacing = {sp[0].get<double>(), sp[1].get<double>()};
        o.grid_crs = py_str(spec.value("grid_crs", Json("")));
        o.horizon_asset_id = py_str(spec.value("horizon_asset_id", Json("")));
        if (spec.contains("confidence") && !spec["confidence"].is_null()) {
            const Arr2 c = arr2d(spec["confidence"], "confidence");
            std::vector<std::vector<double>> cd = std::move(c.data);
            o.confidence = std::move(cd);
        }
        for (const auto& pair : spec.value("attributes", Json::array())) {
            const Arr2 ad = arr2d(pair[1], "attribute");
            o.attributes.emplace_back(py_str(pair[0]), std::move(ad.data));
        }
    } else if (kind == "fault" || kind == "volume") {
        const Arr2 va = arr2d_spec(spec.value("verts", Json::array()), "verts");
        if (va.cols < 0 || (va.rows && va.cols != 3))
            throw DomainError(o.object_id + ": verts must be (N, 3)");
        o.verts = to_vec3(va);
        const Arr2 fa = arr2d_spec(spec.value("faces", Json::array()), "faces");
        if (fa.cols >= 0 && fa.rows && fa.cols != 3)
            throw DomainError(o.object_id + ": faces must be (M, 3)");
        // faces=[] -> (0,) 1-D: Python reshape(-1,3) does NOT run at
        // construction; np.asarray([]) stays (0,) — but f.size==0 skips the
        // shape check, so accept it as empty.
        if (fa.cols < 0 && fa.rows != 0)
            throw DomainError(o.object_id + ": faces must be (M, 3)");
        o.faces = to_faces(fa);
        if (kind == "fault") {
            o.representation = py_str(
                spec.value("representation", Json("triangulated_3d")));
            if (spec.contains("trace_xy") && !spec["trace_xy"].is_null()) {
                const Arr2 t = arr2d(spec["trace_xy"], "trace_xy");
                o.trace_xy = to_vec2(t);
            }
            if (spec.contains("z_extent") && !spec["z_extent"].is_null()) {
                const Json& z = spec["z_extent"];
                o.z_extent = std::array<double, 2>{z[0].get<double>(),
                                                   z[1].get<double>()};
            }
            if (spec.contains("throw_m") && !spec["throw_m"].is_null())
                o.throw_m = spec["throw_m"].get<double>();
            if (spec.contains("strike_dip") &&
                !spec["strike_dip"].is_null()) {
                const Json& s = spec["strike_dip"];
                o.strike_dip = std::array<double, 2>{s[0].get<double>(),
                                                     s[1].get<double>()};
            }
            o.fault_asset_id = py_str(spec.value("fault_asset_id", Json("")));
            for (const auto& h :
                 spec.value("intersects_horizons", Json::array()))
                o.intersects_horizons.push_back(py_str(h));
        } else {
            o.top_id = py_str(spec.value("top_id", Json("")));
            o.base_id = py_str(spec.value("base_id", Json("")));
            if (spec.contains("boundary") && !spec["boundary"].is_null()) {
                const Arr2 b = arr2d(spec["boundary"], "boundary");
                o.boundary = to_vec2(b);
            }
            o.formation = py_str(spec.value("formation", Json("")));
            if (spec.contains("facies") && !spec["facies"].is_null()) {
                std::vector<std::int64_t> fv;
                for (const auto& el : spec["facies"])
                    fv.push_back(el.is_null()
                                     ? 0
                                     : el.get<std::int64_t>());
                o.facies = std::move(fv);
            }
            for (const auto& pair : spec.value("properties", Json::array())) {
                std::vector<double> pv;
                for (const auto& el : pair[1])
                    pv.push_back(el.is_null()
                                     ? std::numeric_limits<double>::quiet_NaN()
                                     : el.get<double>());
                o.properties.emplace_back(py_str(pair[0]), std::move(pv));
            }
            o.has_cell_mesh = spec.contains("cell_mesh") &&
                              !spec["cell_mesh"].is_null();
            o.quality = spec.value("quality", Json::object());
        }
    } else if (kind == "tunnel") {
        const Arr2 a = arr2d_spec(spec.value("path", Json::array()), "path");
        if (a.cols < 0 || (a.rows && a.cols != 3))
            throw DomainError(o.object_id + ": path must be (N, 3)");
        o.path = to_vec3(a);
        o.radius = spec.value("radius", Json(3.0)).get<double>();
    } else if (kind == "measure") {
        o.measurement_kind = py_str(
            spec.value("measurement_kind", Json("distance")));
        const Arr2 a = arr2d_spec(spec.value("points", Json::array()),
                                  "points");
        if (a.cols < 0 || (a.rows && a.cols != 3))
            throw DomainError(o.object_id + ": points must be (N, 3)");
        o.points = to_vec3(a);
        if (spec.contains("result") && !spec["result"].is_null())
            o.result = spec["result"].get<double>();
        o.extra = spec.value("extra", Json::object());
    } else {
        throw DomainError("unknown object kind for " +
                          py_repr(Json(o.object_id)));
    }
    o.validate();
    return o;
}

Json DomainObject::meta() const {
    Json m;
    m["object_id"] = object_id;
    m["name"] = name;
    m["crs"] = crs;
    const std::string k = kind();
    if (k == "horizon") m["grid_crs"] = grid_crs;
    m["vertical_domain"] = vertical_domain;
    m["unit"] = unit;
    if (k == "well") {
        m["z_unit"] = (z_unit && !z_unit->empty()) ? *z_unit : unit;
        m["representation"] = representation;
        m["well_asset_id"] = well_asset_id;
        Json tops = Json::array();
        for (const auto& [tn, tv] : formation_tops)
            tops.push_back(Json::array({tn, tv}));
        m["formation_tops"] = std::move(tops);
    } else if (k == "horizon") {
        m["origin"] = Json::array({origin[0], origin[1]});
        m["spacing"] = Json::array({spacing[0], spacing[1]});
        const std::size_t r = z_grid.size(),
                          c = z_grid.empty() ? 0 : z_grid[0].size();
        m["shape"] = Json::array({static_cast<long long>(r),
                                  static_cast<long long>(c)});
        m["horizon_asset_id"] = horizon_asset_id;
        Json names = Json::array();
        for (const auto& [an, _] : attributes) names.push_back(an);
        m["attribute_names"] = std::move(names);
    } else if (k == "fault") {
        m["representation"] = representation;
        m["z_extent"] = z_extent
                            ? Json::array({(*z_extent)[0], (*z_extent)[1]})
                            : Json(nullptr);
        m["throw_m"] = throw_m ? Json(*throw_m) : Json(nullptr);
        m["strike_dip"] =
            strike_dip
                ? Json::array({(*strike_dip)[0], (*strike_dip)[1]})
                : Json(nullptr);
        m["fault_asset_id"] = fault_asset_id;
        m["intersects_horizons"] = intersects_horizons;
    } else if (k == "volume") {
        m["top_id"] = top_id;
        m["base_id"] = base_id;
        m["formation"] = formation;
        Json names = Json::array();
        for (const auto& [pn, _] : properties) names.push_back(pn);
        m["property_names"] = std::move(names);
        m["has_cell_mesh"] = has_cell_mesh;
    } else if (k == "tunnel") {
        m["radius"] = radius;
    } else if (k == "measure") {
        m["measurement_kind"] = measurement_kind;
        Json pts = Json::array();
        for (const auto& p : points)
            pts.push_back(Json::array({p[0], p[1], p[2]}));
        m["points"] = std::move(pts);
        m["result"] = result ? Json(*result) : Json(nullptr);
        m["extra"] = extra;
    }
    m["provenance"] = provenance.to_meta();
    m["version"] = version;
    if (k != "measure") m["stats"] = geometry_stats(*this);
    if (k == "horizon") {
        std::size_t finite = 0, total = 0;
        for (const auto& row : z_grid)
            for (double v : row) {
                ++total;
                if (std::isfinite(v)) ++finite;
            }
        m["stats_extra"] = {
            {"node_count", static_cast<long long>(total)},
            {"nan_fraction",
             total ? 1.0 - static_cast<double>(finite) / total : 0.0}};
    }
    if (k == "volume") m["quality"] = quality;
    return m;
}

DomainObject DomainObject::from_meta(const Json& meta) {
    DomainObject o;
    o.object_id = req_str(meta, "object_id");
    o.name = req_str(meta, "name");
    o.crs = meta.contains("crs") ? py_str(meta["crs"]) : "unknown";
    o.vertical_domain =
        meta.contains("vertical_domain") ? py_str(meta["vertical_domain"])
                                         : "depth";
    o.unit = meta.contains("unit") ? py_str(meta["unit"]) : "m";
    o.provenance = Provenance::from_meta(meta.value("provenance",
                                                  Json::object()));
    if (meta.contains("version"))
        o.version = py_int(meta["version"]);
    const std::string k = o.kind();
    if (k == "well") {
        if (meta.contains("z_unit") && !meta["z_unit"].is_null())
            o.z_unit = py_str(meta["z_unit"]);
        o.representation = meta.contains("representation")
                               ? py_str(meta["representation"])
                               : "measured";
        o.well_asset_id = meta.contains("well_asset_id")
                              ? py_str(meta["well_asset_id"])
                              : "";
        if (meta.contains("formation_tops"))
            for (const auto& t : meta["formation_tops"])
                o.formation_tops.emplace_back(py_str(t[0]),
                                              py_float(t[1]));
    } else if (k == "horizon") {
        o.grid_crs =
            meta.contains("grid_crs") ? py_str(meta["grid_crs"]) : "";
        if (meta.contains("origin"))
            o.origin = {meta["origin"][0].get<double>(),
                        meta["origin"][1].get<double>()};
        if (meta.contains("spacing"))
            o.spacing = {meta["spacing"][0].get<double>(),
                         meta["spacing"][1].get<double>()};
        o.horizon_asset_id = meta.contains("horizon_asset_id")
                                 ? py_str(meta["horizon_asset_id"])
                                 : "";
    } else if (k == "fault") {
        o.representation = meta.contains("representation")
                               ? py_str(meta["representation"])
                               : "triangulated_3d";
        if (meta.contains("z_extent") && !meta["z_extent"].is_null() &&
            meta["z_extent"].is_array() && !meta["z_extent"].empty())
            o.z_extent = {py_float(meta["z_extent"][0]),
                          py_float(meta["z_extent"][1])};
        if (meta.contains("throw_m") && !meta["throw_m"].is_null())
            o.throw_m = py_float(meta["throw_m"]);
        if (meta.contains("strike_dip") && !meta["strike_dip"].is_null() &&
            meta["strike_dip"].is_array() && !meta["strike_dip"].empty())
            o.strike_dip = {py_float(meta["strike_dip"][0]),
                            py_float(meta["strike_dip"][1])};
        o.fault_asset_id = meta.contains("fault_asset_id")
                               ? py_str(meta["fault_asset_id"])
                               : "";
        if (meta.contains("intersects_horizons"))
            o.intersects_horizons = clean_ids(meta["intersects_horizons"]);
    } else if (k == "volume") {
        o.top_id = meta.contains("top_id") ? py_str(meta["top_id"]) : "";
        o.base_id = meta.contains("base_id") ? py_str(meta["base_id"]) : "";
        o.formation =
            meta.contains("formation") ? py_str(meta["formation"]) : "";
        o.quality =
            meta.contains("quality") ? meta["quality"] : Json::object();
    } else if (k == "tunnel") {
        o.radius =
            meta.contains("radius") ? py_float(meta["radius"]) : 3.0;
    } else if (k == "measure") {
        o.measurement_kind = meta.contains("measurement_kind")
                                 ? py_str(meta["measurement_kind"])
                                 : "distance";
        {
            // np.asarray(meta.get("points", [])) -> __post_init__ (N, 3)
            const Arr2 a = arr2d(meta.value("points", Json::array()),
                                 "points");
            if (a.cols < 0 || (a.rows && a.cols != 3))
                throw DomainError(o.object_id +
                                  ": points must be (N, 3)");
            o.points = to_vec3(a);
        }
        if (meta.contains("result") && !meta["result"].is_null())
            o.result = py_float(meta["result"]);
        o.extra = meta.contains("extra") ? meta["extra"] : Json::object();
    }
    o.validate();
    return o;
}

namespace {

Json stats_of_verts(const std::vector<Vec3>& verts) {
    if (verts.empty()) return Json{{"vertex_count", 0}};
    Vec3 lo = verts[0], hi = verts[0];
    for (const auto& p : verts)
        for (int i = 0; i < 3; ++i) {
            lo[i] = std::min(lo[i], p[i]);
            hi[i] = std::max(hi[i], p[i]);
        }
    return Json{{"vertex_count", static_cast<long long>(verts.size())},
                {"bounds",
                 Json::array({lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]})}};
}

}  // namespace

namespace {

// mutate() scalar: null -> NaN; strings take the same float() coercion the
// spec arrays use.
double mut_value(const Json& v) {
    if (v.is_null()) return std::numeric_limits<double>::quiet_NaN();
    if (v.is_number()) return v.get<double>();
    if (v.is_string()) return py_float(v);
    return py_float(v);  // bool etc. -> float() coercion
}

[[noreturn]] void oob(long long i, int axis, long long size) {
    throw IndexError("index " + std::to_string(i) +
                     " is out of bounds for axis " + std::to_string(axis) +
                     " with size " + std::to_string(size));
}

// numpy flat[i] / a[i, j] assignment into a row-major matrix view.
template <typename Set>
void mut_assign(const Json& idx, double v, long long rows, long long cols,
                Set&& set) {
    if (idx.is_number_integer() || idx.is_number_unsigned()) {
        long long i = idx.get<long long>();
        const long long n = rows * cols;
        if (i < 0) i += n;  // numpy negative indexing
        if (i < 0 || i >= n) oob(i, 0, n);
        set(i / cols, i % cols, v);
        return;
    }
    if (!idx.is_array() || idx.size() < 2)
        throw TypeError("tuple index out of range");
    const auto& t = idx;
    long long i = t.at(0).get<long long>();
    long long j = t.at(1).get<long long>();
    if (i < 0) i += rows;
    if (j < 0) j += cols;
    if (i < 0 || i >= rows) oob(i, 0, rows);
    if (j < 0 || j >= cols) oob(j, 1, cols);
    set(i, j, v);
}

}  // namespace

void apply_mutations(DomainObject& obj, const Json& spec) {
    if (!spec.contains("_mutate") || !spec["_mutate"].is_array()) return;
    for (const auto& m : spec["_mutate"]) {
        const std::string target = m.at("field").get<std::string>();
        const Json& idx = m.contains("index") ? m["index"] : Json(nullptr);
        const double v = mut_value(m.value("value", Json(nullptr)));
        const long long iv = static_cast<long long>(v);
        auto rows_of = [](const auto& vv) {
            return static_cast<long long>(vv.size());
        };
        if (target == "stations") {
            mut_assign(idx, v, rows_of(obj.stations), 4,
                       [&](long long i, long long j, double x) {
                           obj.stations[i][j] = x;
                       });
        } else if (target == "verts" || target == "path" ||
                   target == "points") {
            std::vector<Vec3>& vv =
                target == "verts" ? obj.verts
                                  : (target == "path" ? obj.path
                                                      : obj.points);
            mut_assign(idx, v, rows_of(vv), 3,
                       [&](long long i, long long j, double x) {
                           vv[i][j] = x;
                       });
        } else if (target == "z_grid" || target == "confidence") {
            if (target == "confidence" && !obj.confidence)
                throw TypeError(
                    "'NoneType' object does not support item assignment");
            std::vector<std::vector<double>>& g =
                target == "z_grid" ? obj.z_grid : *obj.confidence;
            const long long cols =
                g.empty() ? 0 : static_cast<long long>(g[0].size());
            mut_assign(idx, v, rows_of(g), cols,
                       [&](long long i, long long j, double x) {
                           g[i][j] = x;
                       });
        } else if (target == "faces") {
            mut_assign(idx, static_cast<double>(iv), rows_of(obj.faces), 3,
                       [&](long long i, long long j, double x) {
                           obj.faces[i][j] = static_cast<std::int64_t>(x);
                       });
        }
        // unknown targets: Python getattr raises AttributeError — the oracle
        // never produces them (AssertionError upstream); ignore silently.
    }
}

Json geometry_stats(const DomainObject& obj) {
    const std::string k = obj.kind();
    if (k == "well") {
        std::vector<Vec3> xyz;
        xyz.reserve(obj.stations.size());
        for (const auto& s : obj.stations)
            xyz.push_back(Vec3{s[1], s[2], s[3]});
        return stats_of_verts(xyz);
    }
    if (k == "fault" || k == "volume") return stats_of_verts(obj.verts);
    if (k == "tunnel") return stats_of_verts(obj.path);
    if (k == "measure") return stats_of_verts(obj.points);
    if (k == "horizon") {
        double lo = std::numeric_limits<double>::quiet_NaN(),
               hi = std::numeric_limits<double>::quiet_NaN();
        bool any = false;
        for (const auto& row : obj.z_grid)
            for (double v : row)
                if (std::isfinite(v)) {
                    if (!any) {
                        lo = hi = v;
                        any = true;
                    } else {
                        lo = std::min(lo, v);
                        hi = std::max(hi, v);
                    }
                }
        if (!any) return Json{{"vertex_count", 0}};
        const std::size_t r = obj.z_grid.size(),
                          c = obj.z_grid.empty() ? 0 : obj.z_grid[0].size();
        std::vector<Vec3> corner = {
            Vec3{obj.origin[0], obj.origin[1], lo},
            Vec3{obj.origin[0] + (static_cast<double>(c) - 1) * obj.spacing[1],
                 obj.origin[1] + (static_cast<double>(r) - 1) * obj.spacing[0],
                 hi}};
        return stats_of_verts(corner);
    }
    return Json{{"vertex_count", 0}};
}

// ---------------------------------------------------------------------------
// ModelAssembly
// ---------------------------------------------------------------------------

namespace {
const std::unordered_map<std::string, bool>& kind_registry() {
    static const std::unordered_map<std::string, bool> reg = {
        {"well", true}, {"horizon", true}, {"fault", true},
        {"volume", true}, {"tunnel", true}, {"measure", true}};
    return reg;
}
}  // namespace

ModelAssembly::ModelAssembly(std::string n) : name(std::move(n)) {}

std::size_t ModelAssembly::size() const {
    std::lock_guard lk(lock_);
    return order_.size();
}

bool ModelAssembly::contains(const std::string& object_id) const {
    std::lock_guard lk(lock_);
    return objects_.count(object_id) != 0;
}

std::vector<DomainObject> ModelAssembly::objects(
    const std::optional<std::string>& kind) const {
    std::lock_guard lk(lock_);
    std::vector<DomainObject> out;
    for (const auto& id : order_) {
        if (!kind || id.substr(0, id.find(':')) == *kind)
            out.push_back(objects_.at(id));
    }
    return out;
}

const DomainObject* ModelAssembly::get(const std::string& object_id) const {
    std::lock_guard lk(lock_);
    auto it = objects_.find(object_id);
    return it == objects_.end() ? nullptr : &it->second;
}

std::vector<std::string> ModelAssembly::ids(
    const std::optional<std::string>& kind) const {
    std::lock_guard lk(lock_);
    std::vector<std::string> out;
    for (const auto& id : order_)
        if (!kind || id.substr(0, id.find(':')) == *kind)
            out.push_back(id);
    return out;
}

DomainObject& ModelAssembly::add(DomainObject obj) {
    const std::string k = obj.kind();
    if (!kind_registry().count(k))
        throw DomainError("unknown object kind for " +
                          py_repr(Json(obj.object_id)));
    std::lock_guard lk(lock_);
    if (objects_.count(obj.object_id))
        throw DomainError("duplicate object_id " +
                          py_repr(Json(obj.object_id)) +
                          " — use replace()");
    order_.push_back(obj.object_id);
    return objects_.emplace(obj.object_id, std::move(obj)).first->second;
}

DomainObject& ModelAssembly::replace(DomainObject obj) {
    std::lock_guard lk(lock_);
    auto it = objects_.find(obj.object_id);
    if (it == objects_.end())
        throw DomainError("unknown object_id " +
                          py_repr(Json(obj.object_id)));
    it->second = std::move(obj);
    return it->second;
}

bool ModelAssembly::remove(const std::string& object_id) {
    std::lock_guard lk(lock_);
    if (!objects_.erase(object_id)) return false;
    order_.erase(std::remove(order_.begin(), order_.end(), object_id),
                 order_.end());
    if (display.is_object()) display.erase(object_id);
    return true;
}

int ModelAssembly::clear(const std::optional<std::string>& kind) {
    std::lock_guard lk(lock_);
    int n = 0;
    for (auto it = order_.begin(); it != order_.end();) {
        const std::string& id = *it;
        if (!kind || id.substr(0, id.find(':')) == *kind) {
            objects_.erase(id);
            if (display.is_object()) display.erase(id);
            it = order_.erase(it);
            ++n;
        } else {
            ++it;
        }
    }
    return n;
}

DomainObject& ModelAssembly::bump_version(const std::string& object_id) {
    std::lock_guard lk(lock_);
    auto it = objects_.find(object_id);
    if (it == objects_.end()) throw KeyError(py_repr(Json(object_id)));
    DomainObject bumped = it->second;
    bumped.version += 1;
    it->second = std::move(bumped);
    return it->second;
}

Json ModelAssembly::to_meta() const {
    std::lock_guard lk(lock_);
    Json objs = Json::array();
    for (const auto& id : order_) objs.push_back(objects_.at(id).meta());
    return Json{{"name", name}, {"frame", frame}, {"display", display},
                {"objects", std::move(objs)}};
}

std::vector<std::string> ModelAssembly::apply_meta(const Json& meta) {
    if (meta.contains("name")) name = py_str(meta["name"]);
    // meta.get("frame", "world") — always assigned, default resets.
    frame = meta.contains("frame") ? py_str(meta["frame"]) : "world";
    // meta.get("display", {}) — absent resets to empty.
    display = meta.contains("display") && meta["display"].is_object()
                  ? meta["display"]
                  : Json::object();
    std::vector<std::string> restored;
    if (!meta.contains("objects")) return restored;
    for (const auto& entry : meta["objects"]) {
        const std::string oid =
            entry.contains("object_id") ? py_str(entry["object_id"]) : "";
        const std::string k =
            oid.substr(0, oid.find(':'));
        if (!kind_registry().count(k)) continue;
        try {
            add(DomainObject::from_meta(entry));
            restored.push_back(oid);
        } catch (const DomainError&) {
            continue;
        } catch (const KeyError&) {
            continue;
        } catch (const TypeError&) {
            continue;
        } catch (const ValueError&) {
            continue;
        }
    }
    return restored;
}

// ---------------------------------------------------------------------------
// builders.py constructors
// ---------------------------------------------------------------------------

DomainObject build_well_trajectory(
    const std::string& name,
    const std::vector<std::vector<double>>& stations,
    const std::string& crs, const std::string& unit,
    const std::string& vertical_domain, const std::string& well_asset_id,
    const std::vector<std::pair<std::string, double>>& formation_tops,
    std::optional<Provenance> provenance,
    const std::optional<std::string>& object_id) {
    for (const auto& row : stations)
        if (row.size() != 4)
            throw DomainError(name +
                              ": stations must be (N, 4) [md,x,y,z]");
    for (std::size_t i = 1; i < stations.size(); ++i)
        if (stations[i][0] <= stations[i - 1][0])
            throw DomainError(name + ": MD must be strictly increasing");
    DomainObject o;
    o.object_id = object_id.value_or("well:" + slugify(Json(name), "obj"));
    o.name = name;
    o.crs = crs;
    o.unit = unit;
    o.vertical_domain = vertical_domain;
    o.stations.reserve(stations.size());
    for (const auto& row : stations)
        o.stations.push_back({row[0], row[1], row[2], row[3]});
    o.representation = "measured";
    o.well_asset_id = well_asset_id;
    o.formation_tops = formation_tops;
    o.provenance = provenance.value_or(Provenance{});
    o.validate();
    return o;
}

DomainObject build_simplified_vertical_well(
    const std::string& name, const std::vector<double>& head_xyz,
    double total_depth, const std::string& crs, const std::string& unit,
    const std::string& vertical_domain, const std::string& well_asset_id,
    const std::vector<std::pair<std::string, double>>& formation_tops,
    std::optional<Provenance> provenance,
    const std::optional<std::string>& object_id) {
    if (head_xyz.size() != 3)
        throw DomainError(name + ": head_xyz must be (x, y, z)");
    for (double c : head_xyz)
        if (!std::isfinite(c))
            throw DomainError(name + ": head_xyz must be finite");
    if (!(total_depth > 0.0))
        throw DomainError(name + ": total_depth must be positive");
    const bool depth_like =
        vertical_domain == "depth" || vertical_domain == "tvdss";
    const double td_z =
        depth_like ? head_xyz[2] + total_depth : total_depth;
    DomainObject o;
    o.object_id = object_id.value_or("well:" + slugify(Json(name), "obj"));
    o.name = name;
    o.crs = crs;
    o.unit = unit;
    o.vertical_domain = vertical_domain;
    o.stations = {{0.0, head_xyz[0], head_xyz[1], head_xyz[2]},
                  {total_depth, head_xyz[0], head_xyz[1], td_z}};
    o.representation = "simplified_vertical";
    o.well_asset_id = well_asset_id;
    o.formation_tops = formation_tops;
    o.provenance = provenance.value_or(Provenance{});
    o.validate();
    return o;
}

DomainObject build_fault_from_mesh(
    const std::string& name,
    const std::vector<std::vector<double>>& verts,
    const std::vector<std::vector<std::int64_t>>& faces,
    const std::string& crs, const std::string& unit,
    const std::string& vertical_domain, std::optional<double> throw_m,
    std::optional<std::array<double, 2>> strike_dip,
    const std::string& fault_asset_id, std::optional<Provenance> provenance,
    const std::optional<std::string>& object_id) {
    for (const auto& row : verts)
        if (row.size() != 3)
            throw DomainError(name + ": verts must be (N, 3)");
    for (const auto& row : faces)
        if (row.size() != 3)
            throw DomainError(name + ": faces must be (M, 3)");
    DomainObject o;
    o.object_id =
        object_id.value_or("fault:" + slugify(Json(name), "obj"));
    o.name = name;
    o.crs = crs;
    o.unit = unit;
    o.vertical_domain = vertical_domain;
    o.verts.reserve(verts.size());
    for (const auto& row : verts)
        o.verts.push_back({row[0], row[1], row[2]});
    o.faces.reserve(faces.size());
    for (const auto& row : faces)
        o.faces.push_back({row[0], row[1], row[2]});
    o.representation = "triangulated_3d";
    o.throw_m = throw_m;
    o.strike_dip = strike_dip;
    o.fault_asset_id = fault_asset_id;
    o.provenance = provenance.value_or(Provenance{});
    o.validate();
    return o;
}

}  // namespace pwb::geomodel
