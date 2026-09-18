// Error types for the well curve-ops kernels (CONV-11).
// Message texts are frozen against the Python modules (see
// docs/development/cpp-conversion-swarm-20/ledgers/11-decisions.md D10).
#pragma once

#include <stdexcept>
#include <string>

#include <pwb/well_science/depth_unit.hpp>

namespace pwb::well_science {

// Base for every frozen-message refusal raised by the curve kernels.
class CurveOpError : public std::runtime_error {
public:
    explicit CurveOpError(const std::string& what) : std::runtime_error(what) {}
};

// V6 P0-3 typed refusal: a unit-dependent operation met an unknown/undeclared
// depth unit. Carries the classified info and the refusing operation name so
// diagnostics stay locatable (mirrors well_science.UnknownDepthUnitError).
class UnknownDepthUnitError : public CurveOpError {
public:
    UnknownDepthUnitError(DepthUnitInfo info, std::string operation);

    const DepthUnitInfo& info() const { return info_; }
    const std::string& operation() const { return operation_; }

private:
    DepthUnitInfo info_;
    std::string operation_;
};

}  // namespace pwb::well_science
