#pragma once

// UI-09 — CorrelationLinkEditor row semantics (Qt-free).
//
// Ports:
//   _METHOD_LABELS  — MANUAL/DTW_ASSISTED/CURVE_SHAPE_ASSISTED/IMPORTED
//                     -> 手工 / DTW 辅助 / 曲线形态辅助 / 导入
//   _STATUS_LABELS  — active / tentative / rejected
//   link table      — sorted by (top_a_id, top_b_id, id); cells resolve
//                     top fields through a REBUILT id->top map ("?" when a
//                     referenced top is absent — review R3-M3)
//   top table       — sorted by (well_name, marker, depth)
//   top picker      — "{well} · {marker} ({depth:.1f}) #{i}" unique labels

#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_wellseis/slices.hpp>

namespace pwb::ui_wellseis {

// _method_label parity: known enum strings -> Chinese label; anything else
// passes through verbatim.
std::string correlation_method_label(const std::string& method);

// _STATUS_LABELS verbatim order.
extern const std::vector<std::string> kCorrelationStatuses;

// Link row resolved against a top-id map (rebuilt per refresh like Python).
struct CorrelationLinkRow {
    std::string id;
    std::string marker;      // top_a marker or "?"
    std::string pair_text;   // "{well_a} → {well_b}" ("?" per missing side)
    std::string method_label;
    std::string adjacent_text;  // "是" / "否"
    std::string notes;
};

// Top row cells verbatim (depth formatted "{:.2f} {domain}",
// confidence "" -> "—").
struct CorrelationTopRow {
    std::string id;
    std::string well_name;
    std::string marker;
    std::string depth_text;
    std::string method_label;
    std::string confidence_text;
};

// Sorted + resolved row models (the Qt shells bind these to views).
std::vector<CorrelationLinkRow> correlation_link_rows(
    const CorrelationDraftSlice& draft);
std::vector<CorrelationTopRow> correlation_top_rows(
    const CorrelationDraftSlice& draft);

// Add-link picker entries, sorted by (well_name, marker), each with the
// unique "#i" suffix label the Python dialog builds.
struct CorrelationTopChoice {
    std::string label;  // "{well} · {marker} ({depth:.1f}) #{i}"
    std::string top_id;
};
std::vector<CorrelationTopChoice> correlation_top_choices(
    const CorrelationDraftSlice& draft);

// Session mutation seams — the Python editor routes every change through
// draft/session ops; these helpers perform the same draft-level mutation so
// the Qt dialog stays a shell. `new_link_id` is supplied by the caller (id
// authority lives in the session layer, not here).
bool correlation_add_manual_link(CorrelationDraftSlice& draft,
                                 const std::string& new_link_id,
                                 const std::string& top_a_id,
                                 const std::string& top_b_id,
                                 bool adjacent_only,
                                 const std::string& notes);
bool correlation_remove_link(CorrelationDraftSlice& draft,
                             const std::string& link_id);
bool correlation_edit_link(CorrelationDraftSlice& draft,
                           const std::string& link_id,
                           const std::string& method,
                           const std::string& notes);
bool correlation_edit_top(CorrelationDraftSlice& draft,
                          const std::string& top_id,
                          const std::string& method,
                          const std::string& confidence,
                          const std::string& status,
                          const std::string& notes);

}  // namespace pwb::ui_wellseis
