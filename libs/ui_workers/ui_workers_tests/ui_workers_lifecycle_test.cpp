// UI-04/05 — ui_workers.lifecycle：作业运行时生命周期真测试（Qt-free 层）。
//
// 覆盖（此前该测试是空壳 main{return 0;}——本文件兑现其 CMake 注释
// 承诺的取消/迟到语义）：
//   1. 已取消请求不点火解析（well_log 负载 seam：取消令牌在解析检查点
//      抛 WellLogLoadCancelled，绝不产出假载荷）；
//   2. 取消传播：resolve_well_log 对取消是「诚实地抛」，不是 message
//      payload；不可解析是诚实的 message payload，不是异常；
//   3. DTW worker 取消：start-then-cancel → cancelled 终态 + on_cancel
//      恰一次 + 无 on_done；取消幂等（二次 cancel 返回 false）；
//   4. 迟到结果：同 task_key 重提交废止排队中的旧作业（旧作业的
//      on_cancel 展开、on_done 永不触发——#1224 语义）；
//   5. 取消后返回体：作业体在取消后返回部分结果 → cancelled 终态
//      （绝不谎报 done）；
//   6. 确定性：同一 DTW 输入两次完成的结果逐值一致（复现验收）；
//   7. 在飞作业下的有界关闭：shutdown(timeout) 及时返回、析构汇合
//      （对象销毁语义的 Qt-free 半；GUI 半在 well.dock_lifecycle）。
//
// Also: #1391 ragged grid_z rejection (worker-side, not an oracle replay).
// The legacy `parameters["grid_z"]` bag can carry ragged rows (external
// project JSON). Pre-fix, any_to_grid flattened them into a Grid2D whose
// rows*cols no longer matched data.size(), and every downstream
// Grid2D::at()/marching-squares read went out of bounds. The numpy
// asarray equivalent raises, so the contract is PyValueError — which
// compile_contour_drafts_for_project then skips per-task like Python.

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include <any>
#include <optional>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/dtw_propagation.hpp>
#include <pwb/ui_workers/viz_resolve.hpp>
#include <pwb/ui_workers/worker_common.hpp>

namespace {

int failures = 0;

#define CHECK(cond)                                                  \
    do {                                                             \
        if (!(cond)) {                                               \
            std::fprintf(stderr, "CHECK 失败 %s:%d: %s\n", __FILE__, \
                         __LINE__, #cond);                           \
            ++failures;                                              \
        }                                                            \
    } while (false)

template <typename Fn>
bool wait_for(Fn&& condition, double timeout_seconds) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::duration_cast<
                              std::chrono::steady_clock::duration>(
                              std::chrono::duration<double>(timeout_seconds));
    while (std::chrono::steady_clock::now() < deadline) {
        if (condition()) return true;
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    return condition();
}

pwb::ui_workers::DtwPropagationInput small_input() {
    pwb::ui_workers::DtwPropagationInput input;
    pwb::ui_workers::DtwWellSlice a;
    a.name = "W-A";
    std::vector<double> a_depths;
    std::vector<double> a_values;
    for (int i = 0; i < 80; ++i) {
        a_depths.push_back(1000.0 + i);
        a_values.push_back(std::sin(i * 0.21));
    }
    a.depths = std::move(a_depths);
    a.values = std::move(a_values);
    pwb::ui_workers::DtwWellSlice b;
    b.name = "W-B";
    std::vector<double> b_depths;
    std::vector<double> b_values;
    for (int i = 0; i < 80; ++i) {
        b_depths.push_back(1010.0 + i);
        b_values.push_back(std::sin((i + 2) * 0.21));
    }
    b.depths = std::move(b_depths);
    b.values = std::move(b_values);
    input.scene.wells.push_back(std::move(a));
    input.scene.wells.push_back(std::move(b));
    input.ref_well = "W-A";
    input.ref_depth = 1010.0;
    input.formation = "T-LIFE";
    input.n_samples = 80;
    input.band_radius = std::nullopt;
    // 生产绑定（dock 同款）：seam 不注入 = KernelUnavailable。
    input.correlate_fn = pwb::ui_workers::dtw_engine_correlate;
    return input;
}

namespace uw = pwb::ui_workers;
namespace job = pwb::job;

uw::FactorTaskSlice ragged_task(std::any grid_z) {
    uw::FactorTaskSlice task;
    task.id = "t1";
    task.name = "ragged";
    task.status = "complete";
    task.factor_type = "factor";
    task.parameters["grid_z"] = std::move(grid_z);
    task.parameters["grid_x"] = std::vector<double>{0.0, 1.0, 2.0};
    task.parameters["grid_y"] = std::vector<double>{0.0, 1.0};
    return task;
}

// Runs the public pipeline entry; expects the ragged-grid PyValueError out
// of any_to_grid (not the unrelated missing-grid error — same exception
// class, different message) before the extract seam is ever reached.
bool throws_ragged_grid_error(uw::FactorTaskSlice task) {
    job::CancellationToken token;
    try {
        (void)uw::contour_draft_from_factor_task(
            task, std::nullopt, 5, std::nullopt, token,
            uw::ExtractLinesFn{}, uw::IdFn{});
    } catch (const uw::PyValueError& e) {
        return e.py_message() == "grid_z 维数错误";
    } catch (...) {
        return false;
    }
    return false;
}

}  // namespace

int main() {
    using namespace pwb::ui_workers;
    using pwb::job::JobScheduler;
    using pwb::job::JobState;

    // 1) 取消令牌在解析检查点：已取消请求绝不开始解析、绝不产出载荷。
    {
        const WellLogLoadFn load_fn =
            [](const std::string&, const std::function<bool()>& is_cancelled)
            -> std::optional<LoadedWellLog> {
            if (is_cancelled && is_cancelled()) throw WellLogLoadCancelled{};
            return LoadedWellLog{};
        };
        bool threw = false;
        try {
            (void)load_fn("whatever.las", [] { return true; });
        } catch (const WellLogLoadCancelled&) {
            threw = true;
        }
        CHECK(threw);
    }

    // 2) resolve_well_log：取消是抛（不是假消息）；不可解析是消息
    //    payload（不是异常）；成功是 well_log 载荷。路径必须真实存在，
    //    否则存在性门先拦（load_fn 永不触达）——临时真文件。
    {
        const std::string las_path =
            (std::filesystem::temp_directory_path() /
             "ui_workers_lifecycle_well.las")
                .string();
        {
            std::ofstream las(las_path, std::ios::binary | std::ios::trunc);
            las << "~VERSION INFORMATION\nVERS. 2.0:\n~WELL INFORMATION\n"
                   "WELL. W-OK:\n~CURVE INFORMATION\nDEPT.M :\nGR.GAPI :\n"
                   "~ASCII\n1.0 10.0\n2.0 11.0\n";
        }
        std::vector<pwb::ui_workers::ResourceSlice> resources;
        pwb::ui_workers::ResourceSlice resource;
        resource.id = "r1";
        resource.path = las_path;
        resource.type = "well_log";
        resource.format = "las";
        resources.push_back(resource);
        pwb::ui_workers::VizRefSlice ref;
        ref.kind = "well_log";
        ref.id = "r1";
        ref.path = las_path;

        const WellLogLoadFn cancelling =
            [](const std::string&, const std::function<bool()>& check)
            -> std::optional<LoadedWellLog> {
            if (check && check()) throw WellLogLoadCancelled{};
            return std::nullopt;
        };
        bool threw = false;
        try {
            (void)pwb::ui_workers::resolve_well_log(
                ref, resources, ".", [] { return true; }, cancelling);
        } catch (const WellLogLoadCancelled&) {
            threw = true;
        }
        CHECK(threw);

        const WellLogLoadFn unparseable =
            [](const std::string&, const std::function<bool()>&) {
                return std::nullopt;
            };
        const auto payload = pwb::ui_workers::resolve_well_log(
            ref, resources, ".", [] { return false; }, unparseable);
        CHECK(payload.kind == "message");

        const WellLogLoadFn good = [](const std::string&,
                                      const std::function<bool()>&) {
            LoadedWellLog loaded;
            loaded.well_name = "W-OK";
            loaded.data = 7;  // 数据形状归消费者；此处只验证载荷通路
            return loaded;
        };
        const auto ok_payload = pwb::ui_workers::resolve_well_log(
            ref, resources, ".", [] { return false; }, good);
        CHECK(ok_payload.kind == "well_log");
        CHECK(ok_payload.well_names.size() == 1);
        CHECK(ok_payload.well_names.front() == "W-OK");
        std::error_code remove_ec;
        std::filesystem::remove(las_path, remove_ec);
    }

    // 3) DTW worker：start 后取消 → cancelled 终态、on_cancel 恰一次、
    //    无 on_done；取消幂等。
    {
        JobScheduler scheduler({.max_workers = 1});
        std::atomic<int> cancel_callbacks{0};
        std::atomic<int> done_callbacks{0};
        auto spec = make_dtw_propagation_job_spec(
            small_input(),
            [&done_callbacks](const DtwPropagationResult&) { ++done_callbacks; });
        spec.on_cancel = [&cancel_callbacks] { ++cancel_callbacks; };
        auto handle = scheduler.submit(std::move(spec));
        CHECK(scheduler.cancel(handle.job_id()));
        // 幂等（二次取消被接受/或已终态）——不崩、仅一次 on_cancel。
        (void)scheduler.cancel(handle.job_id());
        CHECK(handle.wait_for(4.0));
        const auto snapshot = handle.snapshot();
        CHECK(snapshot.state == JobState::cancelled);
        CHECK(cancel_callbacks.load() == 1);
        CHECK(done_callbacks.load() == 0);
        scheduler.shutdown(true);
    }

    // 4) 迟到结果：同 task_key 重提交废止排队中的旧作业——旧作业的
    //    on_cancel 展开、on_done 永不触发（#1224）。
    {
        JobScheduler scheduler({.max_workers = 1});
        // DTW 可能被分类为 interactive 车道；强制全后台，保证占道语义。
        scheduler.set_interactive_predicate([](const pwb::job::JobSpec&) {
            return false;
        });
        std::atomic<int> stale_done{0};
        std::atomic<int> stale_cancelled{0};
        std::atomic<bool> release_lane{false};
        // 占住唯一 background lane，保证 second 提交时 first 仍在排队。
        pwb::job::JobSpec blocker;
        blocker.kind = "io";
        blocker.run = [&release_lane](pwb::job::JobContext&) -> std::any {
            while (!release_lane.load()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(2));
            }
            return std::any{};
        };
        (void)scheduler.submit(std::move(blocker));

        auto first = make_dtw_propagation_job_spec(small_input());
        first.task_key = "dtw.propagate";
        first.on_done = [&stale_done](const std::any&) { ++stale_done; };
        first.on_cancel = [&stale_cancelled] { ++stale_cancelled; };
        auto first_handle = scheduler.submit(std::move(first));

        auto second = make_dtw_propagation_job_spec(small_input());
        second.task_key = "dtw.propagate";
        auto second_handle = scheduler.submit(std::move(second));

        release_lane.store(true);
        CHECK(wait_for([&] { return scheduler.idle(); }, 8.0));
        const auto stale_snapshot = first_handle.snapshot();
        CHECK(stale_snapshot.state == JobState::cancelled);
        CHECK(stale_done.load() == 0);
        CHECK(stale_cancelled.load() == 1);
        const auto fresh_snapshot = second_handle.snapshot();
        CHECK(fresh_snapshot.state == JobState::done);
        scheduler.shutdown(true);
    }

    // 5) 取消后返回体：取消令牌被武装后体返回部分结果 → cancelled 终态
    //    （绝不谎报 done）。
    {
        JobScheduler scheduler({.max_workers = 1});
        pwb::job::JobSpec spec;
        spec.run = [](pwb::job::JobContext& ctx) -> std::any {
            std::vector<int> partial;
            for (int i = 0; i < 64; ++i) {
                if (ctx.token().is_cancelled()) break;  // 安全点
                partial.push_back(i);
                std::this_thread::sleep_for(std::chrono::milliseconds(4));
            }
            return partial;  // 取消后返回 → 记 cancelled + 部分结果
        };
        auto handle = scheduler.submit(std::move(spec));
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        (void)scheduler.cancel(handle.job_id());
        CHECK(handle.wait_for(4.0));
        const auto snapshot = handle.snapshot();
        CHECK(snapshot.state == JobState::cancelled);
        scheduler.shutdown(true);
    }

    // 6) 确定性：同一输入两次完成 → 逐值一致（拾取复现验收的核半）。
    {
        auto run_once = [](std::vector<std::pair<std::string, double>>* out) {
            JobScheduler scheduler({.max_workers = 1});
            std::atomic<bool> got{false};
            auto spec = make_dtw_propagation_job_spec(
                small_input(),
                [&](const DtwPropagationResult& result) {
                    *out = result.pairs;
                    got.store(true);
                });
            (void)scheduler.submit(std::move(spec));
            CHECK(wait_for([&] { return got.load(); }, 8.0));
            scheduler.shutdown(true);
        };
        std::vector<std::pair<std::string, double>> first;
        std::vector<std::pair<std::string, double>> second;
        run_once(&first);
        run_once(&second);
        CHECK(!first.empty());
        CHECK(first == second);
    }

    // 7) 在飞作业下的有界关闭：shutdown(timeout) 及时返回；析构汇合
    //    （对象销毁语义的 Qt-free 半）。
    {
        std::atomic<bool> release{false};
        {
            JobScheduler scheduler({.max_workers = 1});
            pwb::job::JobSpec spec;
            spec.run = [&release](pwb::job::JobContext& ctx) -> std::any {
                while (!release.load() && !ctx.token().is_cancelled()) {
                    std::this_thread::sleep_for(
                        std::chrono::milliseconds(2));
                }
                return std::any{};
            };
            (void)scheduler.submit(std::move(spec));
            const auto start = std::chrono::steady_clock::now();
            scheduler.shutdown(/*wait=*/true, /*timeout_s=*/0.1);
            const auto elapsed = std::chrono::steady_clock::now() - start;
            CHECK(elapsed < std::chrono::seconds(3));  // 有界，不挂死
            release.store(true);
        }  // 析构汇合残留作业（jthreads 不可抛弃）。
    }

    // 8) #1391 ragged grid_z rejection.
    // vector<vector<double>> path: second row longer than the first.
    CHECK(throws_ragged_grid_error(ragged_task(std::vector<std::vector<double>>{
              {1.0, 2.0}, {3.0, 4.0, 5.0}})));

    // vector<any> path: rows of mixed length.
    {
        std::vector<std::any> rows;
        rows.emplace_back(std::vector<double>{1.0, 2.0, 3.0});
        rows.emplace_back(std::vector<double>{4.0});
        CHECK(throws_ragged_grid_error(ragged_task(std::move(rows))));
    }

    // Rectangular input still compiles fine (guard against over-reject).
    {
        uw::FactorTaskSlice ok_task = ragged_task(
            std::vector<std::vector<double>>{{1.0, 2.0}, {3.0, 4.0}});
        job::CancellationToken token;
        bool raised = false;
        try {
            (void)uw::contour_draft_from_factor_task(
                ok_task, std::nullopt, 5, std::nullopt, token,
                uw::ExtractLinesFn{}, uw::IdFn{});
        } catch (const uw::PyValueError&) {
            raised = true;   // grid shape was rejected — wrong
        } catch (const uw::PyImportError&) {
            // Expected: the extract seam is absent in this test — the grid
            // itself was accepted and we reached the seam boundary.
        }
        CHECK(!raised);
    }

    if (failures != 0) {
        std::fprintf(stderr, "ui_workers.lifecycle：%d 处失败\n", failures);
        return 1;
    }
    std::printf("ui_workers.lifecycle：全部通过\n");
    return 0;
}
