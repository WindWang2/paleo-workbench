// Frozen cross-module run contracts, v3 (v3-contracts.md).
//
// B owns the run lifecycle surface A/C/E drive: durable registration of an
// algorithm run, terminal states, and the run-state query shape. The
// publish path (PublishRequestV1) lives in commit_coordinator.hpp next to
// the other journal request types and reuses StagedAssetV1 unchanged.
// Inputs are domain IDs, JSON/POD metadata and staged files only — never
// Qt/QGIS/Science types (C/E objects are converted by A's application
// layer before reaching B).
#pragma once

#include "pwb/catalog/models.hpp"
#include "pwb/domain/ids.hpp"
#include "pwb/domain/json.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::data {

// Run status vocabulary (Python catalog parity: "running" is the only
// non-terminal status; terminal values can never transition again — retry
// after a failed/cancelled run creates a NEW run id).
inline constexpr std::string_view kRunStatusRunning = "running";
inline constexpr std::string_view kRunStatusComplete = "complete";
inline constexpr std::string_view kRunStatusFailed = "failed";
inline constexpr std::string_view kRunStatusCancelled = "cancelled";

inline constexpr bool is_run_status_terminal(std::string_view status) {
    return status == kRunStatusComplete || status == kRunStatusFailed ||
           status == kRunStatusCancelled;
}

// Registration of a run BEFORE the algorithm executes (durable "running"
// row; audit reports it as run_incomplete until it reaches a terminal
// state). Idempotent on run_id: replaying a registration returns the
// existing row and never creates a second one.
struct RunRegistrationV1 {
    domain::RunId run_id;  // caller-generated idempotency key
    std::string operation;  // e.g. "seismic.coherence_c3", "manual_edit"
    // Algorithm identity "algorithm_id@version[+build]" — stored verbatim
    // in the run row (provenance queries surface it as-is).
    std::string generator;
    // Full parameter record (JSON/POD only). B never interprets keys;
    // recommended members are documented in v3-contracts.md §5.
    domain::Json parameters = domain::Json::object();
    std::vector<domain::VersionId> input_version_ids;
    // Optional typed ports; every port version id must be a member of
    // input_version_ids (single-writer invariant, adapter.py parity).
    std::vector<catalog::RunPort> input_ports;
    std::optional<domain::Json> model_ref;  // optional model-registry ref
};

// Read model of one run row (echo for registration / terminal transitions
// and the query surface behind pwb-inspect --run).
struct RunStateV1 {
    domain::RunId run_id;
    std::string operation;
    std::string generator;
    std::string status;
    std::vector<domain::VersionId> input_version_ids;
    std::vector<domain::VersionId> output_version_ids;
    std::vector<catalog::RunPort> input_ports;
    std::vector<catalog::RunPort> output_ports;
    domain::Json parameters = domain::Json::object();
    std::optional<domain::Json> model_ref;
    std::string created_at;
};

// Terminal transition requested after registration. "complete" is reached
// ONLY through publish (all-durable ordering); Failed/Cancelled are the
// explicit algorithm-failure / user-cancel paths.
enum class RunTerminalStatus { Failed, Cancelled };

inline constexpr std::string_view to_string(RunTerminalStatus terminal) {
    switch (terminal) {
        case RunTerminalStatus::Failed: return kRunStatusFailed;
        case RunTerminalStatus::Cancelled: return kRunStatusCancelled;
    }
    return kRunStatusFailed;
}

// One run row projected to JSON (pwb-inspect --run / --provenance shape).
domain::Json run_state_to_json(const RunStateV1& state);

}  // namespace pwb::data
