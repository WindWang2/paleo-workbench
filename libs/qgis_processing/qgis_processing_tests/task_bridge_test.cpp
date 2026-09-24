// qgis_processing.task_bridge — QgsTaskManager bridge lifecycle battery:
// owner single-flight/deliver, degraded/failed/JobCancelled outcomes,
// gate admission storms, task_key dedupe/supersede, bounded shutdown with
// released-suppression, TaskCenter projection and #1471 reissue parity.
// Event-loop driven (QEventLoop + timer deadline + condition polling).

#include <QElapsedTimer>
#include <QEventLoop>
#include <QPointer>
#include <QThread>
#include <QTimer>

#include <qgsapplication.h>
#include <qgstaskmanager.h>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/qgis_processing/task_source.hpp>

#include "test_framework.hpp"

#include <atomic>
#include <chrono>
#include <functional>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

using namespace pwb::qgis_processing;

// Spins the GUI event loop until `pred()` holds or the deadline expires.
// Returns pred() — a false return means "timed out".
bool spin_until(const std::function<bool()>& pred, int timeout_ms) {
    if (pred()) return true;
    QEventLoop loop;
    bool done = false;
    QTimer deadline;
    deadline.setSingleShot(true);
    QObject::connect(&deadline, &QTimer::timeout, &loop, &QEventLoop::quit);
    QTimer poller;
    QObject::connect(&poller, &QTimer::timeout, &loop,
                     [&]() {
                         if (pred()) {
                             done = true;
                             loop.quit();
                         }
                     });
    deadline.start(timeout_ms);
    poller.start(10);
    loop.exec();
    return done || pred();
}

// Extra event rounds to flush queued deliveries / deletions.
void spin_milliseconds(int ms) {
    QEventLoop loop;
    QTimer::singleShot(ms, &loop, &QEventLoop::quit);
    loop.exec();
}

QgsTaskManager* manager() { return QgsApplication::taskManager(); }

// ---- owner basics ----------------------------------------------------------

void test_owner_basic_completion() {
    PwbTaskOwner owner;
    std::atomic<bool> done{false};
    PaleoTaskOutcome received;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("basic"),
               [](PaleoTaskBodyContext& ctx) {
                   if (!ctx.sleep_interruptible(0.05)) return false;
                   ctx.set_result(QStringLiteral("payload-42"));
                   return true;
               },
               [&](const PaleoTaskOutcome& outcome) {
                   received = outcome;
                   done.store(true);
               });
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
    PWB_CHECK(received.completed);
    PWB_CHECK(!received.failed);
    PWB_CHECK(!received.cancelled);
    PWB_CHECK(!received.degraded);
    PWB_CHECK(received.result.toString() == QStringLiteral("payload-42"));
    PWB_CHECK(!owner.is_running());
}

void test_owner_progress_callbacks() {
    PwbTaskOwner owner;
    std::atomic<int> progress_calls{0};
    std::atomic<bool> done{false};
    owner.start(QStringLiteral("test.kind"), QStringLiteral("progress"),
               [](PaleoTaskBodyContext& ctx) {
                   for (int i = 1; i <= 5; ++i) {
                       if (!ctx.sleep_interruptible(0.01)) return false;
                       ctx.report_progress(i / 5.0, QStringLiteral("step"));
                   }
                   return true;
               },
               [&](const PaleoTaskOutcome&) { done.store(true); },
               [&](double, const QString&) { progress_calls.fetch_add(1); });
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
    PWB_CHECK(progress_calls.load() >= 1);
}

void test_owner_cancel() {
    PwbTaskOwner owner;
    std::atomic<bool> done{false};
    std::atomic<bool> body_entered{false};
    PaleoTaskOutcome received;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("cancel-me"),
               [&body_entered](PaleoTaskBodyContext& ctx) {
                   body_entered.store(true);
                   return ctx.sleep_interruptible(5.0);
               },
               [&](const PaleoTaskOutcome& outcome) {
                   received = outcome;
                   done.store(true);
               });
    // Wait for the body to be RUNNING (is_running() alone is also true
    // while the task is still QUEUED — cancelling then terminates it
    // before the body ever starts).
    PWB_CHECK(spin_until([&] { return body_entered.load(); }, 15000));
    owner.cancel();
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
    PWB_CHECK(received.cancelled);
    PWB_CHECK(!received.completed);
    PWB_CHECK(!received.failed);
}

void test_owner_single_flight() {
    PwbTaskOwner owner;
    std::atomic<bool> done{false};
    std::atomic<bool> body_entered{false};
    owner.start(QStringLiteral("test.kind"), QStringLiteral("long"),
               [&body_entered](PaleoTaskBodyContext& ctx) {
                   body_entered.store(true);
                   return ctx.sleep_interruptible(5.0);
               },
               [&](const PaleoTaskOutcome&) { done.store(true); });
    PWB_CHECK(spin_until([&] { return body_entered.load(); }, 15000));
    bool threw = false;
    try {
        owner.start(QStringLiteral("test.kind"), QStringLiteral("second"),
                   [](PaleoTaskBodyContext&) { return true; },
                   [](const PaleoTaskOutcome&) {});
    } catch (const std::logic_error&) {
        threw = true;
    }
    PWB_CHECK(threw);
    owner.cancel();
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
}

void test_owner_degraded() {
    PwbTaskOwner owner;
    std::atomic<bool> done{false};
    PaleoTaskOutcome received;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("degraded"),
               [](PaleoTaskBodyContext& ctx) {
                   ctx.mark_degraded(QStringLiteral("cap"));
                   return true;
               },
               [&](const PaleoTaskOutcome& outcome) {
                   received = outcome;
                   done.store(true);
               });
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
    PWB_CHECK(received.completed);
    PWB_CHECK(received.degraded);
    PWB_CHECK(received.caveat == QStringLiteral("cap"));
}

void test_owner_failure_paths() {
    // Body returns false -> failed.
    {
        PwbTaskOwner owner;
        std::atomic<bool> done{false};
        PaleoTaskOutcome received;
        owner.start(QStringLiteral("test.kind"), QStringLiteral("false-body"),
                   [](PaleoTaskBodyContext&) { return false; },
                   [&](const PaleoTaskOutcome& outcome) {
                       received = outcome;
                       done.store(true);
                   });
        PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
        PWB_CHECK(received.failed);
        PWB_CHECK(!received.completed);
        PWB_CHECK(!received.cancelled);
    }
    // Body throws std::runtime_error -> failed with the message.
    {
        PwbTaskOwner owner;
        std::atomic<bool> done{false};
        PaleoTaskOutcome received;
        owner.start(QStringLiteral("test.kind"), QStringLiteral("throwing"),
                   [](PaleoTaskBodyContext&) -> bool {
                       throw std::runtime_error("boom");
                   },
                   [&](const PaleoTaskOutcome& outcome) {
                       received = outcome;
                       done.store(true);
                   });
        PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
        PWB_CHECK(received.failed);
        PWB_CHECK(!received.cancelled);
        PWB_CHECK(received.error.contains(QStringLiteral("boom")));
    }
}

void test_owner_job_cancelled_exception() {
    PwbTaskOwner owner;
    std::atomic<bool> done{false};
    PaleoTaskOutcome received;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("safe-point"),
               [](PaleoTaskBodyContext&) -> bool {
                   throw pwb::job::JobCancelled("job-1");
               },
               [&](const PaleoTaskOutcome& outcome) {
                   received = outcome;
                   done.store(true);
               });
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
    PWB_CHECK(received.cancelled);
    PWB_CHECK(!received.failed);
    PWB_CHECK(!received.completed);
}

// ---- gate storms -------------------------------------------------------------

void test_submit_storm_120(PwbTaskGate& gate) {
    std::atomic<int> bodies_finished{0};
    for (int i = 0; i < 120; ++i) {
        gate.submit(new PaleoFunctionTask(
                        QStringLiteral("test.storm"),
                        QStringLiteral("storm %1").arg(i),
                        [&bodies_finished](PaleoTaskBodyContext& ctx) {
                            (void)ctx.sleep_interruptible(0.005);
                            ctx.report_progress(1.0);
                            bodies_finished.fetch_add(1);
                            return true;
                        }),
                    QStringLiteral("storm.%1").arg(i));
    }
    // All 120 are registered with the manager at this point (the count is a
    // live window — terminal tasks are cleaned up and drop out of it).
    const int count_after_submit = paleo_task_count();
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         60000));
    // Drain implies every body returned; give queued deletions a beat.
    spin_milliseconds(200);
    PWB_CHECK(bodies_finished.load() == 120);
    PWB_CHECK(count_after_submit >= 120);
}

void test_cancel_storm_50(PwbTaskGate& gate) {
    std::vector<QPointer<PaleoFunctionTask>> tasks;
    std::atomic<int> cancelled_bodies{0};
    for (int i = 0; i < 50; ++i) {
        auto* task = new PaleoFunctionTask(
            QStringLiteral("test.storm"), QStringLiteral("long %1").arg(i),
            [&cancelled_bodies](PaleoTaskBodyContext& ctx) {
                const bool slept = ctx.sleep_interruptible(30.0);
                if (!slept) cancelled_bodies.fetch_add(1);
                return slept;
            });
        tasks.push_back(task);
        gate.submit(task, QStringLiteral("cancel.%1").arg(i));
    }
    for (const QPointer<PaleoFunctionTask>& task : tasks) {
        if (task != nullptr) task->cancel();
    }
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         60000));
    // At least the tasks that reached a worker observed cancellation.
    PWB_CHECK(cancelled_bodies.load() >= 1);
}

// ---- task_key dedupe / supersede -----------------------------------------------

// P1-2 regression: a duplicate-key rejection out of PwbTaskOwner::start
// must neither leak the never-admitted task nor wedge the single-flight
// slot — the owner stays usable for a fresh start.
void test_owner_duplicate_key_rejection_recovers(PwbTaskGate& gate) {
    // A long RUNNING task under key K, submitted through the gate.
    std::atomic<bool> first_entered{false};
    QPointer<PaleoFunctionTask> first(
        new PaleoFunctionTask(QStringLiteral("test.dedupe"),
                              QStringLiteral("owner-dup-long"),
                              [&first_entered](PaleoTaskBodyContext& ctx) {
                                  first_entered.store(true);
                                  return ctx.sleep_interruptible(5.0);
                              }));
    gate.submit(first, QStringLiteral("owner-dup"));
    PWB_CHECK(spin_until([&] {
        return first == nullptr || first->status() == QgsTask::Running;
    }, 15000));
    PWB_CHECK(first != nullptr && first->status() == QgsTask::Running);

    // owner.start with the SAME key routes through the shared gate and
    // must throw PaleoTaskRejected — without stranding the owner.
    PwbTaskOwner owner;
    bool rejected = false;
    try {
        owner.start(QStringLiteral("test.dedupe"),
                    QStringLiteral("owner-dup-second"),
                    [](PaleoTaskBodyContext&) { return true; },
                    [](const PaleoTaskOutcome&) {},
                    /*on_progress=*/nullptr,
                    QStringLiteral("owner-dup"));
    } catch (const PaleoTaskRejected&) {
        rejected = true;
    }
    PWB_CHECK(rejected);
    PWB_CHECK(!owner.is_running());  // slot freed despite the rejection

    // The owner accepts (and delivers) a fresh start afterwards.
    std::atomic<bool> done{false};
    PaleoTaskOutcome received;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("after-reject"),
               [](PaleoTaskBodyContext& ctx) {
                   return ctx.sleep_interruptible(0.05);
               },
               [&](const PaleoTaskOutcome& outcome) {
                   received = outcome;
                   done.store(true);
               });
    PWB_CHECK(spin_until([&] { return done.load(); }, 15000));
    PWB_CHECK(received.completed);

    if (first != nullptr) first->cancel();
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         30000));
    spin_milliseconds(100);  // flush deleteLater + key release
}

void test_duplicate_task_key_running(PwbTaskGate& gate) {
    QPointer<PaleoFunctionTask> first(
        new PaleoFunctionTask(QStringLiteral("test.dedupe"),
                              QStringLiteral("dup-first"),
                              [](PaleoTaskBodyContext& ctx) {
                                  return ctx.sleep_interruptible(2.0);
                              }));
    gate.submit(first, QStringLiteral("dup-key"));
    PWB_CHECK(spin_until([&] {
        return first == nullptr || first->status() == QgsTask::Running;
    }, 15000));
    PWB_CHECK(first != nullptr && first->status() == QgsTask::Running);

    auto* second = new PaleoFunctionTask(
        QStringLiteral("test.dedupe"), QStringLiteral("dup-second"),
        [](PaleoTaskBodyContext&) { return true; });
    bool rejected = false;
    std::string code;
    try {
        gate.submit(second, QStringLiteral("dup-key"));
    } catch (const PaleoTaskRejected& rejection) {
        rejected = true;
        code = rejection.code();
    }
    PWB_CHECK(rejected);
    PWB_CHECK(code == kRejectDuplicateTaskKey);
    delete second;  // never admitted; the manager never owned it

    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         30000));
    spin_milliseconds(100);  // flush deleteLater + key release
}

void test_queued_supersede(PwbTaskGate& gate) {
    // Saturate the manager's thread pool so the keyed task stays QUEUED.
    const int pool_size = QThread::idealThreadCount();
    std::vector<QPointer<PaleoFunctionTask>> blockers;
    for (int i = 0; i < pool_size; ++i) {
        auto* blocker = new PaleoFunctionTask(
            QStringLiteral("test.storm"), QStringLiteral("blocker %1").arg(i),
            [](PaleoTaskBodyContext& ctx) {
                return ctx.sleep_interruptible(3.0);
            });
        blockers.push_back(blocker);
        gate.submit(blocker);
    }
    const auto all_blockers_running = [&blockers]() {
        for (const QPointer<PaleoFunctionTask>& blocker : blockers) {
            if (blocker == nullptr ||
                blocker->status() != QgsTask::Running) {
                return false;
            }
        }
        return true;
    };
    PWB_CHECK(spin_until(all_blockers_running, 15000));

    std::atomic<bool> new_completed{false};
    QPointer<PaleoFunctionTask> old_task(
        new PaleoFunctionTask(QStringLiteral("test.dedupe"),
                              QStringLiteral("superseded-old"),
                              [](PaleoTaskBodyContext& ctx) {
                                  return ctx.sleep_interruptible(1.0);
                              }));
    gate.submit(old_task, QStringLiteral("supersede-key"));
    PWB_CHECK(old_task != nullptr &&
              old_task->status() == QgsTask::Queued);

    // Same key while QUEUED: supersede (cancel the old), not reject.
    gate.submit(new PaleoFunctionTask(
                    QStringLiteral("test.dedupe"),
                    QStringLiteral("superseded-new"),
                    [&new_completed](PaleoTaskBodyContext&) {
                        new_completed.store(true);
                        return true;
                    }),
                QStringLiteral("supersede-key"));
    PWB_CHECK(old_task == nullptr ||
              old_task->status() == QgsTask::Terminated);
    PWB_CHECK(!new_completed.load());  // still queued behind the blockers

    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         60000));
    PWB_CHECK(new_completed.load());
}

// ---- shutdown / released suppression ---------------------------------------------

void test_shutdown_bounded_and_suppressed() {
    PwbTaskOwner owner;
    std::atomic<bool> delivered{false};
    std::atomic<bool> body_entered{false};
    QElapsedTimer timer;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("shutdown-me"),
               // Non-cooperative body: ignores cancellation for 1 s.
               [&body_entered](PaleoTaskBodyContext&) {
                   body_entered.store(true);
                   std::this_thread::sleep_for(std::chrono::milliseconds(1000));
                   return true;
               },
               [&](const PaleoTaskOutcome&) { delivered.store(true); });
    PWB_CHECK(spin_until([&] { return body_entered.load(); }, 15000));
    timer.start();
    const bool finished_in_time = owner.shutdown(200);
    // Bounded: returns around the 200 ms cap, never the body's full second.
    PWB_CHECK(timer.elapsed() < 900);
    PWB_CHECK(!finished_in_time);  // body is still mid-sleep at the deadline
    // P2-8: the timeout frees the owner slot (the manager adopts the task).
    PWB_CHECK(!owner.is_running());
    // The task still terminates later; the released flag must suppress the
    // delivery (on_done never fires after shutdown).
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         15000));
    spin_milliseconds(300);
    PWB_CHECK(!delivered.load());
}

// P1-3 regression: QgsTask::waitForFinished(0) means "wait forever" in QGIS
// (timeout 0 -> INT_MAX), so shutdown(0) must skip the wait entirely and
// return immediately while the body is still running.
void test_shutdown_zero_returns_immediately() {
    PwbTaskOwner owner;
    std::atomic<bool> body_entered{false};
    std::atomic<bool> delivered{false};
    QElapsedTimer timer;
    owner.start(QStringLiteral("test.kind"), QStringLiteral("shutdown-zero"),
               // Non-cooperative body: ignores cancellation for 2 s.
               [&body_entered](PaleoTaskBodyContext&) {
                   body_entered.store(true);
                   std::this_thread::sleep_for(std::chrono::milliseconds(2000));
                   return true;
               },
               [&](const PaleoTaskOutcome&) { delivered.store(true); });
    PWB_CHECK(spin_until([&] { return body_entered.load(); }, 15000));
    timer.start();
    const bool finished_in_time = owner.shutdown(0);
    PWB_CHECK(timer.elapsed() < 100);  // 0 = don't wait, not wait-forever
    PWB_CHECK(!finished_in_time);
    // P2-8: the no-wait path frees the owner slot as well.
    PWB_CHECK(!owner.is_running());
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         15000));
    spin_milliseconds(300);
    PWB_CHECK(!delivered.load());  // released flag suppresses the delivery
}

// ---- TaskCenter projection --------------------------------------------------------

void test_task_source_projection(PwbTaskGate& gate) {
    QPointer<PaleoFunctionTask> probe(
        new PaleoFunctionTask(QStringLiteral("projection.kind"),
                              QStringLiteral("rows-probe"),
                              [](PaleoTaskBodyContext& ctx) {
                                  return ctx.sleep_interruptible(0.5);
                              }));
    probe->set_run_id(QStringLiteral("run-7"));
    const long probe_id = gate.submit(probe, QStringLiteral("rows.key"));
    PWB_CHECK(spin_until([&] {
        return probe == nullptr || probe->status() == QgsTask::Running;
    }, 15000));

    bool row_found = false;
    QString row_state;
    for (const PaleoTaskRow& row : paleo_task_rows()) {
        if (row.task_key != QStringLiteral("rows.key")) continue;
        row_found = true;
        row_state = row.state;
        PWB_CHECK(row.id == QString::number(probe_id));
        PWB_CHECK(row.kind == QStringLiteral("projection.kind"));
        PWB_CHECK(row.run_id == QStringLiteral("run-7"));
        PWB_CHECK(row.title == QStringLiteral("rows-probe"));
        PWB_CHECK(row.cancel_supported);
    }
    PWB_CHECK(row_found);
    PWB_CHECK(row_state == QStringLiteral("running"));
    PWB_CHECK(paleo_task_count() >= 1);

    // Cancel by row id; unknown/invalid ids fail honestly.
    PWB_CHECK(cancel_paleo_task(QString::number(probe_id)));
    PWB_CHECK(!cancel_paleo_task(QStringLiteral("not-a-number")));
    PWB_CHECK(!cancel_paleo_task(QStringLiteral("999999")));
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         15000));
    spin_milliseconds(100);
    PWB_CHECK(!cancel_paleo_task(QString::number(probe_id)));
}

// ---- #1471 reissue parity -----------------------------------------------------------

void test_reissue_when_terminal() {
    PwbTaskOwner owner;
    QObject context;
    std::atomic<int> reissue_runs{0};
    std::atomic<bool> on_gui_thread{false};
    std::atomic<bool> done{false};
    owner.start(QStringLiteral("test.kind"), QStringLiteral("reissue-host"),
               [](PaleoTaskBodyContext& ctx) {
                   return ctx.sleep_interruptible(0.1);
               },
               [&](const PaleoTaskOutcome&) { done.store(true); });
    PWB_CHECK(owner.is_running());
    reissue_when_terminal(owner, &context, [&] {
        reissue_runs.fetch_add(1);
        on_gui_thread.store(QThread::currentThread() ==
                            QgsApplication::instance()->thread());
    });
    PWB_CHECK(spin_until([&] { return reissue_runs.load() >= 1; }, 15000));
    spin_milliseconds(300);  // exactly once, not re-fired by later rounds
    PWB_CHECK(reissue_runs.load() == 1);
    PWB_CHECK(on_gui_thread.load());
    PWB_CHECK(done.load());
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    PWB_CHECK(manager() != nullptr);

    test_owner_basic_completion();
    test_owner_progress_callbacks();
    test_owner_cancel();
    test_owner_single_flight();
    test_owner_degraded();
    test_owner_failure_paths();
    test_owner_job_cancelled_exception();

    {
        PwbTaskGate gate;  // no governor: pure admission-free policy tests
        set_shared_task_gate(&gate);

        test_submit_storm_120(gate);
        test_cancel_storm_50(gate);
        test_owner_duplicate_key_rejection_recovers(gate);
        test_duplicate_task_key_running(gate);
        test_queued_supersede(gate);
        test_task_source_projection(gate);

        set_shared_task_gate(nullptr);
    }

    test_shutdown_bounded_and_suppressed();
    test_shutdown_zero_returns_immediately();
    test_reissue_when_terminal();

    // No residue before QGIS teardown.
    PWB_CHECK(spin_until([&] { return manager()->countActiveTasks() == 0; },
                         15000));

    pwb::qgis::QgisRuntime::release();
    return ::pwb::test::report("qgis_processing.task_bridge");
}
