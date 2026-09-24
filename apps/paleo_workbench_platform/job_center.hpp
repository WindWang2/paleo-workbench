#pragma once

// QGIS Processing/Task convergence — CONV-QGIS-PROCESSING
// (docs/development/qgis-native-processing-convergence/07-target-architecture.md).
//
// JobCenter is now a projection host, not a scheduler owner:
//   * the Paleo Processing provider is registered with
//     QgsApplication::processingRegistry() (single algorithm authority);
//   * background execution lives on QgsApplication::taskManager();
//   * PwbTaskGate adds the thin Paleo policy QGIS does not have
//     (resource admission via the retained governance stack, task_key
//     dedupe/supersede, kind tagging);
//   * owners are PwbTaskOwner slots (QgsTask-backed); the manager owns
//     every task, so window-close adoption is inherent;
//   * the TaskCenter projects manager tasks through paleo_task_rows()
//     (no second scheduler, no second queue).

#include <atomic>
#include <memory>
#include <vector>

#include <QObject>
#include <QString>

#include <pwb/job_runtime/job_contract.hpp>
#include <pwb/qgis_processing/task_bridge.hpp>

namespace pwb::app {

class JobCenter {
public:
    JobCenter();
    ~JobCenter();

    JobCenter(const JobCenter&) = delete;
    JobCenter& operator=(const JobCenter&) = delete;

    // Registers the Paleo provider (idempotent) and installs the
    // governance-backed shared task gate. Requires QgisRuntime::acquire()
    // to have run (bootstrap does it before any window exists).
    void install_processing_runtime();

    // Creates an owner parented to `parent` and registered for the close
    // protocol. Owners must live on the GUI thread.
    [[nodiscard]] pwb::qgis_processing::PwbTaskOwner& make_owner(QObject* parent);

    // TaskCenter projection: QGIS manager tasks as legacy JobSnapshot DTOs
    // (the ui_workstation row layer keeps its vocabulary; the SOURCE is
    // now QgsTaskManager).
    [[nodiscard]] std::vector<pwb::job::JobSnapshot> task_snapshots() const;
    [[nodiscard]] int task_count() const;
    bool cancel_task(const QString& task_id);

    // The shared admission gate (WorkflowController's runners submit
    // through it; null never happens for an installed JobCenter, but the
    // consumer contract allows null = no admission).
    [[nodiscard]] pwb::qgis_processing::PwbTaskGate* gate() const {
        return gate_.get();
    }

    // closeEvent protocol (bounded, GUI-safe). Cancels every owner; tasks
    // keep running under the manager (adoption) unless the app quits.
    void shutdown_workers(int wait_ms = 400);

    // Shared liveness flag for task bodies (unchanged contract).
    [[nodiscard]] std::shared_ptr<std::atomic<bool>> alive() const {
        return alive_;
    }

private:
    std::shared_ptr<std::atomic<bool>> alive_ =
        std::make_shared<std::atomic<bool>>(true);
    std::vector<std::unique_ptr<pwb::qgis_processing::PwbTaskOwner>> owners_;
    std::unique_ptr<pwb::qgis_processing::PwbTaskGate> gate_;
};

}  // namespace pwb::app
