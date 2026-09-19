// UI-06 — resource_summary/completeness_card update_state.
#include <pwb/ui_pages_data/readiness.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {
namespace {

using pwb::domain::Json;

int jint_or_zero(const Json& v) {
    if (v.is_number_integer() || v.is_number_unsigned())
        return v.get<int>();
    if (v.is_number_float()) return static_cast<int>(v.get<double>());
    return 0;
}

}  // namespace

ResourceReadinessView format_resource_readiness(const Json& state) {
    ResourceReadinessView view;
    // state.get("resource_readiness", {}) — absent → empty dict semantics.
    Json readiness = Json::object();
    if (state.is_object() && state.contains("resource_readiness") &&
        state.at("resource_readiness").is_object()) {
        readiness = state.at("resource_readiness");
    }
    const Json available = readiness.value("available_counts", Json::object());
    const Json missing = readiness.value("missing_types", Json::array());
    const bool ready =
        readiness.contains("ready") && readiness.at("ready").is_boolean()
            ? readiness.at("ready").get<bool>()
            : false;

    for (const std::string_view type : kRequiredResourceTypes) {
        ReadinessRow row;
        row.type = std::string(type);
        row.name_label = std::string(resource_label(type));
        int count = 0;
        if (available.is_object() && available.contains(std::string(type))) {
            count = jint_or_zero(available.at(std::string(type)));
        }
        row.count = count;
        row.count_label =
            std::to_string(count) + std::string(resource_unit(type));
        row.ready = count > 0;
        row.status_label = row.ready ? "已就绪" : "缺失";
        view.rows.push_back(std::move(row));
    }

    view.ready = ready;
    if (ready) {
        view.status_line = "数据完整";
        view.status_token = "SUCCESS";
    } else {
        // missing_types are type ids → RESOURCE_LABELS.get(m, m).
        std::string labels;
        bool first = true;
        if (missing.is_array()) {
            for (const auto& m : missing) {
                if (!m.is_string()) continue;
                if (!first) labels += "、";
                first = false;
                labels += std::string(resource_label(m.get<std::string>()));
            }
        }
        view.status_line = "缺少: " + labels;
        view.status_token = "ERROR_RED";
    }
    return view;
}

}  // namespace pwb::ui_pages_data
