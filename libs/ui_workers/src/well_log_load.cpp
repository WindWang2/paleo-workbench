#include "pwb/ui_workers/well_log_load.hpp"

namespace pwb::ui_workers {

void request_well_log_cancel(const WellLogLoadPhasePtr& phase,
                             const std::function<void()>& on_cancelling) {
    if (!phase) return;
    // cancel() parity: set the event first; the honest hint fires exactly
    // once — only when the parse is in flight on the FIRST cancel call.
    const bool was = phase->cancel_requested.exchange(true);
    if (!was && phase->parse_active.load() &&
        !phase->cancelling_sent.exchange(true)) {
        if (on_cancelling) on_cancelling();
    }
}

WellLogLoadResult run_well_log_load(const WellLogLoadInput& input,
                                    job::JobContext& ctx) {
    return with_py_errors([&]() -> WellLogLoadResult {
        const auto is_cancelled = [&] {
            return (input.phase &&
                    input.phase->cancel_requested.load()) ||
                   ctx.token().is_cancelled();
        };
        // Pre-parse cancel: cancelled WITHOUT running the parse (and no
        // cancelling hint — nothing was in flight).
        if (is_cancelled()) {
            throw job::JobCancelled(ctx.job_id());
        }
        if (input.phase) input.phase->parse_active.store(true);
        VizPayloadSlice payload;
        try {
            if (input.resolve_fn) {
                payload = input.resolve_fn(input.ref, input.resources,
                                           input.project_root, is_cancelled);
            } else {
                payload = viz_resolve(input.ref, input.resources,
                                      input.project_root, is_cancelled,
                                      input.load_fn);
            }
        } catch (const WellLogLoadCancelled&) {
            if (input.phase) input.phase->parse_active.store(false);
            throw job::JobCancelled(ctx.job_id());
        } catch (const job::JobCancelled& exc) {
            if (input.phase) input.phase->parse_active.store(false);
            // Same blanket-`except Exception` parity as correlation: a
            // JobCancelled without the flag set is a failure text
            // ("JobCancelled: msg"), not a cancel.
            if (!is_cancelled()) {
                throw PyStyleError("JobCancelled", exc.what());
            }
            throw;
        } catch (const std::exception& exc) {
            if (input.phase) input.phase->parse_active.store(false);
            if (is_cancelled()) {
                throw job::JobCancelled(ctx.job_id());
            }
            rethrow_as_py_error(exc);
        }
        // finally: _parse_started=False — cleared BEFORE the late-result
        // check so a post-run cancel() can't emit a spurious cancelling.
        if (input.phase) input.phase->parse_active.store(false);
        if (is_cancelled()) {
            // Late result DISCARDED — cancelled, finished never fires.
            // Throwing JobCancelled keeps the dropped payload out of the
            // recorded result (true discard parity).
            throw job::JobCancelled(ctx.job_id());
        }
        return {std::move(payload)};
    });
}

job::JobSpec make_well_log_load_job_spec(
    WellLogLoadInput input,
    std::function<void(const WellLogLoadResult&)> on_done,
    std::function<void(const std::string&)> on_fail,
    std::function<void()> on_cancel) {
    job::JobSpec spec;
    spec.kind = "load.well_log";
    spec.title = "井曲线加载";
    spec.run = [input = std::move(input)](job::JobContext& ctx) -> std::any {
        return run_well_log_load(input, ctx);
    };
    spec.on_done = [on_done = std::move(on_done)](const std::any& result) {
        if (on_done) {
            on_done(std::any_cast<const WellLogLoadResult&>(result));
        }
    };
    spec.on_fail = std::move(on_fail);
    spec.on_cancel = std::move(on_cancel);
    return spec;
}

}  // namespace pwb::ui_workers
