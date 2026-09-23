#pragma once

// Unified Processing entry points. GUI, Agent, batch and E2E callers all
// go through these (or through QgsProcessingRegistry directly) — never
// around them to the kernels.

#include <functional>
#include <memory>

#include <QVariantMap>

#include <qgsprocessingcontext.h>
#include <qgstaskmanager.h>

#include <QString>
#include <QStringList>

class QgsProject;
class QgsProcessingAlgorithm;
class QgsProcessingFeedback;

namespace pwb::qgis_processing {

struct PaleoAlgorithmInfo {
    QString id;           // "paleo:<name>"
    QString name;         // "<name>"
    QString display_name;
    QString group_id;
    QString group;
};

// Discovery from the registry (provider "paleo" only).
[[nodiscard]] QList<PaleoAlgorithmInfo> paleo_algorithm_infos();
[[nodiscard]] QStringList paleo_algorithm_ids();

// Registry prototype lookup by full id ("paleo:<name>"). The prototype is
// owned by the registry — createInstance()/run() clone it; callers must
// not mutate or delete it. Null when the id is unknown or the registry is
// not initialized. Use for parameter-schema introspection before a run.
[[nodiscard]] const QgsProcessingAlgorithm* paleo_algorithm_prototype(
    const QString& id);

// Synchronous run (main thread only — QgsProcessingAlgorithm::run
// contract). Returns false with `error` set on failure or cancellation
// (cancelled runs report error.isEmpty() == false with a "cancelled" marker
// in `cancelled`).
bool run_paleo_algorithm(const QString& id, const QVariantMap& parameters,
                         QgsProject* project, QgsProcessingFeedback* feedback,
                         QVariantMap& results, QString& error, bool* cancelled = nullptr);

// Self-contained Processing task: owns algorithm instance, context and
// feedback, follows the prepare (main thread) / runPrepared (task thread) /
// postProcess (finished, main thread) contract of
// QgsProcessingAlgRunnerTask but keeps the context alive for the task
// lifetime, which the stock runner task cannot.
class PaleoAlgorithmTask final : public QgsTask {
    Q_OBJECT
public:
    using Done = std::function<void(bool ok, const QVariantMap& results)>;

    // Main thread. `parameters` follow the algorithm's schema; feedback may
    // be null (an internal feedback bridges progress to the task).
    PaleoAlgorithmTask(const QString& algorithm_id, QVariantMap parameters,
                       QgsProject* project, Done on_done = nullptr);
    ~PaleoAlgorithmTask() override;

    void cancel() override;

    [[nodiscard]] QString algorithm_id() const { return algorithm_id_; }
    [[nodiscard]] const QVariantMap& results() const { return results_; }
    [[nodiscard]] bool succeeded() const { return ok_; }
    [[nodiscard]] QString error_text() const { return error_; }

signals:
    void executed(bool ok, const QVariantMap& results);

protected:
    bool run() override;
    void finished(bool result) override;

private:
    QString algorithm_id_;
    QVariantMap parameters_;
    std::unique_ptr<QgsProcessingAlgorithm> algorithm_;
    std::unique_ptr<QgsProcessingFeedback> feedback_;
    // Context holds the project pointer + temp layer store; it lives with
    // the task so the worker and postProcess phases share one object
    // (QgsProcessingAlgRunnerTask cannot own its context; this task can).
    std::unique_ptr<QgsProcessingContext> context_;
    Done on_done_;
    QVariantMap results_;
    bool ok_ = false;
    bool cancelled_ = false;
    QString error_;
};

}  // namespace pwb::qgis_processing
