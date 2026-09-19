#pragma once
// CONV-32 — constraint capabilities (workflow/constraint_capabilities.py
// port): the engine-vocabulary constraint support matrix per interpolation
// method + honest request evaluation (accept/partial/unsupported with
// verbatim diagnostics). The geological vocabulary -> engine vocabulary
// mapping lives in constraint_product.hpp.
#include <pwb/domain/json.hpp>

#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::workflow_interpretation {

using domain::Json;

enum class ConstraintKind { BOUNDARY_MASK, BARRIER, DIRECTION, ANISOTROPY, TREND };
enum class Support { SUPPORTED, PARTIAL, APPROXIMATION, UNSUPPORTED };

[[nodiscard]] std::string to_string(ConstraintKind v);
[[nodiscard]] std::string to_string(Support v);
// Python ValueError parity: "'<v>' is not a valid ConstraintKind" /
// "'<v>' is not a valid Support".
[[nodiscard]] ConstraintKind constraint_kind_from(const std::string& v);
[[nodiscard]] Support support_from(const std::string& v);

struct ConstraintSupport {
    Support level = Support::UNSUPPORTED;
    std::string note;
};

struct MethodCapabilities {
    std::string method;
    std::string label;
    // Only declared cells; for_kind fills the default
    // (UNSUPPORTED, "not consumed by this method").
    std::map<ConstraintKind, ConstraintSupport> support;
    std::vector<std::string> prerequisites;
    [[nodiscard]] ConstraintSupport for_kind(ConstraintKind kind) const;
};

// Python: ValueError subclass. Message joins parts with ";":
// "method '<m>' cannot honor the requested constraints:" [+ "; unsupported: a, b"] [+ "; ignored: c"]
class ConstraintViolationError : public std::runtime_error {
public:
    ConstraintViolationError(std::string method, std::vector<std::string> unsupported,
                             std::vector<std::string> ignored);
    std::string method;
    std::vector<std::string> unsupported;
    std::vector<std::string> ignored;
};

struct ConstraintApplication {
    std::string method;
    std::vector<std::string> requested, applied, partial, ignored, unsupported,
        diagnostics;
    [[nodiscard]] bool honest() const;  // no ignored minus diagnostics labels
    [[nodiscard]] std::set<std::string> diagnostics_labels() const;  // split(':')[0]
    // Keys: method, requested_constraints, applied_constraints,
    // partial_constraints, ignored_constraints, unsupported_constraints,
    // constraint_diagnostics.
    [[nodiscard]] Json as_dict() const;
};

// KeyError parity: "unknown interpolation method '<original>'; known:
// ['constrained_idw', 'directional', 'idw', 'kriging', 'linear', 'nearest',
// 'rbf', 'spline']" (repr of the ORIGINAL argument).
[[nodiscard]] MethodCapabilities capabilities_for_method(const std::string& method);

// Requested kinds as value strings (dedup keep-first, encounter order);
// invalid kind value throws ("'<v>' is not a valid ConstraintKind").
// strict=true + unsupported/ignored -> ConstraintViolationError.
[[nodiscard]] ConstraintApplication evaluate_request(
    const std::string& method, const std::vector<std::string>& requested = {},
    bool strict = false);

// method_id -> {label, prerequisites[], constraints{kind -> {support, notes}}}
// in _METHODS order; all 5 kinds materialized (absent -> default cell).
[[nodiscard]] Json capability_matrix();

}  // namespace pwb::workflow_interpretation
