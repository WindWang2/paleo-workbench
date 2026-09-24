// job_compat.cpp — see include/pwb/qgis_processing/job_compat.hpp.

#include <pwb/qgis_processing/job_compat.hpp>

#include <atomic>
#include <chrono>
#include <exception>
#include <thread>
#include <utility>

namespace pwb::qgis_processing {

PaleoFunctionTask::Body body_from_job_spec(
    job::JobSpec spec, std::shared_ptr<std::any> result_stash) {
    return [spec = std::move(spec),
            stash = std::move(result_stash)](
               PaleoTaskBodyContext& ctx) mutable -> bool {
        // Cooperative-cancel bridge: the retired scheduler flipped the
        // worker-visible token from the job side; here the task's
        // isCanceled() drives the same CancellationToken (20 ms poll —
        // scheduler poll parity). Bodies that call ctx.token() /
        // check_cancelled() at safe points observe the cancel.
        job::CancellationToken token;
        std::atomic<bool> body_finished{false};
        std::thread watcher([&ctx, &token, &body_finished] {
            while (!body_finished.load(std::memory_order_acquire)) {
                if (ctx.cancel_requested()) {
                    token.cancel();
                    return;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }
        });
        job::JobContext jc(spec.task_key.empty() ? "paleo.task"
                                                 : spec.task_key,
                           token);
        jc.set_progress_sink([&ctx](double ratio, const std::string& message) {
            ctx.report_progress(ratio, QString::fromStdString(message));
        });

        std::any result;
        std::exception_ptr failure;
        std::string error_text;
        bool raised_cancelled = false;
        try {
            result = spec.run(jc);
        } catch (const job::JobCancelled&) {
            raised_cancelled = true;
        } catch (const std::exception& error) {
            failure = std::current_exception();
            error_text = error.what();
        } catch (...) {
            failure = std::current_exception();
            error_text = "unknown job body error";
        }
        body_finished.store(true, std::memory_order_release);
        watcher.join();

        // Stash BEFORE any terminal hop — a cancelled-with-partial run
        // keeps its recorded result (D6 parity); the GUI-thread finish
        // slot reads the stash after the outcome lands.
        if (stash != nullptr) *stash = result;

        const bool cancelled =
            raised_cancelled || token.is_cancelled() || ctx.cancel_requested();
        if (cancelled) {
            if (spec.on_cancel) {
                try {
                    spec.on_cancel();
                } catch (...) {
                }
            }
            // JobCancelled lands in outcome.cancelled (never failed) —
            // PaleoFunctionTask::run maps the throw.
            throw job::JobCancelled(jc.job_id());
        }
        if (failure != nullptr) {
            if (spec.on_fail) {
                try {
                    spec.on_fail(error_text);
                } catch (...) {
                }
            }
            std::rethrow_exception(failure);
        }
        bool degraded = false;
        if (spec.degraded_when) {
            try {
                degraded = spec.degraded_when(result);
            } catch (...) {
                degraded = false;
            }
        }
        if (degraded) {
            ctx.mark_degraded(
                QStringLiteral("degraded (job spec degraded_when)"));
        }
        if (spec.on_done) {
            try {
                spec.on_done(result);
            } catch (...) {
            }
        }
        return true;
    };
}

void start_job_spec(
    PwbTaskOwner& owner, job::JobSpec spec,
    std::function<void(const CompatJobOutcome&)> on_finished,
    PwbTaskOwner::Progress on_progress) {
    auto stash = std::make_shared<std::any>();
    const QString kind = QString::fromStdString(spec.kind);
    const QString title = QString::fromStdString(spec.title);
    const QString task_key = QString::fromStdString(spec.task_key);
    // The bridge reports (fraction >= 0, "") for progress ticks and
    // (-1.0, stage) for stage labels; merge back into the retired
    // (ratio, message) vocabulary — a stage hop keeps the last ratio.
    PwbTaskOwner::Progress progress;
    if (on_progress) {
        auto last_fraction = std::make_shared<double>(0.0);
        progress = [last_fraction,
                    on_progress = std::move(on_progress)](
                       double fraction, const QString& stage) {
            if (fraction >= 0.0) *last_fraction = fraction;
            on_progress(fraction >= 0.0 ? fraction : *last_fraction, stage);
        };
    }
    // Build the body BEFORE owner.start: the finish lambda moves `stash`
    // while body_from_job_spec needs a copy, and function-argument
    // evaluation order is UNSPECIFIED — under right-to-left evaluation
    // (GCC) the lambda would empty `stash` before the body captures it,
    // losing every result delivery.
    PaleoFunctionTask::Body body =
        body_from_job_spec(std::move(spec), stash);
    owner.start(
        kind, title, std::move(body),
        [stash = std::move(stash),
         on_finished = std::move(on_finished)](const PaleoTaskOutcome& o) {
            CompatJobOutcome mapped;
            if (o.cancelled) {
                mapped.state = job::JobState::cancelled;
            } else if (o.failed) {
                mapped.state = job::JobState::failed;
                mapped.error = o.error.toStdString();
            } else if (o.degraded) {
                mapped.state = job::JobState::degraded;
            } else {
                mapped.state = job::JobState::done;
            }
            if (mapped.state != job::JobState::failed) {
                mapped.result = std::move(*stash);
            }
            if (on_finished) on_finished(mapped);
        },
        std::move(progress), task_key);
}

}  // namespace pwb::qgis_processing
