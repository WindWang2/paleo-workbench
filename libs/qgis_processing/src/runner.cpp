#include <pwb/qgis_processing/runner.hpp>

#include <QCoreApplication>
#include <QPointer>

#include <pwb/qgis_processing/algorithm_ids.hpp>
#include <pwb/qgis_processing/provider.hpp>

#include <qgsapplication.h>
#include <qgsexception.h>
#include <qgsfeedback.h>
#include <qgsprocessingalgorithm.h>
#include <qgsprocessingfeedback.h>
#include <qgsprocessingregistry.h>
#include <qgsproject.h>

#include <utility>

namespace pwb::qgis_processing {

QList<PaleoAlgorithmInfo> paleo_algorithm_infos() {
    QList<PaleoAlgorithmInfo> infos;
    QgsProcessingRegistry* registry = QgsApplication::processingRegistry();
    if (registry == nullptr) return infos;
    const QString provider_prefix =
        QString::fromLatin1(kProviderId) + QLatin1Char(':');
    const QList<const QgsProcessingAlgorithm*> algorithms = registry->algorithms();
    for (const QgsProcessingAlgorithm* algorithm : algorithms) {
        if (!algorithm->id().startsWith(provider_prefix)) continue;
        PaleoAlgorithmInfo info;
        info.id = algorithm->id();
        info.name = algorithm->name();
        info.display_name = algorithm->displayName();
        info.group_id = algorithm->groupId();
        info.group = algorithm->group();
        infos.append(std::move(info));
    }
    return infos;
}

QStringList paleo_algorithm_ids() {
    QStringList ids;
    for (const PaleoAlgorithmInfo& info : paleo_algorithm_infos()) {
        ids << info.id;
    }
    return ids;
}

const QgsProcessingAlgorithm* paleo_algorithm_prototype(const QString& id) {
    QgsProcessingRegistry* registry = QgsApplication::processingRegistry();
    if (registry == nullptr) return nullptr;
    return registry->algorithmById(id);
}

bool run_paleo_algorithm(const QString& id, const QVariantMap& parameters,
                         QgsProject* project, QgsProcessingFeedback* feedback,
                         QVariantMap& results, QString& error, bool* cancelled) {
    if (cancelled != nullptr) *cancelled = false;
    QgsProcessingRegistry* registry = QgsApplication::processingRegistry();
    if (registry == nullptr) {
        error = QStringLiteral("QgsApplication is not initialized");
        return false;
    }
    // Main-thread synchronous run; QgsProcessingAlgorithm::run clones the
    // registry instance internally.
    const QgsProcessingAlgorithm* prototype = registry->algorithmById(id);
    if (prototype == nullptr) {
        error = QStringLiteral("unknown algorithm id '%1'").arg(id);
        return false;
    }
    QgsProcessingContext context;
    if (project != nullptr) context.setProject(project);
    std::unique_ptr<QgsProcessingFeedback> owned_feedback;
    if (feedback == nullptr) {
        owned_feedback = std::make_unique<QgsProcessingFeedback>();
        feedback = owned_feedback.get();
    }
    bool ok = false;
    try {
        results = prototype->run(parameters, context, feedback, &ok,
                                 /*configuration=*/QVariantMap(),
                                 /*catchExceptions=*/false);
    } catch (const QgsProcessingException& failure) {
        if (feedback->isCanceled() && cancelled != nullptr) *cancelled = true;
        error = failure.what();
        return false;
    }
    // Cancellation outranks the algorithm's own ok flag: a cancel observed
    // at the run's end is a cancelled run (never success, never a plain
    // failure) — the caller maps *cancelled to its cancelled terminal
    // state. Checked BEFORE the ok verdict on purpose.
    if (feedback->isCanceled()) {
        if (cancelled != nullptr) *cancelled = true;
        if (error.isEmpty()) error = QStringLiteral("cancelled");
        return false;
    }
    if (!ok) {
        error = QStringLiteral("algorithm '%1' failed").arg(id);
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// PaleoAlgorithmTask
// ---------------------------------------------------------------------------

PaleoAlgorithmTask::PaleoAlgorithmTask(const QString& algorithm_id,
                                       QVariantMap parameters, QgsProject* project,
                                       Done on_done)
    : QgsTask(QCoreApplication::translate("pwb::qgis_processing",
                                          "Processing: %1")
                  .arg(algorithm_id)),
      algorithm_id_(algorithm_id),
      parameters_(std::move(parameters)),
      context_(std::make_unique<QgsProcessingContext>()),
      on_done_(std::move(on_done)) {
    QgsProcessingRegistry* registry = QgsApplication::processingRegistry();
    if (registry != nullptr) {
        algorithm_.reset(registry->createAlgorithmById(algorithm_id_));
    }
    if (algorithm_ == nullptr) {
        error_ = QStringLiteral("unknown algorithm id '%1'").arg(algorithm_id_);
        cancel();
        return;
    }
    if (project != nullptr) context_->setProject(project);
    feedback_ = std::make_unique<QgsProcessingFeedback>();
    // Bridge feedback progress to the task (the stock runner task does the
    // same; QgsFeedback::setProgress is not virtual). DirectConnection so
    // worker-thread progress reaches the task immediately.
    connect(feedback_.get(), &QgsFeedback::progressChanged, this,
            [this](double progress) { QgsTask::setProgress(progress); },
            Qt::DirectConnection);
    // Main-thread prepare (mirrors QgsProcessingAlgRunnerTask's contract).
    try {
        if (!algorithm_->prepare(parameters_, *context_, feedback_.get())) {
            error_ = QStringLiteral("algorithm '%1' failed to prepare").arg(algorithm_id_);
            cancel();
        }
    } catch (const QgsProcessingException& failure) {
        error_ = failure.what();
        cancel();
    }
}

PaleoAlgorithmTask::~PaleoAlgorithmTask() = default;

void PaleoAlgorithmTask::cancel() {
    // Cancel the run's feedback too so a cancel observed from any thread
    // stops the algorithm at its next safe point (stock
    // QgsProcessingAlgRunnerTask parity). feedback_ may still be null when
    // the constructor fails before creating it.
    if (feedback_ != nullptr) feedback_->cancel();
    QgsTask::cancel();
}

bool PaleoAlgorithmTask::run() {
    if (algorithm_ == nullptr || !error_.isEmpty()) return false;
    try {
        results_ = algorithm_->runPrepared(parameters_, *context_, feedback_.get());
        ok_ = true;
    } catch (const QgsProcessingException& failure) {
        error_ = failure.what();
        ok_ = false;
    }
    // Stock runner semantics: a run that reports success while the
    // feedback is cancelled is still a cancelled run — success alongside a
    // cancel request would publish partial output as complete.
    if (feedback_ != nullptr && feedback_->isCanceled()) {
        ok_ = false;
        cancelled_ = true;
    }
    setProperty("pwb.outcome",
                ok_ ? QStringLiteral("completed")
                    : (cancelled_ ? QStringLiteral("cancelled")
                                  : QStringLiteral("failed")));
    return ok_;
}

void PaleoAlgorithmTask::finished(bool result) {
    // Main thread. postProcess publishes sinks/layers created during run.
    if (algorithm_ != nullptr && result) {
        try {
            QVariantMap post =
                algorithm_->postProcess(*context_, feedback_.get(), /*runResult=*/true);
            if (!post.isEmpty()) results_ = std::move(post);
        } catch (const QgsProcessingException& failure) {
            error_ = failure.what();
            ok_ = false;
        }
    } else if (algorithm_ != nullptr) {
        try {
            algorithm_->postProcess(*context_, feedback_.get(), /*runResult=*/false);
        } catch (const QgsProcessingException&) {
            // cleanup path best-effort
        }
    }
    emit executed(ok_, results_);
    if (on_done_) on_done_(ok_, results_);
}

}  // namespace pwb::qgis_processing
