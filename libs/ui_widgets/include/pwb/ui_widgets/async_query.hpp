#pragma once

// UI-02 — single-slot latest-only async query facade + the owned
// worker-thread job it wraps, ported from
// paleo_workbench/ui/modelview/async_query.py +
// paleo_workbench/ui/owned_worker_job.py +
// paleo_workbench/ui/thread_keeper.py (goal §9 GUI-thread contract).
//
// Hard constraints (01-ui-audit D1/D4):
//  - the query function NEVER runs on the GUI thread;
//  - every submit bumps an epoch; callbacks fire only for the LATEST
//    epoch (latest-only);
//  - after shutdown()/destruction every late callback is dropped
//    (job released flag + epoch check — double safety);
//  - cancel is cooperative: the submitter may pass a cancel hook that a
//    newer submit invokes when it takes the slot.
//
// Thread facilities: an owned QThread per job (one job at a time,
// queued delivery, destruction-safe), plus a process-lifetime detached
// keeper for jobs that outlive their owner (#1057: worker affinity is
// pushed off the dying worker thread via a DirectConnection on
// finished — the only legal direction).

#include <QObject>
#include <QVariant>
#include <QString>
#include <QThread>

#include <atomic>
#include <functional>
#include <map>
#include <memory>

namespace pwb::ui_widgets {
namespace detail {

// Single-function worker: run() executes the query on the owned thread
// and emits done to terminate it. Must be constructed WITHOUT a parent
// so moveToThread can relocate it (C17 — a parented worker would
// silently stay on the GUI thread).
class QueryWorker : public QObject {
    Q_OBJECT
public:
    QueryWorker(std::function<QVariant()> fn, int epoch)
        : fn_(std::move(fn)), epoch_(epoch) {}

public slots:
    void run();

signals:
    void done();
    void call(int epoch, const QVariant& result);
    void fail(int epoch, const QString& error);

private:
    std::function<QVariant()> fn_;
    int epoch_;
};

// Owns one worker thread until it has completely stopped (the Python
// OwnedWorkerJob). The released flag marks the slot dead before any
// already-queued delivery can commit.
class QueryJob : public QObject {
    Q_OBJECT
public:
    explicit QueryJob(QObject* parent = nullptr);
    ~QueryJob() override;

    void start(QueryWorker* worker,
               std::function<void()> cancel,
               int target);
    void cancel();  // cooperative — never force-kills native code
    bool shutdown(int wait_ms = 3000);
    bool is_running() const { return thread_ != nullptr; }
    int target() const { return target_; }

signals:
    void released();

private slots:
    void on_thread_stopped();

private:
    void release_identity(bool delete_thread);

    QThread* thread_ = nullptr;         // owned until release/adopt
    QueryWorker* worker_ = nullptr;     // owned until release/adopt
    std::function<void()> cancel_;
    int target_ = -1;
    std::shared_ptr<std::atomic<bool>> released_;
};

// Application-lifetime ownership for jobs that outlive their owner
// (detached_job_keeper parity): keeps the QThread+worker alive until
// the thread actually finishes, then deletes them on the app thread.
class DetachedJobKeeper : public QObject {
    Q_OBJECT
public:
    static DetachedJobKeeper& instance();

    void adopt(QThread* thread, QObject* worker);
    int job_count() const { return int(jobs_.size()); }

private slots:
    void release(QThread* key);

private:
    std::map<QThread*, QObject*> jobs_;
};

}  // namespace detail

// Single-slot latest-only async query facade (constructed and used on
// the GUI thread). Heavier service calls (full SQL, hashing, lineage
// traversal, large JSON) MUST go through here rather than being called
// synchronously on the GUI thread; light in-memory lookups may stay
// synchronous (module docstring parity).
class AsyncQuery : public QObject {
    Q_OBJECT
public:
    explicit AsyncQuery(QObject* parent = nullptr);
    ~AsyncQuery() override { shutdown(0); }

    bool is_pending() const;

    // Cancel and wait for the in-flight query (page close / project
    // shutdown). Bumps the epoch so every in-flight delivery dies.
    void shutdown(int wait_ms = 500);

    // Run `fn` on a worker thread, deliver the result to `on_ready` on
    // the GUI thread. Returns this submission's epoch. When a query is
    // already in flight: the old one is cooperatively cancelled and its
    // slot released immediately — its result is never delivered.
    //
    // on_error receives the worker's exception message (the Python
    // callback receives the exception object; across the C++ boundary
    // the message string is the honest equivalent).
    int submit(std::function<QVariant()> fn,
               std::function<void(const QVariant& result)> on_ready,
               std::function<void(const QString& error)> on_error = {},
               std::function<void()> cancel = {});

private slots:
    void deliver(int epoch, const QVariant& result);
    void deliver_error(int epoch, const QString& error);

private:
    int epoch_ = 0;
    detail::QueryJob* job_ = nullptr;  // child object; slot may outlive the pointer
    std::function<void(const QVariant&)> on_ready_;
    std::function<void(const QString&)> on_error_;
};

}  // namespace pwb::ui_widgets
