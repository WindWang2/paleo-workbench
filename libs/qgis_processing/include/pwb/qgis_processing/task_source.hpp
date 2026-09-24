#pragma once

// Stateless QgsTaskManager projection for the Workstation TaskCenter
// (Phase 3 of the convergence: the task center observes QGIS tasks; it
// owns no scheduler, no queue and no history of its own beyond a bounded
// window over manager tasks).

#include <QString>
#include <QStringList>
#include <QList>

namespace pwb::qgis_processing {

struct PaleoTaskRow {
    QString id;           // task manager id (decimal)
    QString title;        // task description
    QString kind;         // "pwb.kind" tag (empty for foreign tasks)
    QString task_key;     // "pwb.task_key" tag
    QString run_id;       // "pwb.run_id" tag (provenance column)
    QString state;        // queued | hold | running | completed | degraded |
                          // failed | cancelled
    double progress = 0.0;  // [0,1]
    bool cancel_supported = false;
};

// Snapshot of the manager's tasks, newest last, bounded to `limit`
// (history parity: 200).
[[nodiscard]] QList<PaleoTaskRow> paleo_task_rows(int limit = 200);

// Cancel by row id; false when unknown/already terminal.
bool cancel_paleo_task(const QString& id);

// Count of non-hidden tasks known to the manager (active + bounded
// history).
[[nodiscard]] int paleo_task_count();

}  // namespace pwb::qgis_processing
