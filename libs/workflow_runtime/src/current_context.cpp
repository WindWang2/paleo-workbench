// current_context.cpp — see include/pwb/workflow_runtime/current_context.hpp.

#include <pwb/workflow_runtime/current_context.hpp>

namespace pwb::workflow_runtime {

namespace {
const char* const kDefaultDisplayOnlyKeys[] = {
    "colormap", "color_map", "line_width",  "linewidth", "viewport",
    "visibility", "opacity", "color",       "display",   "style",
    "zoom",      "pan",
};
}  // namespace

CurrentProjectVersionContext::CurrentProjectVersionContext() {
    for (const char* key : kDefaultDisplayOnlyKeys) {
        display_only_keys_.insert(key);
    }
}

void CurrentProjectVersionContext::discard_selected(const std::string& vid) {
    const auto it = selected_set_.find(vid);
    if (it == selected_set_.end()) return;
    selected_set_.erase(it);
    for (auto sit = selected_order_.begin(); sit != selected_order_.end();
         ++sit) {
        if (*sit == vid) {
            selected_order_.erase(sit);
            break;
        }
    }
}

void CurrentProjectVersionContext::select(const std::string& asset_id,
                                          const std::string& version_id,
                                          const std::string& label) {
    if (asset_id.empty() || version_id.empty()) return;
    const auto it = current_by_asset_.find(asset_id);
    if (it != current_by_asset_.end() && it->second != version_id) {
        discard_selected(it->second);
    }
    current_by_asset_[asset_id] = version_id;
    if (selected_set_.insert(version_id).second) {
        selected_order_.push_back(version_id);
    }
    if (!label.empty()) {
        labels_[version_id] = label;
    }
}

void CurrentProjectVersionContext::mark_domain_product_current(
    const std::string& domain_task_id, const std::string& version_id) {
    if (domain_task_id.empty() || version_id.empty()) return;
    const auto it = current_by_domain_task_.find(domain_task_id);
    if (it != current_by_domain_task_.end() && it->second != version_id) {
        discard_selected(it->second);
    }
    current_by_domain_task_[domain_task_id] = version_id;
    if (selected_set_.insert(version_id).second) {
        selected_order_.push_back(version_id);
    }
}

std::optional<std::string> CurrentProjectVersionContext::current_for_asset(
    const std::optional<std::string>& asset_id) const {
    if (!asset_id || asset_id->empty()) return std::nullopt;
    const auto it = current_by_asset_.find(*asset_id);
    if (it == current_by_asset_.end()) return std::nullopt;
    return it->second;
}

bool CurrentProjectVersionContext::is_current_version(
    const std::string& version_id) const {
    return selected_set_.count(version_id) != 0;
}

void CurrentProjectVersionContext::set_expected_identity(
    const std::string& key, const std::optional<std::string>& generator_version,
    const std::optional<std::string>& input_snapshot_hash,
    const Json& parameters, const Json& model_ref) {
    Json payload = Json::object();
    if (generator_version) {
        payload["generator_version"] = *generator_version;
    }
    if (input_snapshot_hash) {
        payload["input_snapshot_hash"] = *input_snapshot_hash;
    }
    if (!parameters.is_null()) {
        Json stripped = Json::object();
        for (auto it = parameters.begin(); it != parameters.end(); ++it) {
            if (display_only_keys_.count(it.key()) != 0) continue;
            if (it.key().rfind("_display", 0) == 0) continue;
            stripped[it.key()] = it.value();
        }
        payload["parameters"] = std::move(stripped);
    }
    if (!model_ref.is_null()) {
        payload["model_ref"] = model_ref;
    }
    expected_identity_[key] = std::move(payload);
}

}  // namespace pwb::workflow_runtime
