#pragma once

// Minimal result type for algorithm termination states. Success carries an
// AlgorithmResultV1; failure carries diagnostics; cancellation is distinct so
// a cancelled run can never be mistaken for a produced result.

#include <cassert>
#include <utility>
#include <variant>

#include <pwb/science/types.hpp>

namespace pwb::science {

struct AlgorithmError {
    std::vector<Diagnostic> diagnostics; // at least one "error" entry
};

struct TaskCancelled {
    std::string stage; // where the cancellation was observed
};

template <typename T>
class Result {
public:
    Result(T value) : value_(std::move(value)) {}
    Result(AlgorithmError error) : value_(std::move(error)) {}
    Result(TaskCancelled cancelled) : value_(std::move(cancelled)) {}

    [[nodiscard]] bool has_value() const noexcept {
        return std::holds_alternative<T>(value_);
    }
    [[nodiscard]] bool is_error() const noexcept {
        return std::holds_alternative<AlgorithmError>(value_);
    }
    [[nodiscard]] bool is_cancelled() const noexcept {
        return std::holds_alternative<TaskCancelled>(value_);
    }

    [[nodiscard]] T& value() & {
        assert(has_value());
        return std::get<T>(value_);
    }
    [[nodiscard]] const T& value() const& {
        assert(has_value());
        return std::get<T>(value_);
    }
    [[nodiscard]] AlgorithmError& error() {
        assert(is_error());
        return std::get<AlgorithmError>(value_);
    }
    [[nodiscard]] const AlgorithmError& error() const {
        assert(is_error());
        return std::get<AlgorithmError>(value_);
    }
    [[nodiscard]] TaskCancelled& cancelled() {
        assert(is_cancelled());
        return std::get<TaskCancelled>(value_);
    }

private:
    std::variant<T, AlgorithmError, TaskCancelled> value_;
};

} // namespace pwb::science
