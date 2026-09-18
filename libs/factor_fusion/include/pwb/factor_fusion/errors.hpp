#pragma once

// Python exception-class mirrors for the factor_fusion surface. The module
// raises ValueError everywhere except the empty-grid IndexError edge frozen
// from _aligned_or_raise([]).

#include <stdexcept>
#include <string>

namespace pwb::factor_fusion {

struct PyError : std::runtime_error {
    using std::runtime_error::runtime_error;
    virtual const char* python_class() const = 0;
};

struct ValueError : PyError {
    using PyError::PyError;
    const char* python_class() const override { return "ValueError"; }
};

struct IndexError : PyError {
    using PyError::PyError;
    const char* python_class() const override { return "IndexError"; }
};

}  // namespace pwb::factor_fusion
