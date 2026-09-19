// Provider SDK error hierarchy — C++ port of paleo_workbench/providers/errors.py.
//
// All errors are part of the stable SDK surface: hosts catch them, callers map
// them to explainable results, and the registry uses them to quarantine bad
// providers instead of refusing to boot. Message strings are byte-identical
// to the Python oracle (house convention for ports); the {id!r} reprs are the
// single-quoted Python forms.
#pragma once

#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::providers {

class ProviderError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class InvalidProviderError : public ProviderError {
public:
    InvalidProviderError(std::string provider_id, std::vector<std::string> problems);

    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::vector<std::string>& problems() const noexcept { return problems_; }

private:
    std::string provider_id_;
    std::vector<std::string> problems_;
};

class DuplicateProviderError : public ProviderError {
public:
    DuplicateProviderError(std::string provider_id, std::string existing_version);

    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::string& existing_version() const noexcept { return existing_version_; }

private:
    std::string provider_id_;
    std::string existing_version_;
};

class UnknownProviderError : public ProviderError {
public:
    // family: optional scope hint ("no provider 'x' in family 'exporter'").
    UnknownProviderError(std::string provider_id, std::string family = "");

    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::string& family() const noexcept { return family_; }

private:
    std::string provider_id_;
    std::string family_;
};

class ProviderRejectedInputError : public ProviderError {
public:
    ProviderRejectedInputError(std::string provider_id, std::string reason);

    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::string& reason() const noexcept { return reason_; }

private:
    std::string provider_id_;
    std::string reason_;
};

class InvalidParametersError : public ProviderError {
public:
    InvalidParametersError(std::string provider_id, std::vector<std::string> problems);

    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::vector<std::string>& problems() const noexcept { return problems_; }

private:
    std::string provider_id_;
    std::vector<std::string> problems_;
};

class ProviderExecutionError : public ProviderError {
public:
    // cause_type_name mirrors Python's type(cause).__name__ inside the message
    // ("provider 'x' failed: ValueError: boom").
    ProviderExecutionError(std::string provider_id, std::string cause_type_name,
                           std::string cause_message);

    const std::string& provider_id() const noexcept { return provider_id_; }

private:
    std::string provider_id_;
};

class ProviderVerificationError : public ProviderError {
public:
    ProviderVerificationError(std::string provider_id, std::string reason);

    const std::string& provider_id() const noexcept { return provider_id_; }
    const std::string& reason() const noexcept { return reason_; }

private:
    std::string provider_id_;
    std::string reason_;
};

// Cooperative cancellation (#1137): a first-class outcome, never a failure.
// The executor rethrows it unwrapped and lands the catalog run in
// "cancelled". Aligned with the workflow_engine Cancelled exception.
class TaskCancelled : public std::runtime_error {
public:
    explicit TaskCancelled(const std::string& message) : std::runtime_error(message) {}
};

// Admission refused by the resource port (pressure shedding is first-class,
// mirroring ResourceExhausted in the Python runtime). Raised by the injected
// IAdmissionPort; the executor propagates it unwrapped.
class AdmissionRejected : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// Maps a caught std::exception to the Python exception class name used in
// ProviderExecutionError messages (house raise_class convention).
std::string python_exception_class(const std::exception& exc);

}  // namespace pwb::providers
