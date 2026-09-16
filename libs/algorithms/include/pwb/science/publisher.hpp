#pragma once

// Result publication boundary. C defines the interface; A implements the
// adapter into B's versioned catalog transactions. C itself never touches
// SQLite or any persistence layer.

#include <string>

#include <pwb/science/types.hpp>

namespace pwb::science {

class IResultPublisherV1 {
public:
    struct Failure {
        std::string request_id;
        std::string code;      // e.g. "algorithm.error", "task.cancelled"
        std::string message;
        bool cancelled{false}; // true when the failure is a cancellation
    };

    // At most one publish_* call per request id. A cancelled or failed run
    // must be published as failure (visibility), never as success.
    virtual void publish_success(const AlgorithmResultV1& result) = 0;
    virtual void publish_failure(const Failure& failure) = 0;

protected:
    ~IResultPublisherV1() = default;
};

} // namespace pwb::science
