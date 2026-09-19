#include <pwb/ui_composite/topology_checker.hpp>

#include <chrono>
#include <cstdio>
#include <stdexcept>

namespace pwb::ui_composite {
namespace {

std::string str_field(const Json& object, const char* key) {
    if (!object.is_object()) {
        return {};
    }
    auto it = object.find(key);
    if (it == object.end() || it->is_null()) {
        return {};
    }
    if (it->is_string()) {
        return it->get<std::string>();
    }
    if (it->is_number_integer()) {
        return std::to_string(it->get<long long>());
    }
    if (it->is_number()) {
        return std::to_string(it->get<double>());
    }
    if (it->is_boolean()) {
        return it->get<bool>() ? "True" : "False";
    }
    return {};
}

// Raw bridge payload normalization: object passes through, JSON text is
// parsed, anything else becomes {}.
Json parse_payload(const Json& raw) {
    if (raw.is_object()) {
        return raw;
    }
    if (raw.is_string()) {
        try {
            const Json parsed = Json::parse(raw.get<std::string>());
            return parsed.is_object() ? parsed : Json::object();
        } catch (...) {
            return Json::object();
        }
    }
    return Json::object();
}

std::vector<Json> error_list(const Json& payload) {
    std::vector<Json> out;
    auto it = payload.find("errors");
    if (it != payload.end() && it->is_array()) {
        for (const Json& entry : *it) {
            if (entry.is_object()) {
                out.push_back(entry);
            }
        }
    }
    return out;
}

std::string utc_now_iso() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t t = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
#if defined(_WIN32)
    gmtime_s(&tm, &t);
#else
    gmtime_r(&t, &tm);
#endif
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d+00:00",
                  tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour,
                  tm.tm_min, tm.tm_sec);
    return buf;
}

}  // namespace

IgnoreKey ignore_key(const Json& error) {
    return {str_field(error, "rule"), str_field(error, "layer_id"),
            str_field(error, "feature_id"),
            str_field(error, "other_feature_id")};
}

void TopologyChecker::ignore(const Json& error,
                             const std::string& reason) {
    ignored_[ignore_key(error)] = reason;
}

void TopologyChecker::restore(const Json& error) {
    ignored_.erase(ignore_key(error));
}

bool TopologyChecker::is_ignored(const Json& error) const {
    return ignored_.count(ignore_key(error)) != 0;
}

std::set<IgnoreKey> TopologyChecker::ignored_keys() const {
    std::set<IgnoreKey> out;
    for (const auto& [key, reason] : ignored_) {
        out.insert(key);
    }
    return out;
}

void TopologyChecker::add_allowed_gap(const Json& geometry) {
    allowed_gaps.push_back(geometry);
}

std::vector<Json> TopologyChecker::blocking_errors(
    const std::optional<std::vector<Json>>& errors) const {
    const std::vector<Json>& source =
        errors.has_value() ? *errors : last_errors;
    std::vector<Json> out;
    for (const Json& error : source) {
        if (!is_ignored(error)) {
            out.push_back(error);
        }
    }
    return out;
}

Json TopologyChecker::persist() const {
    Json ignored_list = Json::array();
    for (const auto& [key, reason] : ignored_) {
        ignored_list.push_back({
            {"rule", key[0]},
            {"layer_id", key[1]},
            {"feature_id", key[2]},
            {"other_feature_id", key[3]},
            {"reason", reason},
        });
    }
    return {
        {"ignored", std::move(ignored_list)},
        {"allowed_gaps", allowed_gaps},
        {"workspace",
         workspace.has_value() ? *workspace : Json(nullptr)},
    };
}

void TopologyChecker::restore_state(const Json& snapshot) {
    ignored_.clear();
    allowed_gaps.clear();
    workspace = std::nullopt;
    if (!snapshot.is_object()) {
        return;
    }
    auto ignored_it = snapshot.find("ignored");
    if (ignored_it != snapshot.end() && ignored_it->is_array()) {
        for (const Json& entry : *ignored_it) {
            if (!entry.is_object()) {
                continue;
            }
            ignored_[ignore_key(entry)] = str_field(entry, "reason");
        }
    }
    auto gaps_it = snapshot.find("allowed_gaps");
    if (gaps_it != snapshot.end() && gaps_it->is_array()) {
        for (const Json& geom : *gaps_it) {
            if (geom.is_object()) {
                allowed_gaps.push_back(geom);
            }
        }
    }
    auto workspace_it = snapshot.find("workspace");
    if (workspace_it != snapshot.end() && workspace_it->is_object()) {
        workspace = *workspace_it;
    }
}

std::vector<Json> TopologyChecker::run(
    const std::vector<std::string>& layer_ids, const Json& extra_config) {
    if (!run_fn_) {
        throw std::runtime_error(
            "no geometry-checks bridge installed on TopologyChecker");
    }
    Json config = {
        {"layer_ids", layer_ids},
        {"rules",
         {"overlap", "gap", "is_valid", "workspace_remainder", "dangle"}},
        {"precision", 8},
    };
    if (workspace.has_value()) {
        config["workspace"] = *workspace;
    }
    if (!allowed_gaps.empty()) {
        Json features = Json::array();
        for (const Json& geom : allowed_gaps) {
            features.push_back(
                {{"type", "Feature"},
                 {"geometry", geom},
                 {"properties", Json::object()}});
        }
        config["allowed_gaps"] = {{"type", "FeatureCollection"},
                                  {"features", std::move(features)}};
    }
    if (extra_config.is_object()) {
        for (const auto& [key, value] : extra_config.items()) {
            config[key] = value;
        }
    }
    const Json payload = parse_payload(run_fn_(config));
    last_errors = error_list(payload);
    auto harvested = payload.find("allowed_gaps");
    if (harvested != payload.end() && harvested->is_array() &&
        !harvested->empty()) {
        allowed_gaps.clear();
        for (const Json& geom : *harvested) {
            if (geom.is_object()) {
                allowed_gaps.push_back(geom);
            }
        }
    }
    last_run_at = utc_now_iso();
    return last_errors;
}

std::vector<Json> TopologyChecker::run_for_commit(
    const std::vector<std::string>& layer_ids) {
    run(layer_ids);
    return blocking_errors();
}

Json TopologyChecker::fix(const std::string& error_id, int method) {
    if (!fix_fn_) {
        throw std::runtime_error(
            "no geometry-fix bridge installed on TopologyChecker");
    }
    const Json payload = parse_payload(fix_fn_(error_id, method));
    if (auto it = payload.find("errors");
        it != payload.end() && it->is_array()) {
        last_errors = error_list(payload);
    }
    return payload;
}

Json TopologyChecker::fix_all(const std::vector<std::string>& error_ids,
                              int method) {
    if (!fix_all_fn_) {
        throw std::runtime_error(
            "no geometry-fix bridge installed on TopologyChecker");
    }
    const Json payload = parse_payload(fix_all_fn_(error_ids, method));
    if (auto it = payload.find("errors");
        it != payload.end() && it->is_array()) {
        last_errors = error_list(payload);
    }
    return payload;
}

}  // namespace pwb::ui_composite
