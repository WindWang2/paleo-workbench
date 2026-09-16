#pragma once

// Algorithm registry + request validation against a descriptor.

#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <pwb/science/algorithm.hpp>

namespace pwb::science {

// Thread-safe registry. Registration validates the descriptor shape; a
// duplicate algorithm_id (any version) is rejected — versioning happens by
// bumping the descriptor, not by registering siblings.
class AlgorithmRegistry {
public:
    // Returns "" on success or the rejection reason.
    [[nodiscard]] std::string register_algorithm(std::unique_ptr<IAlgorithm> algorithm);
    [[nodiscard]] IAlgorithm* find(const std::string& algorithm_id) const;
    [[nodiscard]] std::vector<std::string> algorithm_ids() const;

private:
    mutable std::mutex mutex_;
    std::map<std::string, std::unique_ptr<IAlgorithm>> algorithms_;
};

// Descriptor shape validation: id pattern, non-empty version, port names
// unique, parameter names unique. Returns problems (empty = valid).
[[nodiscard]] std::vector<std::string> validate_descriptor(const AlgorithmDescriptor& descriptor);

// Request validation against a descriptor: id/version match, required volume
// inputs present with nonzero shape, params parse and respect bounds.
// Returns error diagnostics (empty = valid).
[[nodiscard]] std::vector<Diagnostic> validate_request(const AlgorithmDescriptor& descriptor,
                                                       const AlgorithmRequestV1& request);

// Typed parameter lookup after validate_request passed. Falls back to the
// parameter's default_json when the request does not carry the param.
[[nodiscard]] Result<long long> request_param_integer(const AlgorithmRequestV1& request,
                                                      const ParamSpec& spec);
[[nodiscard]] Result<double> request_param_number(const AlgorithmRequestV1& request,
                                                  const ParamSpec& spec);

} // namespace pwb::science
