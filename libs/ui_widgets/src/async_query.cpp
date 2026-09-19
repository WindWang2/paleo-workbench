#include "pwb/ui_widgets/async_query.hpp"

#include <QCoreApplication>
#include <QLoggingCategory>

#include <exception>

namespace pwb::ui_widgets {
namespace {

Q_LOGGING_CATEGORY(lcAsyncQuery, "pwb.ui_widgets.async_query")

// #1057: Qt only permits pushing a QObject OUT of the thread it
// currently belongs to — i.e. this must run on the dying worker thread
// itself (DirectConnection on QThread::finished), never as a pull from
// the GUI thread.
void push_worker_to_app_thread(QObject* worker) {
    QCoreApplication* app = QCoreApplication::instance();
    if (app == nullptr || worker->thread() == app->thread()) {
        return;
    }
    worker->moveToThread(app->thread());
}

}  // namespace

namespace detail {

// ------------------------------------------------------------- QueryWorker

void QueryWorker::run() {
    try {
        QVariant result = fn_();
        emit call(epoch_, result);
    } catch (const std::exception& e) {
        emit fail(epoch_, QString::fromUtf8(e.what()));
    } catch (...) {
        emit fail(epoch_, QStringLiteral("unknown worker error"));
    }
    emit done();
}

// ---------------------------------------------------------------- QueryJob

QueryJob::QueryJob(QObject* parent) : QObject(parent) {}

QueryJob::~QueryJob() {
    // Destroyed without an explicit shutdown: detach any running thread
    // so the worker can finish without touching the dead owner (the
    // Python destroyed -> _safe_detach_on_destroy wiring).
    if (thread_ != nullptr && thread_->isRunning()) {
        released_->store(true);
        if (cancel_) {
            try {
                cancel_();
            } catch (...) {
            }
        }
        disconnect(thread_, &QThread::finished, this, nullptr);
        thread_->requestInterruption();
        thread_->quit();
        DetachedJobKeeper::instance().adopt(thread_, worker_);
    }
    thread_ = nullptr;
    worker_ = nullptr;
}

void QueryJob::start(QueryWorker* worker,
                     std::function<void()> cancel,
                     int target) {
    if (thread_ != nullptr) {
        qFatal("QueryJob::start: job already owns a thread");
    }
    if (worker->parent() != nullptr) {
        // moveToThread cannot relocate a parented QObject (silent no-op +
        // warning), which would leave run() executing on the GUI thread.
        // Fail loudly so this wiring bug can never regress (C17).
        qFatal("QueryJob::start: worker must be constructed without a parent");
    }

    released_ = std::make_shared<std::atomic<bool>>(false);
    thread_ = new QThread;  // no parent: released or adopted explicitly
    worker_ = worker;
    cancel_ = std::move(cancel);
    target_ = target;
    worker_->moveToThread(thread_);
    connect(thread_, &QThread::started, worker_, &QueryWorker::run);
    connect(worker_, &QueryWorker::done, thread_, &QThread::quit,
            Qt::DirectConnection);
    // Push worker affinity back to the app thread while the worker
    // thread is still winding down (#1057 — legal direction).
    connect(thread_, &QThread::finished, worker_,
            [w = worker_] { push_worker_to_app_thread(w); },
            Qt::DirectConnection);
    // Deferred release on the GUI thread (queued — the finished signal
    // is emitted from the managed thread).
    connect(thread_, &QThread::finished, this, &QueryJob::on_thread_stopped,
            Qt::QueuedConnection);
    thread_->start();
}

void QueryJob::cancel() {
    if (cancel_) {
        try {
            cancel_();
        } catch (...) {
        }
    }
}

bool QueryJob::shutdown(int wait_ms) {
    QThread* thread = thread_;
    QueryWorker* worker = worker_;
    if (thread == nullptr || worker == nullptr) {
        return true;
    }

    // Mark released before disconnecting so any already-queued delivery
    // is dropped (epoch also guards at the AsyncQuery level).
    released_->store(true);
    disconnect(thread, &QThread::finished, this,
               &QueryJob::on_thread_stopped);
    cancel();

    bool joined = true;
    thread->requestInterruption();
    if (thread->isRunning()) {
        thread->quit();
        joined = thread->wait(qMax(0, wait_ms));
    }
    if (!joined) {
        thread->requestInterruption();
        thread->quit();
        DetachedJobKeeper::instance().adopt(thread, worker);
    }
    release_identity(/*delete_thread=*/joined);
    return joined;
}

void QueryJob::on_thread_stopped() {
    QThread* thread = thread_;
    QueryWorker* worker = worker_;
    if (thread == nullptr || worker == nullptr) {
        return;
    }
    release_identity(/*delete_thread=*/true);
}

void QueryJob::release_identity(bool delete_thread) {
    QThread* thread = thread_;
    QueryWorker* worker = worker_;
    released_->store(true);
    thread_ = nullptr;
    worker_ = nullptr;
    cancel_ = {};
    if (delete_thread) {
        // Worker affinity is already the app thread (pushed on
        // finished); deleteLater posts to the app event loop.
        if (worker != nullptr) {
            worker->deleteLater();
        }
        if (thread != nullptr) {
            thread->deleteLater();
        }
    }
    emit released();
}

// ------------------------------------------------------- DetachedJobKeeper

DetachedJobKeeper& DetachedJobKeeper::instance() {
    static DetachedJobKeeper keeper;
    return keeper;
}

void DetachedJobKeeper::adopt(QThread* thread, QObject* worker) {
    if (jobs_.find(thread) != jobs_.end()) {
        return;
    }
    thread->setParent(this);
    jobs_[thread] = worker;
    // #1057: wire the worker's move back to the app thread NOW, as a
    // DirectConnection on finished — it executes on the still-valid
    // worker thread, the only legal push direction. A pull from the GUI
    // thread after the thread died leaves deleteLater posted to a dead
    // event queue forever (leaked QObject).
    connect(thread, &QThread::finished, thread,
            [worker] { push_worker_to_app_thread(worker); },
            Qt::DirectConnection);
    connect(thread, &QThread::finished, this,
            [this, thread] { release(thread); }, Qt::QueuedConnection);
    if (thread->isFinished()) {
        // TOCTOU: finished fired between the shutdown wait() timeout and
        // our connects — the emission is already past, release manually.
        release(thread);
    }
}

void DetachedJobKeeper::release(QThread* key) {
    const auto it = jobs_.find(key);
    if (it == jobs_.end()) {
        return;
    }
    QObject* worker = it->second;
    jobs_.erase(it);
    if (worker != nullptr) {
        if (worker->thread() != nullptr && worker->thread()->isRunning()) {
            worker->deleteLater();
        } else {
            // TOCTOU path: worker still on the dead thread — delete
            // directly (its thread no longer runs, so no event can ever
            // be delivered to it).
            delete worker;
        }
    }
    delete key;  // finished QThread: direct delete is safe
}

}  // namespace detail

// --------------------------------------------------------------- AsyncQuery

AsyncQuery::AsyncQuery(QObject* parent) : QObject(parent) {}

bool AsyncQuery::is_pending() const {
    return job_ != nullptr && job_->is_running();
}

void AsyncQuery::shutdown(int wait_ms) {
    ++epoch_;  // kill every in-flight delivery
    on_ready_ = {};
    on_error_ = {};
    if (job_ != nullptr) {
        job_->shutdown(wait_ms);
        job_ = nullptr;
    }
}

int AsyncQuery::submit(std::function<QVariant()> fn,
                       std::function<void(const QVariant&)> on_ready,
                       std::function<void(const QString&)> on_error,
                       std::function<void()> cancel) {
    if (job_ != nullptr && job_->is_running()) {
        job_->cancel();
        job_->shutdown(0);  // no wait; late results die on the epoch check
    }
    ++epoch_;
    const int epoch = epoch_;
    on_ready_ = std::move(on_ready);
    on_error_ = std::move(on_error);

    auto* worker = new detail::QueryWorker(std::move(fn), epoch);  // no parent!
    auto* job = new detail::QueryJob(this);
    // Result slots live on this (GUI-thread) object: force queued
    // delivery so a completion can never mutate Qt state from the
    // worker thread. Context `this` auto-disconnects on destruction —
    // together with the epoch check this is the released-flag double
    // safety of the Python guarded slot.
    connect(worker, &detail::QueryWorker::call, this, &AsyncQuery::deliver,
            Qt::QueuedConnection);
    connect(worker, &detail::QueryWorker::fail, this,
            &AsyncQuery::deliver_error, Qt::QueuedConnection);
    // Released jobs self-clean (high-frequency selection does not
    // accumulate released QObject children).
    connect(job, &detail::QueryJob::released, job, &QObject::deleteLater);
    job->start(worker, std::move(cancel), epoch);
    job_ = job;
    return epoch;
}

void AsyncQuery::deliver(int epoch, const QVariant& result) {
    if (epoch != epoch_) {
        return;  // late result: a newer request won or we shut down
    }
    if (job_ != nullptr && job_->target() == epoch) {
        job_ = nullptr;  // slot cleanup only on the GUI thread
    }
    auto callback = on_ready_;
    if (callback) {
        try {
            callback(result);
        } catch (const std::exception& e) {
            qCWarning(lcAsyncQuery)
                << "AsyncQuery on_ready callback failed:" << e.what();
        } catch (...) {
            qCWarning(lcAsyncQuery) << "AsyncQuery on_ready callback failed";
        }
    }
}

void AsyncQuery::deliver_error(int epoch, const QString& error) {
    if (epoch != epoch_) {
        return;
    }
    if (job_ != nullptr && job_->target() == epoch) {
        job_ = nullptr;
    }
    auto callback = on_error_;
    if (callback) {
        try {
            callback(error);
        } catch (const std::exception& e) {
            qCWarning(lcAsyncQuery)
                << "AsyncQuery on_error callback failed:" << e.what();
        } catch (...) {
            qCWarning(lcAsyncQuery) << "AsyncQuery on_error callback failed";
        }
    }
}

}  // namespace pwb::ui_widgets
