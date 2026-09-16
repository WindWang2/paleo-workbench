#pragma once

// C-side result publisher port (CPP-A contract §5). C (feat/cpp-science-viz)
// defines the abstraction semantics; A implements the adapter that routes
// results into B's version transaction. Module-only in this round.

#include <string>
#include <vector>

namespace pwb::application {

struct ResultAssetV1 {
    std::string asset_path;
    std::string kind;         // e.g. "grid"|"curve"|"report"
    std::string sha256;
};

struct ProvenanceRecordV1 {
    std::string algorithm_id;
    std::string algorithm_version;
    std::vector<std::string> input_version_refs;
};

class IResultPublisher {
public:
    virtual ~IResultPublisher() = default;
    // Errors/cancellations must not fabricate a successful DataRun (C-side
    // contract); this port only carries the outcome downstream.
    virtual bool publish(const std::vector<ResultAssetV1>& assets,
                         const ProvenanceRecordV1& provenance,
                         std::string* new_version) = 0;
};

}  // namespace pwb::application
