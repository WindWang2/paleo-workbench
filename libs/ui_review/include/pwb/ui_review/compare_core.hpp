#pragma once

// M5 (ribbon five-workspaces, plan 00-plan.md §4-M5) — 解释 vs 预测对比
// core (design F:72-75 验证节, Qt-free):
//
//   * three modes — 并排 / 叠加 / 差异 — over per-well depth bands built
//     from the REAL payloads only:
//       - 解释版本 = project.correlation_interpretations entry + its
//         artifact's scientific payload (FormationTop rows: well/marker/
//         depth) → unit bands between consecutive tops. Interpretation
//         tops carry NO facies class — the band klass stays empty and the
//         UI shows 未标注 instead of inventing one;
//       - 预测成果 = project.prediction_tasks entry, result_summary
//         .predicted_regions rows (well/stratigraphic_unit/top/bottom/
//         facies/probability);
//   * 岩性与沉积相分别对照: bands carry the taxonomy they came from
//     ("facies" | "lithology" | ""); the widget renders the two systems
//     in separate columns and never cross-colors them;
//   * depth stays in its native domain (MD metres) — m/ms coupling is a
//     UI-level concern gated on a real time-depth calibration, never
//     assumed here.

#include <optional>
#include <string>
#include <vector>

#include "pwb/domain/json.hpp"

namespace pwb::ui_review {

enum class CompareMode { SideBySide, Overlay, Difference };

const char* compare_mode_label(CompareMode mode);
std::optional<CompareMode> compare_mode_from_string(const std::string& value);

// One depth band on one well, from EITHER source.
struct CompareBand {
    std::string well_id;
    std::string well_name;
    std::string unit;      // stratigraphic unit / marker name
    std::string klass;     // class label; empty = 未标注 (honest)
    std::string taxonomy;  // "facies" | "lithology" | ""
    double top = 0.0;      // depth, native domain (MD metres today)
    double bottom = 0.0;
    std::string domain = "MD";
    double confidence = 0.0;  // prediction probability; interpretation → 0
};

// interpretation entry (correlation_interpretations ref) + the artifact's
// "scientific" payload Json. Tops with status "rejected" are dropped
// (active interpretation only); a well needs ≥2 tops to form a band.
std::vector<CompareBand> bands_from_interpretation(
    const domain::Json& interp_ref, const domain::Json& artifact_scientific);

// prediction_tasks entry (status != complete still renders — the bands
// are the task's real product; completeness is a label, not a filter).
std::vector<CompareBand> bands_from_prediction(const domain::Json& task);

struct BandPair {
    std::string well_id;
    std::string well_name;
    std::string unit;
    bool in_interpretation = false;
    bool in_prediction = false;
    std::string interpreted_class;  // may be empty (解释未标注)
    std::string predicted_class;
    double top = 0.0;
    double bottom = 0.0;
    bool comparable = false;  // both sides carry classes
    bool match = false;       // comparable && same class && depth overlap
};

// Pair by (well, unit). Presence on one side only stays visible — the
// diff column counts it as a mismatch, never hides it.
std::vector<BandPair> pair_bands(
    const std::vector<CompareBand>& interpretation,
    const std::vector<CompareBand>& prediction);

struct CompareSummary {
    int matched = 0;
    int mismatched = 0;
    int incomparable = 0;  // both sides present but a class is missing
    int interpretation_only = 0;
    int prediction_only = 0;
};

CompareSummary summarize_pairs(const std::vector<BandPair>& pairs);

}  // namespace pwb::ui_review
