#include <pwb/providers/errors.hpp>

namespace pwb::providers {

namespace {
// Python repr() of a plain identifier string: single quotes.
std::string quoted(std::string_view value) {
    return "'" + std::string(value) + "'";
}

std::string join_problems(const std::vector<std::string>& problems) {
    std::string joined;
    for (std::size_t i = 0; i < problems.size(); ++i) {
        if (i != 0) joined += "; ";
        joined += problems[i];
    }
    return joined;
}
}  // namespace

InvalidProviderError::InvalidProviderError(std::string provider_id,
                                           std::vector<std::string> problems)
    : ProviderError("provider " + quoted(provider_id) + " failed validation: " +
                    join_problems(problems)),
      provider_id_(std::move(provider_id)),
      problems_(std::move(problems)) {}

DuplicateProviderError::DuplicateProviderError(std::string provider_id,
                                               std::string existing_version)
    : ProviderError("provider " + quoted(provider_id) + " already registered (version " +
                    existing_version + ")"),
      provider_id_(std::move(provider_id)),
      existing_version_(std::move(existing_version)) {}

UnknownProviderError::UnknownProviderError(std::string provider_id, std::string family)
    : ProviderError("no provider " + quoted(provider_id) +
                    (family.empty() ? "" : " in family " + quoted(family))),
      provider_id_(std::move(provider_id)),
      family_(std::move(family)) {}

ProviderRejectedInputError::ProviderRejectedInputError(std::string provider_id,
                                                       std::string reason)
    : ProviderError("provider " + quoted(provider_id) + " rejected inputs: " + reason),
      provider_id_(std::move(provider_id)),
      reason_(std::move(reason)) {}

InvalidParametersError::InvalidParametersError(std::string provider_id,
                                               std::vector<std::string> problems)
    : ProviderError("parameters for " + quoted(provider_id) +
                    " failed schema validation: " + join_problems(problems)),
      provider_id_(std::move(provider_id)),
      problems_(std::move(problems)) {}

ProviderExecutionError::ProviderExecutionError(std::string provider_id,
                                               std::string cause_type_name,
                                               std::string cause_message)
    : ProviderError("provider " + quoted(provider_id) + " failed: " +
                    std::move(cause_type_name) + ": " + std::move(cause_message)),
      provider_id_(std::move(provider_id)) {}

ProviderVerificationError::ProviderVerificationError(std::string provider_id,
                                                     std::string reason)
    : ProviderError("provider " + quoted(provider_id) + " verification failed: " + reason),
      provider_id_(std::move(provider_id)),
      reason_(std::move(reason)) {}

std::string python_exception_class(const std::exception& exc) {
    // Most-derived first; mirrors the house raise_class convention that maps
    // C++ std exception types onto the Python names used in messages.
    if (dynamic_cast<const std::invalid_argument*>(&exc) != nullptr) return "ValueError";
    if (dynamic_cast<const std::out_of_range*>(&exc) != nullptr) return "IndexError";
    if (dynamic_cast<const std::overflow_error*>(&exc) != nullptr) return "OverflowError";
    if (dynamic_cast<const std::bad_alloc*>(&exc) != nullptr) return "MemoryError";
    if (dynamic_cast<const std::runtime_error*>(&exc) != nullptr) return "RuntimeError";
    if (dynamic_cast<const std::logic_error*>(&exc) != nullptr) return "LogicError";
    return "Exception";
}

}  // namespace pwb::providers
