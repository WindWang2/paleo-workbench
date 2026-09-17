// Execution semantics: pre-set and mid-run cancellation (deterministic
// barrier via the progress callback — no timing races), monotonic progress
// with a success terminal of exactly 1.0, input immutability, output
// lifetime outliving the result object, byte-identical determinism, and a
// real TaskRuntime smoke run of all four algorithms through a publisher
// test double (module-level proof only — NOT proof of B-line persistence).

#include "pwb_test.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include <pwb/science/algorithm.hpp>
#include <pwb/science/publisher.hpp>
#include <pwb/science/registry.hpp>
#include <pwb/science/types.hpp>
#include <pwb/seismic_attributes/attributes.hpp>
#include <pwb/workflow/task_runtime.hpp>

namespace {

using pwb::science::AlgorithmRegistry;
using pwb::science::AlgorithmRequestV1;
using pwb::science::AlgorithmResultV1;
using pwb::science::IResultPublisherV1;
using pwb::science::ProgressReport;
using pwb::science::VolumeView;
using pwb::workflow::TaskRuntime;

std::shared_ptr<std::vector<float>> synthetic_volume(std::int64_t n_il,
                                                     std::int64_t n_xl,
                                                     std::int64_t n_t,
                                                     unsigned seed) {
    auto data = std::make_shared<std::vector<float>>(
        static_cast<std::size_t>(n_il * n_xl * n_t));
    unsigned state = seed ? seed : 1;
    for (float& v : *data) {
        state = state * 1664525u + 1013904223u;
        v = static_cast<float>(static_cast<int>((state >> 8) & 0xFFFF) - 32768) /
            32768.0f;
    }
    return data;
}

std::uint64_t fnv1a(const std::vector<float>& data) {
    std::uint64_t hash = 1469598103934665603ull;
    const auto* bytes = reinterpret_cast<const unsigned char*>(data.data());
    const std::size_t n = data.size() * sizeof(float);
    for (std::size_t i = 0; i < n; ++i) {
        hash ^= bytes[i];
        hash *= 1099511628211ull;
    }
    return hash;
}

struct CollectedResult {
    std::string request_id;
    std::string algorithm_id;
    std::size_t outputs{0};
    std::size_t elements{0};
    std::string unit;
    bool has_provenance{false};
    std::string provenance_id;
};

class CollectorPublisher final : public IResultPublisherV1 {
public:
    void publish_success(const AlgorithmResultV1& result) override {
        const std::lock_guard<std::mutex> lock(mutex_);
        CollectedResult c;
        c.request_id = result.request_id;
        c.algorithm_id = result.provenance.algorithm_id;
        c.outputs = result.outputs.size();
        for (const auto& output : result.outputs) {
            c.elements += static_cast<std::size_t>(output.volume.size());
            c.unit = output.unit;
        }
        c.has_provenance = !result.provenance.algorithm_id.empty() &&
                           !result.provenance.build_identity.empty() &&
                           !result.provenance.started_utc.empty() &&
                           !result.provenance.finished_utc.empty();
        c.provenance_id = result.provenance.algorithm_id;
        successes_.push_back(c);
    }
    void publish_failure(const Failure& failure) override {
        const std::lock_guard<std::mutex> lock(mutex_);
        failures_.push_back(failure);
    }
    std::vector<CollectedResult> successes() {
        const std::lock_guard<std::mutex> lock(mutex_);
        return successes_;
    }
    std::vector<Failure> failures() {
        const std::lock_guard<std::mutex> lock(mutex_);
        return failures_;
    }

private:
    std::mutex mutex_;
    std::vector<CollectedResult> successes_;
    std::vector<Failure> failures_;
};

} // namespace

TEST(cancel_before_run) {
    auto algorithm = pwb::seismic_attributes::make_envelope("build-rt");
    auto holder = synthetic_volume(4, 4, 16, 7);
    AlgorithmRequestV1 request;
    request.algorithm_id = algorithm->descriptor().algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    VolumeView view;
    view.data = holder->data();
    view.shape = {4, 4, 16};
    view.strides = {0, 0, 0};
    view.lifetime = holder;
    request.input_volumes.push_back(view);

    std::stop_source stop;
    stop.request_stop(); // cancelled before the first batch
    auto result = algorithm->run(request, nullptr, stop.get_token());
    PWB_CHECK(result.is_cancelled());
    PWB_CHECK(!result.cancelled().stage.empty());
    std::printf("pre-set cancel stage: '%s'\n", result.cancelled().stage.c_str());
}

TEST(cancel_during_run_at_progress_barrier) {
    // (200,200,64) = 40000 traces, batch 512 -> 79 batches. Cancellation is
    // requested from inside the FIRST progress callback (synchronous
    // barrier), so the second batch observes stop_requested — deterministic,
    // independent of machine speed.
    auto algorithm = pwb::seismic_attributes::make_rms_amplitude("build-rt");
    auto holder = synthetic_volume(200, 200, 64, 11);
    AlgorithmRequestV1 request;
    request.algorithm_id = algorithm->descriptor().algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    VolumeView view;
    view.data = holder->data();
    view.shape = {200, 200, 64};
    view.strides = {0, 0, 0};
    view.lifetime = holder;
    request.input_volumes.push_back(view);

    std::stop_source stop;
    std::atomic<int> callbacks{0};
    pwb::science::ProgressSink sink = [&](const ProgressReport& report) {
        const int n = callbacks.fetch_add(1) + 1;
        if (n == 1 && report.fraction < 1.0) {
            stop.request_stop(); // deterministic cancel point
        }
    };
    auto result = algorithm->run(request, sink, stop.get_token());
    PWB_CHECK(result.is_cancelled());
    PWB_CHECK(callbacks.load() >= 1);
    std::printf("mid-run cancel after %d progress callbacks, stage '%s'\n",
                callbacks.load(), result.cancelled().stage.c_str());
}

TEST(progress_monotonic_and_terminal) {
    auto algorithm = pwb::seismic_attributes::make_instantaneous_frequency("build-rt");
    auto holder = synthetic_volume(120, 120, 32, 13); // 14400 traces, 29 batches
    AlgorithmRequestV1 request;
    request.algorithm_id = algorithm->descriptor().algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    request.params_json["sample_interval"] = "0.002";
    VolumeView view;
    view.data = holder->data();
    view.shape = {120, 120, 32};
    view.strides = {0, 0, 0};
    view.lifetime = holder;
    request.input_volumes.push_back(view);

    std::vector<double> fractions;
    std::vector<std::string> stages;
    pwb::science::ProgressSink sink = [&](const ProgressReport& report) {
        fractions.push_back(report.fraction);
        stages.push_back(report.stage);
    };
    const auto result = algorithm->run(request, sink, {});
    PWB_CHECK(result.has_value());
    PWB_CHECK(fractions.size() >= 3); // several batches + terminal
    for (std::size_t i = 1; i < fractions.size(); ++i) {
        PWB_CHECK(fractions[i] >= fractions[i - 1]); // weakly monotonic
    }
    PWB_CHECK(fractions.back() == 1.0);
    PWB_CHECK(stages.back() == "done");
    std::printf("progress: %zu reports, first=%.4f last=%.1f/%s\n", fractions.size(),
                fractions.front(), fractions.back(), stages.back().c_str());
}

TEST(input_immutable_and_deterministic) {
    auto algorithm = pwb::seismic_attributes::make_envelope("build-rt");
    auto holder = synthetic_volume(24, 20, 64, 17);
    const std::uint64_t hash_before = fnv1a(*holder);

    AlgorithmRequestV1 request;
    request.algorithm_id = algorithm->descriptor().algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    VolumeView view;
    view.data = holder->data();
    view.shape = {24, 20, 64};
    view.strides = {0, 0, 0};
    view.lifetime = holder;
    request.input_volumes.push_back(view);

    const auto first = algorithm->run(request, nullptr, {});
    PWB_CHECK(first.has_value());
    PWB_CHECK(fnv1a(*holder) == hash_before); // input untouched

    const auto second = algorithm->run(request, nullptr, {});
    PWB_CHECK(second.has_value());
    const VolumeView& a = first.value().outputs[0].volume;
    const VolumeView& b = second.value().outputs[0].volume;
    PWB_CHECK(a.size() == b.size());
    PWB_CHECK(std::memcmp(a.data, b.data,
                          static_cast<std::size_t>(a.size()) * sizeof(float)) == 0);
    std::printf("determinism: %lld elements byte-identical across runs\n",
                static_cast<long long>(a.size()));
}

TEST(output_lifetime_outlives_result) {
    auto algorithm = pwb::seismic_attributes::make_rms_amplitude("build-rt");
    auto holder = synthetic_volume(8, 8, 32, 19);
    AlgorithmRequestV1 request;
    request.algorithm_id = algorithm->descriptor().algorithm_id;
    request.algorithm_version = algorithm->descriptor().version;
    request.params_json["window"] = "5";
    VolumeView view;
    view.data = holder->data();
    view.shape = {8, 8, 32};
    view.strides = {0, 0, 0};
    view.lifetime = holder;
    request.input_volumes.push_back(view);

    VolumeView kept;
    {
        const auto result = algorithm->run(request, nullptr, {});
        PWB_CHECK(result.has_value());
        kept = result.value().outputs[0].volume; // view + lifetime guard copy
    } // AlgorithmResultV1 destroyed here
    PWB_CHECK(kept.data != nullptr);
    PWB_CHECK(kept.lifetime != nullptr);
    double sum = 0.0;
    for (std::int64_t i = 0; i < kept.size(); ++i) {
        const float v = kept.data[i];
        PWB_CHECK(std::isfinite(v));
        sum += v;
    }
    std::printf("output survives result destruction: %lld elements, sum=%.3f\n",
                static_cast<long long>(kept.size()), sum);
}

TEST(task_runtime_smoke_all_four) {
    // Real TaskRuntime (Pwb::Workflow, base 53e22b67 version — the C-line v3
    // publish-before-terminal fix is consumed at A-line integration time).
    // Each of the four algorithms runs at least once through submit() with a
    // publisher; the module publisher double only collects results.
    auto holder = synthetic_volume(12, 10, 48, 23);
    auto publisher = std::make_shared<CollectorPublisher>();
    {
        TaskRuntime runtime;
        struct Job {
            std::shared_ptr<pwb::science::IAlgorithm> algorithm;
            const char* id;
            const char* param;
            const char* value;
        };
        Job jobs[] = {
            {pwb::seismic_attributes::make_envelope("build-rt"),
             "seismic.envelope", nullptr, nullptr},
            {pwb::seismic_attributes::make_instantaneous_phase("build-rt"),
             "seismic.instantaneous_phase", nullptr, nullptr},
            {pwb::seismic_attributes::make_instantaneous_frequency("build-rt"),
             "seismic.instantaneous_frequency", "sample_interval", "0.002"},
            {pwb::seismic_attributes::make_rms_amplitude("build-rt"),
             "seismic.rms_amplitude", "window", "3"},
        };
        pwb::workflow::TaskHandle handles[4];
        for (std::size_t j = 0; j < 4; ++j) {
            const Job& job = jobs[j];
            AlgorithmRequestV1 request;
            request.request_id = std::string("rt-") + job.id;
            request.algorithm_id = job.id;
            request.algorithm_version = job.algorithm->descriptor().version;
            if (job.param != nullptr) {
                request.params_json[job.param] = job.value;
            }
            VolumeView view;
            view.data = holder->data();
            view.shape = {12, 10, 48};
            view.strides = {0, 0, 0};
            view.lifetime = holder;
            request.input_volumes.push_back(view);
            handles[j] = runtime.submit(job.algorithm, request, publisher);
        }
        for (auto& handle : handles) {
            handle.wait();
            PWB_CHECK(handle.valid());
            const auto snapshot = handle.snapshot();
            PWB_CHECK(snapshot.status == pwb::workflow::TaskStatus::succeeded);
            PWB_CHECK(snapshot.error_code.empty());
        }
    } // runtime destroyed: drains + joins

    const auto successes = publisher->successes();
    const auto failures = publisher->failures();
    PWB_CHECK(failures.empty());
    PWB_CHECK(successes.size() == 4);
    std::size_t total_elements = static_cast<std::size_t>(12 * 10 * 48);
    for (const CollectedResult& c : successes) {
        PWB_CHECK(c.outputs == 1);
        PWB_CHECK(c.elements == total_elements);
        PWB_CHECK(c.has_provenance);
        std::printf("published: %s -> %zu elements, unit '%s'\n", c.algorithm_id.c_str(),
                    c.elements, c.unit.c_str());
    }
}

int main() {
    for (const auto& test : pwb_test::registry()) {
        std::printf("== %s ==\n", test.name.c_str());
        test.body();
    }
    std::printf("all runtime tests passed (%zu tests)\n", pwb_test::registry().size());
    return 0;
}
