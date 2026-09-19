#pragma once
// CONV-32 — execution receipts (dag/receipt.py port). One receipt per
// succeeded/degraded node execution; failed/cancelled/rejected/unavailable
// nodes carry no receipt. Nondeterministic inputs (clock, environment
// identity) are injected seams. Qt-free, Python-free.
#include <pwb/domain/json.hpp>

#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::workflow_engine {

using domain::Json;

inline constexpr std::string_view kReceiptSchemaVersion = "1.0";

// dag/receipt.py environment_identity() — {"python","platform","workbench"}.
// Production supplies host values; oracle tests inject Python's frozen
// triple (parity is structural, not machine-equal).
struct EnvironmentIdentity {
    std::string python;
    std::string platform;
    std::string workbench;
    [[nodiscard]] Json to_dict() const;
};
using EnvironmentProvider = std::function<EnvironmentIdentity()>;
using Clock = std::function<double()>;

// harness.executor.ActionResult JSON-able projection subset consumed by
// build_receipt. statuses: success|degraded|failed|cancelled|rejected|unavailable.
struct ActionResultView {
    std::string status = "success";
    Json outputs = Json::object();
    Json verification = Json::object();
    std::vector<std::string> warnings;
    Json metrics = Json::object();  // may carry "provenance"
    std::optional<std::string> error;
    double elapsed_ms = 0.0;
};

struct ExecutionReceipt {
    // Member order == to_dict key order (frozen against Python).
    std::string schema_version{"1.0"};
    std::optional<std::string> node_id;
    std::optional<std::string> workflow_run_id;
    std::string action_id;
    std::string action_version;
    std::string description;
    Json parameters = Json::object();
    std::vector<std::string> input_version_ids;
    std::optional<std::string> provider_id;
    std::optional<std::string> provider_version;
    std::optional<std::string> resource_category;
    Json estimated_resources = Json::object();
    std::string status = "success";
    std::optional<double> started_at;
    std::optional<double> finished_at;
    double duration_ms = 0.0;
    std::vector<std::string> output_version_ids;
    Json outputs_summary = Json::object();
    std::optional<std::string> catalog_run_id;
    Json verification = Json::object();
    Json qc_metrics = Json::object();
    std::vector<std::string> warnings;
    std::optional<std::string> degraded_reason;
    std::optional<std::string> error;
    std::optional<std::string> cache_identity;
    bool from_cache = false;
    int attempt = 1;
    Json environment = Json::object();

    [[nodiscard]] Json to_dict() const;  // duration_ms rounded half-to-even, 3dp
    [[nodiscard]] static ExecutionReceipt from_dict(const Json& data);
};

struct BuildReceiptArgs {
    std::optional<std::string> node_id;
    std::optional<std::string> workflow_run_id;
    std::string action_id;
    std::string action_version;
    std::string description;
    Json parameters = Json::object();
    std::vector<std::string> input_version_ids;
    Json estimated_resources = Json::object();
    std::optional<std::string> resource_category;
    std::optional<std::string> cache_identity;
    bool from_cache = false;
    int attempt = 1;
    std::optional<double> started_at;
};

// Engine calls this only for status in {"success","degraded"}.
[[nodiscard]] ExecutionReceipt build_receipt(const ActionResultView& result,
                                             const BuildReceiptArgs& args,
                                             EnvironmentProvider env, Clock clock);

// artifacts[].version.version_id | version_id | version_id singular —
// dedup keep-first, encounter order.
[[nodiscard]] std::vector<std::string> collect_output_version_ids(const Json& outputs);
// "<in-process handle>" / "<N items>" / "<N keys>" / artifact_count / scalars.
[[nodiscard]] Json summarize_outputs(const Json& outputs);

}  // namespace pwb::workflow_engine
