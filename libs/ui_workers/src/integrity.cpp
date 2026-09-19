#include "pwb/ui_workers/integrity.hpp"

#include <array>
#include <filesystem>
#include <fstream>
#include <thread>

#include <pwb/domain/sha256.hpp>

namespace pwb::ui_workers {

const char* to_string(IntegrityState state) noexcept {
    switch (state) {
    case IntegrityState::verified:
        return "VERIFIED";
    case IntegrityState::modified:
        return "MODIFIED";
    case IntegrityState::missing:
        return "MISSING";
    case IntegrityState::unmanaged:
        return "UNMANAGED";
    case IntegrityState::unknown:
        return "UNKNOWN";
    }
    return "UNKNOWN";
}

std::optional<IntegrityState> integrity_state_from_string(
    const std::string& value) {
    if (value == "VERIFIED") return IntegrityState::verified;
    if (value == "MODIFIED") return IntegrityState::modified;
    if (value == "MISSING") return IntegrityState::missing;
    if (value == "UNMANAGED") return IntegrityState::unmanaged;
    if (value == "UNKNOWN") return IntegrityState::unknown;
    return std::nullopt;
}

IntegrityState integrity_state_from_catalog_status(
    const std::string& status) noexcept {
    // _CATALOG_STATUS_TO_STATE.get(status, UNKNOWN)
    if (status == "verified") return IntegrityState::verified;
    if (status == "modified") return IntegrityState::modified;
    if (status == "missing") return IntegrityState::missing;
    return IntegrityState::unknown;
}

std::string IntegrityCheckReport::summary_text() const {
    return "已校验: " + std::to_string(verified_count) +
           " · 已修改: " + std::to_string(modified_count) +
           " · 缺失: " + std::to_string(missing_count) +
           " · 外部链接: " + std::to_string(unmanaged_count);
}

std::optional<std::string> compute_sha256(
    const std::string& path, std::optional<long long> max_bytes,
    const std::function<bool()>& is_cancelled) {
    std::error_code ec;
    if (!std::filesystem::is_regular_file(path, ec)) return std::nullopt;
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return std::nullopt;
    pwb::domain::Sha256 hash;
    long long bytes_read = 0;
    std::array<char, 65536> buffer{};
    while (true) {
        if (is_cancelled && is_cancelled()) return std::nullopt;
        stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const auto got = stream.gcount();
        if (got <= 0) break;
        hash.update(buffer.data(), static_cast<std::size_t>(got));
        bytes_read += got;
        std::this_thread::yield();  // QThread.yieldCurrentThread parity
        // `if max_bytes and bytes_read >= max_bytes` — any nonzero bound
        // applies (a negative bound breaks after the first chunk, like
        // Python's truthiness + comparison).
        if (max_bytes && *max_bytes != 0 && bytes_read >= *max_bytes) break;
    }
    if (stream.bad()) return std::nullopt;  // OSError parity
    return hash.hex_digest();
}

namespace {

IntegrityState verify_via_catalog(const std::string& status,
                                  const std::string& version_id,
                                  const std::string& view_name,
                                  IntegrityCheckReport& report) {
    const IntegrityState state =
        integrity_state_from_catalog_status(status);
    switch (state) {
    case IntegrityState::verified:
        ++report.verified_count;
        break;
    case IntegrityState::modified:
        ++report.modified_count;
        report.details.push_back(view_name +
                                 ": 校验和不匹配 (目录记录保持不变)");
        break;
    case IntegrityState::missing:
        ++report.missing_count;
        report.details.push_back(view_name +
                                 ": 文件不存在 (catalog version " +
                                 version_id + ")");
        break;
    default:
        ++report.unknown_count;
        break;
    }
    return state;
}

}  // namespace

IntegrityCheckReport run_integrity_check(const IntegrityInput& input,
                                         job::JobContext& ctx) {
    return with_plain_errors([&]() -> IntegrityCheckReport {
        IntegrityCheckReport report;
        report.total_checked = static_cast<int>(input.assets.size());
        const int total = static_cast<int>(input.assets.size());
        const auto cancelled = [&] { return ctx.token().is_cancelled(); };

        for (int idx = 0; idx < total; ++idx) {
            const auto& view = input.assets[static_cast<std::size_t>(idx)];
            if (cancelled()) {
                report.details.push_back("完整性校验已取消");
                break;
            }
            if (input.on_progress) {
                input.on_progress(idx + 1, total, view.name);
            }
            ctx.report_progress(static_cast<double>(idx + 1),
                                static_cast<double>(total), view.name);
            if (cancelled()) {
                report.details.push_back("完整性校验已取消");
                break;
            }

            const auto bridged = input.bridged_versions.find(view.id);
            if (bridged != input.bridged_versions.end() &&
                input.verify_fn) {
                const std::string status = input.verify_fn(bridged->second);
                const IntegrityState state = verify_via_catalog(
                    status, bridged->second, view.name, report);
                report.results[view.id] = state;
                continue;
            }

            namespace fs = std::filesystem;
            fs::path path_obj(view.path);
            if (path_obj.is_relative() && !input.project_root.empty()) {
                path_obj = fs::path(input.project_root) / path_obj;
            }
            std::error_code ec;
            const bool exists = fs::exists(path_obj, ec);

            IntegrityState state;
            if (!exists) {
                state = IntegrityState::missing;
                ++report.missing_count;
                report.details.push_back(view.name + ": 文件不存在 (" +
                                         view.path + ")");
            } else if (!view.managed) {
                state = IntegrityState::unmanaged;
                ++report.unmanaged_count;
            } else if (view.checksum && !view.checksum->empty()) {
                auto actual = compute_sha256(
                    path_obj.string(), std::nullopt, cancelled);
                if (cancelled()) {
                    report.details.push_back("完整性校验已取消");
                    break;
                }
                if (actual && *actual == *view.checksum) {
                    state = IntegrityState::verified;
                    ++report.verified_count;
                } else {
                    state = IntegrityState::modified;
                    ++report.modified_count;
                    const std::string expected = view.checksum->substr(
                        0, std::min<std::size_t>(8, view.checksum->size()));
                    const std::string actual8 =
                        actual
                            ? actual->substr(
                                  0, std::min<std::size_t>(8, actual->size()))
                            : "N/A";
                    report.details.push_back(
                        view.name + ": 校验和不匹配 (预期 " + expected +
                        ", 实际 " + actual8 + ")");
                }
            } else {
                auto new_hash = compute_sha256(
                    path_obj.string(), std::nullopt, cancelled);
                if (cancelled()) {
                    report.details.push_back("完整性校验已取消");
                    break;
                }
                if (new_hash) {
                    report.checksum_updates[view.id] = *new_hash;
                    state = IntegrityState::verified;
                    ++report.verified_count;
                } else {
                    state = IntegrityState::unknown;
                    ++report.unknown_count;
                }
            }
            report.results[view.id] = state;
        }
        return report;
    });
}

job::JobSpec make_integrity_job_spec(
    IntegrityInput input,
    std::function<void(const IntegrityCheckReport&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "verify.integrity";
    spec.title = "资源完整性校验";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        IntegrityCheckReport report = run_integrity_check(input, ctx);
        // finished(report) even on a cancel break — landing cancelled WITH
        // the report is the runtime's partial-result parity.
        return report;
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const IntegrityCheckReport&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_workers
