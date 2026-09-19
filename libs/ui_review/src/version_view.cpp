#include "pwb/ui_review/version_view.hpp"

#include "pwb/ui_data_core/asset_view.hpp"

#include <nlohmann/json.hpp>

#include <set>

namespace pwb::ui_review {

namespace {

// _json_text needs sort_keys=True — ordered_json preserves insertion
// order, so copy into plain nlohmann::json (sorted object keys) first.
nlohmann::json sorted_copy(const domain::Json& value) {
    if (value.is_object()) {
        nlohmann::json out = nlohmann::json::object();
        for (const auto& [k, v] : value.items()) {
            out[k] = sorted_copy(v);
        }
        return out;
    }
    if (value.is_array()) {
        nlohmann::json out = nlohmann::json::array();
        for (const auto& v : value) {
            out.push_back(sorted_copy(v));
        }
        return out;
    }
    return value;  // scalar — same type family in both json types
}

std::string str_or_missing(const std::optional<std::string>& value) {
    return (value && !value->empty()) ? *value : std::string(kMissing);
}

// DataVersion::run_id is optional<RunId>; _short_id works on the string.
std::optional<std::string>
run_id_str(const std::optional<domain::RunId>& run_id) {
    if (!run_id || run_id->empty()) {
        return std::nullopt;
    }
    return run_id->str();
}

}  // namespace

std::string stage_display(const catalog::DataVersion& version) {
    if (version.trashed) {
        return std::string(kTrashedStageDisplay);
    }
    // _STAGE_DISPLAY parity — the workbench timeline shows the enum
    // token (RAW/DERIVED/INTERMEDIATE/OUTPUT), NOT the Chinese
    // stage_label used elsewhere (e.g. lineage item labels).
    switch (version.stage) {
        case domain::DataStage::Raw: return "RAW";
        case domain::DataStage::Derived: return "DERIVED";
        case domain::DataStage::Intermediate: return "INTERMEDIATE";
        case domain::DataStage::Output: return "OUTPUT";
    }
    return std::string(domain::to_string(version.stage));
}

std::string checksum_display(const std::optional<std::string>& sha256) {
    if (!sha256 || sha256->empty()) {
        return std::string(kMissing);
    }
    return sha256->substr(0, 12);
}

std::string short_id(const std::optional<std::string>& value, int keep) {
    if (!value || value->empty()) {
        return std::string(kMissing);
    }
    if (static_cast<int>(value->size()) <= keep) {
        return *value;
    }
    return value->substr(0, std::size_t(keep));
}

std::string value_display(const domain::Json& value) {
    if (value.is_null()) {
        return std::string(kMissing);
    }
    if (value.is_string()) {
        return value.get<std::string>();
    }
    return value.dump();  // json.dumps(v, ensure_ascii=False) — compact
}

std::string json_text(const domain::Json& value) {
    return sorted_copy(value).dump(2, ' ', false);
}

std::string version_cell(const catalog::DataVersion& version,
                         const std::string& current_version_id) {
    std::string cell = "v" + std::to_string(version.version_number);
    if (!current_version_id.empty() &&
        version.id.str() == current_version_id) {
        cell += "（当前）";
    }
    return cell;
}

std::string workbench_header_text(const catalog::DataAsset& asset,
                                  const std::optional<int>& current_number) {
    const std::string current_text =
        current_number ? "v" + std::to_string(*current_number)
                       : std::string(kMissing);
    return asset.name + " · " + asset.type + " · 当前 " + current_text;
}

std::string workbench_count_text(int count) {
    return "共 " + std::to_string(count) + " 个版本";
}

VersionDetailText version_detail_text(
    const catalog::DataVersion* version, const LineageHop* hop,
    const std::optional<ResolvedPath>& resolved) {
    VersionDetailText out;
    if (version == nullptr) {
        out.title = "版本详情";
        out.parents = "父版本: —";
        out.run = "生成 Run: —";
        out.path = "记录路径: —";
        out.resolved = "解析位置: —";
        return out;
    }
    out.title = "版本详情 · v" + std::to_string(version->version_number) +
                " (" + version->id.str() + ")";
    if (hop != nullptr && !hop->parents.empty()) {
        out.parents = "父版本: ";
        bool first = true;
        for (const auto& parent : hop->parents) {
            if (!first) {
                out.parents += ", ";
            }
            first = false;
            out.parents += parent.id.str();
        }
    } else {
        out.parents = "父版本: —";
    }
    if (hop != nullptr && hop->run.has_value()) {
        const auto& run = *hop->run;
        out.run = "生成 Run: " + run.operation + " · 状态 " +
                  (run.status.empty() ? std::string(kMissing) : run.status) +
                  " · generator " +
                  (run.generator.empty() ? std::string(kMissing)
                                         : run.generator) +
                  " · " + run.created_at.substr(0, 19);
        out.run_params =
            json_text(run.parameters.is_null() ? domain::Json::object()
                                               : run.parameters);
    } else {
        out.run = "生成 Run: —";
    }
    out.path = "记录路径: " + (version->path.empty()
                                  ? std::string(kMissing)
                                  : version->path);
    if (resolved && resolved->is_file) {
        out.resolved = "解析位置: " + resolved->path;
    } else {
        out.resolved = "解析位置: 源文件缺失";
    }
    out.meta = json_text(version->metadata.is_null()
                             ? domain::Json::object()
                             : version->metadata);
    return out;
}

VersionActionGate version_action_gate(int selected_rows,
                                      bool single_trashed,
                                      bool payload_exists) {
    VersionActionGate gate;
    const bool single = selected_rows == 1;
    gate.promote = single && !single_trashed;
    gate.trash = single && !single_trashed;
    gate.restore = single && single_trashed;
    gate.compare = selected_rows == 2;
    gate.open = single && payload_exists;
    return gate;
}

std::vector<CompareRow> version_compare_rows(
    const catalog::DataVersion& newer, const catalog::DataVersion& older) {
    std::vector<CompareRow> rows;
    auto add = [&rows](std::string field, std::string left,
                       std::string right) {
        rows.push_back(
            {std::move(field), std::move(left), std::move(right),
             /*differ filled below*/ false});
        rows.back().differ = rows.back().left != rows.back().right;
    };
    add("阶段", stage_display(newer), stage_display(older));
    add("大小", ui_data_core::format_size(newer.size_bytes),
        ui_data_core::format_size(older.size_bytes));
    add("校验和", str_or_missing(newer.sha256), str_or_missing(older.sha256));
    add("格式",
        newer.format.empty() ? std::string(kMissing) : newer.format,
        older.format.empty() ? std::string(kMissing) : older.format);
    add("创建时间", newer.created_at.substr(0, 19),
        older.created_at.substr(0, 19));
    add("生成 Run", short_id(run_id_str(newer.run_id)),
        short_id(run_id_str(older.run_id)));

    // sorted(set(newer.metadata) | set(older.metadata)) — sorted union.
    std::set<std::string> keys;
    if (newer.metadata.is_object()) {
        for (const auto& [k, _] : newer.metadata.items()) {
            keys.insert(k);
        }
    }
    if (older.metadata.is_object()) {
        for (const auto& [k, _] : older.metadata.items()) {
            keys.insert(k);
        }
    }
    for (const auto& key : keys) {
        const domain::Json null_json;
        const domain::Json& lv =
            (newer.metadata.is_object() && newer.metadata.contains(key))
                ? newer.metadata.at(key)
                : null_json;
        const domain::Json& rv =
            (older.metadata.is_object() && older.metadata.contains(key))
                ? older.metadata.at(key)
                : null_json;
        add("元数据 · " + key, value_display(lv), value_display(rv));
    }
    return rows;
}

std::string compare_title(const catalog::DataVersion& newer,
                          const catalog::DataVersion& older) {
    return "对比元数据: v" + std::to_string(newer.version_number) + " ↔ v" +
           std::to_string(older.version_number);
}

}  // namespace pwb::ui_review
