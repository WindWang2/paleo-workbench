#pragma once

// pwb::interchange — shared vocabulary of the import/export lifecycle
// (conv-14b): the narrow slice of paleo_workbench/interchange/contracts.py
// the archive/package/model-adapter kernels consume. ImportPlan /
// InspectionResult / SniffResult live in preflight.hpp (conv-14 first slice,
// slightly different C++ shape); everything else is ported here
// branch-for-branch, JSON key order included.

#include <pwb/domain/json.hpp>

#include <functional>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::interchange {

using pwb::domain::Json;

struct InterchangeError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// Raised when a format has no usable adapter or capability.
struct FormatNotSupportedError : InterchangeError {
    using InterchangeError::InterchangeError;
};

// Raised when a cancelled operation reaches a cancellation checkpoint.
struct CancelledError : InterchangeError {
    using InterchangeError::InterchangeError;
};

// Cooperative cancellation handle shared across batch/adapter operations.
// checkpoint() throws CancelledError at well-defined checkpoints so callers
// never observe a partially committed result (all writers use temp +
// atomic rename). Thread-safe: cancel() may fire from another thread.
class CancelToken {
public:
    void cancel(std::string reason = "cancelled");
    bool cancelled() const;
    // Python property `reason` ("" until cancelled).
    std::string reason() const;
    void checkpoint() const;  // throws CancelledError(reason or "cancelled")

private:
    mutable std::mutex mutex_;
    bool cancelled_ = false;
    std::string reason_;
};

// Process-wide NULL_CANCEL (Python module-level NULL_CANCEL singleton).
CancelToken& null_cancel();

using ProgressCallback = std::function<void(double fraction, std::string message)>;

// What an adapter honestly supports (declared, never guessed).
struct FormatCapability {
    bool read = false;
    bool inspect = false;
    bool import_data = false;
    bool can_export = false;  // JSON key "export" ("export" is a C++20 keyword)
    bool roundtrip_verify = false;
    std::string notes;

    Json to_dict() const;
};

enum class VerificationState { VERIFIED, VERIFIED_WITH_WARNINGS, FAILED, UNVERIFIED };

std::string_view to_string(VerificationState state);

struct VerificationCheck {
    std::string name;
    bool passed = false;
    std::string detail;

    Json to_dict() const;
};

// Structural re-open result of an exported artifact.
struct ExportVerification {
    VerificationState state = VerificationState::UNVERIFIED;
    std::vector<VerificationCheck> checks;
    std::vector<std::string> warnings;
    std::string detail;

    bool ok() const;
    // Python ExportVerification.summary() layout (key order preserved).
    Json summary() const;

    static ExportVerification unverified(std::string detail);
    static ExportVerification failed(std::vector<VerificationCheck> checks,
                                     std::string detail = "");
};

// Serializable statement of what an export will produce.
struct ExportPlan {
    std::string format_id;
    std::string source_path;
    std::string target_path;
    long long estimated_bytes = 0;
    Json options = Json::object();
    std::vector<std::string> warnings;
    std::vector<std::string> source_version_ids;  // catalog lineage
    std::string linked_id;  // domain entity this export belongs to (e.g. task id)

    Json to_dict() const;
};

}  // namespace pwb::interchange
