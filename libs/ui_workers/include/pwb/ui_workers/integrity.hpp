#pragma once

// UI-04 — IntegrityWorker core.
// Port of paleo_workbench/ui/pages/integrity_worker.py.
//
// Signal/progress contract (Python parity):
//   progress(idx+1, total, asset_name) emitted BEFORE hashing each asset;
//   cancel checks before each asset, right after the progress emit, and
//   inside the chunked hash; a mid-run cancel breaks out and STILL emits
//   finished(report) with the partial report (no `cancelled` signal —
//   cancelled runs land JobState::cancelled WITH the report recorded as
//   the job's partial result, the runtime's canonical parity);
//   failed(str(exc)) — PLAIN message, not "Class: msg".
// The worker never mutates assets; checksum_updates ride the report.

#include <any>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace pwb::ui_workers {

// IntegrityState (data_view_models.py) — string-valued.
enum class IntegrityState : std::uint8_t {
    verified,
    modified,
    missing,
    unmanaged,
    unknown,
};

[[nodiscard]] const char* to_string(IntegrityState state) noexcept;
[[nodiscard]] std::optional<IntegrityState>
integrity_state_from_string(const std::string& value);

// Catalog verify status -> presentation state (_CATALOG_STATUS_TO_STATE).
[[nodiscard]] IntegrityState
integrity_state_from_catalog_status(const std::string& status) noexcept;

// IntegrityCheckReport — field-exact port + summary_text.
struct IntegrityCheckReport {
    int total_checked = 0;
    int verified_count = 0;
    int modified_count = 0;
    int missing_count = 0;
    int unmanaged_count = 0;
    int unknown_count = 0;
    std::map<std::string, IntegrityState> results;
    std::vector<std::string> details;
    std::map<std::string, std::string> checksum_updates;

    // f"已校验: {v} · 已修改: {m} · 缺失: {x} · 外部链接: {u}"
    [[nodiscard]] std::string summary_text() const;
};

// compute_sha256 — 65536-byte chunks, cancel check BEFORE each read,
// max_bytes early break, None on cancel/missing/OSError.
std::optional<std::string> compute_sha256(
    const std::string& path, std::optional<long long> max_bytes = std::nullopt,
    const std::function<bool()>& is_cancelled = {});

// asset_view_from_object's output — the five fields the loop reads.
struct IntegrityAssetSlice {
    std::string id;
    std::string name;
    std::string path;
    bool managed = true;
    std::optional<std::string> checksum;
};

struct IntegrityInput {
    std::vector<IntegrityAssetSlice> assets;
    std::string project_root;
    // asset id -> catalog version id (bridged_versions).
    std::map<std::string, std::string> bridged_versions;
    // DataCatalogService.verify_integrity(version_id) -> status string
    // ("verified"|"modified"|"missing"|"unknown"). Python takes the
    // catalog path only when service is present — an unbound seam with a
    // bridged asset falls through to the self-hashing path (parity).
    std::function<std::string(const std::string& version_id)> verify_fn;
    // Typed progress hook (current, total, name).
    std::function<void(int, int, const std::string&)> on_progress;
};

// run_integrity_check — the worker loop. Cancel checkpoints at the same
// places; a cancel break yields the partial report and this function
// returns it (the scheduler publishes it as the cancelled run's result —
// the finished(report)-on-cancel parity).
IntegrityCheckReport run_integrity_check(const IntegrityInput& input,
                                         job::JobContext& ctx);

// JobSpec builder — kind "verify.integrity". on_done receives the report;
// on_fail the PLAIN message (str(exc) parity); on_cancel fires when the
// run is cancelled — and handle.try_result<IntegrityCheckReport>() then
// holds the partial report.
job::JobSpec make_integrity_job_spec(
    IntegrityInput input,
    std::function<void(const IntegrityCheckReport&)> on_done = {},
    std::function<void(const std::string&)> on_fail = {},
    std::function<void()> on_cancel = {});

}  // namespace pwb::ui_workers
