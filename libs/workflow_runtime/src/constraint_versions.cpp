// constraint_versions.cpp — C++ port of
// paleo_workbench/workflow/constraint_versions.py (CONV-26). See
// include/pwb/workflow_runtime/constraint_versions.hpp.

#include <pwb/workflow_runtime/constraint_versions.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/factor_host/canonical_json.hpp>

#include "python_compat.hpp"

#include <algorithm>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>

namespace pwb::workflow_runtime {

namespace {

using pwb::factor_host::canonical_encode;

Json to_json(const std::optional<std::string>& value) {
    return value ? Json(*value) : Json(nullptr);
}

// _canonical_line — the identity-bearing projection of one constraint line.
// Line ids/name/role etc. coerce through str(); coordinates round to 9
// decimals (Python round()); sync-back stamps ride via properties.
Json canonical_line(const Json& line) {
    Json payload = Json::object();
    payload["line_id"] =
        pycompat::str_scalar(pycompat::dict_get(line, "id", Json("")));
    payload["name"] =
        pycompat::str_scalar(pycompat::dict_get(line, "name", Json("")));
    payload["role"] =
        pycompat::str_scalar(pycompat::dict_get(line, "role", Json("")));
    payload["active"] = pycompat::truthy(pycompat::dict_get(line, "active",
                                                            Json(true)));
    payload["target_horizon"] = pycompat::str_scalar(
        pycompat::dict_get(line, "target_horizon", Json("")));

    Json coordinates = Json::array();
    for (const auto& point :
         pycompat::dict_get(line, "coordinates", Json::array())) {
        if (!point.is_array() || point.size() < 2) continue;
        Json pair = Json::array();
        pair.push_back(pycompat::round9(point.at(0).get<double>()));
        pair.push_back(pycompat::round9(point.at(1).get<double>()));
        coordinates.push_back(std::move(pair));
    }
    payload["coordinates"] = std::move(coordinates);

    for (const char* key : {"azimuth_deg", "semi_major", "semi_minor"}) {
        const Json value = pycompat::dict_get(line, key, Json(nullptr));
        if (!value.is_null()) {
            payload[key] = value.get<double>();
        }
    }
    // Scientific identity carried by the sync-back stamps; free-form UI
    // properties stay out of identity.
    const Json properties =
        pycompat::dict_get(line, "properties", Json::object());
    if (properties.is_object()) {
        for (const char* key :
             {"constraint_kind", "content_fingerprint", "layer_id"}) {
            if (properties.contains(key)) {
                payload[key] = pycompat::str_scalar(properties.at(key));
            }
        }
    }
    return payload;
}

// _canonical_group_payload — lines sorted by line_id.
Json canonical_group_payload(const Json& group) {
    std::vector<Json> lines;
    for (const auto& line :
         pycompat::dict_get(group, "lines", Json::array())) {
        lines.push_back(canonical_line(line));
    }
    std::sort(lines.begin(), lines.end(),
              [](const Json& a, const Json& b) {
                  return a.at("line_id").get_ref<const std::string&>() <
                         b.at("line_id").get_ref<const std::string&>();
              });
    Json lines_arr = Json::array();
    for (auto& line : lines) lines_arr.push_back(std::move(line));

    Json payload = Json::object();
    payload["group_id"] =
        pycompat::str_scalar(pycompat::dict_get(group, "id", Json("")));
    payload["name"] =
        pycompat::str_scalar(pycompat::dict_get(group, "name", Json("")));
    payload["target_horizon"] = pycompat::str_scalar(
        pycompat::dict_get(group, "target_horizon", Json("")));
    const Json crs = pycompat::dict_get(group, "crs", Json(nullptr));
    payload["crs"] = crs.is_null() ? Json(nullptr) : crs;
    payload["lines"] = std::move(lines_arr);
    return payload;
}

// _payload_hash — canonical sha256 (byte-identical to Python
// json.dumps(sort_keys=True, ensure_ascii=False, separators=(",",":"))).
std::string payload_hash(const Json& payload) {
    return pwb::domain::Sha256::of_bytes(canonical_encode(payload));
}

// _asset_for_group — one asset per constraint group (lazy-safe listing).
std::optional<AssetRecord> asset_for_group(CatalogRepository& repository,
                                           const std::string& group_id) {
    for (const AssetRecord& asset : repository.list_assets()) {
        if (asset.type != CONSTRAINT_ASSET_TYPE) continue;
        if (pycompat::dict_get(asset.metadata, "constraint_group_id",
                               Json(""))
                .get_ref<const std::string&>() == group_id) {
            return asset;
        }
    }
    return std::nullopt;
}

// _latest_version — per-asset listing (version-sorted, last = latest).
std::optional<VersionRecord> latest_version(CatalogRepository& repository,
                                            const std::string& asset_id) {
    const auto versions = repository.list_versions(asset_id);
    if (versions.empty()) return std::nullopt;
    return versions.back();
}

// Latest committed version of a group whose content hash matches
// (content-addressed late binding).
std::optional<VersionRecord> version_by_content_hash(
    CatalogRepository& repository, const std::string& group_id,
    const std::string& content_hash) {
    const auto asset = asset_for_group(repository, group_id);
    if (!asset) return std::nullopt;
    std::optional<VersionRecord> match;
    for (const VersionRecord& v : repository.list_versions(asset->id)) {
        if (pycompat::dict_get(v.metadata, "content_hash", Json(""))
                .get_ref<const std::string&>() == content_hash) {
            match = v;
        }
    }
    return match;  // list_versions is sorted — last match wins
}

}  // namespace

Json ConstraintCommitReport::to_dict() const {
    Json out = Json::object();
    out["group_id"] = group_id;
    out["group_name"] = group_name;
    out["committed"] = committed;
    out["reason"] = reason;
    out["asset_id"] = to_json(asset_id);
    out["version_id"] = to_json(version_id);
    out["previous_version_id"] = to_json(previous_version_id);
    out["run_id"] = to_json(run_id);
    out["content_hash"] = to_json(content_hash);
    out["line_count"] = line_count;
    return out;
}

std::pair<std::string, int> constraint_group_content_hash(const Json& group) {
    const Json payload = canonical_group_payload(group);
    // ID-FREE and ORDER-FREE identity: strip line_id/group_id, keep only
    // active lines with real coordinates, sort by canonical serialization.
    std::vector<Json> content_lines;
    for (const Json& line : payload.at("lines")) {
        if (!line.at("active").get<bool>()) continue;
        const Json& coords = line.at("coordinates");
        if (coords.empty() || coords.size() < 2) continue;
        Json stripped = Json::object();
        for (auto it = line.begin(); it != line.end(); ++it) {
            if (it.key() == "line_id") continue;
            stripped[it.key()] = it.value();
        }
        content_lines.push_back(std::move(stripped));
    }
    std::sort(content_lines.begin(), content_lines.end(),
              [](const Json& a, const Json& b) {
                  return canonical_encode(a) < canonical_encode(b);
              });
    Json content = Json::object();
    for (auto it = payload.begin(); it != payload.end(); ++it) {
        if (it.key() == "group_id") continue;
        content[it.key()] = it.value();
    }
    Json lines_arr = Json::array();
    for (auto& line : content_lines) lines_arr.push_back(std::move(line));
    content["lines"] = std::move(lines_arr);
    return {payload_hash(content), static_cast<int>(lines_arr.size())};
}

ConstraintCommitReport commit_constraint_group(CatalogRepository& repository,
                                               const Json& group,
                                               const std::string& actor,
                                               const std::string& notes) {
    const auto [content_hash, n_lines] =
        constraint_group_content_hash(group);
    const std::string group_id =
        pycompat::str_scalar(pycompat::dict_get(group, "id", Json("")));
    const std::string group_name =
        pycompat::str_scalar(pycompat::dict_get(group, "name", Json("")));
    if (n_lines == 0) {
        ConstraintCommitReport report;
        report.group_id = group_id;
        report.group_name = group_name;
        report.committed = false;
        report.reason = "no_content";
        report.line_count = 0;
        return report;
    }

    const auto asset = asset_for_group(repository, group_id);
    std::optional<VersionRecord> previous;
    if (asset) {
        previous = latest_version(repository, asset->id);
    }
    // Content-unchanged commits are no-ops returning the matching version.
    if (previous) {
        if (pycompat::dict_get(previous->metadata, "content_hash", Json(""))
                .get_ref<const std::string&>() == content_hash) {
            ConstraintCommitReport report;
            report.group_id = group_id;
            report.group_name = group_name;
            report.committed = false;
            report.reason = "unchanged";
            report.asset_id = asset->id;
            report.version_id = previous->version_id;
            report.previous_version_id = previous->version_id;
            report.content_hash = content_hash;
            report.line_count = n_lines;
            return report;
        }
    }

    const Json payload = canonical_group_payload(group);
    const std::string payload_json = payload.dump();
    Json version_metadata = Json::object();
    version_metadata["constraint_group_id"] = group_id;
    version_metadata["content_hash"] = content_hash;
    version_metadata["line_count"] = n_lines;
    version_metadata["actor"] = actor;
    version_metadata["notes"] = notes;

    Json parameters = Json::object();
    parameters["constraint_group_id"] = group_id;
    parameters["content_hash"] = content_hash;
    parameters["n_lines"] = n_lines;
    parameters["actor"] = actor;
    parameters["notes"] = notes;

    const std::string run_id = repository.register_run(
        CONSTRAINT_COMMIT_OPERATION,
        previous ? std::vector<std::string>{previous->version_id}
                 : std::vector<std::string>{},
        parameters, std::string("constraint-lifecycle-v1"), "running");

    std::optional<RegisteredAssetVersion> registered;
    try {
        if (!asset) {
            // First commit: asset + version + run linkage in one atomic op.
            Json asset_metadata = Json::object();
            asset_metadata["constraint_group_id"] = group_id;
            asset_metadata["group_name"] = group_name;
            asset_metadata["target_horizon"] = pycompat::str_scalar(
                pycompat::dict_get(group, "target_horizon", Json("")));
            registered = repository.register_result_asset(
                "constraints:" + (group_name.empty() ? group_id
                                                     : group_name),
                CONSTRAINT_ASSET_TYPE, "json", asset_metadata, payload_json,
                "DERIVED", run_id, version_metadata);
        } else {
            const std::string version_id = repository.register_version(
                asset->id, payload_json, "DERIVED",
                previous ? std::vector<std::string>{previous->version_id}
                         : std::vector<std::string>{},
                run_id, version_metadata);
            registered = RegisteredAssetVersion{asset->id, version_id};
        }
    } catch (...) {
        // The Python path marks the run failed before re-raising; the
        // repository seam is expected not to leave partial state (atomic),
        // but the run status is still poisoned honestly.
        try {
            repository.update_run_status(run_id, "failed");
        } catch (...) {
        }
        throw;
    }
    repository.update_run_status(run_id, "complete");

    ConstraintCommitReport report;
    report.group_id = group_id;
    report.group_name = group_name;
    report.committed = true;
    report.reason = "changed";
    report.asset_id = registered->asset_id;
    report.version_id = registered->version_id;
    report.previous_version_id =
        previous ? std::optional<std::string>(previous->version_id)
                 : std::nullopt;
    report.run_id = run_id;
    report.content_hash = content_hash;
    report.line_count = n_lines;
    return report;
}

std::vector<ConstraintCommitReport> commit_all_constraints(
    CatalogRepository& repository, const Json& project,
    const std::string& actor, const std::string& notes) {
    std::vector<ConstraintCommitReport> reports;
    for (const auto& group :
         pycompat::dict_get(project, "constraint_layers", Json::array())) {
        reports.push_back(
            commit_constraint_group(repository, group, actor, notes));
    }
    return reports;
}

std::optional<VersionRecord> current_constraint_version(
    CatalogRepository& repository, const std::string& group_id) {
    const auto asset = asset_for_group(repository, group_id);
    if (!asset) return std::nullopt;
    return latest_version(repository, asset->id);
}

Json constraint_pins_for_task(const Json& task, const Json& project,
                              CatalogRepository* repository) {
    const std::string horizon = pycompat::str_scalar(
        pycompat::dict_get(task, "target_horizon", Json("")));
    Json pins = Json::array();
    for (const auto& group :
         pycompat::dict_get(project, "constraint_layers", Json::array())) {
        const std::string group_horizon = pycompat::str_scalar(
            pycompat::dict_get(group, "target_horizon", Json("")));
        if (!horizon.empty() && !group_horizon.empty() &&
            group_horizon != horizon) {
            continue;
        }
        const auto [hash, n_lines] = constraint_group_content_hash(group);
        if (n_lines == 0) continue;
        // None keeps the pin honest: content known, version binding absent
        // → UNKNOWN (never fabricated).
        std::optional<std::string> version_id;
        if (repository != nullptr) {
            const auto version =
                current_constraint_version(*repository,
                                           pycompat::str_scalar(
                                               pycompat::dict_get(
                                                   group, "id", Json(""))));
            if (version) {
                if (pycompat::dict_get(version->metadata, "content_hash",
                                       Json(""))
                        .get_ref<const std::string&>() == hash) {
                    version_id = version->version_id;
                }
            }
        }
        Json pin = Json::object();
        pin["group_id"] = pycompat::str_scalar(
            pycompat::dict_get(group, "id", Json("")));
        pin["group_name"] = pycompat::str_scalar(
            pycompat::dict_get(group, "name", Json("")));
        pin["content_hash"] = hash;
        pin["line_count"] = n_lines;
        pin["version_id"] = to_json(version_id);
        pins.push_back(std::move(pin));
    }
    return pins;
}

std::vector<Json> pinned_constraint_pins(const Json& task) {
    const Json params = pycompat::dict_get(task, "parameters", Json::object());
    const Json pins = pycompat::dict_get(params, "constraint_pins",
                                         Json(nullptr));
    std::vector<Json> out;
    if (!pins.is_array()) return out;
    for (const auto& pin : pins) {
        if (pin.is_object()) out.push_back(pin);
    }
    return out;
}

Json constraint_pins_staleness(const Json& task, const Json& project,
                               CatalogRepository* repository) {
    const std::vector<Json> pins = pinned_constraint_pins(task);
    std::unordered_map<std::string, Json> pin_by_group;
    for (const Json& pin : pins) {
        pin_by_group[pycompat::str_scalar(
            pycompat::dict_get(pin, "group_id", Json("")))] = pin;
    }
    const std::string task_horizon = pycompat::str_scalar(
        pycompat::dict_get(task, "target_horizon", Json("")));
    // Same dependency scoping as the pin itself: a group bound to a
    // different horizon can never make this task stale.
    std::vector<std::pair<std::string, Json>> groups;
    for (const auto& group :
         pycompat::dict_get(project, "constraint_layers", Json::array())) {
        const std::string group_horizon = pycompat::str_scalar(
            pycompat::dict_get(group, "target_horizon", Json("")));
        if (!task_horizon.empty() && !group_horizon.empty() &&
            group_horizon != task_horizon) {
            continue;
        }
        groups.emplace_back(
            pycompat::str_scalar(pycompat::dict_get(group, "id", Json(""))),
            group);
    }

    Json entries = Json::array();
    for (const auto& [group_id, group] : groups) {
        const auto [content_hash, n_lines] =
            constraint_group_content_hash(group);
        if (n_lines == 0) continue;
        const auto pin_it = pin_by_group.find(group_id);
        if (pin_it == pin_by_group.end()) {
            Json entry = Json::object();
            entry["group_id"] = group_id;
            entry["state"] = "unpinned";
            entry["line_count"] = n_lines;
            entries.push_back(std::move(entry));
            continue;
        }
        const Json& pin = pin_it->second;
        std::string state = "current";
        std::string detail;
        std::optional<std::string> pinned_version;
        if (repository != nullptr) {
            // Late binding: the pin's content hash addresses the committed
            // version it was computed against.
            const auto bound = version_by_content_hash(
                *repository, group_id,
                pycompat::str_scalar(
                    pycompat::dict_get(pin, "content_hash", Json(""))));
            pinned_version =
                bound ? std::optional<std::string>(bound->version_id)
                      : std::nullopt;
        }
        const std::string pin_hash = pycompat::str_scalar(
            pycompat::dict_get(pin, "content_hash", Json("")));
        if (pin_hash != content_hash) {
            state = "stale_content";
            detail =
                "constraint content changed (geometry, role or naming) "
                "after this task was computed";
        } else if (repository != nullptr) {
            if (!pinned_version) {
                state = "unknown";
                detail =
                    "pin content was never committed — no version baseline "
                    "exists (commit the constraints to make this decidable)";
            } else {
                const auto latest =
                    current_constraint_version(*repository, group_id);
                if (latest && latest->version_id != *pinned_version) {
                    state = "stale_version";
                    detail = "pinned " + pycompat::head12(*pinned_version) +
                             "… is not the latest commit " +
                             pycompat::head12(latest->version_id) + "…";
                }
            }
        } else {
            state = pycompat::dict_get(pin, "version_id", Json(nullptr))
                            .is_null()
                        ? "unknown"
                        : "current";
        }
        Json entry = Json::object();
        entry["group_id"] = group_id;
        entry["state"] = state;
        entry["detail"] = detail;
        const Json pin_version =
            pycompat::dict_get(pin, "version_id", Json(nullptr));
        entry["pinned_version_id"] =
            pinned_version ? to_json(pinned_version) : pin_version;
        entry["line_count"] = n_lines;
        entries.push_back(std::move(entry));
    }
    // Groups that vanished since the pin (pins order — Python dict
    // insertion order).
    for (const Json& pin : pins) {
        const std::string group_id = pycompat::str_scalar(
            pycompat::dict_get(pin, "group_id", Json("")));
        const auto known = std::find_if(
            groups.begin(), groups.end(),
            [&group_id](const auto& kv) { return kv.first == group_id; });
        if (known == groups.end()) {
            Json entry = Json::object();
            entry["group_id"] = group_id;
            entry["state"] = "missing";
            entry["detail"] = "pinned constraint group no longer exists";
            entry["pinned_version_id"] =
                pycompat::dict_get(pin, "version_id", Json(nullptr));
            entries.push_back(std::move(entry));
        }
    }

    // Aggregate verdict never fabricates: worst state by rank.
    static const std::map<std::string, int> rank = {
        {"current", 0}, {"unpinned", 1},  {"unknown", 2}, {"missing", 3},
        {"stale_version", 4}, {"stale_content", 5},
    };
    std::string worst = "current";
    for (const auto& entry : entries) {
        const std::string state =
            entry.at("state").get_ref<const std::string&>();
        const int state_rank = rank.count(state) ? rank.at(state) : 2;
        const int worst_rank =
            rank.count(worst) ? rank.at(worst) : 0;
        if (state_rank > worst_rank) worst = state;
    }
    Json out = Json::object();
    out["state"] = worst;
    out["groups"] = std::move(entries);
    return out;
}

Json compare_constraint_versions(CatalogRepository& repository,
                                 const std::string& version_a,
                                 const std::string& version_b) {
    auto load = [&repository](const std::string& version_id) -> Json {
        const auto version = repository.resolve_version(version_id);
        if (!version) {
            throw std::invalid_argument(
                "constraint version '" + version_id +
                "' has no payload location");
        }
        Json payload;
        try {
            payload = Json::parse(version->payload_json);
        } catch (const std::exception&) {
            throw std::invalid_argument(
                "constraint version '" + version_id +
                "' payload is not valid JSON");
        }
        return payload;
    };

    const Json a = load(version_a);
    const Json b = load(version_b);

    auto index_lines = [](const Json& payload) {
        std::map<std::string, Json> indexed;
        if (payload.is_object() && payload.contains("lines") &&
            payload.at("lines").is_array()) {
            for (const auto& line : payload.at("lines")) {
                indexed[line.at("line_id").get_ref<const std::string&>()] =
                    line;
            }
        }
        return indexed;
    };
    const auto ia = index_lines(a);
    const auto ib = index_lines(b);

    std::vector<std::string> added;
    for (const auto& [id, line] : ib) {
        (void)line;
        if (ia.count(id) == 0) added.push_back(id);
    }
    std::sort(added.begin(), added.end());
    std::vector<std::string> removed;
    for (const auto& [id, line] : ia) {
        (void)line;
        if (ib.count(id) == 0) removed.push_back(id);
    }
    std::sort(removed.begin(), removed.end());

    Json changed = Json::array();
    int unchanged = 0;
    std::vector<std::string> common;
    for (const auto& [id, line] : ia) {
        (void)line;
        if (ib.count(id) != 0) common.push_back(id);
    }
    std::sort(common.begin(), common.end());
    for (const std::string& line_id : common) {
        if (ia.at(line_id) == ib.at(line_id)) {
            ++unchanged;
            continue;
        }
        Json changes = Json::array();
        for (const char* key :
             {"coordinates", "role", "active", "azimuth_deg", "semi_major",
              "semi_minor", "content_fingerprint"}) {
            const Json a_val = ia.at(line_id).contains(key)
                                   ? ia.at(line_id).at(key)
                                   : Json(nullptr);
            const Json b_val = ib.at(line_id).contains(key)
                                   ? ib.at(line_id).at(key)
                                   : Json(nullptr);
            if (a_val != b_val) changes.push_back(key);
        }
        Json entry = Json::object();
        entry["line_id"] = line_id;
        entry["changes"] = std::move(changes);
        changed.push_back(std::move(entry));
    }

    const std::string hash_a = payload_hash(a);
    const std::string hash_b = payload_hash(b);
    Json added_arr = Json::array();
    for (const auto& id : added) added_arr.push_back(id);
    Json removed_arr = Json::array();
    for (const auto& id : removed) removed_arr.push_back(id);

    Json out = Json::object();
    out["version_a"] = version_a;
    out["version_b"] = version_b;
    out["group_id_a"] =
        a.is_object() && a.contains("group_id") ? a.at("group_id")
                                                : Json(nullptr);
    out["group_id_b"] =
        b.is_object() && b.contains("group_id") ? b.at("group_id")
                                                : Json(nullptr);
    const std::string gid_a =
        out["group_id_a"].is_string()
            ? out["group_id_a"].get<std::string>()
            : "";
    const std::string gid_b =
        out["group_id_b"].is_string()
            ? out["group_id_b"].get<std::string>()
            : "";
    out["same_group"] = gid_a == gid_b;
    out["content_hash_a"] = hash_a;
    out["content_hash_b"] = hash_b;
    out["lines_added"] = std::move(added_arr);
    out["lines_removed"] = std::move(removed_arr);
    out["lines_changed"] = std::move(changed);
    out["lines_unchanged"] = unchanged;
    out["identical"] = hash_a == hash_b;
    return out;
}

Json resolve_constraint_ref(const Json& project,
                            CatalogRepository* repository,
                            const std::string& ref) {
    if (ref == "constraints:current") {
        std::optional<std::string> worst;
        std::vector<std::string> details;
        for (const auto& group :
             pycompat::dict_get(project, "constraint_layers",
                                Json::array())) {
            const auto [content_hash, n_lines] =
                constraint_group_content_hash(group);
            if (n_lines == 0) continue;
            const std::string display =
                pycompat::str_scalar(pycompat::dict_get(group, "name",
                                                        Json("")));
            const std::string gid = pycompat::str_scalar(
                pycompat::dict_get(group, "id", Json("")));
            const std::string shown =
                !display.empty() ? display : gid;
            if (repository == nullptr) {
                if (!worst) worst = "unknown";
                details.push_back(shown + ": no catalog — cannot compare");
                continue;
            }
            const auto latest = current_constraint_version(
                *repository,
                pycompat::str_scalar(pycompat::dict_get(group, "id",
                                                        Json(""))));
            if (!latest) {
                if (!worst) worst = "unknown";
                details.push_back(shown +
                                  ": never committed — no baseline");
                continue;
            }
            if (pycompat::dict_get(latest->metadata, "content_hash",
                                   Json(""))
                    .get_ref<const std::string&>() == content_hash) {
                details.push_back(shown + ": matches latest commit");
            } else {
                worst = "stale";
                details.push_back(
                    shown + ": document content differs from latest commit " +
                    pycompat::head12(latest->version_id) + "…");
            }
        }
        std::string joined;
        for (std::size_t i = 0; i < details.size(); ++i) {
            if (i != 0) joined += "; ";
            joined += details[i];
        }
        const std::string status =
            (!worst && !details.empty()) ? "current" : worst.value_or("unknown");
        Json out = Json::object();
        out["status"] = status;
        out["detail"] = joined.empty() ? "no constraints" : joined;
        return out;
    }

    if (ref.rfind("constraints:", 0) == 0) {
        const std::string rest = ref.substr(12);
        const auto first = rest.find(':');
        const std::string group_id =
            first == std::string::npos ? rest : rest.substr(0, first);
        const std::string version_id =
            first == std::string::npos ? "" : rest.substr(first + 1);
        if (version_id.empty() || repository == nullptr) {
            Json out = Json::object();
            out["status"] = "unknown";
            out["detail"] = "pinned constraint ref without version or catalog";
            return out;
        }
        const auto latest =
            current_constraint_version(*repository, group_id);
        if (!latest) {
            Json out = Json::object();
            out["status"] = "unknown";
            out["detail"] = "constraint group '" + group_id +
                            "' has no commits";
            return out;
        }
        if (latest->version_id == version_id) {
            Json out = Json::object();
            out["status"] = "current";
            out["detail"] = "pinned commit is latest";
            return out;
        }
        Json out = Json::object();
        out["status"] = "superseded";
        out["detail"] = "constraint group has a newer commit " +
                        pycompat::head12(latest->version_id) + "… (pinned " +
                        pycompat::head12(version_id) + "…)";
        return out;
    }

    Json out = Json::object();
    out["status"] = "unknown";
    out["detail"] = "unrecognized ref '" + ref + "'";
    return out;
}

}  // namespace pwb::workflow_runtime
