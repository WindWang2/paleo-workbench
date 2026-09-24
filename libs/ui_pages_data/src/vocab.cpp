#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data {

std::string_view status_text(std::string_view status) {
    // tokens.STATUS_TEXT — unknown keys pass through (dict.get default).
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"complete", "已完成"}, {"stale", "需更新"},  {"running", "处理中"},
        {"pending", "待开始"},  {"warning", "警告"},  {"failed", "异常"},
        {"ready", "就绪"},      {"skipped", "已跳过"}, {"mock", "Mock"},
    };
    for (const auto& [k, v] : kMap) {
        if (k == status) return v;
    }
    return status;
}

std::string_view resource_label(std::string_view type) {
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"well_log", "测井数据"},
        {"seismic", "地震数据"},
        {"horizon", "层位数据"},
    };
    for (const auto& [k, v] : kMap) {
        if (k == type) return v;
    }
    return type;
}

std::string_view resource_type_label(std::string_view type) {
    // asset_table_model.RESOURCE_TYPE_LABELS — tokens.RESOURCE_LABELS plus
    // the table extras; unknown keys pass through (dict.get default).
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"well_log", "测井数据"},
        {"seismic", "地震数据"},
        {"horizon", "层位"},
        {"spreadsheet", "表格"},
        {"tabular", "表格"},
        {"time_depth", "时深"},
        {"well_stratification", "井分层"},
        {"document", "文档"},
        {"image_reference", "影像"},
        {"reference_map", "参考图"},
        {"well_reference", "测井参考"},
        {"geojson", "GeoJSON矢量"},
        {"vector", "矢量"},
        {"unknown", "未知"},
    };
    for (const auto& [k, v] : kMap) {
        if (k == type) return v;
    }
    return type;
}

std::string_view resource_unit(std::string_view type) {
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"well_log", "井"},
        {"seismic", "条测线"},
        {"horizon", "层位"},
    };
    for (const auto& [k, v] : kMap) {
        if (k == type) return v;
    }
    return "";
}

std::string_view qc_result_label(std::string_view severity) {
    // tokens.QC_RESULT_LABELS.
    if (severity == "pass") return "✓通过";
    if (severity == "warning") return "!警告";
    if (severity == "error") return "!待处理";
    return severity;
}

std::string_view stage_label(std::string_view stage_value) {
    // data_view_models.STAGE_LABELS — unknown values pass through like
    // Python's STAGE_LABELS.get(stage, str(stage.value)).
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"raw", "原始输入"},
        {"derived", "派生数据"},
        {"intermediate", "中间结果"},
        {"output", "输出成果"},
    };
    for (const auto& [k, v] : kMap) {
        if (k == stage_value) return v;
    }
    return stage_value;
}

bool is_auxiliary_type(std::string_view type) {
    // filter_index.AUXILIARY_TYPES.
    return type == "document" || type == "image_reference" ||
           type == "reference_map" || type == "tabular";
}

const std::vector<std::pair<std::string, std::optional<std::string>>>&
categories() {
    // filter_index.CATEGORIES — dict order is declaration order.
    static const std::vector<std::pair<std::string, std::optional<std::string>>>
        kCategories = {
            {"全部", std::nullopt},
            {"测井", "well_log"},
            {"地震", "seismic"},
            {"层位", "horizon"},
            {"井分层", "well_stratification"},
            {"时深", "time_depth"},
            {"表格", "tabular"},
            {"文档", "document"},
            {"影像", "image_reference"},
            {"参考图", "reference_map"},
            {"测井参考", "well_reference"},
            {"GeoJSON矢量", "geojson"},
            {"矢量", "vector"},
            {"未知", "unknown"},
        };
    return kCategories;
}

const std::vector<std::pair<std::string, std::string>>& type_leaves() {
    // navigation_tree.TYPE_LEAVES.
    static const std::vector<std::pair<std::string, std::string>> kLeaves = {
        {"测井", "well_log"},         {"地震", "seismic"},
        {"层位", "horizon"},          {"井分层", "well_stratification"},
        {"时深", "time_depth"},       {"表格", "tabular"},
        {"文档", "document"},         {"影像", "image_reference"},
        {"参考图", "reference_map"},  {"测井参考", "well_reference"},
        {"GeoJSON矢量", "geojson"},   {"矢量", "vector"},
        {"未知", "unknown"},
    };
    return kLeaves;
}

const std::vector<std::pair<std::string, std::string>>& stage_leaves() {
    // navigation_tree.STAGE_LEAVES (label includes the icon prefix).
    static const std::vector<std::pair<std::string, std::string>> kLeaves = {
        {"▣ 原始输入", "raw"},
        {"◈ 派生数据", "derived"},
        {"⚡ 中间结果", "intermediate"},
        {"★ 输出成果", "output"},
    };
    return kLeaves;
}

const std::vector<std::pair<std::string, std::string>>& integrity_leaves() {
    // navigation_tree.INTEGRITY_LEAVES (IntegrityState values are UPPERCASE).
    static const std::vector<std::pair<std::string, std::string>> kLeaves = {
        {"✅ 已校验", "VERIFIED"},
        {"⚠️ 已修改", "MODIFIED"},
        {"❌ 缺失", "MISSING"},
        {"§ 外部链接", "UNMANAGED"},
    };
    return kLeaves;
}

std::string_view review_status_label(std::string_view value) {
    // navigation_tree.REVIEW_STATUS_LABELS.
    static constexpr std::pair<std::string_view, std::string_view> kMap[] = {
        {"draft", "草稿"},
        {"pending_review", "待审核"},
        {"approved", "已通过"},
        {"rejected", "已驳回"},
    };
    for (const auto& [k, v] : kMap) {
        if (k == value) return v;
    }
    return value;
}

const std::vector<ColumnDef>& column_definitions() {
    // 稿式列序：名称|类型|关联对象|层位|版本|状态|修改时间|大小 在前
    // （默认可见 8 列），其余列经「列设置」可加回。
    static const std::vector<ColumnDef> kDefs = {
        {"name", "名称", true},       {"type", "类型"},
        {"linked", "关联对象"},        {"horizon", "层位"},
        {"version", "版本"},           {"status", "状态"},
        {"modified", "修改时间"},      {"size", "大小"},
        {"stage", "生命周期"},          {"lineage", "血缘"},
        {"tags", "标签"},             {"managed", "管理方式"},
        {"integrity", "完整性"},       {"format", "格式"},
        {"role", "角色"},             {"review_status", "审核状态"},
        {"source", "来源"},           {"path", "路径"},
    };
    return kDefs;
}

const std::vector<std::string>& default_column_keys() {
    // 稿 ws0 数据列表的默认 8 列。
    static const std::vector<std::string> kDefaults = {
        "name", "type", "linked", "horizon",
        "version", "status", "modified", "size",
    };
    return kDefaults;
}

}  // namespace pwb::ui_pages_data
