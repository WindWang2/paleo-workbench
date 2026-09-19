#pragma once

// pwb::science_service — result publication (CONV-28): the local-persistence
// / mock publisher over the frozen pwb::science IResultPublisherV1 contract.
//
// DirectoryEnvelopePublisher writes, per request id:
//   <root>/<request_id>/envelope.json  — the service result envelope (the
//                                        "envelope" ProducedRecord)
//   <root>/<request_id>/result.json    — full AlgorithmResultV1 debug dump
//                                        (provenance, diagnostics, records)
//   <root>/<request_id>/records/<name> — any additional ProducedRecords
//   <root>/<request_id>/failure.json   — terminal failures/cancellations
// Every file lands through a temp-file + rename atomic write; a publisher
// crash never leaves a half-written artifact that a later reader could
// mistake for a complete publication. This is the "local persistence / mock
// publisher" of the CONV-28 acceptance loop — the production catalog adapter
// (data line) implements the same interface against the real catalog.

#include <pwb/science/publisher.hpp>
#include <pwb/science/types.hpp>

#include <filesystem>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace pwb::science_service {

class DirectoryEnvelopePublisher : public science::IResultPublisherV1 {
public:
    // Creates `root` (parents included). Throws std::filesystem::/
    // std::runtime_error on unwritable targets — a publisher that silently
    // drops results would violate the publish-before-terminal contract.
    explicit DirectoryEnvelopePublisher(std::filesystem::path root);

    void publish_success(const science::AlgorithmResultV1& result) override;
    void publish_failure(const science::IResultPublisherV1::Failure& failure) override;

    [[nodiscard]] const std::filesystem::path& root() const { return root_; }
    // Directory of the most recent publication (empty before the first).
    [[nodiscard]] std::filesystem::path last_request_dir() const;

private:
    std::filesystem::path request_dir(const std::string& request_id) const;
    static void atomic_write(const std::filesystem::path& target,
                             const std::string& content);

    std::filesystem::path root_;
    mutable std::mutex mutex_;
    std::filesystem::path last_dir_;
};

// Capture publisher for tests / workflow adapters that want the results
// in-memory. Thread-safe.
class InMemoryCapturePublisher : public science::IResultPublisherV1 {
public:
    void publish_success(const science::AlgorithmResultV1& result) override;
    void publish_failure(const science::IResultPublisherV1::Failure& failure) override;

    [[nodiscard]] std::vector<science::AlgorithmResultV1> successes() const;
    [[nodiscard]] std::vector<science::IResultPublisherV1::Failure> failures() const;

private:
    mutable std::mutex mutex_;
    std::vector<science::AlgorithmResultV1> successes_;
    std::vector<science::IResultPublisherV1::Failure> failures_;
};

}  // namespace pwb::science_service
