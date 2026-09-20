// cache_run_rail.cpp — see include/pwb/closure_workflow/cache_run_rail.hpp.

#include <pwb/closure_workflow/cache_run_rail.hpp>

#include <stdexcept>

namespace pwb::closure_workflow {

std::string CatalogCacheRunRail::register_cache_run(
    const std::string& operation,
    const std::vector<std::string>& input_version_ids,
    const pwb::domain::Json& parameters,
    const std::string& generator_version) {
    const std::string run_id = repository_.register_run(
        operation, input_version_ids, parameters, generator_version,
        "running");
    // Complete like any other run — the node itself already succeeded
    // (the engine registers the rail only on the receipt path).
    repository_.update_run_status(run_id, "complete");
    return run_id;
}

}  // namespace pwb::closure_workflow
