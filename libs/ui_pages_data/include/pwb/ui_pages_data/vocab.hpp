// UI-06 — shared vocabulary the data/home pages read.
//
// These constants mirror paleo_workbench/tokens.py, workflow/service.py and
// pages/{data_view_models,filter_index,data_table_columns}.py verbatim.
// They are seams: when the owning slices (UI-03 view models, UI-14 tokens)
// land, this header should be replaced by theirs — every entry is marked
// with its Python source of truth.
#pragma once

#include <array>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::ui_pages_data {

// --- data_view_models.py :: DataStage --------------------------------------
namespace stage {
inline constexpr std::string_view kRaw = "raw";
inline constexpr std::string_view kDerived = "derived";
inline constexpr std::string_view kIntermediate = "intermediate";
inline constexpr std::string_view kOutput = "output";
}  // namespace stage

// --- data_view_models.py :: IntegrityState (values are UPPERCASE) ----------
namespace integrity_state {
inline constexpr std::string_view kVerified = "VERIFIED";
inline constexpr std::string_view kModified = "MODIFIED";
inline constexpr std::string_view kMissing = "MISSING";
inline constexpr std::string_view kUnmanaged = "UNMANAGED";
}  // namespace integrity_state

// --- workflow/service.py :: REQUIRED_RESOURCE_TYPES ------------------------
inline constexpr std::array<std::string_view, 3> kRequiredResourceTypes = {
    "well_log", "seismic", "horizon"};

// --- workflow/service.py :: STEP_ORDER --------------------------------------
inline constexpr std::array<std::string_view, 6> kStepOrder = {
    "data_check", "factor_map", "prediction", "map_compile", "qc", "export"};

// --- tokens.py :: STEP_LABELS (parallel to kStepOrder) ----------------------
inline constexpr std::array<std::string_view, 6> kStepLabels = {
    "数据管理", "数据转换", "制图数据制备",
    "沉积相预测", "古地理图编制", "质控与导出"};

// --- tokens.py :: STATUS_TEXT ------------------------------------------------
// Unknown status passes through verbatim (Python ``.get(status, status)``).
std::string_view status_text(std::string_view status);

// --- tokens.py :: RESOURCE_LABELS / RESOURCE_UNITS ---------------------------
// Unknown type passes through verbatim (Python ``.get(t, t)`` for labels).
std::string_view resource_label(std::string_view type);
std::string_view resource_unit(std::string_view type);  // "" when unknown

// --- asset_table_model.py :: RESOURCE_TYPE_LABELS ---------------------------
// RESOURCE_LABELS plus the table-model extras; unknown passes through.
std::string_view resource_type_label(std::string_view type);

// --- data_view_models.py :: STAGE_LABELS -------------------------------------
// stage_label(DataStage) → "原始输入"/"派生数据"/"中间结果"/"输出成果";
// unknown stage values pass through verbatim.
std::string_view stage_label(std::string_view stage_value);

// --- tokens.py :: DEFAULT_QC_RULES -------------------------------------------
inline constexpr std::array<std::string_view, 6> kDefaultQcRules = {
    "层级一致性", "未分类区域", "低可信区",
    "边界碎斑异常", "图例符号完整性", "字段与输出格式完整性"};

// --- tokens.py :: QC_RESULT_LABELS / verdict colors --------------------------
std::string_view qc_result_label(std::string_view severity);  // pass/warning/error

// --- filter_index.py :: AUXILIARY_TYPES ---------------------------------------
bool is_auxiliary_type(std::string_view type);

// --- filter_index.py :: CATEGORIES (ordered label → type|none) ----------------
// "全部" maps to no type; every other label maps to a resource type string.
const std::vector<std::pair<std::string, std::optional<std::string>>>&
categories();

// --- navigation_tree.py leaf vocabularies --------------------------------------
// (label, value) pairs in declared order.
const std::vector<std::pair<std::string, std::string>>& type_leaves();
const std::vector<std::pair<std::string, std::string>>& stage_leaves();
const std::vector<std::pair<std::string, std::string>>& integrity_leaves();
std::string_view review_status_label(std::string_view value);  // else value

// --- data_table_columns.py :: COLUMN_DEFINITIONS / DEFAULT_COLUMN_KEYS ---------
struct ColumnDef {
    std::string_view key;
    std::string_view label;
    bool required = false;
};
const std::vector<ColumnDef>& column_definitions();
const std::vector<std::string>& default_column_keys();

// --- filter_chips_bar.py :: SAVED_FILTERS_KEY -----------------------------------
inline constexpr std::string_view kSavedFiltersKey =
    "data_explorer/saved_filters";
inline constexpr std::string_view kSavedFiltersPlaceholder = "已保存过滤器…";

}  // namespace pwb::ui_pages_data
