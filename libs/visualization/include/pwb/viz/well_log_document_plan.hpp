#pragma once

// Workbench → retained WellLogEngine document plan — C++ port of
// paleo_workbench/viz/welllog_engine_adapter.py (the Python module remains the
// behavioural oracle and stays byte-comparable through parity_snapshot()).
//
// The Workbench project model stays authoritative: this layer only normalizes
// immutable typed curve buffers and derives the engine document + presentation
// payload in one complete plan. It deliberately owns no renderer, LOD pyramid
// or parallel scene model — the engine does.
//
// Semantics frozen against the Python oracle (see
// tests/cpp/science/fixtures/welllog/generate_oracle.py):
//   * stable_entity_id  — deterministic UUIDv5 (namespace a1690000-…-0001),
//     parts joined with "|" after stripping, so C++ and Python agree on every
//     document/axis/curve/interval/marker id.
//   * gap-honest alignment — samples with a finite depth stay on the axis even
//     when the value is NaN (the engine splits LOD runs at non-finite values);
//     only non-finite depths are dropped. null_indices are diagnostics-only
//     positions in the pre-alignment arrays.
//   * depth-unit honesty — unknown units submit labeled "m" for rendering with
//     declared=false plus a diagnostic; the unknown state is never hidden.
//   * log-scale honesty — RT/RXO default to logarithmic with a 1e-10 floor
//     when a positive finite sample exists; otherwise linear fallback with a
//     diagnostic (the engine rejects log ranges with minimum <= 0).
//
// Qt-free and engine-free: this header needs neither Qt nor welllog so the
// plan can be unit-tested standalone. The engine document/presentation
// construction lives in the host widget translation unit.

#include <atomic>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <vector>

namespace pwb::viz {

// BEGIN VIZ-A — the vendored facies color table (frozen Python
// FACIES_COLORS, order significant for longest-substring tie-breaks).
// Shared with well_log_patterns.hpp so the table is not duplicated.
const std::vector<std::pair<std::string, std::string>>& facies_colors();
// END VIZ-A

// Deterministic UUIDv5 for Workbench-owned business entities (oracle:
// stable_entity_id). Parts are stripped and joined with "|".
[[nodiscard]] std::string
stable_entity_id(std::vector<std::string_view> parts);

// --- input DTO (the Catalog/Workspace seam) -------------------------------
// In the C++ product chain a workspace/catalog service materializes one
// WellLogDocumentInput per well; the engine adapter consumes it without
// copying curve samples (shared_ptr<const vector<double>> buffers).

struct WellLogCurveInput {
    std::string mnemonic;
    std::string unit;
    std::shared_ptr<const std::vector<double>> depth;
    std::shared_ptr<const std::vector<double>> values;
    // Optional per-curve display range (value axis); nullopt = (0, 100).
    std::optional<std::pair<double, double>> display_range;
    // "#rrggbb" override; empty = mnemonic palette default.
    std::string color;
};
// Note: Python duck-typed attributes with no typed equivalent here
// (display_range falsy→(0,100), curve.name str()-coercion, the facies
// label-attr choice between .facies/.name) are the DTO builder's
// responsibility: this seam receives already-normalized values.

struct WellLogIntervalInput {
    double top{0.0};
    double bottom{0.0};
    std::string label;
};

struct WellLogMarkerInput {
    double depth{0.0};
    std::string label;
    // "formation_top" by convention when empty.
    std::string semantic;
    // Stable business id when the source store has one; empty = derived.
    std::string id;
};

struct WellLogFaciesGroupsInput {
    // Mirrors the Python WellIntervals shape: a lithology bucket plus the
    // grouped facies buckets. adapt_well_log_data falls back to the grouped
    // lithology only when the document-level lithology list is empty (the
    // Python `if not lithology` rule).
    std::vector<WellLogIntervalInput> lithology;
    std::vector<WellLogIntervalInput> phase;
    std::vector<WellLogIntervalInput> sub_phase;
    std::vector<WellLogIntervalInput> micro_phase;
};

struct WellLogDocumentInput {
    std::string well_name;
    double top_depth{0.0};
    double bottom_depth{0.0};
    // Header-declared depth unit token; nullopt = undeclared (unknown).
    std::optional<std::string> depth_unit;
    std::vector<WellLogCurveInput> curves;
    std::vector<WellLogIntervalInput> lithology;
    std::vector<WellLogIntervalInput> facies;
    std::optional<WellLogFaciesGroupsInput> facies_groups;
    std::vector<WellLogMarkerInput> markers;
};

// Lazy per-curve source seam: a workspace/catalog service implements this to
// feed load without materializing every curve up-front. load_curve_values may
// do file/network IO and must honor cancellation between samples/blocks.
class WellLogCurveSource {
public:
    virtual ~WellLogCurveSource() = default;
    [[nodiscard]] virtual std::string well_name() const = 0;
    [[nodiscard]] virtual std::optional<std::string> depth_unit() const = 0;
    [[nodiscard]] virtual std::pair<double, double> depth_envelope() const = 0;
    [[nodiscard]] virtual std::size_t curve_count() const = 0;
    // Metadata without sample buffers (cheap).
    [[nodiscard]] virtual WellLogCurveInput curve_meta(std::size_t index) const = 0;
    // Full curve with sample buffers (lazy; may block).
    [[nodiscard]] virtual WellLogCurveInput
    load_curve(std::size_t index, const std::atomic_bool& cancel) = 0;
    // Interpretation context; empty by default so a curve-only source stays
    // valid._loaded into the plan verbatim (facies/lithology tracks, tops).
    [[nodiscard]] virtual std::vector<WellLogIntervalInput> lithology_intervals() const {
        return {};
    }
    [[nodiscard]] virtual std::vector<WellLogIntervalInput> facies_intervals() const {
        return {};
    }
    [[nodiscard]] virtual std::vector<WellLogMarkerInput> markers() const {
        return {};
    }
};

// --- normalized plan -------------------------------------------------------

struct EngineCurveSubmission {
    std::string document_id;
    std::string axis_id;
    std::string curve_id;
    std::string mnemonic;
    // Position in the SOURCE document input (not the adapted curve list):
    // layout keys are input-indexed, so presentation mapping survives
    // curve_empty drops.
    std::size_t input_index{0};
    std::string depth_unit;  // "m"/"ft" label; "m" when unknown (see declared)
    std::string value_unit;
    std::shared_ptr<const std::vector<double>> depth;
    std::shared_ptr<const std::vector<double>> values;
    std::vector<std::uint64_t> null_indices;
    std::pair<double, double> display_range{0.0, 100.0};
    std::string color;
    bool depth_unit_declared{true};

    [[nodiscard]] std::uint64_t sample_count() const {
        return depth != nullptr ? static_cast<std::uint64_t>(depth->size()) : 0;
    }
};

struct EngineIntervalSubmission {
    std::string interval_id;
    double top{0.0};
    double bottom{0.0};
    std::string semantic; // "lithology" | "facies"
    std::string label;
    std::string fill_color;
};

struct EngineMarkerSubmission {
    std::string marker_id;
    double depth{0.0};
    std::string label;
    std::string semantic; // "formation_top" default
};

struct EngineLoadPlan {
    std::string well_name;
    double top_depth{0.0};
    double bottom_depth{0.0};
    std::vector<EngineCurveSubmission> curves;
    std::vector<EngineIntervalSubmission> intervals;
    std::vector<EngineMarkerSubmission> markers;
    std::vector<std::tuple<double, double, std::string>> lithology_bounds;
    std::vector<std::tuple<double, double, std::string>> facies_bounds;
    std::optional<std::string> primary_curve_id;
    std::vector<std::string> diagnostics;

    [[nodiscard]] const EngineCurveSubmission* primary() const;
    [[nodiscard]] std::optional<std::string> document_id() const;
};

// Create a complete typed engine document plan from Workbench data (oracle:
// adapt_well_log_data).
[[nodiscard]] EngineLoadPlan
adapt_well_log_data(const WellLogDocumentInput& input);

// Adapt from a lazy source, pulling curves one at a time with cooperative
// cancellation checkpoints between curves (returns nullopt + "cancelled" on
// cancellation).
[[nodiscard]] std::optional<EngineLoadPlan>
adapt_well_log_data_from_source(WellLogCurveSource& source,
                                const std::atomic_bool& cancel,
                                std::vector<std::string>* diagnostics);

// --- presentation payload ---------------------------------------------------

struct EngineTrackPlan {
    double width_mm{40.0};
    // When set, this track renders document intervals of that semantic
    // ("lithology"/"facies") and carries no curve.
    std::optional<std::string> interval_semantic;
    std::string scale_mode; // "linear" | "log"
    double scale_min{0.0};
    double scale_max{1.0};
    std::string curve_id;
    std::string color;
};

// Build the ordered track payload: interval tracks first, then one track per
// curve. Log-range sanitization may append "log_scale_fallback:{mnemonic}" to
// *diagnostics (oracle: _track_payload).
[[nodiscard]] std::vector<EngineTrackPlan>
build_track_payload(const EngineLoadPlan& plan,
                    std::vector<std::string>* diagnostics);

// Reference depth envelope for the presentation builder (oracle: the
// top/bottom normalization in plan_to_submit_payload). Returns nullopt when
// the plan has no submittable curve.
[[nodiscard]] std::optional<std::pair<double, double>>
submit_depth_envelope(const EngineLoadPlan& plan);

// Host-comparable semantic snapshot for regression tests — field names and
// values match the Python parity_snapshot output (JSON, ensure_ascii off).
[[nodiscard]] std::string parity_snapshot_json(const EngineLoadPlan& plan);

} // namespace pwb::viz
