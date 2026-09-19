// Implementation of batch.hpp — branch-for-branch port of
// paleo_workbench/interchange/batch.py over the native model-adapter
// service.
#include <pwb/interchange/batch.hpp>

#include <algorithm>
#include <chrono>
#include <mutex>
#include <thread>

#include <pwb/interchange/path_safety.hpp>
#include <pwb/interchange/unicode.hpp>

namespace pwb::interchange {

namespace {

long long monotonic_ms_since(std::chrono::steady_clock::time_point start) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now() - start)
        .count();
}

}  // namespace

Json BatchItemResult::to_json() const {
    Json out = Json::object();
    out["source"] = source;
    out["target"] = target;
    out["status"] = status;
    out["detail"] = detail;
    out["duration_ms"] = duration_ms;
    out["verification_state"] = verification_state;
    return out;
}

Json BatchResult::summary() const {
    Json counts = Json::object();
    for (const auto& item : results) {
        counts[item.status] = counts.value(item.status, 0) + 1;
    }
    Json out = Json::object();
    out["total"] = static_cast<long long>(results.size());
    // Python {**counts} spread: the count keys land after "total".
    for (auto it = counts.begin(); it != counts.end(); ++it) {
        out[it.key()] = it.value();
    }
    out["was_cancelled"] = cancelled;
    out["total_duration_ms"] = total_duration_ms;
    out["estimated_disk_bytes"] = estimated_disk_bytes;
    return out;
}

Json BatchResult::to_json() const {
    Json out = summary();
    out["results"] = Json::array();
    for (const auto& item : results) {
        out["results"].push_back(item.to_json());
    }
    return out;
}

const ModelAdapter* BatchConversionService::adapter_for(
    const std::filesystem::path& source, const std::string& target_format) const {
    (void)source;
    const ModelAdapter* adapter = service_.adapter(target_format);
    if (adapter != nullptr && adapter->capability().can_export) {
        return adapter;
    }
    return nullptr;
}

std::filesystem::path BatchConversionService::target_path(
    const ConversionJob& job, const std::filesystem::path& output_dir) const {
    const ModelAdapter* adapter = service_.adapter(job.target_format);
    const std::string extension =
        (adapter != nullptr && !adapter->extensions.empty()) ? adapter->extensions.front()
                                                             : std::string("bin");
    std::string name;
    if (job.target_name.has_value()) {
        name = sanitize_filename(*job.target_name);
    } else {
        name = job.source.stem().string() + "." + extension;
    }
    return output_dir / name;
}

std::pair<long long, std::vector<std::string>> BatchConversionService::estimate(
    const std::vector<ConversionJob>& jobs,
    const std::filesystem::path& output_dir) const {
    long long total = 0;
    std::vector<std::string> warnings;
    for (const auto& job : jobs) {
        const ModelAdapter* adapter = adapter_for(job.source, job.target_format);
        if (adapter == nullptr) {
            warnings.push_back("无法识别: " + job.source.string());
            continue;
        }
        try {
            const ExportPlan plan =
                adapter->plan_export(job.source, target_path(job, output_dir), job.options);
            total += plan.estimated_bytes;
        } catch (const std::exception& exc) {
            warnings.push_back(job.source.string() + ": " + exc.what());
        }
    }
    return {total, warnings};
}

std::vector<ConversionJob> BatchConversionService::dedupe_targets(
    const std::vector<ConversionJob>& ordered,
    const std::filesystem::path& output_dir) const {
    // Deterministic collision-free names: <stem>-2.ext, -3.ext, ...
    std::vector<std::string> used;
    std::vector<ConversionJob> result;
    for (ConversionJob job : ordered) {
        std::string base = target_path(job, output_dir).filename().string();
        std::string candidate = base;
        int counter = 1;
        while (true) {
            const std::string folded = casefold_utf8(candidate);
            if (std::find(used.begin(), used.end(), folded) == used.end()) break;
            ++counter;
            const std::filesystem::path base_path(base);
            candidate = base_path.stem().string() + "-" + std::to_string(counter) +
                        base_path.extension().string();
        }
        used.push_back(casefold_utf8(candidate));
        job.target_name = candidate;
        result.push_back(std::move(job));
    }
    return result;
}

BatchResult BatchConversionService::convert(const std::vector<ConversionJob>& jobs,
                                            const std::filesystem::path& output_dir,
                                            const CancelToken& cancel,
                                            BatchProgressFn progress,
                                            bool verify) const {
    cancel.checkpoint();
    const auto started = std::chrono::steady_clock::now();
    BatchResult result;
    result.estimated_disk_bytes = estimate(jobs, output_dir).first;

    std::filesystem::create_directories(output_dir);

    // Deterministic order: sort by (source path, target name).
    std::vector<ConversionJob> ordered = jobs;
    std::sort(ordered.begin(), ordered.end(), [](const ConversionJob& a, const ConversionJob& b) {
        const std::string a_source = a.source.string();
        const std::string b_source = b.source.string();
        if (a_source != b_source) return a_source < b_source;
        return a.target_name.value_or("") < b.target_name.value_or("");
    });
    ordered = dedupe_targets(ordered, output_dir);

    // A failing callback must not lose the batch result.
    auto safe_progress = [&progress](int done, int total, const std::string& current) {
        if (!progress) return;
        try {
            progress(done, total, current);
        } catch (...) {
        }
    };

    auto run_one = [&](const ConversionJob& job) {
        BatchItemResult item;
        item.source = job.source.string();
        const auto item_start = std::chrono::steady_clock::now();
        try {
            cancel.checkpoint();
            const ModelAdapter* adapter = adapter_for(job.source, job.target_format);
            if (adapter == nullptr) {
                item.status = "skipped";
                item.detail = "无适配器或能力不可用";
                item.duration_ms = monotonic_ms_since(item_start);
                return item;
            }
            const std::filesystem::path target = target_path(job, output_dir);
            ExportPlan plan = adapter->plan_export(job.source, target, job.options);
            item.target = target.string();
            plan.target_path = target.string();
            const std::filesystem::path output = adapter->export_data(plan, cancel);
            ExportVerification verification =
                verify ? adapter->verify_output(output, plan)
                       : ExportVerification::unverified("verify=False（调用方选择跳过校验）");
            item.verification_state = std::string(to_string(verification.state));
            // Only FAILED fails the item. With verify=False the output is
            // UNVERIFIED (recorded honestly), which the caller opted into.
            if (verification.state == VerificationState::FAILED) {
                item.status = "failed";
                item.detail =
                    !verification.detail.empty() ? verification.detail : "输出未通过校验";
            } else {
                item.status = "converted";
                if (registration_ != nullptr && verification.ok()) {
                    try {
                        registration_->register_export(plan, output, verification);
                    } catch (const std::exception& exc) {
                        // 登记失败追加 warning 不改结果。
                        item.detail = std::string("输出登记失败: ") + exc.what();
                    }
                } else if (verification.state == VerificationState::UNVERIFIED && verify) {
                    item.detail = !verification.detail.empty()
                                      ? verification.detail
                                      : "输出未验证（校验器异常）";
                }
            }
        } catch (const CancelledError&) {
            item.status = "cancelled";
            item.duration_ms = monotonic_ms_since(item_start);
            throw;
        } catch (const std::exception& exc) {
            item.status = "failed";
            item.detail = exc.what();
        }
        item.duration_ms = monotonic_ms_since(item_start);
        return item;
    };

    const int total = static_cast<int>(ordered.size());
    int done = 0;
    if (max_workers_ == 1 || total <= 1) {
        for (const auto& job : ordered) {
            try {
                result.results.push_back(run_one(job));
            } catch (const CancelledError&) {
                BatchItemResult item;
                item.source = job.source.string();
                item.status = "cancelled";
                result.results.push_back(std::move(item));
                if (cancel.cancelled()) result.cancelled = true;
                // A job-internal CancelledError is failure isolation, not a
                // batch stop — only a cancelled shared token stops us.
            }
            ++done;
            safe_progress(done, total, job.source.string());
            if (result.cancelled) {
                // Everything after the shared-token cancellation is
                // cancelled without running.
                for (std::size_t i = done; i < ordered.size(); ++i) {
                    BatchItemResult item;
                    item.source = ordered[i].source.string();
                    item.status = "cancelled";
                    result.results.push_back(std::move(item));
                }
                break;
            }
        }
    } else {
        // Bounded worker pool; results collected in submission order.
        std::mutex result_mutex;
        std::vector<BatchItemResult> collected(ordered.size());
        std::vector<std::thread> workers;
        std::size_t next = 0;
        bool stop = false;
        for (int worker = 0; worker < max_workers_ && worker < total; ++worker) {
            workers.emplace_back([&] {
                for (;;) {
                    std::size_t index = 0;
                    {
                        std::lock_guard<std::mutex> guard(result_mutex);
                        if (stop || next >= ordered.size()) return;
                        index = next++;
                    }
                    BatchItemResult item;
                    try {
                        item = run_one(ordered[index]);
                    } catch (const CancelledError&) {
                        item.source = ordered[index].source.string();
                        item.status = "cancelled";
                        if (cancel.cancelled()) {
                            std::lock_guard<std::mutex> guard(result_mutex);
                            stop = true;
                        }
                    } catch (const std::exception& exc) {  // defensive: isolate everything
                        item.source = ordered[index].source.string();
                        item.status = "failed";
                        item.detail = exc.what();
                    }
                    {
                        std::lock_guard<std::mutex> guard(result_mutex);
                        collected[index] = std::move(item);
                    }
                }
            });
        }
        for (auto& worker : workers) worker.join();
        for (auto& item : collected) {
            result.results.push_back(std::move(item));
            ++done;
            // Progress after the fact keeps the ordering deterministic; the
            // current label mirrors the just-finished job.
            safe_progress(done, total, result.results.back().source);
        }
        if (cancel.cancelled()) {
            result.cancelled = true;
            for (auto& item : result.results) {
                if (item.status == "pending") item.status = "cancelled";
            }
        }
    }
    result.total_duration_ms = monotonic_ms_since(started);
    // Order results deterministically regardless of completion order.
    std::stable_sort(result.results.begin(), result.results.end(),
                     [](const BatchItemResult& a, const BatchItemResult& b) {
                         return a.source < b.source;
                     });
    return result;
}

}  // namespace pwb::interchange
