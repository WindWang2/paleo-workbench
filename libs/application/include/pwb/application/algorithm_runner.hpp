#pragma once

// AlgorithmRunner — the application-side composition of the compute loop,
// unified on QgsProcessingRegistry (CONV-QGIS-PROCESSING phase 4).
//
// Discovery AND execution both delegate to the Paleo Processing provider
// ("paleo"): the runner holds no kernel map — submit() maps the algorithm
// id onto its "paleo:<name>" Processing id and executes synchronously
// through pwb::qgis_processing::run_paleo_algorithm (worker-thread safe for
// the file-based paleo algorithms; see runner.hpp). Inputs are PWBVOL1
// catalog versions staged as packed float32 INPUT files; successful runs
// publish a durable result version through the real run lifecycle
// (register -> payload -> publish -> complete) via CatalogResultPublisher.
//
// submit() is SYNCHRONOUS: it returns only after compute + publication
// finished, so outcome() is terminal by then. GUI hosts wrap it in a
// background job body (MainWindow::superviseAttributeRun) instead of
// calling it on the GUI thread.

#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <pwb/application/adapters/catalog_publisher.hpp>
#include <pwb/application/adapters/data_store.hpp>
#include <pwb/science/algorithm.hpp>
#include <pwb/science/types.hpp>

class QgsProcessingFeedback;

namespace pwb::application {

class AlgorithmRunner {
public:
    struct Outcome {
        bool known = false;    // request id ever submitted here
        std::string status;    // succeeded/failed/cancelled
        std::string error_code;
        std::string run_id;    // B run row id (once registered)
        std::string version_id;  // published catalog version (success only)
        std::string error;     // publisher/kernel error detail, if any
    };

    AlgorithmRunner();
    ~AlgorithmRunner();

    AlgorithmRunner(const AlgorithmRunner&) = delete;
    AlgorithmRunner& operator=(const AlgorithmRunner&) = delete;

    // Cooperative cancellation hook, polled while the algorithm runs; the
    // GUI/job host bridges its cancel token here. When it flips true the
    // run's Processing feedback is cancelled and the kernel stops at its
    // next safe point (outcome status "cancelled").
    using CancelHook = std::function<bool()>;

    // Runs one `algorithm_id` over the PWBVOL1 catalog version
    // `input_version_id`, publishing into `store`, and BLOCKS until the
    // run + publication reached a terminal state. Accepts the Processing
    // id ("paleo:seismic_envelope") or the science id ("seismic.envelope").
    // Returns the request id ("" + *error on failure).
    std::string submit(const std::shared_ptr<PwbDataStore>& store,
                       const std::string& algorithm_id,
                       const std::map<std::string, std::string>& params,
                       const std::string& input_version_id, std::string* error,
                       CancelHook cancel_requested = nullptr);

    // Terminal outcome of one synchronous submit. Non-terminal states no
    // longer exist (the request is finished when submit returns), but the
    // query stays cheap and idempotent for polling hosts.
    Outcome outcome(const std::string& request_id);

    // BEGIN CONV-30 — cooperative cancellation of one run. Still honored:
    // cancels the active run's Processing feedback (any thread); false when
    // the request is unknown or already terminal. Hosts that pass a
    // CancelHook to submit() usually cancel through the hook instead.
    bool cancel(const std::string& request_id);
    // END CONV-30

private:
    // Registration of the live feedback of an in-flight submit so the
    // cancel() entry point can reach the kernel.
    void register_feedback(const std::string& request_id,
                           std::shared_ptr<QgsProcessingFeedback> feedback);
    void unregister_feedback(const std::string& request_id);

    mutable std::mutex mutex_;
    std::map<std::string, Outcome> finished_;
    // shared_ptr: cancel() copies under the lock and calls cancel()
    // outside it — the object must outlive that window even when submit()
    // concurrently finishes and unregisters.
    std::map<std::string, std::shared_ptr<QgsProcessingFeedback>> active_;
};

}  // namespace pwb::application
