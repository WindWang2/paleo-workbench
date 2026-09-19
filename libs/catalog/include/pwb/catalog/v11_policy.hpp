// V11 data-fabric policy core (conv-31; catalog/service_v11.py parity).
//
// The pure decision surfaces of the V11 mixin: typed-run-port assignment
// invariants (ports ⊆ flat io lists, MAX_RUN_PORTS budget), anonymous-port
// synthesis for legacy runs, the operation→output-role backfill heuristic,
// the pin governance overlay (metadata["pin"]), retention classes with
// stage defaults, double-gate cleanup eligibility and the shared lifecycle
// status read. Persistence stays with CatalogRepository transactions —
// nothing here touches IO.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

inline constexpr int kMaxBundleMembers = 64;  // MAX_BUNDLE_MEMBERS
inline constexpr int kMaxRunPorts = 256;      // MAX_RUN_PORTS

// RETENTION_CLASSES (declared order is the error-text order).
inline constexpr std::string_view kRetentionClasses[] = {"cache", "recomputable",
                                                         "retain", "user"};

// _DEFAULT_RETENTION_FOR_STAGE.
std::string default_retention_for_stage(domain::DataStage stage);

// ---- typed ports -------------------------------------------------------------

// _coerce_ports parity: dict specs → RunPort (role defaults to the
// direction). A non-object spec is an error with the Python message shape.
domain::Result<std::vector<RunPort>> coerce_ports(const domain::Json& ports,
                                                  const std::string& direction);

// _apply_run_ports parity over one run (no persistence). *validate against
// the index enforces committed-version references; ports keep the flat id
// lists a superset. Port-budget error text is byte-identical.
domain::DataError apply_run_ports(
    DataRun* run, const DocumentIndex* index,
    const std::optional<std::vector<RunPort>>& input_ports,
    const std::optional<std::vector<RunPort>>& output_ports);

// ports_for_run parity: typed ports, anonymous synthesis for legacy runs.
struct RunPortsView {
    std::vector<RunPort> input;
    std::vector<RunPort> output;
};
RunPortsView ports_for_run(const DataRun& run);

// inputs_by_role parity over the synthesized view.
std::vector<RunPort> inputs_by_role(const DataRun& run, const std::string& role);

// runs_consuming parity: runs whose input ports match role and/or version;
// legacy untyped runs still count when the flat list carries the version.
std::vector<const DataRun*> runs_consuming(const CatalogDocument& document,
                                           const DocumentIndex& index,
                                           const std::optional<std::string>& role,
                                           const std::optional<std::string>& version_id);

// _OPERATION_OUTPUT_ROLES heuristic table.
const std::vector<std::pair<std::string, std::string>>& operation_output_roles();

// migrate_run_ports parity (in-place over document.runs; returns counts).
struct PortBackfillCounts {
    int runs_annotated = 0;
    int ports_added = 0;
};
PortBackfillCounts migrate_run_ports(CatalogDocument* document,
                                     const DocumentIndex& index);

// ---- bundle member planning (register_bundle_version pure core) ---------------

// The pre-placement decisions of register_bundle_version: member budget,
// spec-vs-reality sanity, and the ONE unified used-name pool (bare name →
// rel path → numeric ~N suffix fallback) with duplicate detection.
struct BundleMemberPlan {
    // rel_path (POSIX, sorted) → assigned member name.
    std::vector<std::pair<std::string, std::string>> names;
};
domain::Result<BundleMemberPlan> plan_bundle_members(
    const std::vector<std::string>& source_rel_paths,
    const std::vector<VersionMember>& member_specs);

// ---- pin / retention / eligibility --------------------------------------------

bool is_pinned(const DataVersion& version);
// pin_version writes {"reason": ..., "pinned_at": ...} into metadata.
void apply_pin(DataVersion* version, const std::string& reason,
               const std::string& pinned_at_iso);
void apply_unpin(DataVersion* version);

// set_retention_class validation (error text parity) + effective class read.
domain::DataError validate_retention_class(const std::string& retention_class);
std::string retention_class_of(const DataVersion& version);

struct CleanupEligibility {
    std::string version_id;
    bool eligible = false;
    std::vector<std::string> blockers;
    std::string retention_class;
    int downstream_count = 0;
};
// cleanup_eligibility parity. *live_working_copy stands in for the
// working-copy registry probe (the caller owns that store).
CleanupEligibility cleanup_eligibility(const CatalogDocument& document,
                                        const DocumentIndex& index,
                                        const std::string& version_id,
                                        bool live_working_copy);

domain::Json version_lifecycle_status(const CatalogDocument& document,
                                       const DocumentIndex& index,
                                       const std::string& version_id,
                                       bool live_working_copy);

}  // namespace pwb::catalog
