#pragma once

// C++ port of paleo_workbench/workflow/factor_fusion.py (CONV-24).
// register_output stays Python-side (catalog write seam, D1); every other
// symbol is mirrored: Normalization / FactorEvidence / FusionRule /
// FusionModel / FusionResult / fuse / sensitivity_report, plus the internal
// _aligned_or_raise + _build_grid + _classify_grid semantics.

#include <pwb/domain/json.hpp>
#include <pwb/factor_fusion/errors.hpp>
#include <pwb/factor_fusion/factor_grid.hpp>

#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace pwb::factor_fusion {

using pwb::domain::Json;

inline constexpr const char* kFusionGeneratorVersion = "factor-fusion-v1";

// --- Normalization ---------------------------------------------------------

struct Normalization {
    std::string kind;  // "minmax" | "ramp"
    double low = 0.0;
    double high = 0.0;

    // __post_init__ validation — throws ValueError with the Python messages.
    Normalization(std::string kind, double low, double high);

    // clip((v - low) / (high - low), 0, 1) on finite elements only.
    std::vector<double> apply(const std::vector<double>& values) const;

    Json to_dict() const;
    static Normalization from_dict(const Json& data);
};

// --- FactorEvidence --------------------------------------------------------

struct FactorEvidence {
    std::string factor_name;
    FactorGrid grid;
    double weight = 0.0;
    Normalization normalization{"minmax", 0.0, 1.0};

    // __post_init__ weight validation — ValueError when not finite/positive.
    FactorEvidence(std::string factor_name, FactorGrid grid, double weight,
                   Normalization normalization);

    Json to_dict() const;
};

// --- FusionRule ------------------------------------------------------------

struct FusionRule {
    // (factor, op, threshold); op in {">=","<=",">","<","=="}.
    std::vector<std::tuple<std::string, std::string, double>> conditions;
    std::string class_name;

    FusionRule(
        std::vector<std::tuple<std::string, std::string, double>> conditions,
        std::string class_name);

    Json to_dict() const;
    static FusionRule from_dict(const Json& data);
};

// Raw-row construction mirroring __post_init__ on unvalidated sequences —
// Json rows may be ragged/mistyped exactly like Python tuples. The
// `from_dict_messages` flag selects which shape-error wording applies
// ("(factor, op, threshold)" ctor vs "[factor, op, threshold]" from_dict).
FusionRule rule_from_rows(const Json& rows, const std::string& class_name,
                          bool from_dict_messages);

// --- FusionModel -----------------------------------------------------------

struct FusionModel {
    std::string name;
    std::string kind;  // "weighted_evidence" | "rule_based"
    std::vector<FactorEvidence> evidences;
    std::vector<FusionRule> rules;
    std::string default_class = "未定";
    std::vector<double> class_thresholds;
    std::vector<std::string> class_names;
    std::optional<Json> weight_provenance;

    // __post_init__ validation — ValueError on every Python branch.
    void validate() const;

    Json to_dict() const;
    // grids seam (D5): runtime grids injected by factor name — never
    // serialised; a missing grid is a ValueError verbatim.
    static FusionModel from_dict(const Json& data,
                                 const std::map<std::string, FactorGrid>& grids);

    // sha256 of json.dumps(to_dict(), sort_keys=True, ensure_ascii=False,
    // default=str) — Python's default ", "/": " separators (D3).
    std::string fingerprint() const;
};

// --- FusionResult ----------------------------------------------------------

struct FusionResult {
    FusionModel model;
    Json model_dict;
    FactorGrid likelihood;
    FactorGrid confidence;
    std::optional<FactorGrid> variance;
    std::vector<std::string> class_names;
    Json qc = Json::object();

    Json provenance() const;
};

// --- fusion entry points ---------------------------------------------------

FusionResult fuse(const FusionModel& model);
FusionResult fuse_weighted(const FusionModel& model);    // _fuse_weighted
FusionResult fuse_rule_based(const FusionModel& model);  // _fuse_rule_based

// _aligned_or_raise: geometry + CRS discipline; returns declared CRS of the
// first grid, or nullopt when every input is undeclared. IndexError on an
// empty grid list (frozen edge).
std::optional<std::string> aligned_or_raise(const std::vector<FactorGrid>& grids);

// Leave-one-factor-out sensitivity (weighted family only). The Python
// signature accepts an unused `delta` keyword — kept for parity, ignored.
Json sensitivity_report(const FusionModel& model, const FusionResult& baseline,
                        double delta = -1.0);

}  // namespace pwb::factor_fusion
