#include <pwb/factor_fusion/factor_units.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::factor_fusion {
namespace {

// --- generated tables ------------------------------------------------------

struct FactorUnitEntry {
    const char* key;
    const char* unit;
    const char* color_ramp;
};
struct FactorFamily {
    const char* name;
    std::vector<const char*> aliases;
};

#include "factor_units_data.inc"
#include "units_lower_map.inc"

// --- minimal UTF-8 / Python str helpers ------------------------------------

// Decode one code point; returns U+FFFD-ish sentinel 0 on malformed input.
char32_t decode_one(std::string_view s, std::size_t& pos) {
    const auto lead = static_cast<unsigned char>(s[pos]);
    if (lead < 0x80) {
        ++pos;
        return lead;
    }
    int need = 0;
    char32_t cp = 0;
    if ((lead & 0xE0) == 0xC0) { need = 1; cp = lead & 0x1F; }
    else if ((lead & 0xF0) == 0xE0) { need = 2; cp = lead & 0x0F; }
    else if ((lead & 0xF8) == 0xF0) { need = 3; cp = lead & 0x07; }
    else { ++pos; return 0xFFFD; }
    if (pos + need >= s.size()) { pos = s.size(); return 0xFFFD; }
    for (int i = 1; i <= need; ++i) {
        const auto cont = static_cast<unsigned char>(s[pos + i]);
        if ((cont & 0xC0) != 0x80) { ++pos; return 0xFFFD; }
        cp = (cp << 6) | (cont & 0x3F);
    }
    pos += need + 1;
    return cp;
}

// str.isspace() code point set (bidirectional-whitespace + separators).
bool is_py_space(char32_t cp) {
    if (cp >= 0x09 && cp <= 0x0D) return true;
    if (cp >= 0x1C && cp <= 0x1F) return true;
    switch (cp) {
        case 0x20: case 0x85: case 0xA0: case 0x1680:
        case 0x2028: case 0x2029: case 0x202F: case 0x205F: case 0x3000:
            return true;
        default:
            return cp >= 0x2000 && cp <= 0x200A;
    }
}

const char* lower_mapped(char32_t cp) {
    // Binary search over kLowerMap (sorted by code point at generation time).
    std::size_t lo = 0, hi = sizeof(kLowerMap) / sizeof(kLowerMap[0]);
    while (lo < hi) {
        const std::size_t mid = (lo + hi) / 2;
        if (kLowerMap[mid].first < cp) lo = mid + 1;
        else hi = mid;
    }
    if (lo < sizeof(kLowerMap) / sizeof(kLowerMap[0]) &&
        kLowerMap[lo].first == cp) {
        return kLowerMap[lo].second;
    }
    return nullptr;
}

// str.strip(): trim Unicode whitespace at both ends (on code points).
std::string py_strip(std::string_view s) {
    std::size_t start = 0;
    while (start < s.size()) {
        std::size_t probe = start;
        if (!is_py_space(decode_one(s, probe))) break;
        start = probe;
    }
    std::size_t end = s.size();
    while (end > start) {
        // walk back over a UTF-8 sequence tail
        std::size_t seq = end;
        do { --seq; } while (seq > start &&
                             (static_cast<unsigned char>(s[seq]) & 0xC0) == 0x80);
        std::size_t probe = seq;
        if (!is_py_space(decode_one(s, probe)) || probe != end) break;
        end = seq;
    }
    return std::string(s.substr(start, end - start));
}

// str.lower(): per-code-point map; unmapped code points pass through raw.
std::string py_lower(std::string_view s) {
    std::string out;
    out.reserve(s.size());
    std::size_t pos = 0;
    while (pos < s.size()) {
        const std::size_t cp_start = pos;
        const char32_t cp = decode_one(s, pos);
        if (const char* mapped = lower_mapped(cp)) {
            out += mapped;
        } else {
            out.append(s.substr(cp_start, pos - cp_start));
        }
    }
    return out;
}

std::string py_lower_str(std::string_view s) { return py_lower(s); }

const FactorUnitEntry* find_defaults(std::string_view key) {
    for (const auto& e : kFactorDefaults) {
        if (key == e.key) return &e;
    }
    return nullptr;
}

const FactorUnitEntry* folded_entry(std::string_view factor_name) {
    const std::string key = normalize_factor_key(factor_name);
    if (const FactorUnitEntry* e = find_defaults(factor_name)) return e;
    if (const FactorUnitEntry* e = find_defaults(key)) return e;
    for (const auto& family : kFactorFamilies) {
        bool hit = false;
        for (const char* alias : family.aliases) {
            if (key == py_lower_str(alias)) { hit = true; break; }
        }
        if (!hit) continue;
        for (const char* representative : family.aliases) {
            if (const FactorUnitEntry* e = find_defaults(representative)) return e;
            if (const FactorUnitEntry* e =
                    find_defaults(py_lower_str(representative))) {
                return e;
            }
        }
    }
    return nullptr;
}

// Python f"{v:.3g}" — same notation rules as printf %.3g for our value range.
std::string fmt_g3(double v) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.3g", v);
    return buf;
}

std::string py_repr_str(std::string_view s) {
    // repr() with single quotes; escapes for backslash/quote/non-printables
    // only where the frozen messages can reach (factor names / ops).
    std::string out = "'";
    for (char c : s) {
        switch (c) {
            case '\'': out += "\\'"; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += c;
        }
    }
    out += "'";
    return out;
}

}  // namespace

std::string normalize_factor_key(std::string_view factor_name) {
    if (factor_name.empty()) return "";
    return py_lower(py_strip(factor_name));
}

std::optional<std::string> unit_for_factor(std::string_view factor_name) {
    const FactorUnitEntry* e = folded_entry(factor_name);
    if (!e || !*e->unit) return std::nullopt;
    return std::string(e->unit);
}

std::optional<std::string> color_ramp_for_factor(std::string_view factor_name) {
    const FactorUnitEntry* e = folded_entry(factor_name);
    if (!e || !*e->color_ramp) return std::nullopt;
    return std::string(e->color_ramp);
}

std::vector<std::string> validate_factor_unit_against_values(
    std::string_view factor_name, const std::optional<std::string>& unit,
    const std::vector<float>& values) {
    if (!unit.has_value()) return {};
    double lo = 0.0, hi = 0.0;
    bool any = false;
    std::vector<double> finite;
    finite.reserve(values.size());
    for (float v : values) {
        if (std::isfinite(v)) {
            const double d = static_cast<double>(v);
            finite.push_back(d);
            if (!any) { lo = hi = d; any = true; }
            else { lo = std::min(lo, d); hi = std::max(hi, d); }
        }
    }
    if (!any) return {};
    std::vector<std::string> diagnostics;
    const std::string u = py_strip(*unit);
    const std::string name_repr = py_repr_str(factor_name);
    if (u == "%" || u == "percent") {
        if (lo < 1.5 && 1.5 < hi) {
            diagnostics.push_back(
                "factor " + name_repr + " declares % but values span [" +
                fmt_g3(lo) + ", " + fmt_g3(hi) +
                "] — mixed fraction and percent scale");
        } else if (lo >= 0.0 && hi <= 1.5) {
            // np.allclose(finite, np.round(finite)) — rtol=1e-5, atol=1e-8,
            // np.round = round-half-even.
            bool all_int = true;
            for (double v : finite) {
                const double r = std::nearbyint(v);
                if (std::fabs(v - r) > 1e-8 + 1e-5 * std::fabs(r)) {
                    all_int = false;
                    break;
                }
            }
            if (!all_int) {
                diagnostics.push_back(
                    "factor " + name_repr + " declares % but values span [" +
                    fmt_g3(lo) + ", " + fmt_g3(hi) +
                    "] — fractions misread as percent (÷100 or relabel as v/v)");
            }
        }
    } else if (u == "1" || u == "v/v" || u == "fraction") {
        if (lo >= 1.5 || hi > 1.5) {
            diagnostics.push_back(
                "factor " + name_repr + " declares dimensionless " +
                py_repr_str(u) + " but values span [" + fmt_g3(lo) + ", " +
                fmt_g3(hi) + "] — percent-scale data in a 0..1 unit");
        }
    }
    return diagnostics;
}

}  // namespace pwb::factor_fusion
