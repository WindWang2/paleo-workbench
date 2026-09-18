// Provider execution context + cancellation surface — C++ port of
// paleo_workbench/providers/base.py (ProviderContext) and paths.py
// (resolve_contained_output, #1177).
//
// The context is a typed struct rather than the Python dataclass-with-dict:
// the two extension points Python carried in `extras` as live objects
// (admission lease #1146) are explicit non-owning fields here; `extras`
// remains a Json object for provider-defined lookup tables.
#pragma once

#include <pwb/domain/json.hpp>

#include <atomic>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>

#include <pwb/providers/errors.hpp>
#include <pwb/providers/refs.hpp>

namespace pwb::providers {

using Json = pwb::domain::Json;

// Cooperative cancellation token shared with hosts/schedulers.
class CancelToken {
public:
    void cancel() noexcept { cancelled_.store(true, std::memory_order_release); }
    bool is_cancelled() const noexcept {
        return cancelled_.load(std::memory_order_acquire);
    }
    // Throws TaskCancelled when cancelled (message mirrors the host scheduler's).
    void raise_if_cancelled() const {
        if (is_cancelled()) {
            throw TaskCancelled("operation cancelled");
        }
    }

private:
    std::atomic<bool> cancelled_{false};
};

// Catalog write port (the DataRun authority). Non-owning pointer in the
// context; null in catalog-less unit runs — providers must degrade
// gracefully. All methods may throw; the executor treats catalog failures as
// non-fatal (Python parity: records continue without run bookkeeping).
class ICatalogPort {
public:
    virtual ~ICatalogPort() = default;

    struct RunSpec {
        std::string operation;
        std::vector<std::string> input_version_ids;
        Json parameters = Json::object();
        std::string generator_version;
    };
    struct RunRef {
        std::string run_id;
    };

    virtual std::optional<RunRef> begin_run(const RunSpec& spec) = 0;
    // status: "complete" | "failed" | "cancelled"
    virtual void complete_run(const std::string& run_id, const std::string& status) = 0;
    // Providers register data outputs through the port inside execute().
    virtual std::optional<Json> register_intermediate(const std::string& run_id,
                                                      const std::string& name,
                                                      const std::string& path,
                                                      const std::string& kind,
                                                      const std::string& format) = 0;
};

// Resource admission port. The first-party Python ResourceGovernor is not
// ported; hosts inject an adapter over their own governor (or the no-op
// admission used by tests/catalog-less runs). admit() throws
// AdmissionRejected when pressure shedding refuses the request.
struct AdmissionRequest {
    std::string category;
    std::string title;
    double estimated_cpu_cores = 1.0;
    long long estimated_ram_bytes = 0;
    long long estimated_vram_bytes = 0;
    double io_weight = 1.0;
};

class IAdmissionLease {
public:
    virtual ~IAdmissionLease() = default;
    virtual void release() = 0;
    virtual const AdmissionRequest& request() const = 0;
};

class IAdmissionPort {
public:
    virtual ~IAdmissionPort() = default;
    virtual std::unique_ptr<IAdmissionLease> admit(const AdmissionRequest& request) = 0;
};

// Minimal observability seam. Python logs swallowed catalog bookkeeping
// failures and the #1146 under-reservation warning through `logging`; the
// C++ SDK exposes the same events through an injectable sink. Default is
// quiet; hosts install a sink at startup if they want the events.
using LogSink = std::function<void(const char* level, const std::string& message)>;
void set_log_sink(LogSink sink);
void log_event(const char* level, const std::string& message);

struct ProviderContext {
    ICatalogPort* catalog = nullptr;  // non-owning; may be null
    std::string workspace_root;       // containment root for file outputs
    std::string session_id;
    std::string run_id;  // DataRun id when the executor opened one
    std::function<void(double, const std::string&)> emit_progress;
    const CancelToken* cancel = nullptr;  // non-owning; may be null
    std::string work_dir;                 // scratch directory owned by this execution
    Json extras = Json::object();         // provider-defined lookup tables
    IAdmissionLease* admission_lease = nullptr;  // non-owning; enclosing lease (#1146)

    // Progress must never kill a provider: callback exceptions swallowed,
    // ratio clamped to [0, 1].
    void report_progress(double ratio, const std::string& message = "") const {
        if (emit_progress) {
            try {
                emit_progress(ratio < 0.0 ? 0.0 : (ratio > 1.0 ? 1.0 : ratio), message);
            } catch (...) {
            }
        }
    }

    // Throws TaskCancelled("provider execution cancelled") when the token is
    // set (Python base.py parity).
    void check_cancelled() const {
        if (cancel != nullptr && cancel->is_cancelled()) {
            throw TaskCancelled("provider execution cancelled");
        }
    }
};

// Resolve an output path and enforce workspace containment (#1177):
// root = workspace_root falling back to work_dir; absolute inputs must land
// under the root after resolution, relative inputs resolve against it;
// existing files are refused. Throws ProviderExecutionError when the path
// escapes, would overwrite, or no root exists to check against.
std::filesystem::path resolve_contained_output(const ProviderContext& context,
                                               const std::string& raw,
                                               const std::string& provider_id);

}  // namespace pwb::providers
