#pragma once

// AlgorithmRunner — the application-side composition of the compute loop:
// one TaskRuntime owning the worker set, kernels registered by the host
// (the app layer registers CPP-E's attribute factories; this class never
// names an algorithm family), and one CatalogResultPublisher per
// submission into the caller's real B store. Inputs are PWBVOL1 catalog
// versions; successful runs publish a durable result version through the
// real run lifecycle (register -> payload -> publish -> complete).

#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <pwb/application/adapters/catalog_publisher.hpp>
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/science/algorithm.hpp>
#include <pwb/workflow/task_runtime.hpp>

namespace pwb::application {

class AlgorithmRunner {
public:
    struct Outcome {
        bool known = false;    // request id ever submitted here
        std::string status;    // queued/running/succeeded/failed/cancelled
        std::string error_code;
        std::string run_id;    // B run row id (once registered)
        std::string version_id;  // published catalog version (success only)
        std::string error;     // publisher/kernel error detail, if any
    };

    AlgorithmRunner();
    ~AlgorithmRunner();

    AlgorithmRunner(const AlgorithmRunner&) = delete;
    AlgorithmRunner& operator=(const AlgorithmRunner&) = delete;

    // The runner owns the kernel instance it submits. Returns "" on
    // success or the reason (duplicate id, empty id, ...).
    std::string register_kernel(std::unique_ptr<pwb::science::IAlgorithm> kernel);

    struct AlgorithmInfo {
        std::string algorithm_id;
        std::string display_name;
        std::string version;
    };
    std::vector<AlgorithmInfo> algorithms() const;

    // Submits one run of `algorithm_id` over the PWBVOL1 catalog version
    // `input_version_id`, publishing into `store`. Returns the request id
    // ("" + *error on failure).
    std::string submit(const std::shared_ptr<PwbDataStore>& store,
                       const std::string& algorithm_id,
                       const std::map<std::string, std::string>& params,
                       const std::string& input_version_id,
                       std::string* error);

    // Polls one run. Terminal outcomes stay queryable; the input payload
    // keep-alive is released once terminal.
    Outcome outcome(const std::string& request_id);

private:
    struct Pending {
        pwb::workflow::TaskHandle handle;
        std::shared_ptr<pwb::application::CatalogResultPublisher> publisher;
        std::shared_ptr<std::vector<float>> samples;  // input keep-alive
    };

    std::map<std::string, std::shared_ptr<pwb::science::IAlgorithm>> kernels_;
    pwb::workflow::TaskRuntime runtime_;
    mutable std::mutex mutex_;
    std::map<std::string, Pending> pending_;
    std::map<std::string, Outcome> finished_;
};

}  // namespace pwb::application
