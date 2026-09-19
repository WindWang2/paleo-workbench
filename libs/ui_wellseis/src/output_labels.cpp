#include <pwb/ui_wellseis/output_labels.hpp>

#include <algorithm>
#include <cstdio>
#include <utility>
#include <vector>

#include <pwb/ui_wellseis/json_helpers.hpp>

namespace pwb::ui_wellseis {

namespace {

bool is_online_model(const Json& summary) {
    const std::string model_type = json_str(summary, "model_type", "");
    return model_type == "geoviz_online" ||
           model_type == "inference_api_online";
}

}  // namespace

std::string seismic_output_nature(const Json& result_summary) {
    std::string nature;
    if (json_bool(result_summary, "is_mock")) {
        nature = "Mock";
    } else if (!json_bool(result_summary, "final_scientific_prediction",
                          false)) {
        nature = "启发式";
    } else {
        nature = "科学预测";
    }
    if (json_bool(result_summary, "demo") ||
        json_str(result_summary, "source", "") == "synthetic/demo") {
        nature = "Demo · " + nature;
    }
    const char* replaceable =
        json_bool(result_summary, "is_replaceable") ? "可替换" : "固定";
    return nature + " · " + replaceable;
}

std::string well_log_output_nature(const Json& result_summary) {
    std::string nature;
    if (is_online_model(result_summary)) {
        nature = "线上测井预测";
    } else if (json_bool(result_summary, "is_mock")) {
        nature = "Mock";
    } else if (!json_bool(result_summary, "final_scientific_prediction",
                          false)) {
        nature = "启发式";
    } else {
        nature = "科学预测";
    }
    if (json_bool(result_summary, "demo")) {
        nature = "Demo · " + nature;
    }
    const char* replaceable =
        json_bool(result_summary, "is_replaceable") ? "可替换" : "固定";
    return nature + " · " + replaceable;
}

std::string prediction_source_label(const Json& result_summary,
                                    bool bound_las) {
    if (is_online_model(result_summary)) {
        return "认证线上推理服务";
    }
    if (json_bool(result_summary, "demo") ||
        json_str(result_summary, "source", "") == "synthetic/demo") {
        return "合成演示数据";
    }
    return bound_las ? "绑定 LAS" : "合成曲线";
}

std::string target_horizon_of(const Json& model_metadata,
                              const Json& result_summary) {
    std::string horizon = json_str(model_metadata, "target_horizon", "");
    if (horizon.empty()) {
        horizon = json_str(result_summary, "target_horizon", "");
    }
    return horizon;
}

std::string volume_shape_text(
    const std::optional<std::array<std::int64_t, 3>>& shape) {
    if (!shape.has_value()) {
        return "—";
    }
    return std::to_string((*shape)[0]) + " × " + std::to_string((*shape)[1]) +
           " × " + std::to_string((*shape)[2]);
}

std::string attribute_label_or_default(const std::string& label) {
    return label.empty() ? "振幅" : label;
}

std::size_t predicted_region_count(const Json& result_summary) {
    const Json& regions = json_array(result_summary, "predicted_regions");
    return regions.size();
}

ClassDistribution class_distribution_of(const Json& result_summary) {
    ClassDistribution out;
    const Json& remote = json_object(result_summary, "remote_summary");
    const Json& counts = json_object(remote, "classCounts");
    double total = 0.0;
    std::vector<std::pair<std::string, double>> ranked;
    for (const auto& [name, value] : counts.items()) {
        if (!value.is_number()) {
            continue;
        }
        const double count = value.get<double>();
        total += count;
        ranked.emplace_back(name, count);
    }
    if (ranked.empty()) {
        return out;  // text stays empty -> "—" display
    }
    std::sort(ranked.begin(), ranked.end(),
              [](const auto& a, const auto& b) { return a.second > b.second; });
    std::vector<std::string> head;
    for (std::size_t i = 0; i < ranked.size() && i < 2; ++i) {
        const auto& [name, count] = ranked[i];
        char buf[64];
        if (total != 0.0) {
            // Python f"{count/total:.1%}" — one decimal + '%'.
            std::snprintf(buf, sizeof(buf), "%.1f%%",
                          count / total * 100.0);
        } else {
            std::snprintf(buf, sizeof(buf), "%g", count);
        }
        head.push_back(name + " " + buf);
    }
    for (std::size_t i = 0; i < head.size(); ++i) {
        if (i != 0) {
            out.text += "、";
        }
        out.text += head[i];
    }
    for (std::size_t i = 0; i < ranked.size(); ++i) {
        if (i != 0) {
            out.tooltip += "\n";
        }
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%g", ranked[i].second);
        out.tooltip += ranked[i].first + ": " + buf;
    }
    return out;
}

std::vector<std::string> evidence_rows(const Json& evidence_contribution) {
    std::vector<std::string> rows;
    if (!evidence_contribution.is_array()) {
        return rows;
    }
    for (const auto& item : evidence_contribution) {
        const std::string name =
            item.is_object() ? json_str(item, "name", "未命名证据")
                             : "未命名证据";
        double weight = 0.0;
        if (item.is_object() && item.contains("weight") &&
            item["weight"].is_number()) {
            weight = item["weight"].get<double>();
        }
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.0f%%", weight * 100.0);
        rows.push_back(name + ": " + buf);
    }
    return rows;
}

}  // namespace pwb::ui_wellseis
