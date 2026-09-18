// Error types mirroring the Python exception classes the contract modules
// raise. C++ class names match the Python classes so oracle "raises" fields
// compare 1:1, and the inheritance mirrors Python (ModelPackageError and
// UnicodeDecodeError are ValueError subclasses; InputContractError too).
#pragma once

#include <stdexcept>
#include <string>

namespace pwb::prediction {

// Built-in ValueError paths outside ModelPackageError's own class
// (e.g. int("abc") inside merged_sample_count accumulation, batch < 1).
class ValueError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// paleo_workbench.prediction.model_package.ModelPackageError (ValueError).
class ModelPackageError : public ValueError {
public:
    using ValueError::ValueError;
};

// Propagated (unwrapped) by load_manifest_dict on non-UTF-8 manifest bytes —
// Python lets the built-in UnicodeDecodeError (a ValueError) escape instead
// of converting it to ModelPackageError (21-decisions.md D8).
class UnicodeDecodeError : public ValueError {
public:
    using ValueError::ValueError;
};

// Raised where the Python source would hit a built-in AttributeError
// (truthy non-mapping inputs, e.g. inputs="junk").
class AttributeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Built-in TypeError paths (e.g. iterating a non-iterable schema value).
class TypeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Native prediction runtime: a grid descriptor / band mapping violates the
// model package contract. Mirrors input_contract.py's InputContractError
// (a ValueError subclass) for callers that switch on the class.
class InputContractError : public ValueError {
public:
    using ValueError::ValueError;
};

}  // namespace pwb::prediction
