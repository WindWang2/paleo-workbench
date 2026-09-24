# Migration patterns (JobOwner/JobScheduler → QgsTaskManager)

Consumer-side reference for Wave B/C. API source: `libs/qgis_processing/include/pwb/qgis_processing/task_bridge.hpp`.

## Ownership slot

```cpp
// BEFORE (JobOwner + JobScheduler):
auto* owner = &jobs->make_owner(this);          // JobCenter factory
pwb::job::JobSpec spec;
spec.kind = "seismic.attribute";
spec.title = u"读取地震体";
spec.priority = 50;
spec.task_key = "preview.volume";
spec.run = [deps](pwb::job::JobContext& ctx) -> std::any {
    ctx.report_progress(done, total, "stage");   // done/total => [0,1] fraction
    ctx.check_cancelled();                       // throws JobCancelled
    ctx.sleep_interruptible(0.2);
    return payload;                              // std::any, copyable
};
owner->start(jobs->scheduler(), std::move(spec),
    [this](const pwb::job::qtbridge::JobOutcome& o) { /* GUI thread */ },
    [this](double done, std::optional<double> total, std::string msg) {});
owner->is_running(); owner->cancel(); owner->shutdown(3000);

// AFTER (PwbTaskOwner over QgsTaskManager):
auto* owner = &jobs->make_owner(this);           // same JobCenter factory
owner->start(QStringLiteral("seismic.attribute"), QStringLiteral("读取地震体"),
    [deps](pwb::qgis_processing::PaleoTaskBodyContext& ctx) -> bool {
        ctx.report_progress(0.5, QStringLiteral("stage"));   // fraction [0,1]
        if (ctx.cancel_requested()) return false;            // or sleep_interruptible
        ctx.sleep_interruptible(0.2);                        // false when cancelled
        ctx.set_result(QVariant::fromValue(payload));        // copyable payload
        ctx.mark_degraded(QStringLiteral("caveat"));
        return true;                                         // false = failure
    },
    [this](const pwb::qgis_processing::PaleoTaskOutcome& o) {
        if (o.completed && !o.degraded) { auto p = o.result.value<Payload>(); ... }
        else if (o.cancelled) { ... }
        else { qWarning() << o.error; }
    },
    [this](double fraction, const QString& stage) {},        // optional
    QStringLiteral("preview.volume"));                       // optional task_key
```

Mapping notes:
- `JobCancelled` thrown by a body still lands in `outcome.cancelled`.
- Outcome states: `completed` (body true), `degraded` (true + mark_degraded), `failed` (false/exception, `o.error`), `cancelled`.
- `reissue_when_terminal(PwbTaskOwner&, QObject* context, fn)` keeps #1471 semantics.
- Shutdown: cancel + bounded wait; the task keeps running under QgsTaskManager (adoption inherent — no DetachedJobKeeper).
- No scheduler instance anywhere: the shared `PwbTaskGate` (set by JobCenter) applies admission + dedupe.

## CMake

- Replace `Pwb::JobQt` links with `Pwb::QgisProcessing` (brings QGIS SDK + gate).
- Vocabulary-only consumers (JobContext/JobSpec/JobState types) link `Pwb::JobContracts` (not `Pwb::JobRuntime`).
- Only headless scheduler tests link `Pwb::JobRuntime` / `Pwb::JobQt` (gated `PWB_BUILD_JOB_SCHEDULER`, default ON).

## Projection (TaskCenter)

`JobCenter::task_snapshots()` maps `paleo_task_rows()` (QgsTaskManager → PaleoTaskRow → JobSnapshot DTO); cancel goes through `JobCenter::cancel_task(id)` → `cancel_paleo_task`.
