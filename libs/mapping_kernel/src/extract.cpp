#include <pwb/mapping/extract.hpp>

#include <pwb/domain/text.hpp>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <initializer_list>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace pwb::mapping {
namespace {

std::string ascii_lower(std::string s) {
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s;
}

std::string strip(std::string s) {
    return domain::strip_ascii(s);  // shared impl (#1392)
}

bool py_truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_number_float()) {
        const double d = v.get<double>();
        if (d != d) return true;  // NaN is truthy in Python
        return d != 0.0;
    }
    if (v.is_number_unsigned()) return v.get<std::uint64_t>() != 0;
    if (v.is_number_integer()) return v.get<std::int64_t>() != 0;
    if (v.is_string()) return !v.get<std::string>().empty();
    if (v.is_array() || v.is_object()) return !v.empty();
    return true;
}

std::string py_str(const Json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_unsigned()) return std::to_string(v.get<std::uint64_t>());
    if (v.is_number_integer()) return std::to_string(v.get<std::int64_t>());
    if (v.is_number_float()) {
        std::string s = Json(v.get<double>()).dump();
        return s;
    }
    if (v.is_null()) return "None";
    return v.dump();
}

std::string first_str(const Json& rec,
                      std::initializer_list<const char*> keys,
                      const std::string& fallback) {
    for (const char* k : keys) {
        auto it = rec.find(k);
        if (it == rec.end()) continue;
        if (py_truthy(*it)) return py_str(*it);
    }
    return fallback;
}

bool py_float(const Json& v, double& out) {
    if (v.is_number()) {
        out = v.get<double>();
        return true;
    }
    if (v.is_boolean()) {
        out = v.get<bool>() ? 1.0 : 0.0;
        return true;
    }
    if (!v.is_string()) return false;
    std::string s = strip(v.get<std::string>());
    if (s.empty()) return false;
    char* end = nullptr;
    out = std::strtod(s.c_str(), &end);
    if (end == s.c_str()) return false;
    while (*end && std::isspace(static_cast<unsigned char>(*end))) ++end;
    return *end == '\0';
}

Json folded_copy(const Json& rec) {
    Json out = Json::object();
    for (auto it = rec.begin(); it != rec.end(); ++it) {
        out[ascii_lower(it.key())] = it.value();
    }
    return out;
}

// Copied from pipeline.py _FACTOR_ALIAS_GROUPS (insertion order).
const std::vector<std::pair<std::string, std::vector<std::string>>>&
alias_groups() {
    static const std::vector<std::pair<std::string, std::vector<std::string>>>
        kGroups = {
            {"porosity",
             {"porosity", "por", "poro", "phie", "phit", "孔隙度"}},
            {"permeability", {"permeability", "perm", "k", "渗透率"}},
            {"net_pay",
             {"net_pay", "h_pay", "h_net", "pay_thickness", "有效厚度",
              "净产层厚度"}},
            {"formation_thickness",
             {"formation_thickness", "thickness", "h_t", "total_thickness",
              "地层厚度"}},
            {"sand_thickness",
             {"sand_thickness", "h_s", "sand", "砂岩厚度"}},
            {"sand_ratio", {"sand_ratio", "r_s", "砂地比"}},
            {"top_depth",
             {"top_depth", "top_md", "top_tvd", "top", "地层顶界", "顶界深度",
              "tops", "formation_top"}},
            {"base_depth",
             {"base_depth", "base_md", "base_tvd", "base", "地层底界",
              "底界深度", "formation_base"}},
            {"toc", {"toc"}},
            {"water_depth", {"water_depth", "古水深"}},
        };
    return kGroups;
}

std::vector<std::string> find_matching_aliases(const std::string& factor_name) {
    const std::string norm = ascii_lower(strip(factor_name));
    for (const auto& [key, aliases] : alias_groups()) {
        if (norm == key) return aliases;
        for (const auto& a : aliases) {
            if (norm == ascii_lower(a)) return aliases;
        }
    }
    return {factor_name, norm};
}

// Units only from paleo_workbench/workflow/factor_units.py FACTOR_DEFAULTS
// (color ramps omitted).
const std::unordered_map<std::string, std::string>& factor_units() {
    static const std::unordered_map<std::string, std::string> kUnits = {
        {"孔隙度", "%"},
        {"porosity", "%"},
        {"POR", "%"},
        {"PORO", "%"},
        {"PHIE", "%"},
        {"PHIT", "%"},
        {"渗透率", "mD"},
        {"permeability", "mD"},
        {"PERM", "mD"},
        {"PERMEABILITY", "mD"},
        {"K", "mD"},
        {"有效厚度", "m"},
        {"net_pay", "m"},
        {"NET_PAY", "m"},
        {"净产层厚度", "m"},
        {"H_pay", "m"},
        {"H_net", "m"},
        {"PAY_THICKNESS", "m"},
        {"地层厚度", "m"},
        {"formation_thickness", "m"},
        {"thickness", "m"},
        {"H_t", "m"},
        {"TOTAL_THICKNESS", "m"},
        {"砂岩厚度", "m"},
        {"sand_thickness", "m"},
        {"H_s", "m"},
        {"SAND_THICKNESS", "m"},
        {"砂地比", "%"},
        {"sand_ratio", "%"},
        {"R_s", "%"},
        {"SAND_RATIO", "%"},
        {"地层顶界", "m"},
        {"顶界深度", "m"},
        {"top_depth", "m"},
        {"top_md", "m"},
        {"top_tvd", "m"},
        {"TOP", "m"},
        {"TOP_DEPTH", "m"},
        {"地层底界", "m"},
        {"底界深度", "m"},
        {"base_depth", "m"},
        {"base_md", "m"},
        {"base_tvd", "m"},
        {"BASE", "m"},
        {"BASE_DEPTH", "m"},
        {"TOC", "%"},
        {"toc", "%"},
        {"古水深", "m"},
        {"water_depth", "m"},
        {"paleo_water_depth", "m"},
        {"PALEO_WATER_DEPTH", "m"},
        {"probability", "1"},
        {"PROBABILITY", "1"},
        {"概率", "1"},
        {"沉积概率", "1"},
    };
    return kUnits;
}

std::string default_unit(const std::string& factor_name) {
    const auto& units = factor_units();
    auto it = units.find(factor_name);
    if (it != units.end()) return it->second;
    it = units.find(ascii_lower(factor_name));
    if (it != units.end()) return it->second;
    return "";
}

struct CoordFamily {
    const char* name;
    const char* x;
    const char* y;
};

// Audit #1150: never cross-pair keys from different CRS families.
constexpr CoordFamily kCoordFamilies[] = {
    {"project", "project_x", "project_y"},
    {"xy", "x", "y"},
    {"lnglat", "lng", "lat"},
    {"lnglat", "longitude", "latitude"},
    {"surface", "surface_x", "surface_y"},
};

Json lookup_top(const Json& rec, const std::string& factor_name,
                const std::vector<std::string>& aliases) {
    if (rec.contains(factor_name)) return rec[factor_name];
    if (rec.contains("value")) return rec["value"];
    if (rec.contains("val")) return rec["val"];
    const Json rec_lower = folded_copy(rec);
    for (const auto& alias : aliases) {
        const std::string al = ascii_lower(alias);
        if (rec_lower.contains(al)) return rec_lower[al];
    }
    return Json();
}

const char* kSandRatioRule = "sand_ratio = H_s / H_t";
const char* kThicknessRule = "formation_thickness = base_depth - top_depth";

}  // namespace

FactorDataset extract_factors(const Json& records,
                              const std::string& factor_name,
                              const ExtractOptions& options) {
    const std::string resolved_unit =
        options.unit.has_value() ? *options.unit : default_unit(factor_name);
    const std::vector<std::string> aliases =
        find_matching_aliases(factor_name);

    FactorDataset out;
    out.factor_name = factor_name;
    out.unit = resolved_unit;
    out.target_horizon = options.target_horizon;
    out.crs = options.crs;

    unsigned skipped_missing = 0;
    unsigned skipped_invalid = 0;
    unsigned derived_points = 0;
    Json families = Json::object();

    const Json* recs = records.is_array() ? &records : nullptr;
    if (recs) {
        for (const auto& rec : *recs) {
            if (!rec.is_object()) continue;

            Json x;
            Json y;
            std::string family_used;
            for (const auto& fam : kCoordFamilies) {
                auto vx = rec.find(fam.x);
                auto vy = rec.find(fam.y);
                if (vx != rec.end() && vy != rec.end() && !vx->is_null() &&
                    !vy->is_null()) {
                    x = *vx;
                    y = *vy;
                    family_used = fam.name;
                    break;
                }
            }
            if (x.is_null() || y.is_null()) {
                auto cit = rec.find("coordinates");
                if (cit != rec.end() && cit->is_array() && cit->size() >= 2) {
                    x = (*cit)[0];
                    y = (*cit)[1];
                    family_used = "coordinates";
                }
            }
            if (x.is_null() || y.is_null()) {
                ++skipped_missing;
                continue;
            }

            double fx = 0.0;
            double fy = 0.0;
            if (!py_float(x, fx) || !py_float(y, fy)) {
                ++skipped_invalid;
                continue;
            }
            if (!family_used.empty()) {
                const unsigned n =
                    families.contains(family_used)
                        ? families[family_used].get<unsigned>()
                        : 0u;
                families[family_used] = n + 1u;
            }

            Json val = lookup_top(rec, factor_name, aliases);
            if (val.is_null()) {
                for (const char* sub_key :
                     {"attributes", "properties", "metadata"}) {
                    auto sit = rec.find(sub_key);
                    if (sit == rec.end() || !sit->is_object()) continue;
                    const Json& sub = *sit;
                    if (sub.contains(factor_name)) {
                        val = sub[factor_name];
                        break;
                    }
                    if (sub.contains("value")) {
                        val = sub["value"];
                        break;
                    }
                    const Json sub_lower = folded_copy(sub);
                    for (const auto& alias : aliases) {
                        const std::string al = ascii_lower(alias);
                        if (sub_lower.contains(al)) {
                            val = sub_lower[al];
                            break;
                        }
                    }
                    if (!val.is_null()) break;
                }
            }

            std::string derived_rule;
            Json derived_sources = Json::object();
            if (val.is_null()) {
                const std::string norm = ascii_lower(factor_name);
                const Json rec_lower = folded_copy(rec);
                if (norm == "砂地比" || norm == "sand_ratio" ||
                    norm == "r_s") {
                    const auto sand_aliases =
                        find_matching_aliases("sand_thickness");
                    const auto thick_aliases =
                        find_matching_aliases("formation_thickness");
                    Json hs;
                    Json ht;
                    std::string hs_key;
                    std::string ht_key;
                    for (const auto& sa : sand_aliases) {
                        const std::string sl = ascii_lower(sa);
                        if (rec_lower.contains(sl)) {
                            hs = rec_lower[sl];
                            hs_key = sa;
                            break;
                        }
                    }
                    for (const auto& ta : thick_aliases) {
                        const std::string tl = ascii_lower(ta);
                        if (rec_lower.contains(tl)) {
                            ht = rec_lower[tl];
                            ht_key = ta;
                            break;
                        }
                    }
                    if (!hs.is_null() && !ht.is_null()) {
                        double f_hs = 0.0;
                        double f_ht = 0.0;
                        if (py_float(hs, f_hs) && py_float(ht, f_ht) &&
                            f_ht > 0.0) {
                            val = 100.0 * f_hs / f_ht;
                            derived_rule = kSandRatioRule;
                            derived_sources["H_s"] = hs_key;
                            derived_sources["H_t"] = ht_key;
                        }
                    }
                } else if (norm == "地层厚度" ||
                           norm == "formation_thickness" ||
                           norm == "thickness" || norm == "h_t" ||
                           norm == "total_thickness") {
                    const auto base_aliases =
                        find_matching_aliases("base_depth");
                    const auto top_aliases =
                        find_matching_aliases("top_depth");
                    Json base;
                    Json top;
                    std::string base_key;
                    std::string top_key;
                    for (const auto& ba : base_aliases) {
                        const std::string bl = ascii_lower(ba);
                        if (rec_lower.contains(bl)) {
                            base = rec_lower[bl];
                            base_key = ba;
                            break;
                        }
                    }
                    for (const auto& ta : top_aliases) {
                        const std::string tl = ascii_lower(ta);
                        if (rec_lower.contains(tl)) {
                            top = rec_lower[tl];
                            top_key = ta;
                            break;
                        }
                    }
                    if (!base.is_null() && !top.is_null()) {
                        double f_base = 0.0;
                        double f_top = 0.0;
                        if (py_float(base, f_base) && py_float(top, f_top) &&
                            f_base > f_top) {
                            val = f_base - f_top;
                            derived_rule = kThicknessRule;
                            derived_sources["base"] = base_key;
                            derived_sources["top"] = top_key;
                        }
                    }
                }
            }

            if (val.is_null()) continue;
            double fval = 0.0;
            if (!py_float(val, fval)) continue;

            const std::string well_id =
                first_str(rec, {"well_id", "id"}, "");
            const std::string well_name =
                first_str(rec, {"name", "well_name", "well"}, well_id);
            const std::string qc_flag = first_str(rec, {"qc_flag"}, "ok");
            const std::string formation = first_str(
                rec, {"formation", "target_horizon"}, options.target_horizon);

            Json point_metadata = Json::object();
            auto pit = rec.find("properties");
            if (pit != rec.end() && pit->is_object()) {
                point_metadata = *pit;
            }
            if (!derived_rule.empty()) {
                point_metadata["derived"] = Json{
                    {"rule", derived_rule},
                    {"sources", derived_sources},
                };
                ++derived_points;
            }

            FactorPoint pt;
            pt.name = factor_name;
            pt.value = fval;
            pt.unit = resolved_unit;
            pt.well_id = well_id;
            pt.well_name = well_name;
            pt.x = fx;
            pt.y = fy;
            pt.crs = options.crs;
            pt.formation = formation;
            pt.qc_flag = qc_flag;
            pt.metadata = std::move(point_metadata);
            out.points.push_back(std::move(pt));
        }
    }

    Json diagnostics = {
        {"coordinate_key_families_used", families},
        {"skipped_missing_coordinates", skipped_missing},
        {"skipped_invalid_coordinates", skipped_invalid},
        {"derived_points", derived_points},
    };
    if (families.size() > 1) {
        diagnostics["coordinate_key_family_mixing"] = true;
    }
    out.metadata = std::move(diagnostics);
    return out;
}

}  // namespace pwb::mapping
