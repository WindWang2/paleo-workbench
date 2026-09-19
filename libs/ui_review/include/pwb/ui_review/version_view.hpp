#pragma once

// UI-11 — version_workbench_dialog.py Qt-free semantics: timeline cell
// text, the header/count lines, the selection-driven detail block,
// lifecycle action gating, and the two-version compare rows.
// All mutations stay in the catalog service — this header only shapes
// what the dialog shows and which buttons are enabled.

#include "pwb/ui_review/catalog_api.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_review {

// _MISSING placeholder.
inline constexpr std::string_view kMissing = "—";
// _TRASHED_STAGE_DISPLAY.
inline constexpr std::string_view kTrashedStageDisplay = "已删除";

// _stage_display: trashed → 已删除 else RAW/DERIVED/INTERMEDIATE/OUTPUT.
std::string stage_display(const catalog::DataVersion& version);
// _checksum_display: sha256[:12] or —.
std::string checksum_display(const std::optional<std::string>& sha256);
// _short_id: id if len<=keep else id[:keep]; empty → —.
std::string short_id(const std::optional<std::string>& value, int keep = 12);
// _value_display: null → —, string → verbatim, else compact json.
std::string value_display(const domain::Json& value);
// _json_text: json.dumps(indent=2, ensure_ascii=False, sort_keys=True).
std::string json_text(const domain::Json& value);

// "v{n}" + "（当前）" when id == current_version_id.
std::string version_cell(const catalog::DataVersion& version,
                         const std::string& current_version_id);

// header: "{asset.name} · {asset.type} · 当前 {vN|—}".
std::string workbench_header_text(const catalog::DataAsset& asset,
                                  const std::optional<int>& current_number);
// count: "共 {n} 个版本".
std::string workbench_count_text(int count);

// ---- detail block (selection-driven) ------------------------------------
struct VersionDetailText {
    std::string title;      // "版本详情 · v{n} ({id})" or plain "版本详情"
    std::string parents;    // "父版本: {id, id|—}"
    std::string run;        // "生成 Run: {op} · 状态 {s} · generator {g} · {t[:19]}" | "生成 Run: —"
    std::string run_params; // json_text(run.parameters) or ""
    std::string path;       // "记录路径: {path|—}"
    std::string resolved;   // "解析位置: {p}" | "解析位置: 源文件缺失"
    std::string meta;       // json_text(version.metadata) or ""
};

// version==nullptr → the placeholder detail block (all "—" lines).
VersionDetailText version_detail_text(
    const catalog::DataVersion* version, const LineageHop* hop,
    const std::optional<ResolvedPath>& resolved);

// ---- action gating (_sync_action_buttons) --------------------------------
struct VersionActionGate {
    bool promote = false;   // single && !trashed
    bool trash = false;     // single && !trashed
    bool restore = false;   // single && trashed
    bool compare = false;   // exactly two rows
    bool open = false;      // single && payload exists
};
VersionActionGate version_action_gate(int selected_rows,
                                      bool single_trashed,
                                      bool payload_exists);

// ---- compare dialog rows (_VersionCompareDialog) --------------------------
struct CompareRow {
    std::string field;   // "阶段" / "元数据 · {key}" / …
    std::string left;    // newer (lower row index)
    std::string right;   // older
    bool differ = false; // marker: 同/异, red when differ
};

// (newer, older) → the fixed field rows + sorted union metadata rows.
std::vector<CompareRow> version_compare_rows(
    const catalog::DataVersion& newer, const catalog::DataVersion& older);

// Window title for the compare dialog.
std::string compare_title(const catalog::DataVersion& newer,
                          const catalog::DataVersion& older);

}  // namespace pwb::ui_review
