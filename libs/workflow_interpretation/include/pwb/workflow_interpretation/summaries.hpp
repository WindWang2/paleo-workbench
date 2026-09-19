#pragma once
// CONV-32 — Inspector summary contracts (workflow/interpretation/summaries.py
// port): UI never reads internal models — every domain object projects a
// directly displayable summary (Method/Unit/CRS/Inputs/Version/State/QC/
// Uncertainty). Plain-dict in / plain-dict out, zero domain dependencies for
// the consumer.
//
// Value formatting is PYTHON str() semantics (no rounding): floats use the
// shortest round-trip repr, ints plain digits, bools "True"/"False", null
// "None", strings verbatim.
#include <pwb/domain/json.hpp>
#include <pwb/workflow_interpretation/factor_product.hpp>

#include <string>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

struct SummaryRow {
    std::string label;
    std::string value;
    std::string state = "ok";  // "ok" | "missing" | "unknown" | "warn"
};

struct FactorSummary {
    std::string factor_id;
    std::string title;
    std::vector<SummaryRow> rows;

    // Keys: kind("factor"), factor_id, title, rows[{label,value,state}].
    [[nodiscard]] Json to_display_dict() const;
};

struct InterpretationSummary {
    std::string interpretation_id;
    std::string title;
    std::vector<SummaryRow> rows;

    // Keys: kind("integrated_interpretation"), interpretation_id, title,
    // rows[{label,value,state}].
    [[nodiscard]] Json to_display_dict() const;
};

// FactorProduct -> display rows (product missing -> honest missing summary).
[[nodiscard]] FactorSummary factor_summary(const FactorProduct* product);

// Compose without a freshness entry (factor_product_for_task + factor_summary).
[[nodiscard]] FactorSummary factor_summary_for_task(
    const Json& tasks_array, const std::string& task_id,
    const CatalogResolver& catalog = {},
    const WorkspaceView& workspace_state = {});

// Integrated interpretation -> display rows. Seam: `interpretation` is a
// to_dict-shaped IntegratedInterpretation JSON (interpretation_id/name/
// input_set_id/layer_id/fusion_version_id/committed_version_id/maturity/
// class_schema[]/conflicts{}/revision_ids[]/last_committed_revision_id),
// `latest_revision` a to_dict-shaped InterpretationRevision JSON or nullptr
// (Python: find_by_layer miss -> no-record summary).
[[nodiscard]] InterpretationSummary interpretation_summary_rows(
    const Json& interpretation, const Json* latest_revision);

}  // namespace pwb::workflow_interpretation
