#pragma once

// cpp-close-02 — CatalogCacheRunRail: the catalog provenance rail for
// cacheable workflow node executions (engine.py _register_cache_run
// L735, wired into RunEngine via the CacheRunRail seam). Every cacheable
// node with a cache identity books a `workflow.node.<action>` run on the
// catalog — begin/complete like any other run — so cross-run reuse is
// traceable through the SAME provenance store freshness reads. The rail
// complements the provider's own finer-grained run; it never replaces it
// (receipt.catalog_run_id keeps the first id it recorded).
//
// Fail-closed where it matters, honest where it doesn't: the engine
// swallows rail failures (execution stays valid; reuse for that node is
// store-limited — Python logs an exception and continues; this library's
// no-log-sink parity keeps the swallow).
//
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>
#include <pwb/workflow_engine/run_engine.hpp>
#include <pwb/workflow_runtime/catalog_seam.hpp>

#include <string>
#include <vector>

namespace pwb::closure_workflow {

class CatalogCacheRunRail : public pwb::workflow_engine::CacheRunRail {
public:
    explicit CatalogCacheRunRail(
        pwb::workflow_runtime::CatalogRepository& repository)
        : repository_(repository) {}

    // register_run("workflow.node.<action>", inputs, parameters,
    //              generator) + update_run_status("complete"); returns
    // the rail run id. Throws propagate to the engine's best-effort
    // catch.
    [[nodiscard]] std::string register_cache_run(
        const std::string& operation,
        const std::vector<std::string>& input_version_ids,
        const pwb::domain::Json& parameters,
        const std::string& generator_version) override;

private:
    pwb::workflow_runtime::CatalogRepository& repository_;
};

}  // namespace pwb::closure_workflow
