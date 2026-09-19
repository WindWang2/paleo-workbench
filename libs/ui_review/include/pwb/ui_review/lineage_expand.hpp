#pragma once

// UI-11 — lineage_explorer_dialog.py Qt-free semantics.
//
// The lazy provenance tree: every expansion performs exactly ONE
// get_lineage hop (direct parents / children — the full-chain helper is
// never used). This core produces the child-node specs a hop renders:
// the interleaved run node (OUTPUT → ⚙ Run → INPUT), cycle notes (↺),
// red broken-link rows (⚠ 断链), the bounded 「…还有 N 个（未展开）」
// overflow row, and the terminal notes (（无上游 — RAW 根）/（无下游衍生）).
//
// Hard display caps are module constants so tests can tighten them.

#include "pwb/ui_review/catalog_api.hpp"

#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::ui_review {

inline constexpr int kMaxChildrenPerNode = 200;  // MAX_CHILDREN_PER_NODE
inline constexpr int kMaxExpandDepth = 25;       // MAX_EXPAND_DEPTH
inline constexpr int kMaxExpandNodes = 1000;     // MAX_EXPAND_NODES
inline constexpr int kShortIdLen = 12;           // _SHORT_ID_LEN

// One tree row produced by an expansion.
struct LineageNodeSpec {
    enum class Kind { Run, Version, Broken, Note, Overflow, Current, Branch };
    Kind kind = Kind::Note;
    std::string label;
    // version/current nodes:
    std::string version_id;
    std::string asset_id;
    std::string stage;              // domain::DataStage value ("raw"...)
    std::string direction;          // "up" | "down" | "" (current)
    std::vector<std::string> ancestors;  // ids on the path (cycle check)
    bool lazy = false;              // re-expandable on first expand
    bool selectable = true;
    bool red = false;               // ⚠ 断链 foreground
    bool disabled = false;          // overflow row
    bool show_indicator = true;     // expand affordance
    // run nodes:
    std::string run_id;
    std::string output_version_id;
};

using AssetNameFn =
    std::function<std::string(const std::string& asset_id)>;

// _populate_inputs parity: one up-hop → [run?] + version/broken/cycle
// rows + terminal/overflow notes. hop == nullptr → single
// "（无法读取血缘）" note. The run node is returned FIRST when present
// (the widget hangs the version rows beneath it).
std::vector<LineageNodeSpec>
expand_inputs(const LineageHop* hop,
              const std::vector<std::string>& ancestors,
              const AssetNameFn& asset_name);

// _populate_outputs parity: one down-hop → version/cycle rows +
// terminal/overflow notes (no run interleave downstream).
std::vector<LineageNodeSpec>
expand_outputs(const LineageHop* hop,
               const std::vector<std::string>& ancestors,
               const AssetNameFn& asset_name);

// _make_version_item label: "{icon} {asset} · v{n} · {stage} · {id[:12]}"
// (+ " ✕回收站" when trashed). Reuses ui_data_core stage_icon/stage_label.
std::string version_item_label(const catalog::DataVersion& version,
                               const std::string& asset_name);

// The centered-node spec (_rebuild_tree current row): label "■ 当前: …",
// kind Version, lazy=false, direction="", ancestors={version.id},
// DontShowIndicator.
LineageNodeSpec current_item_spec(const catalog::DataVersion& version,
                                  const std::string& asset_name);

// Branch rows (_make_branch): "⬆ 上游 (← RAW)" / "⬇ 下游 (→ 产物)",
// kind Branch, lazy=true, selectable=false, ShowIndicator.
LineageNodeSpec branch_spec(const std::string& direction,
                            const std::string& version_id);

// ── summary / run-card text (fill_summary / fill_run_card) ──────────────
struct SummaryCardText {
    std::string title;   // "{icon} {asset} · v{n} · {stage}"
    std::string meta;    // "ID: … · 校验和: … · 创建于: … · 受管|外部"
    std::string path;    // "路径: …" (+ "　⚠ 源文件缺失")
};
SummaryCardText summary_card_text(const catalog::DataVersion& version,
                                  const std::string& asset_name,
                                  bool payload_exists);

struct RunCardText {
    std::string title;    // "⚙ 生成运行 · {operation}" | "无生成运行"
    std::string meta;     // "状态: … · 生成器: … · {created_at}"
    std::string params;   // pretty JSON (indent 2, no ascii escape)
    bool has_run = false;
};
RunCardText run_card_text(const catalog::DataRun* run);

// expand-to-RAW status lines (_on_expand_raw tail).
std::string expand_raw_capped_status();
std::string expand_raw_done_status(int roots, int upstream_versions);

}  // namespace pwb::ui_review
