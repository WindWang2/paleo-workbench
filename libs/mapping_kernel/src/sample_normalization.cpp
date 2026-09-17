#include <pwb/mapping/sample_normalization.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <map>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace pwb::mapping {
namespace {

bool known_policy(const std::string& policy) {
    for (const char* p : kDuplicatePolicies) {
        if (policy == p) return true;
    }
    return false;
}

std::string py_repr_float(double v) {
    std::ostringstream o;
    o.setf(std::ios::fmtflags(0), std::ios::floatfield);
    o << v;
    std::string s = o.str();
    if (s.find('.') == std::string::npos && s.find('e') == std::string::npos
        && s.find('E') == std::string::npos) {
        s += ".0";
    }
    return s;
}

bool json_to_float(const Json& v, double& out) {
    if (v.is_number()) {
        out = v.get<double>();
        return true;
    }
    if (v.is_boolean()) {
        out = v.get<bool>() ? 1.0 : 0.0;
        return true;
    }
    if (!v.is_string()) return false;
    const std::string s = v.get<std::string>();
    if (s == "inf" || s == "Infinity" || s == "+inf") {
        out = std::numeric_limits<double>::infinity();
        return true;
    }
    if (s == "-inf" || s == "-Infinity") {
        out = -std::numeric_limits<double>::infinity();
        return true;
    }
    char* end = nullptr;
    out = std::strtod(s.c_str(), &end);
    return end != s.c_str() && end != nullptr && *end == '\0';
}

bool json_truthy(const Json& v) {
    if (v.is_null()) return false;
    if (v.is_boolean()) return v.get<bool>();
    if (v.is_string()) return !v.get<std::string>().empty();
    if (v.is_number()) return v.get<double>() != 0.0;
    if (v.is_array() || v.is_object()) return !v.empty();
    return true;
}

std::string json_str(const Json& v) {
    if (v.is_string()) return v.get<std::string>();
    if (v.is_boolean()) return v.get<bool>() ? "True" : "False";
    if (v.is_number_unsigned()) return std::to_string(v.get<std::uint64_t>());
    if (v.is_number_integer()) return std::to_string(v.get<std::int64_t>());
    if (v.is_number_float()) return Json(v.get<double>()).dump();
    if (v.is_null()) return "None";
    return v.dump();
}

std::optional<Json> valid_record(const Json& pt) {
    if (!pt.is_object()) return std::nullopt;
    double x = 0.0, y = 0.0, z = 0.0;
    if (pt.contains("x") && pt.contains("y")) {
        if (!json_to_float(pt["x"], x) || !json_to_float(pt["y"], y)) {
            return std::nullopt;
        }
    } else if (pt.contains("lng") && pt.contains("lat")) {
        if (!json_to_float(pt["lng"], x) || !json_to_float(pt["lat"], y)) {
            return std::nullopt;
        }
    } else {
        return std::nullopt;
    }
    Json zsrc = Json();
    if (pt.contains("value")) zsrc = pt["value"];
    else if (pt.contains("z")) zsrc = pt["z"];
    else if (pt.contains("v")) zsrc = pt["v"];
    else return std::nullopt;
    if (!json_to_float(zsrc, z)) return std::nullopt;
    if (!(std::isfinite(x) && std::isfinite(y) && std::isfinite(z))) {
        return std::nullopt;
    }
    Json rec = Json::object();
    rec["x"] = x;
    rec["y"] = y;
    rec["z"] = z;
    for (const char* key : {"q", "b_i"}) {
        if (!pt.contains(key) || pt[key].is_null()) continue;
        double n = 0.0;
        if (json_to_float(pt[key], n) && std::isfinite(n)) rec[key] = n;
    }
    if (pt.contains("qc_flag") && !pt["qc_flag"].is_null()) {
        rec["qc_flag"] = json_str(pt["qc_flag"]);
    }
    for (const char* key : {"well_id", "name"}) {
        if (!pt.contains(key)) continue;
        if (json_truthy(pt[key])) rec[key] = json_str(pt[key]);
    }
    return rec;
}

double incremental_mean(const std::vector<double>& values) {
    double acc = 0.0;
    int i = 0;
    for (double v : values) {
        ++i;
        acc += (v - acc) / static_cast<double>(i);
    }
    return acc;
}

}  // namespace

std::string duplicate_policy_from_params(const Json& params) {
    if (!params.is_object() || !params.contains("duplicate_policy")
        || params["duplicate_policy"].is_null()) {
        return kDefaultDuplicatePolicy;
    }
    std::string policy = json_str(params["duplicate_policy"]);
    // strip + lower
    while (!policy.empty() && std::isspace(static_cast<unsigned char>(policy.front()))) {
        policy.erase(policy.begin());
    }
    while (!policy.empty() && std::isspace(static_cast<unsigned char>(policy.back()))) {
        policy.pop_back();
    }
    for (char& c : policy) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    if (!known_policy(policy)) return kDefaultDuplicatePolicy;
    return policy;
}

std::pair<Json, SampleNormalizationReport> normalize_factor_samples(
    const Json& points, const std::string& policy) {
    if (!known_policy(policy)) {
        throw std::invalid_argument(
            "unknown duplicate policy '" + policy
            + "'; choose from ('mean', 'first', 'error', 'keep')");
    }
    const Json arr = points.is_array() ? points : Json::array();
    std::vector<Json> records;
    int n_nonfinite = 0;
    for (const auto& pt : arr) {
        auto rec = valid_record(pt);
        if (!rec.has_value()) {
            ++n_nonfinite;
            continue;
        }
        records.push_back(*rec);
    }
    int n_qc = 0;
    for (const auto& r : records) {
        const std::string flag =
            r.contains("qc_flag") ? r["qc_flag"].get<std::string>() : "";
        if (flag != "" && flag != "ok") ++n_qc;
    }

    SampleNormalizationReport report;
    report.policy = policy;
    report.n_input = static_cast<int>(arr.size());
    report.n_valid = static_cast<int>(records.size());
    report.n_nonfinite_dropped = n_nonfinite;
    report.n_qc_flagged = n_qc;

    if (policy == "keep") {
        Json out = Json::array();
        for (const auto& r : records) out.push_back(r);
        return {out, report};
    }

    std::map<std::pair<double, double>, std::vector<int>> groups;
    std::vector<std::pair<double, double>> order;
    for (int i = 0; i < static_cast<int>(records.size()); ++i) {
        const auto key = std::make_pair(records[static_cast<std::size_t>(i)]["x"].get<double>(),
                                        records[static_cast<std::size_t>(i)]["y"].get<double>());
        if (groups.find(key) == groups.end()) order.push_back(key);
        groups[key].push_back(i);
    }
    std::vector<std::pair<double, double>> duplicate_keys;
    for (const auto& key : order) {
        if (groups[key].size() > 1) duplicate_keys.push_back(key);
    }
    if (policy == "error" && !duplicate_keys.empty()) {
        throw std::invalid_argument(
            "duplicate sample locations present and duplicate_policy='error': "
            + std::to_string(duplicate_keys.size())
            + " location(s) with 2+ samples (first at x="
            + py_repr_float(duplicate_keys[0].first) + ", y="
            + py_repr_float(duplicate_keys[0].second) + ")");
    }

    Json normalized = Json::array();
    int merged = 0;
    for (const auto& key : order) {
        const auto& indices = groups[key];
        if (indices.size() == 1) {
            normalized.push_back(records[static_cast<std::size_t>(indices[0])]);
            continue;
        }
        merged += static_cast<int>(indices.size()) - 1;
        Json base = records[static_cast<std::size_t>(indices[0])];
        if (policy == "mean") {
            std::vector<double> zs;
            for (int idx : indices) {
                zs.push_back(records[static_cast<std::size_t>(idx)]["z"].get<double>());
            }
            base["z"] = incremental_mean(zs);
            for (const char* extra : {"q", "b_i"}) {
                std::vector<double> vals;
                for (int idx : indices) {
                    const Json& m = records[static_cast<std::size_t>(idx)];
                    if (m.contains(extra)) vals.push_back(m[extra].get<double>());
                }
                if (!vals.empty()) base[extra] = incremental_mean(vals);
            }
        }
        std::vector<std::string> flags;
        for (int idx : indices) {
            const Json& m = records[static_cast<std::size_t>(idx)];
            std::string f = m.contains("qc_flag") ? m["qc_flag"].get<std::string>() : "";
            if (f != "" && f != "ok") flags.push_back(f);
        }
        if (!flags.empty()) {
            std::sort(flags.begin(), flags.end());
            // unique? Python set then sorted — unique values, first of sorted
            flags.erase(std::unique(flags.begin(), flags.end()), flags.end());
            base["qc_flag"] = flags.front();
        }
        std::vector<std::string> names;
        std::unordered_set<std::string> seen;
        for (int idx : indices) {
            const Json& m = records[static_cast<std::size_t>(idx)];
            std::string n;
            if (m.contains("well_id")) n = m["well_id"].get<std::string>();
            else if (m.contains("name")) n = m["name"].get<std::string>();
            if (n.empty() || seen.count(n)) continue;
            seen.insert(n);
            names.push_back(n);
        }
        if (!names.empty()) {
            std::string joined = names[0];
            for (std::size_t i = 1; i < names.size(); ++i) {
                joined += "+";
                joined += names[i];
            }
            base["well_id"] = joined;
        }
        normalized.push_back(base);
    }
    report.n_duplicate_groups = static_cast<int>(duplicate_keys.size());
    report.n_duplicates_merged = merged;
    return {normalized, report};
}

}  // namespace pwb::mapping
