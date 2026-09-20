// catalog/lifecycle.py shared run-orchestration skeleton — the pattern
// every register_*_run function follows: resolve inputs → begin_run →
// register output(s) → complete_run, with _fail_run compensation and
// best-effort typed-port annotation. Per-domain register_* bodies are
// thin adaptations over these primitives.
#pragma once

#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

namespace pwb::workflow_runtime {

using Json = pwb::domain::Json;

// begin_run keyword bundle (adapter.begin_run parity).
struct RunSpec {
    std::string operation;
    std::vector<std::string> input_version_ids;
    Json parameters = Json::object();
    std::optional<std::string> generator_version;
    std::optional<std::string> domain_task_id;
    std::optional<std::string> input_snapshot_hash;
    std::optional<std::string> actor;
};

// cat.begin_run(...) → running run id.
std::string begin_run(CatalogRepository& catalog, const RunSpec& spec);

// cat.complete_run(run_id) — Python default status is "complete".
void complete_run(CatalogRepository& catalog, const std::string& run_id);

// _fail_run parity: best-effort `complete_run(status="failed")` — a
// compensation failure is logged-and-swallowed in Python, swallowed here.
void fail_run(CatalogRepository& catalog, const std::string& run_id) noexcept;

// Failure variant carrying error detail (update_run_status extra_parameters
// parity — e.g. "output registration failed" notes ride the run record).
void fail_run(CatalogRepository& catalog, const std::string& run_id,
              const Json& extra_parameters) noexcept;

// _annotate_output_port parity: tag one output endpoint with its role.
// Best-effort — backend failure or missing ports support never fails the
// registration.
void annotate_output_port(CatalogRepository& catalog,
                          const std::string& run_id,
                          const std::string& version_id,
                          const std::string& role) noexcept;

// _annotate_input_ports parity: one shared role over N inputs; each port
// carries its ordinal plus optional entity_type/entity_id pairing (only
// when ordinal < entity_ids.size()).
void annotate_input_ports(
    CatalogRepository& catalog, const std::string& run_id,
    const std::vector<std::string>& version_ids, const std::string& role,
    const std::string& entity_type = "",
    const std::vector<std::string>& entity_ids = {}) noexcept;

// resolve_input_versions parity: legacy resource ids → version ids via the
// bridge index; unknown ids are dropped, order preserved, no dedup.
std::vector<std::string> resolve_input_versions(
    CatalogRepository& catalog,
    const std::vector<std::string>& resource_ids);

// _versions_for_domain_tasks parity: latest COMPLETE run per domain task
// (list order oldest→newest; first-seen task order preserved); prefer that
// run's non-trashed outputs, else its declared inputs. Failed/running/
// cancelled runs never stand in. Catalog errors PROPAGATE — the Python
// `except Exception: return []` wrapper lives in the caller
// (compile_map_production._resolve_map_input_ids), not here.
std::vector<std::string> versions_for_domain_tasks(
    const std::vector<std::string>& task_ids, CatalogRepository& catalog);

}  // namespace pwb::workflow_runtime
