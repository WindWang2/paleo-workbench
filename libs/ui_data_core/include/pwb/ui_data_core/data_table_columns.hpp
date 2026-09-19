// data_table_columns.py port — immutable column vocabulary for the asset
// table. Order and labels are oracle-frozen.
#pragma once

#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace pwb::ui_data_core {

struct ColumnDefinition {
    std::string key;
    std::string label;
    bool required = false;
};

// COLUMN_DEFINITIONS — declaration order is the model's column order.
inline const std::vector<ColumnDefinition>& column_definitions() {
    static const std::vector<ColumnDefinition> defs = {
        {"name", "文件名", true},
        {"type", "类型", false},
        {"stage", "生命周期", false},
        {"version", "版本", false},
        {"lineage", "血缘", false},
        {"tags", "标签", false},
        {"managed", "管理方式", false},
        {"integrity", "完整性", false},
        {"format", "格式", false},
        {"status", "状态", false},
        {"role", "角色", false},
        {"review_status", "审核状态", false},
        {"size", "大小", false},
        {"modified", "修改时间", false},
        {"source", "来源", false},
        {"path", "路径", false},
    };
    return defs;
}

inline const ColumnDefinition* column_by_key(std::string_view key) {
    for (const auto& def : column_definitions()) {
        if (def.key == key) {
            return &def;
        }
    }
    return nullptr;
}

// COLUMN_TOOLTIPS
inline const std::unordered_map<std::string, std::string>& column_tooltips() {
    static const std::unordered_map<std::string, std::string> map = {
        {"name", "资源或成果文件名"},
        {"type", "数据资源类型"},
        {"stage", "生命阶段 (RAW/DERIVED/OUTPUT)"},
        {"version", "当前版本标识"},
        {"lineage", "血缘状态：可溯源至 RAW 的层级 / 断链告警"},
        {"tags", "关联标签列表"},
        {"managed", "项目受管/外部链接"},
        {"integrity", "校验和与存在完整性"},
        {"format", "文件解析格式"},
        {"status", "当前处理状态"},
        {"role", "输入/成果角色"},
        {"review_status", "治理审核状态（草稿/待审核/已通过/已驳回）"},
        {"size", "文件大小"},
        {"modified", "修改或生成时间"},
        {"source", "数据来源说明"},
        {"path", "文件完整路径"},
    };
    return map;
}

inline std::string column_tooltip(std::string_view key) {
    const auto& map = column_tooltips();
    const auto it = map.find(std::string(key));
    if (it != map.end()) {
        return it->second;
    }
    const ColumnDefinition* def = column_by_key(key);
    return def ? def->label : std::string();
}

// DEFAULT_COLUMN_KEYS
inline const std::vector<std::string>& default_column_keys() {
    static const std::vector<std::string> keys = {
        "name", "type", "stage", "version",
        "lineage", "tags", "integrity", "modified",
    };
    return keys;
}

// HEADERS
inline std::vector<std::string> column_headers() {
    std::vector<std::string> out;
    out.reserve(column_definitions().size());
    for (const auto& def : column_definitions()) {
        out.push_back(def.label);
    }
    return out;
}

}  // namespace pwb::ui_data_core
