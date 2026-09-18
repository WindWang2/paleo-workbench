#pragma once

// pwb::science_service — internal support shared by the service sources.
// Not installed, not part of the public API.

#include <pwb/science/algorithm.hpp>
#include <pwb/science/outcome.hpp>
#include <pwb/science/types.hpp>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <exception>
#include <functional>
#include <stdexcept>
#include <stop_token>
#include <string>
#include <vector>

namespace pwb::science_service::detail {

// ISO-8601 UTC timestamp with millisecond precision
// (2026-09-18T12:34:56.789Z) — matches the science SDK provenance format.
[[nodiscard]] inline std::string utc_now_iso() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t secs = std::chrono::system_clock::to_time_t(now);
    const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                        now.time_since_epoch())
                        .count() % 1000;
    std::tm tm_buf{};
#if defined(_WIN32)
    gmtime_s(&tm_buf, &secs);
#else
    gmtime_r(&secs, &tm_buf);
#endif
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                  tm_buf.tm_year + 1900, tm_buf.tm_mon + 1, tm_buf.tm_mday,
                  tm_buf.tm_hour, tm_buf.tm_min, tm_buf.tm_sec,
                  static_cast<int>(ms));
    return buf;
}

[[nodiscard]] inline std::uint64_t epoch_ms() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<
        std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch())
        .count());
}

// One error diagnostic with a stable code.
[[nodiscard]] inline science::Diagnostic error_diag(
    const std::string& code, const std::string& message) {
    science::Diagnostic d;
    d.code = code;
    d.message = message;
    d.severity = "error";
    return d;
}

[[nodiscard]] inline science::Diagnostic warning_diag(
    const std::string& code, const std::string& message) {
    science::Diagnostic d;
    d.code = code;
    d.message = message;
    d.severity = "warning";
    return d;
}

[[nodiscard]] inline science::AlgorithmError make_error(
    const std::string& code, const std::string& message) {
    science::AlgorithmError err;
    err.diagnostics.push_back(error_diag(code, message));
    return err;
}

// Stage guard: observes cancellation at service stage boundaries and reports
// progress. A cancelled request maps to TaskCancelled with the stage name.
inline bool stage_guard(const std::stop_token& stop,
                        const science::ProgressSink& progress, double fraction,
                        const char* stage) {
    if (progress) {
        science::ProgressReport report;
        report.fraction = fraction;
        report.stage = stage;
        progress(report);
    }
    return stop.stop_requested();
}

// Run `fn` translating the frozen kernel exceptions into AlgorithmError with
// `code` (message = exception text, which is contract). std::bad_alloc is
// deliberately NOT swallowed — it propagates to abort the request cleanly.
template <typename T>
[[nodiscard]] science::Result<T> catch_kernel(const std::string& code,
                                              const std::function<T()>& fn) {
    try {
        return fn();
    } catch (const std::bad_alloc&) {
        throw;
    } catch (const std::invalid_argument& e) {
        return science::AlgorithmError{
            {error_diag(code, std::string("ValueError: ") + e.what())}};
    } catch (const std::out_of_range& e) {
        return science::AlgorithmError{
            {error_diag(code, std::string("KeyError: ") + e.what())}};
    } catch (const std::runtime_error& e) {
        return science::AlgorithmError{{error_diag(code, e.what())}};
    } catch (const std::exception& e) {
        return science::AlgorithmError{{error_diag(code, e.what())}};
    }
}

}  // namespace pwb::science_service::detail
