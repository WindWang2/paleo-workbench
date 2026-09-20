// pwb::interchange — batch conversion service, a faithful C++ port of
// paleo_workbench/interchange/batch.py (I14): bounded, cancellable,
// failure-isolated orchestration over the native interchange service.
//
// This is *orchestration only* — every conversion is executed by the
// existing adapter/export machinery (NativeInterchangeService over the
// model adapters). Guarantees preserved from the Python service:
//   * bounded concurrency (default 2 workers, hard cap 4 — the degraded
//     clamp path of the Python governance call);
//   * one failing item never aborts the batch and never corrupts another
//     item's output (atomic writes in the export path);
//   * cooperative cancellation at item boundaries and inside export
//     checkpoints (a job-internal cancellation is failure isolation, only
//     a cancelled shared token stops the batch);
//   * deterministic output naming (sorted stems, casefold collision
//     suffixes -2, -3, ...);
//   * pre-flight disk estimate before any work starts.
//
// Catalog run registration: Python's ExportExecutor registers outputs as a
// single choke point; the C++ kernel has no catalog write seam, so an
// optional IExportRegistration port receives every converted item (the
// closure layer binds it to the line-01 registration surface). A failing
// registration appends a warning and never changes the item result.
#pragma once

#include <pwb/domain/json.hpp>
#include <pwb/interchange/contracts.hpp>
#include <pwb/interchange/service.hpp>

#include <algorithm>
#include <filesystem>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace pwb::interchange {

using Json = pwb::domain::Json;

class IExportRegistration {
public:
    virtual ~IExportRegistration() = default;
    // Returns a registration id; may throw (the caller degrades to a
    // warning, mirroring register_export_output failure handling).
    virtual std::string register_export(const ExportPlan& plan,
                                        const std::filesystem::path& output,
                                        const ExportVerification& verification) = 0;
};

struct ConversionJob {
    std::filesystem::path source;
    std::string target_format;  // adapter format_id (e.g. "flac3d_f3grid", "abaqus_inp")
    std::optional<std::string> target_name;  // default: <stem>.<ext>
    Json options = Json::object();
};

struct BatchItemResult {
    std::string source;
    std::string target;
    std::string status = "pending";  // "converted"|"failed"|"skipped"|"cancelled"
    std::string detail;
    long long duration_ms = 0;
    std::string verification_state;

    Json to_json() const;
};

struct BatchResult {
    std::vector<BatchItemResult> results;
    bool cancelled = false;
    long long total_duration_ms = 0;
    long long estimated_disk_bytes = 0;

    Json summary() const;
    Json to_json() const;
};

using BatchProgressFn = std::function<void(int done, int total, const std::string& current)>;

class BatchConversionService {
public:
    // service must outlive the batch service. max_workers is clamped to
    // [1, 4]; the constructor clamp is the hard safety cap for degraded
    // environments (Python #1225 parity).
    explicit BatchConversionService(NativeInterchangeService& service,
                                    int max_workers = 2,
                                    IExportRegistration* registration = nullptr)
        : service_(service),
          max_workers_(std::clamp(max_workers, 1, 4)),
          registration_(registration) {}

    // (estimated_disk_bytes, warnings) without converting.
    std::pair<long long, std::vector<std::string>> estimate(
        const std::vector<ConversionJob>& jobs,
        const std::filesystem::path& output_dir) const;

    BatchResult convert(const std::vector<ConversionJob>& jobs,
                        const std::filesystem::path& output_dir,
                        const CancelToken& cancel = null_cancel(),
                        BatchProgressFn progress = {},
                        bool verify = true) const;

private:
    const ModelAdapter* adapter_for(const std::filesystem::path& source,
                                    const std::string& target_format) const;
    std::filesystem::path target_path(const ConversionJob& job,
                                      const std::filesystem::path& output_dir) const;
    std::vector<ConversionJob> dedupe_targets(
        const std::vector<ConversionJob>& ordered,
        const std::filesystem::path& output_dir) const;

    NativeInterchangeService& service_;
    int max_workers_;
    IExportRegistration* registration_;
};

}  // namespace pwb::interchange
