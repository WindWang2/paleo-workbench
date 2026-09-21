#include "pwb/ui_workers/factor_prepare.hpp"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <future>
#include <iomanip>
#include <mutex>
#include <random>
#include <sstream>
#include <utility>

#include "pwb/ui_workers/synthetic_points.hpp"

namespace pwb::ui_workers {

const char* to_string(FactorDirtyState state) noexcept {
    switch (state) {
    case FactorDirtyState::clean:
        return "CLEAN";
    case FactorDirtyState::dirty_values:
        return "DIRTY_VALUES";
    case FactorDirtyState::dirty_geometry:
        return "DIRTY_GEOMETRY";
    case FactorDirtyState::dirty_algorithm:
        return "DIRTY_ALGORITHM";
    case FactorDirtyState::dirty_constraints:
        return "DIRTY_CONSTRAINTS";
    case FactorDirtyState::missing_output:
        return "MISSING_OUTPUT";
    case FactorDirtyState::unknown:
        return "UNKNOWN";
    }
    return "DIRTY_VALUES";
}

std::optional<FactorDirtyState> factor_dirty_state_from_string(
    const std::string& value) {
    if (value == "CLEAN") return FactorDirtyState::clean;
    if (value == "DIRTY_VALUES") return FactorDirtyState::dirty_values;
    if (value == "DIRTY_GEOMETRY") return FactorDirtyState::dirty_geometry;
    if (value == "DIRTY_ALGORITHM") return FactorDirtyState::dirty_algorithm;
    if (value == "DIRTY_CONSTRAINTS") return FactorDirtyState::dirty_constraints;
    if (value == "MISSING_OUTPUT") return FactorDirtyState::missing_output;
    if (value == "UNKNOWN") return FactorDirtyState::unknown;
    return std::nullopt;
}

namespace {

// FactorMapTask id default (models.py _id): "factor_" + uuid4 hex[:12].
// Synthesized default tasks need distinct ids — the scheduler keys results
// and the host commit indexes live tasks by id, so empty ids would collide.
std::string new_factor_task_id() {
    static std::mutex mutex;
    static std::mt19937_64 rng(std::random_device{}());
    std::lock_guard<std::mutex> guard(mutex);
    std::ostringstream out;
    out << std::hex << std::setfill('0') << std::setw(16) << rng();
    return "factor_" + out.str().substr(0, 12);
}

double steady_seconds() {
    return std::chrono::duration<double>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

std::function<double()> clock_or_default(const FactorPrepareSeams& seams) {
    return seams.clock_fn ? seams.clock_fn : steady_seconds;
}

std::any synthetic_points_or_default(const FactorPrepareSeams& seams, int seed,
                                     const std::string& factor_type) {
    if (seams.synthetic_points_fn) {
        return seams.synthetic_points_fn(seed, factor_type);
    }
    return synthetic_sample_points(seed, factor_type);
}

PrepareExecContext make_exec_ctx(const FactorPrepareSnapshot& snapshot) {
    return PrepareExecContext{snapshot.coordinate,
                              snapshot.stratigraphy,
                              snapshot.constraint_layers,
                              snapshot.project_crs,
                              snapshot.method,
                              snapshot.grid_n,
                              snapshot.power,
                              snapshot.seed,
                              snapshot.target_horizon};
}

// _task_failure — the recorded per-task diagnostic (degenerate tasks are
// marked `failed` with a `last_error` parameter instead of raising).
std::optional<std::string> task_failure(const FactorTaskSlice& task) {
    if (task.status != "failed") return std::nullopt;
    auto last_error = param_str(task, "last_error");
    return last_error.value_or("interpolation failed");
}

// (task_index, state, result_fingerprint) — indexes point into the mutable
// exec task vector so post-batch mutations (status/last_error) are read.
struct ClassifiedItem {
    std::size_t task_index;
    FactorDirtyState state;
    std::string result_fp;
};

}  // namespace

int prepare_worker_count(const FactorPrepareSeams& seams) {
    const int value = env_int("PALEO_PREPARE_WORKERS", 1);
    const int bounded = std::max(1, std::min(4, value));
    return seams.governor_clamp_fn ? seams.governor_clamp_fn(bounded)
                                   : bounded;
}

FactorPrepareSnapshot build_prepare_snapshot(
    const PrepareProjectSlice& project, int generation,
    const std::string& method, std::optional<int> grid_n, double power,
    bool force, int seed, const std::optional<std::string>& target_horizon,
    const std::optional<std::vector<std::string>>& factor_types,
    const FactorPrepareSeams& seams) {
    const auto clock = clock_or_default(seams);
    const double t0 = clock();

    std::string horizon;
    if (target_horizon && !target_horizon->empty()) {
        horizon = *target_horizon;
    } else if (!project.stratigraphy_target_horizon.empty()) {
        horizon = project.stratigraphy_target_horizon;
    } else if (!project.factor_map_tasks.empty() &&
               !project.factor_map_tasks.front().target_horizon.empty()) {
        horizon = project.factor_map_tasks.front().target_horizon;
    } else {
        horizon = "未指定层位";
    }

    FactorPrepareSnapshot snapshot;
    snapshot.tasks = project.factor_map_tasks;  // slice carries clones
    snapshot.constraint_layers = project.constraint_layers;
    snapshot.coordinate = project.coordinate;
    snapshot.stratigraphy = project.stratigraphy;

    if (snapshot.tasks.empty()) {
        const auto& types =
            factor_types ? *factor_types : kDefaultFactorTypes;
        int index = 0;
        for (const auto& factor_type : types) {
            FactorTaskSlice task;
            task.id = new_factor_task_id();
            task.name = horizon + " " + factor_type;
            task.target_horizon = horizon;
            task.factor_type = factor_type;
            task.method = method;
            task.parameters["sample_points"] = synthetic_points_or_default(
                seams, seed + index, factor_type);
            task.status = "pending";
            task.source_kind = "mixed";
            task.seed = seed + index;
            snapshot.tasks.push_back(std::move(task));
            ++index;
        }
        snapshot.created_defaults = true;
        // stratigraphy.model_copy(update={"target_horizon": horizon}) — the
        // slice's stratigraphy is opaque; the host-side update is a seam
        // (stratigraphy_with_horizon_fn) when the type supports it.
        if (seams.stratigraphy_with_horizon_fn) {
            snapshot.stratigraphy =
                seams.stratigraphy_with_horizon_fn(snapshot.stratigraphy,
                                                   horizon);
        }
    }

    snapshot.generation = generation;
    snapshot.method = method.empty() ? "IDW" : method;
    snapshot.grid_n = grid_n.value_or(kDefaultGridN);
    snapshot.power = power;
    snapshot.force = force;
    snapshot.seed = seed;
    snapshot.target_horizon = horizon;
    snapshot.project_crs = project.project_crs;
    snapshot.build_ms = (clock() - t0) * 1000.0;
    return snapshot;
}

FactorPrepareBatchResult run_factor_prepare_schedule(
    const FactorPrepareSnapshot& snapshot, const job::CancellationToken& token,
    const std::function<void(const FactorPrepareProgress&)>& progress,
    const FactorPrepareSeams& seams, int workers) {
    const int worker_n =
        workers > 0 ? std::max(1, std::min(4, workers))
                    : prepare_worker_count(seams);
    const auto clock = clock_or_default(seams);
    const double t_class0 = clock();

    const auto emit = [&](int total, int clean_n, int dirty_n, int completed,
                          int failed, int cancelled_n,
                          const std::string& phase,
                          const std::optional<std::string>& task_id,
                          const std::optional<std::string>& group,
                          const std::string& message) {
        if (!progress) return;
        FactorPrepareProgress p;
        p.generation = snapshot.generation;
        p.total_tasks = total;
        p.clean = clean_n;
        p.dirty = dirty_n;
        p.completed = completed;
        p.failed = failed;
        p.cancelled = cancelled_n;
        p.phase = phase;
        p.current_task_id = task_id;
        p.current_group = group;
        p.message = message;
        progress(p);
    };

    token.check_cancelled();

    // materialize_execution_project: a mutable task list + the exec ctx
    // (Python shares the same task objects; the slice copies are the
    // worker's private view — same observable behavior).
    std::vector<FactorTaskSlice> exec_tasks = snapshot.tasks;
    const PrepareExecContext exec_ctx = make_exec_ctx(snapshot);
    FingerprintMemo fp_memo;

    // Ensure sample points exist on pending tasks (same as batch_prepare).
    for (auto& task : exec_tasks) {
        if (param_truthy(task, "sample_points")) continue;
        const int seed =
            task.seed.has_value() ? *task.seed : snapshot.seed;
        const std::string factor_type =
            !task.factor_type.empty() ? task.factor_type : task.name;
        task.parameters["sample_points"] =
            synthetic_points_or_default(seams, seed, factor_type);
    }

    if (!seams.classify_fn) {
        throw KernelUnavailable(
            "interpolation_fingerprint (classify_factor_recompute)");
    }
    std::vector<ClassifiedItem> clean_items;
    std::vector<ClassifiedItem> dirty_items;
    for (std::size_t i = 0; i < exec_tasks.size(); ++i) {
        auto [state, result_fp] = seams.classify_fn(
            exec_tasks[i], exec_ctx, snapshot.force, &fp_memo);
        if (state == FactorDirtyState::clean) {
            clean_items.push_back({i, state, std::move(result_fp)});
        } else {
            dirty_items.push_back({i, state, std::move(result_fp)});
        }
    }
    const double classify_ms = (clock() - t_class0) * 1000.0;
    const int total = static_cast<int>(exec_tasks.size());
    const int clean_n = static_cast<int>(clean_items.size());
    const int dirty_n = static_cast<int>(dirty_items.size());

    std::map<std::string, FactorPrepareTaskResult> results_by_id;
    for (const auto& item : clean_items) {
        FactorPrepareTaskResult result;
        result.task_id = exec_tasks[item.task_index].id;
        result.dirty_state = to_string(item.state);
        result.reused = true;
        result.task = exec_tasks[item.task_index];
        result.scheduled_result_fingerprint = item.result_fp;
        results_by_id[result.task_id] = std::move(result);
    }

    emit(total, clean_n, dirty_n, clean_n, 0, 0, "classified", std::nullopt,
         std::nullopt,
         "复用 " + std::to_string(clean_n) + " · 需计算 " +
             std::to_string(dirty_n));

    const auto ordered_results = [&]() {
        std::vector<FactorPrepareTaskResult> ordered;
        for (const auto& task : exec_tasks) {
            auto it = results_by_id.find(task.id);
            if (it != results_by_id.end()) ordered.push_back(it->second);
        }
        return ordered;
    };

    if (dirty_items.empty()) {
        FactorPrepareBatchResult out;
        out.generation = snapshot.generation;
        out.method = snapshot.method;
        out.task_results = ordered_results();
        out.clean_count = clean_n;
        out.dirty_count = 0;
        out.executed_count = 0;
        out.failed_count = 0;
        out.snapshot_ms = snapshot.build_ms;
        out.classify_ms = classify_ms;
        out.execute_ms = 0.0;
        out.workers = worker_n;
        out.created_default_tasks = snapshot.created_defaults;
        // NOTE: grid_n/power stay unset here — Python's early return does
        // not pass them (defaults None/2.0).
        return out;
    }

    token.check_cancelled();

    if (!seams.batch_fn) {
        throw KernelUnavailable("batch_prepare_factor_maps");
    }

    const double t_exec0 = clock();
    int failed_n = 0;
    bool cancelled = false;
    int executed = 0;

    try {
        if (worker_n == 1 || dirty_n == 1) {
            emit(total, clean_n, dirty_n, clean_n, 0, 0, "executing",
                 std::nullopt, std::nullopt,
                 "计算 0/" + std::to_string(dirty_n));
            FactorPrepareSeams::BatchArgs args{exec_tasks, exec_ctx,
                                               snapshot.force, &fp_memo};
            seams.batch_fn(args, token);
            for (const auto& item : dirty_items) {
                ++executed;
                const auto& task = exec_tasks[item.task_index];
                auto error = task_failure(task);
                if (error) ++failed_n;
                FactorPrepareTaskResult result;
                result.task_id = task.id;
                result.dirty_state = to_string(item.state);
                result.reused = false;
                result.task = task;
                result.scheduled_result_fingerprint = item.result_fp;
                result.error = error;
                // #918: a failed run owns no grid — carrying the peeked
                // previous-run payload would let commit invalidation evict
                // a still-valid grid.
                if (!error && seams.grid_peek_fn) {
                    result.grid = seams.grid_peek_fn(task.id);
                }
                results_by_id[task.id] = std::move(result);
            }
            emit(total, clean_n, dirty_n, clean_n + executed, failed_n, 0,
                 "executed", std::nullopt, std::nullopt,
                 "计算 " + std::to_string(executed) + "/" +
                     std::to_string(dirty_n));
        } else {
            // Independent geometry groups — insertion-ordered group map
            // (Python dict order), one completion queue == as_completed.
            if (!seams.group_key_fn) {
                throw KernelUnavailable("_task_plan_group_key");
            }
            // Python keys groups on str | None (dict.setdefault(gkey)) —
            // nullopt keys share ONE group exactly like the None key.
            using GroupKey = std::optional<std::string>;
            std::vector<std::pair<GroupKey, std::vector<ClassifiedItem>>>
                groups;
            std::map<GroupKey, std::size_t> group_index;
            for (const auto& item : dirty_items) {
                GroupKey key = seams.group_key_fn(
                    exec_tasks[item.task_index], exec_ctx);
                auto it = group_index.find(key);
                if (it == group_index.end()) {
                    group_index[key] = groups.size();
                    groups.push_back({key, {item}});
                } else {
                    groups[it->second].second.push_back(item);
                }
            }

            struct GroupOutcome {
                GroupKey key;
                std::vector<FactorPrepareTaskResult> results;
                std::exception_ptr error;
            };
            std::mutex queue_mutex;
            std::condition_variable queue_cv;
            std::deque<GroupOutcome> done_queue;
            std::vector<std::future<void>> futures;
            futures.reserve(groups.size());

            const auto run_group =
                [&](const std::vector<ClassifiedItem>& items)
                -> std::vector<FactorPrepareTaskResult> {
                // Sub-exec context: clones for isolation across threads
                // (Python rebuilds a sub-ProjectDocument per group).
                std::any sub_coordinate = snapshot.coordinate;
                std::any sub_stratigraphy = snapshot.stratigraphy;
                std::vector<std::any> sub_constraints =
                    snapshot.constraint_layers;
                std::vector<FactorTaskSlice> clones;
                clones.reserve(items.size());
                for (const auto& item : items) {
                    clones.push_back(exec_tasks[item.task_index]);
                }
                std::map<std::string, FactorTaskSlice*> id_map;
                for (auto& clone : clones) id_map[clone.id] = &clone;
                PrepareExecContext sub_ctx{sub_coordinate,
                                           sub_stratigraphy,
                                           sub_constraints,
                                           snapshot.project_crs,
                                           snapshot.method,
                                           snapshot.grid_n,
                                           snapshot.power,
                                           snapshot.seed,
                                           snapshot.target_horizon};
                FactorPrepareSeams::BatchArgs args{
                    clones, sub_ctx, /*force=*/true, &fp_memo};
                seams.batch_fn(args, token);
                std::vector<FactorPrepareTaskResult> out;
                for (const auto& item : items) {
                    const auto& updated = *id_map.at(
                        exec_tasks[item.task_index].id);
                    auto error = task_failure(updated);
                    FactorPrepareTaskResult result;
                    result.task_id = updated.id;
                    result.dirty_state = to_string(item.state);
                    result.reused = false;
                    result.task = updated;
                    result.scheduled_result_fingerprint = item.result_fp;
                    result.error = error;
                    if (!error && seams.grid_peek_fn) {
                        result.grid = seams.grid_peek_fn(updated.id);
                    }
                    out.push_back(std::move(result));
                }
                return out;
            };

            for (const auto& [key, items] : groups) {
                futures.push_back(std::async(
                    std::launch::async, [&, key = key, items = items] {
                        GroupOutcome outcome;
                        outcome.key = key;
                        try {
                            outcome.results = run_group(items);
                        } catch (...) {
                            outcome.error = std::current_exception();
                        }
                        {
                            std::lock_guard<std::mutex> guard(queue_mutex);
                            done_queue.push_back(std::move(outcome));
                        }
                        queue_cv.notify_one();
                    }));
            }

            for (std::size_t i = 0; i < groups.size(); ++i) {
                GroupOutcome outcome;
                {
                    std::unique_lock<std::mutex> lock(queue_mutex);
                    queue_cv.wait(lock,
                                  [&] { return !done_queue.empty(); });
                    outcome = std::move(done_queue.front());
                    done_queue.pop_front();
                }
                token.check_cancelled();
                if (outcome.error != nullptr) {
                    const auto group_size = groups
                        .at(group_index.at(outcome.key))
                        .second.size();
                    try {
                        std::rethrow_exception(outcome.error);
                    } catch (const job::JobCancelled&) {
                        // #1168: cooperative cancel is not a group failure —
                        // mark its tasks cancelled, then re-raise so the
                        // outer handler sets cancelled=true.
                        for (const auto& item :
                             groups.at(group_index.at(outcome.key)).second) {
                            FactorPrepareTaskResult result;
                            result.task_id =
                                exec_tasks[item.task_index].id;
                            result.dirty_state = "dirty";
                            result.reused = false;
                            result.task = std::nullopt;
                            result.scheduled_result_fingerprint = "";
                            result.error = "cancelled";
                            results_by_id[result.task_id] = std::move(result);
                            ++executed;
                        }
                        throw;
                    } catch (const PyStyleError& exc) {
                        failed_n += std::max<int>(1, group_size);
                        for (const auto& item :
                             groups.at(group_index.at(outcome.key)).second) {
                            FactorPrepareTaskResult result;
                            result.task_id =
                                exec_tasks[item.task_index].id;
                            result.dirty_state = "dirty";
                            result.reused = false;
                            result.task = std::nullopt;
                            result.scheduled_result_fingerprint = "";
                            result.error =
                                "group failed: " + exc.py_message();
                            results_by_id[result.task_id] = std::move(result);
                            ++executed;
                        }
                        continue;
                    } catch (const std::exception& exc) {
                        failed_n += std::max<int>(1, group_size);
                        for (const auto& item :
                             groups.at(group_index.at(outcome.key)).second) {
                            FactorPrepareTaskResult result;
                            result.task_id =
                                exec_tasks[item.task_index].id;
                            result.dirty_state = "dirty";
                            result.reused = false;
                            result.task = std::nullopt;
                            result.scheduled_result_fingerprint = "";
                            result.error =
                                std::string("group failed: ") + exc.what();
                            results_by_id[result.task_id] = std::move(result);
                            ++executed;
                        }
                        continue;
                    }
                }
                for (const auto& item : outcome.results) {
                    if (item.error) ++failed_n;
                    results_by_id[item.task_id] = item;
                    ++executed;
                }
                emit(total, clean_n, dirty_n, clean_n + executed, failed_n, 0,
                     "executing", std::nullopt,
                     outcome.key ? *outcome.key : std::string("None"),
                     "计算 " + std::to_string(executed) + "/" +
                         std::to_string(dirty_n));
            }
            // All futures join here (vector destructor blocks).
        }
    } catch (const job::JobCancelled&) {
        cancelled = true;
        for (const auto& item : dirty_items) {
            const std::string& id = exec_tasks[item.task_index].id;
            if (results_by_id.find(id) == results_by_id.end()) {
                FactorPrepareTaskResult result;
                result.task_id = id;
                result.dirty_state = to_string(item.state);
                result.reused = false;
                result.task = std::nullopt;
                result.scheduled_result_fingerprint = item.result_fp;
                result.error = "cancelled";
                results_by_id[id] = std::move(result);
            }
        }
    }

    const double execute_ms = (clock() - t_exec0) * 1000.0;
    int cancelled_count = 0;
    for (const auto& [id, item] : results_by_id) {
        if (item.error && *item.error == "cancelled") ++cancelled_count;
    }
    if (cancelled) {
        emit(total, clean_n, dirty_n, clean_n + executed, failed_n,
             cancelled_count, "cancelled", std::nullopt, std::nullopt,
             "已取消（" + std::to_string(cancelled_count) + " 个任务未完成）");
    }

    FactorPrepareBatchResult out;
    out.generation = snapshot.generation;
    out.method = snapshot.method;
    out.task_results = ordered_results();
    out.clean_count = clean_n;
    out.dirty_count = dirty_n;
    out.executed_count = executed;
    out.failed_count = failed_n;
    out.cancelled = cancelled;
    out.cancelled_count = cancelled_count;
    out.snapshot_ms = snapshot.build_ms;
    out.classify_ms = classify_ms;
    out.execute_ms = execute_ms;
    out.workers = worker_n;
    out.created_default_tasks = snapshot.created_defaults;
    out.grid_n = snapshot.grid_n;
    out.power = snapshot.power;
    return out;
}

FactorPrepareBatchResult run_factor_prepare(const FactorPrepareInput& input,
                                            job::JobContext& ctx) {
    return with_py_errors([&]() -> FactorPrepareBatchResult {
        FactorPrepareSnapshot snapshot;
        if (input.snapshot) {
            snapshot = *input.snapshot;
        } else {
            snapshot = build_prepare_snapshot(
                input.slice, input.generation, input.method, input.grid_n,
                input.power, input.force, input.seed, input.target_horizon,
                std::nullopt, input.seams);
        }
        ctx.check_cancelled();
        const auto on_progress = [&](const FactorPrepareProgress& p) {
            if (input.on_progress) input.on_progress(p);
            if (p.total_tasks > 0) {
                ctx.report_progress(static_cast<double>(p.completed),
                                    static_cast<double>(p.total_tasks),
                                    p.message);
            }
        };
        auto result = run_factor_prepare_schedule(
            snapshot, ctx.token(), on_progress, input.seams, input.workers);
        ctx.check_cancelled();
        if (result.cancelled) {
            // Python: cancelled.emit() — the partial result stays the
            // recorded job result (scheduler cancelled-with-partial path:
            // returning a value after the token is set lands cancelled).
            ctx.token().cancel();
            return result;
        }
        return result;
    });
}

job::JobSpec make_factor_prepare_job_spec(
    FactorPrepareInput input,
    std::function<void(const FactorPrepareBatchResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "compute.factor_prepare";
    spec.title = "要素图批量插值准备";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_factor_prepare(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const FactorPrepareBatchResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_workers
