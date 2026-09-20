// pwb::closure_science — catalog-backed result publisher for the science
// services (the CONV-28 IResultPublisherV1 seam, closed with the real
// persistence channel).
//
// Success: the request directory contract holds exactly like the local
// DirectoryEnvelopePublisher (<root>/<request_id>/{envelope,records/*,
// result}.json, atomic writes) — and the result additionally lands in the
// catalog: one DataRun (operation = algorithm id, input lineage from the
// provenance refs, terminal status) + one DERIVED DataVersion pointing at
// the request directory (the envelope.json member is registered; per-record
// files stay on the directory side of the contract), persisted through the
// caller's SaveHook in one dirty set.
// Failure: the run records failed (or cancelled when flagged) with the
// failure diagnostics — a failed science run never produces an output
// version.
#pragma once

#include <pwb/catalog/apply_changes.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/science/publisher.hpp>

#include <filesystem>
#include <mutex>
#include <string>

namespace pwb::closure_science {

class CatalogEnvelopePublisher : public pwb::science::IResultPublisherV1 {
public:
    // `publish_root` is the directory-contract root (typically
    // <artifacts>/derived/science); rows are persisted through *save* over
    // *document* (paths are recorded project-relative when project_dir is
    // set).
    CatalogEnvelopePublisher(catalog::CatalogDocument& document,
                             catalog::SaveHook save,
                             std::filesystem::path publish_root,
                             std::filesystem::path project_dir = {});

    void publish_success(const pwb::science::AlgorithmResultV1& result) override;
    void publish_failure(const Failure& failure) override;

    // The catalog version/run id of the last publish ("" when none). The
    // publisher may be invoked from a TaskRuntime worker thread — the
    // getters take the same lock.
    [[nodiscard]] std::string last_output_version_id() const;
    [[nodiscard]] std::string last_run_id() const;

private:
    catalog::CatalogDocument& document_;
    catalog::SaveHook save_;
    std::filesystem::path publish_root_;
    std::filesystem::path project_dir_;
    mutable std::mutex mutex_;
    std::string last_output_version_id_;
    std::string last_run_id_;
};

}  // namespace pwb::closure_science
