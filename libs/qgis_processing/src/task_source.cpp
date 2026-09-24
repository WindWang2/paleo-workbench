#include <pwb/qgis_processing/task_source.hpp>

#include <qgsapplication.h>
#include <qgstaskmanager.h>

namespace pwb::qgis_processing {

namespace {
[[nodiscard]] QString state_for(const QgsTask* task) {
    switch (task->status()) {
        case QgsTask::Queued:
            return QStringLiteral("queued");
        case QgsTask::OnHold:
            return QStringLiteral("hold");
        case QgsTask::Running:
            return QStringLiteral("running");
        case QgsTask::Complete:
        case QgsTask::Terminated:
            break;
    }
    const QString outcome = task->property("pwb.outcome").toString();
    if (outcome == QLatin1String("cancelled")) return QStringLiteral("cancelled");
    if (outcome == QLatin1String("degraded")) return QStringLiteral("degraded");
    if (outcome == QLatin1String("completed")) return QStringLiteral("completed");
    if (outcome == QLatin1String("failed")) return QStringLiteral("failed");
    return task->status() == QgsTask::Complete ? QStringLiteral("completed")
                                               : QStringLiteral("failed");
}
}  // namespace

QList<PaleoTaskRow> paleo_task_rows(int limit) {
    QList<PaleoTaskRow> rows;
    QgsTaskManager* manager = QgsApplication::taskManager();
    if (manager == nullptr) return rows;
    const QList<QgsTask*> tasks = manager->tasks();
    const int first = tasks.size() > limit ? tasks.size() - limit : 0;
    for (int i = first; i < tasks.size(); ++i) {
        const QgsTask* task = tasks.at(i);
        if (task == nullptr) continue;
        PaleoTaskRow row;
        row.id = QString::number(manager->taskId(const_cast<QgsTask*>(task)));
        row.title = task->description();
        row.kind = task->property("pwb.kind").toString();
        row.task_key = task->property("pwb.task_key").toString();
        row.run_id = task->property("pwb.run_id").toString();
        row.state = state_for(task);
        row.progress = task->progress() / 100.0;
        row.cancel_supported = task->canCancel();
        rows.append(std::move(row));
    }
    return rows;
}

bool cancel_paleo_task(const QString& id) {
    QgsTaskManager* manager = QgsApplication::taskManager();
    if (manager == nullptr) return false;
    bool ok = false;
    const qlonglong task_id = id.toLongLong(&ok);
    if (!ok) return false;
    QgsTask* task = manager->task(static_cast<long>(task_id));
    if (task == nullptr) return false;
    switch (task->status()) {
        case QgsTask::Complete:
        case QgsTask::Terminated:
            return false;
        default:
            task->cancel();
            return true;
    }
}

int paleo_task_count() {
    QgsTaskManager* manager = QgsApplication::taskManager();
    return manager == nullptr ? 0 : manager->count();
}

}  // namespace pwb::qgis_processing
