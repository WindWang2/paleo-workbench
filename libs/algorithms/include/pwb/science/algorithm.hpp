#pragma once

// Execution interface: descriptor + cancellable run with progress.

#include <functional>
#include <stop_token>

#include <pwb/science/outcome.hpp>
#include <pwb/science/types.hpp>

namespace pwb::science {

using ProgressSink = std::function<void(const ProgressReport&)>;

class IAlgorithm {
public:
    virtual ~IAlgorithm() = default;

    // Immutable for the lifetime of the object; every call returns the same
    // logical descriptor.
    [[nodiscard]] virtual const AlgorithmDescriptor& descriptor() const = 0;

    // Terminal states: value => success; AlgorithmError => validation or
    // execution failure (diagnostics carry stable codes); TaskCancelled =>
    // stop was requested at a safe boundary. Implementations must not let
    // C++ exceptions escape across this boundary.
    virtual Result<AlgorithmResultV1> run(const AlgorithmRequestV1& request,
                                          ProgressSink progress,
                                          std::stop_token stop) = 0;
};

} // namespace pwb::science
