#pragma once

// CatalogResultPublisher — A's adapter implementing C's science
// IResultPublisherV1 over B's run lifecycle + single-result publish
// (v3-contracts.md §5):
//   publish_success  -> register_run (idempotent) -> write ONE PWBVOL1
//                       payload -> publish_run_result (run turns "complete"
//                       only after payload+catalog+bindings are durable)
//   publish_failure  -> register_run (idempotent) -> finish_run(Failed |
//                       Cancelled); never a success version
//
// Host duties (this class never guesses): set_request_context() supplies
// the input geometry (axis units/origin/step — ProducedVolume carries only
// data+shape) and the input catalog version ids BEFORE submit. publish()
// is called on the worker thread by C's runtime; it touches no GUI. The
// store it publishes through (PwbDataStore -> CommitCoordinator /
// CatalogRepository) serializes every write internally since #1380/#1381,
// so worker-thread publication is safe against concurrent GUI commits on
// the same store.

#include <map>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/science/publisher.hpp>
#include <pwb/science/types.hpp>
#include <pwb/viz/seismic_volume.hpp>

namespace pwb::application {

// Publication did NOT reach the durable state. C's TaskRuntime contract
// turns a throwing publish_success into a failed task (stable code
// "publisher.publish_threw") instead of a false succeeded/published; for
// failure/cancel outcomes the algorithm verdict stands and the throw is
// recorded as a diagnostic. The publisher's Outcome map keeps the same
// error for tests/UI observability.
class CatalogPublishError : public std::runtime_error {
public:
    explicit CatalogPublishError(const std::string& what)
        : std::runtime_error(what) {}
};

struct RequestContext {
    pwb::viz::VolumeGeometryV1 geometry;      // input volume axes
    std::vector<std::string> input_version_ids;
    std::map<std::string, std::string> params_json;
};

class CatalogResultPublisher : public pwb::science::IResultPublisherV1 {
public:
    // staged_dir: where PWBVOL1 payloads land before B moves them.
    CatalogResultPublisher(std::shared_ptr<PwbDataStore> store,
                           std::filesystem::path staged_dir);

    // ---- host-side context registration (before submit) -------------------
    void set_request_context(const std::string& request_id,
                             RequestContext context);

    // ---- C's IResultPublisherV1 (worker thread) ---------------------------
    void publish_success(const pwb::science::AlgorithmResultV1& result) override;
    void publish_failure(const Failure& failure) override;

    // ---- observability for tests/UI ---------------------------------------
    struct Outcome {
        bool success = false;
        std::string run_id;
        std::string version_id;
        std::string asset_id;
        std::string error;
    };
    Outcome outcome(const std::string& request_id) const;

private:
    pwb::domain::RunId run_id_for(const std::string& request_id) const;

    // Records the outcome, terminates an already-durable "running" run as
    // Failed (best effort — a failing finish_run leaves the run "running",
    // which is B's explicit recovery-pending state), then throws
    // CatalogPublishError so the runtime never reports a false success.
    [[noreturn]] void fail(const std::string& request_id, Outcome outcome,
                           bool terminate_run, std::string message);

    std::shared_ptr<PwbDataStore> store_;
    std::filesystem::path staged_dir_;
    mutable std::mutex mutex_;
    std::map<std::string, RequestContext> contexts_;
    std::map<std::string, Outcome> outcomes_;
};

}  // namespace pwb::application
