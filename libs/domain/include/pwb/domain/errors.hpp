// Error taxonomy for the data kernel (contracts.md §4).
#pragma once

#include <nlohmann/json.hpp>

#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace pwb::domain {

enum class ErrorCode {
    Ok = 0,
    InvalidArgument,
    NotFound,
    ConflictBaseVersion,
    ImmutableVersion,
    DuplicateOperation,
    UnsafeId,
    PathEscape,
    IoError,
    CorruptJson,
    CorruptDatabase,
    FutureSchema,
    RecoveryRequired,
    Cancelled,
    Unknown,
};

inline constexpr std::string_view to_string(ErrorCode code) {
    switch (code) {
        case ErrorCode::Ok: return "ok";
        case ErrorCode::InvalidArgument: return "invalid_argument";
        case ErrorCode::NotFound: return "not_found";
        case ErrorCode::ConflictBaseVersion: return "conflict_base_version";
        case ErrorCode::ImmutableVersion: return "immutable_version";
        case ErrorCode::DuplicateOperation: return "duplicate_operation";
        case ErrorCode::UnsafeId: return "unsafe_id";
        case ErrorCode::PathEscape: return "path_escape";
        case ErrorCode::IoError: return "io_error";
        case ErrorCode::CorruptJson: return "corrupt_json";
        case ErrorCode::CorruptDatabase: return "corrupt_database";
        case ErrorCode::FutureSchema: return "future_schema";
        case ErrorCode::RecoveryRequired: return "recovery_required";
        case ErrorCode::Cancelled: return "cancelled";
        case ErrorCode::Unknown: return "unknown";
    }
    return "unknown";
}

struct DataError {
    ErrorCode code = ErrorCode::Unknown;
    std::string message;
    nlohmann::ordered_json detail = nlohmann::ordered_json::object();

    DataError() = default;
    DataError(ErrorCode c, std::string msg) : code(c), message(std::move(msg)) {}
    DataError(ErrorCode c, std::string msg, nlohmann::ordered_json d)
        : code(c), message(std::move(msg)), detail(std::move(d)) {}

    bool ok() const noexcept { return code == ErrorCode::Ok; }
};

// A minimal expected<T, DataError>. T needs to be movable, not
// default-constructible (v3: session handles are not default-constructible).
template <typename T>
class Result {
public:
    Result(T value) : value_(std::move(value)) {}
    Result(DataError error) : error_(std::move(error)) {}

    bool is_ok() const noexcept { return value_.has_value(); }
    explicit operator bool() const noexcept { return is_ok(); }
    T& value() & { return *value_; }
    const T& value() const& { return *value_; }
    T&& value() && { return std::move(*value_); }
    const DataError& error() const { return *error_; }
    DataError& error() { return *error_; }

private:
    std::optional<T> value_;
    std::optional<DataError> error_;
};

class DataException : public std::runtime_error {
public:
    explicit DataException(DataError error)
        : std::runtime_error(error.message), error_(std::move(error)) {}
    const DataError& error() const noexcept { return error_; }

private:
    DataError error_;
};

}  // namespace pwb::domain
