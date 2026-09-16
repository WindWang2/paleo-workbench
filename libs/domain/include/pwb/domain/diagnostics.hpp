// Timestamps and diagnostics shared by every module.
#pragma once

#include <nlohmann/json.hpp>

#include <chrono>
#include <string>
#include <vector>

namespace pwb::domain {

// `datetime.now(timezone.utc).isoformat()` — six-digit microseconds, +00:00
// offset, matching the Python persistence byte-for-byte.
std::string now_iso8601();
std::string fixed_iso8601_for_tests();

// One structured diagnostic: severity + code + message + optional detail.
// Snapshots carry diagnostics instead of throwing — the caller decides how
// to surface (read-only downgrade, CLI exit code, test assertion).
struct Diagnostic {
    enum class Severity { Info, Warning, Error };
    Severity severity = Severity::Warning;
    std::string code;
    std::string message;
    nlohmann::ordered_json detail = nlohmann::ordered_json::object();

    nlohmann::ordered_json to_json() const;
    static Diagnostic info(std::string code, std::string message,
                           nlohmann::ordered_json detail = nullptr) {
        return {Severity::Info, std::move(code), std::move(message),
                std::move(detail)};
    }
    static Diagnostic warning(std::string code, std::string message,
                              nlohmann::ordered_json detail = nullptr) {
        return {Severity::Warning, std::move(code), std::move(message),
                std::move(detail)};
    }
    static Diagnostic error(std::string code, std::string message,
                            nlohmann::ordered_json detail = nullptr) {
        return {Severity::Error, std::move(code), std::move(message),
                std::move(detail)};
    }
};

using DiagnosticList = std::vector<Diagnostic>;

inline constexpr std::string_view to_string(Diagnostic::Severity severity) {
    switch (severity) {
        case Diagnostic::Severity::Info: return "info";
        case Diagnostic::Severity::Warning: return "warning";
        case Diagnostic::Severity::Error: return "error";
    }
    return "warning";
}

}  // namespace pwb::domain
