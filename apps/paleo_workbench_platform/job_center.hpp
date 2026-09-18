#pragma once

// CONV-30 — product job runtime owner for the platform app.
//
// Composition root for the C++ job runtime inside MainWindow: one bounded
// scheduler (Python get_scheduler() parity: background I/O concurrency 1
// plus one dedicated interactive lane) plus the page-level ownership layer
// (JobOwner registry) that implements the close protocol of the Python
// AppShell.shutdown_workers: on window close every owner is cancelled with
// a bounded wait; residue is adopted by the process-lifetime
// DetachedJobKeeper so work continues without the window. App quit is
// covered by the bridge's quit drain (bounded scheduler drain on
// aboutToQuit).

#include <atomic>
#include <memory>
#include <vector>

#include <QObject>

#include <pwb/job_runtime/job_scheduler.hpp>
#include <pwb/job_runtime/qt/job_bridge.hpp>

namespace pwb::app {

class JobCenter {
public:
    JobCenter();
    ~JobCenter();

    JobCenter(const JobCenter&) = delete;
    JobCenter& operator=(const JobCenter&) = delete;

    [[nodiscard]] pwb::job::JobScheduler& scheduler() { return *scheduler_; }

    // Creates an owner parented to `parent` and registered for the close
    // protocol. Owners must live on the GUI thread.
    [[nodiscard]] pwb::job::qtbridge::JobOwner& make_owner(QObject* parent);

    // closeEvent protocol (bounded, GUI-safe). Returns when every owner
    // either finished within `wait_ms` or was detached to the keeper.
    void shutdown_workers(int wait_ms = 400);

    // Shared liveness flag for job bodies: jobs capture it and bail at
    // their next safe point once cleared, so MainWindow teardown can never
    // race a still-polling body. check it via cancelled-callbacks.
    [[nodiscard]] std::shared_ptr<std::atomic<bool>> alive() const {
        return alive_;
    }

private:
    std::shared_ptr<pwb::job::JobScheduler> scheduler_;
    std::shared_ptr<std::atomic<bool>> alive_ =
        std::make_shared<std::atomic<bool>>(true);
    std::vector<std::unique_ptr<pwb::job::qtbridge::JobOwner>> owners_;
};

}  // namespace pwb::app
