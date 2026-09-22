// job_qt.bridge — the Qt queued event bridge contracts (OwnedWorkerJob /
// DetachedJobKeeper parity): completions are delivered on the GUI thread
// (main-thread assertion); an owner destroyed or shutdown mid-job drops
// the late delivery without committing it; a stubborn job on shutdown is
// adopted by the process-lifetime keeper and reaps back to zero; app quit
// drains the scheduler.
//
// One QCoreApplication exists for the whole binary (created in main()) —
// the delivery pump is parented to it, so tests must never create their
// own.

#include <atomic>
#include <memory>

#include <QCoreApplication>
#include <QEventLoop>
#include <QThread>
#include <QTimer>

#include "job_test.hpp"
#include "pwb/job_runtime/qt/job_bridge.hpp"

using pwb::job::JobContext;
using pwb::job::JobHandle;
using pwb::job::JobScheduler;
using pwb::job::JobSpec;
using pwb::job::JobState;
using pwb::job::qtbridge::DetachedJobKeeper;
using pwb::job::qtbridge::JobOutcome;
using pwb::job::qtbridge::JobOwner;

namespace {

// Processes queued deliveries until `condition` holds or ~5 s elapsed.
void pump_events(const std::function<bool()>& condition) {
    for (int i = 0; i < 500 && !condition(); ++i) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        QThread::msleep(5);
    }
}

}  // namespace

TEST(completion_delivered_on_main_thread) {
    auto* app = QCoreApplication::instance();
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    JobOwner owner;
    std::atomic<bool> finished{false};
    std::atomic<bool> on_app_thread{false};
    std::atomic<bool> progress_on_app_thread{false};
    std::atomic<bool> degraded_seen{false};

    JobSpec spec;
    spec.run = [](JobContext& ctx) -> std::any {
        ctx.report_progress(0.5, std::nullopt, "half");
        return std::string("payload");
    };
    spec.degraded_when = [](const std::any&) { return true; };
    JobHandle handle = owner.start(
        *scheduler, std::move(spec),
        [&](const JobOutcome& outcome) {
            on_app_thread = QThread::currentThread() == app->thread();
            degraded_seen = outcome.state == JobState::degraded;
            finished = true;
        },
        [&](double, const QString&) {
            progress_on_app_thread = QThread::currentThread() == app->thread();
        });
    pump_events([&] { return finished.load(); });
    PWB_CHECK(finished.load());
    PWB_CHECK(on_app_thread.load());
    PWB_CHECK(progress_on_app_thread.load());
    PWB_CHECK(degraded_seen.load());  // GUI sees degraded, never plain done
    // The scheduler cell agrees (never reported as plain done).
    PWB_CHECK(scheduler->snapshot(handle.job_id())->state ==
              JobState::degraded);
}

TEST(plain_success_delivers_done_not_degraded) {
    // Python parity: degraded_when=None ⇒ a successful job is plain done —
    // never degraded (regression guard for the empty-predicate trap).
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    JobOwner owner;
    std::atomic<bool> finished{false};
    std::atomic<bool> done_seen{false};
    JobSpec spec;
    spec.run = [](JobContext&) -> std::any { return std::string("ok"); };
    // NO degraded_when — the exact shape that once degraded everything.
    JobHandle handle = owner.start(
        *scheduler, std::move(spec),
        [&](const JobOutcome& outcome) {
            done_seen = outcome.state == JobState::done;
            finished = true;
        });
    pump_events([&] { return finished.load(); });
    PWB_CHECK(finished.load());
    PWB_CHECK(done_seen.load());
    PWB_CHECK(scheduler->snapshot(handle.job_id())->state == JobState::done);
}

TEST(owner_destroyed_mid_job_drops_delivery) {
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    pump_events([&] {
        return DetachedJobKeeper::instance().job_count() == 0;
    });
    std::atomic<bool> delivered{false};
    {
        JobOwner owner;  // no parent: scoped destruction mid-job
        JobSpec spec;
        spec.run = [](JobContext& ctx) -> std::any {
            ctx.sleep_interruptible(0.15);
            return {};
        };
        (void)owner.start(*scheduler, std::move(spec),
                          [&](const JobOutcome&) { delivered = true; });
        // Destroy the owner while the job runs (window close parity).
    }
    // The adopted job still completes; the late delivery must be dropped.
    pump_events([&] {
        return DetachedJobKeeper::instance().job_count() == 0;
    });
    // Give any wrongly-queued delivery a chance to (wrongly) fire.
    pump_events([] { return false; });
    PWB_CHECK(!delivered.load());
}

TEST(shutdown_releases_and_suppresses_late_callbacks) {
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    JobOwner owner;
    std::atomic<bool> started{false};
    std::atomic<bool> delivered{false};
    std::atomic<bool> released_flag{false};
    JobSpec spec;
    spec.run = [&started](JobContext&) -> std::any {
        started = true;
        // Ignores the token: shutdown cannot finish it within the wait.
        QThread::msleep(120);
        return "late";
    };
    (void)owner.start(*scheduler, std::move(spec),
                      [&](const JobOutcome&) { delivered = true; });
    QObject::connect(&owner, &JobOwner::released,
                     [&] { released_flag = true; });
    // Make sure the job is RUNNING before cancelling (a queued cancel
    // would legitimately finish within the bounded wait).
    while (!started.load()) QThread::msleep(2);
    // Bounded wait → the job has no time to finish; shutdown detaches it
    // to the keeper and releases the owner.
    PWB_CHECK(owner.shutdown(30) == false);
    PWB_CHECK(released_flag.load());
    pump_events([&] {
        return DetachedJobKeeper::instance().job_count() == 0;
    });
    // Give any wrongly-queued delivery a chance to (wrongly) fire.
    pump_events([] { return false; });
    PWB_CHECK(!delivered.load());
}

TEST(stubborn_job_is_adopted_and_kept_queryable) {
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    JobOwner owner;
    std::atomic<bool> started{false};
    JobSpec spec;
    spec.run = [&started](JobContext& ctx) -> std::any {
        started = true;
        // Ignores the token for a while (uncancellable phase), then ends.
        QThread::msleep(300);
        ctx.check_cancelled();
        return "adopted-result";
    };
    JobHandle handle = owner.start(*scheduler, std::move(spec), nullptr);
    while (!started.load()) QThread::msleep(2);
    // shutdown gives up quickly; the keeper adopts the still-running job.
    PWB_CHECK(owner.shutdown(20) == false);
    PWB_CHECK(DetachedJobKeeper::instance().job_count() == 1);
    // The job eventually terminates; the keeper reaps to zero.
    PWB_CHECK(handle.wait_for(5.0));
    pump_events([&] {
        return DetachedJobKeeper::instance().job_count() == 0;
    });
    PWB_CHECK(DetachedJobKeeper::instance().job_count() == 0);
}

TEST(failed_outcome_carries_error) {
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    JobOwner owner;
    std::atomic<bool> failed{false};
    std::atomic<bool> error_seen{false};
    JobSpec spec;
    spec.run = [](JobContext&) -> std::any {
        throw std::runtime_error("native kernel exploded");
    };
    owner.start(*scheduler, std::move(spec),
                [&](const JobOutcome& outcome) {
                    failed = outcome.state == JobState::failed;
                    error_seen =
                        outcome.error.find("native kernel exploded") !=
                        std::string::npos;
                });
    pump_events([&] { return failed.load(); });
    PWB_CHECK(failed.load());
    PWB_CHECK(error_seen.load());
}

TEST(app_quit_drains_running_jobs) {
    auto* app = QCoreApplication::instance();
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    pwb::job::qtbridge::install_quit_drain(scheduler, 5000);
    JobHandle handle;
    QTimer::singleShot(0, app, [&] {
        JobSpec spec;
        spec.run = [&](JobContext& ctx) -> std::any {
            ctx.sleep_interruptible(0.2);
            return {};
        };
        handle = scheduler->submit(std::move(spec));
        // Quit while the job is still running → aboutToQuit must drain.
        QTimer::singleShot(50, app, [&] { app->quit(); });
    });
    app->exec();
    PWB_CHECK(handle.valid());
    PWB_CHECK(handle.snapshot().is_terminal());
    // The drain arms running tokens (shutdown contract): the job observed
    // the cancel at its sleep and landed cancelled — the essential part is
    // that aboutToQuit drained to a terminal state instead of dying with
    // live jthreads.
    PWB_CHECK(handle.snapshot().state == JobState::cancelled);
}

TEST(reissue_when_terminal_defers_until_owner_terminal) {
    // #1471: the scheduler's frozen contract delivers the finished
    // callback BEFORE the job's terminal state lands, so a consumer that
    // resubmits work on the same owner from inside that callback can see
    // is_running() still true — a bare start() throws logic_error out of
    // a queued slot. The terminal-aware reissue seam must run the
    // resubmit exactly once, on the GUI thread, and only once the owner
    // is terminal (so the resubmit's start() cannot throw).
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    JobOwner owner;
    QObject context;
    std::atomic<int> reissues{0};
    std::atomic<bool> ran_on_gui{false};
    std::atomic<bool> saw_terminal{true};
    std::atomic<bool> second_finished{false};

    JobSpec spec;
    spec.run = [](JobContext& ctx) -> std::any {
        ctx.sleep_interruptible(0.15);
        return "first";
    };
    std::atomic<bool> first_finished{false};
    (void)owner.start(*scheduler, std::move(spec),
                      [&](const JobOutcome&) { first_finished = true; });

    // Consumer pattern: reissue requested WHILE the owner genuinely runs
    // (a superset of the callback-before-terminal window).
    pwb::job::qtbridge::reissue_when_terminal(owner, &context, [&] {
        ++reissues;
        ran_on_gui = QThread::currentThread() ==
                     QCoreApplication::instance()->thread();
        saw_terminal = !owner.is_running();
        // The consumer immediately resubmits on the same owner — this
        // start() must be legal from inside the reissue (the seam only
        // fires once terminal; a violation aborts the test process).
        JobSpec next;
        next.run = [](JobContext&) -> std::any { return "second"; };
        (void)owner.start(*scheduler, std::move(next),
                          [&](const JobOutcome&) { second_finished = true; });
    });
    pump_events([&] { return second_finished.load(); });
    PWB_CHECK(first_finished.load());
    PWB_CHECK(reissues.load() == 1);   // exactly once, never re-queued after
    PWB_CHECK(ran_on_gui.load());
    PWB_CHECK(saw_terminal.load());    // start() inside the reissue is legal
    PWB_CHECK(second_finished.load());
}

TEST(reissue_when_terminal_fires_for_idle_owner_and_drops_with_context) {
    // An owner that never started (or is already terminal) fires the
    // reissue on the next GUI turn; a context destroyed before delivery
    // drops the pending reissue entirely.
    auto scheduler = std::make_shared<JobScheduler>(
        JobScheduler::Options{.max_workers = 1});
    {
        JobOwner idle_owner;
        QObject context;
        std::atomic<int> fired{0};
        pwb::job::qtbridge::reissue_when_terminal(idle_owner, &context,
                                                  [&] { ++fired; });
        pump_events([&] { return fired.load() > 0; });
        PWB_CHECK(fired.load() == 1);
    }
    {
        JobOwner owner;
        std::atomic<bool> started{false};
        std::atomic<int> fired{0};
        JobSpec spec;
        spec.run = [&started](JobContext& ctx) -> std::any {
            started = true;
            ctx.sleep_interruptible(0.3);
            return {};
        };
        (void)owner.start(*scheduler, std::move(spec), nullptr);
        while (!started.load()) QThread::msleep(2);
        PWB_CHECK(owner.is_running());  // the reissue below must defer
        {
            QObject context;  // destroyed while the reissue is deferred
            pwb::job::qtbridge::reissue_when_terminal(owner, &context,
                                                      [&] { ++fired; });
            // Deliberately NO event processing inside this scope: the
            // queued hop is still pending when the context dies —
            // ~QObject must drop it (a destroyed context never runs fn).
        }
        pump_events([] { return false; });  // a wrongly-kept hop fires here
        PWB_CHECK(fired.load() == 0);
        PWB_CHECK(owner.shutdown(2000));
    }
}

int main() {
    int argc = 1;
    char name[] = "job_qt.bridge";
    char* argv[] = {name, nullptr};
    QCoreApplication app(argc, argv);
    return pwb_test_main();
}
