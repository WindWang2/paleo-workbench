// QGIS Processing/Task convergence — JobCenter implementation (job_center.hpp).

#include "job_center.hpp"

#include <QCoreApplication>
#include <QDateTime>
#include <QThread>
#include <QTimer>

#include <qgsapplication.h>
#include <qgstaskmanager.h>

#include <pwb/job_runtime/resource_governor.hpp>
#include <pwb/qgis_processing/provider.hpp>
#include <pwb/qgis_processing/task_source.hpp>

namespace pwb::app {

JobCenter::JobCenter() {
    install_processing_runtime();
    // App quit must never die with live tasks: cancel everything and give
    // the manager a bounded drain window (quit-drain parity).
    QObject::connect(QCoreApplication::instance(), &QCoreApplication::aboutToQuit,
                     QCoreApplication::instance(), []() {
                         QgsTaskManager* manager = QgsApplication::taskManager();
                         if (manager == nullptr) return;
                         manager->cancelAll();
                         // Bounded drain: the event loop is going down, so
                         // poll with processEvents like the retired bridge's
                         // quit drain did.
                         const QDateTime deadline =
                             QDateTime::currentDateTimeUtc().addMSecs(5000);
                         while (manager->countActiveTasks() > 0 &&
                                QDateTime::currentDateTimeUtc() < deadline) {
                             QCoreApplication::processEvents(
                                 QEventLoop::AllEvents, 50);
                             QThread::msleep(10);
                         }
                     });
}

JobCenter::~JobCenter() {
    alive_->store(false);
    for (const auto& owner : owners_) {
        owner->shutdown(0);
    }
    if (pwb::qgis_processing::shared_task_gate() == gate_.get()) {
        pwb::qgis_processing::set_shared_task_gate(nullptr);
    }
}

void JobCenter::install_processing_runtime() {
    if (gate_ == nullptr) {
        gate_ = std::make_unique<pwb::qgis_processing::PwbTaskGate>();
        // The retained governance stack stays the admission authority
        // (resource leases QGIS does not model).
        gate_->set_governor(&pwb::job::global_governor());
        pwb::qgis_processing::set_shared_task_gate(gate_.get());
    }
    pwb::qgis_processing::install_paleo_provider();
}

pwb::qgis_processing::PwbTaskOwner& JobCenter::make_owner(QObject* parent) {
    owners_.push_back(
        std::make_unique<pwb::qgis_processing::PwbTaskOwner>(parent));
    return *owners_.back();
}

std::vector<pwb::job::JobSnapshot> JobCenter::task_snapshots() const {
    std::vector<pwb::job::JobSnapshot> snapshots;
    for (const pwb::qgis_processing::PaleoTaskRow& row :
         pwb::qgis_processing::paleo_task_rows()) {
        pwb::job::JobSnapshot snapshot;
        snapshot.job_id = row.id.toStdString();
        snapshot.task_key = row.task_key.toStdString();
        snapshot.kind = row.kind.toStdString();
        snapshot.title = row.title.toStdString();
        snapshot.progress = row.progress;
        snapshot.cancel_requested = row.state == QLatin1String("cancelled");
        if (row.state == QLatin1String("queued") ||
            row.state == QLatin1String("hold")) {
            snapshot.state = pwb::job::JobState::queued;
        } else if (row.state == QLatin1String("running")) {
            snapshot.state = pwb::job::JobState::running;
        } else if (row.state == QLatin1String("degraded")) {
            snapshot.state = pwb::job::JobState::degraded;
        } else if (row.state == QLatin1String("failed")) {
            snapshot.state = pwb::job::JobState::failed;
            snapshot.error = "task failed";
        } else if (row.state == QLatin1String("cancelled")) {
            snapshot.state = pwb::job::JobState::cancelled;
        } else {
            snapshot.state = pwb::job::JobState::done;
        }
        snapshots.push_back(std::move(snapshot));
    }
    return snapshots;
}

int JobCenter::task_count() const { return pwb::qgis_processing::paleo_task_count(); }

bool JobCenter::cancel_task(const QString& task_id) {
    return pwb::qgis_processing::cancel_paleo_task(task_id);
}

void JobCenter::shutdown_workers(int wait_ms) {
    for (const auto& owner : owners_) {
        if (owner->is_running()) {
            owner->shutdown(wait_ms);
        }
    }
}

}  // namespace pwb::app
