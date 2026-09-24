#include <pwb/ui_controllers/qt/project_controller.hpp>

#include <QFileDialog>
#include <QMessageBox>
#include <QCoreApplication>
#include <QTimer>
#include <QWidget>

#include <pwb/ui_controllers/qt/job_owner_runner.hpp>

namespace pwb::ui_controllers::qt {

namespace {

constexpr const char* kProjectFilter = "Paleo 工程 (*.paleo.json)";

}  // namespace

// QTimer(0) parity — marshal onto the GUI thread's next event turn.
// R2-18/R6-1: the receiver matters twice over. A contextless singleShot
// is NEVER dropped when its target dies (UAF), and a lazily-created
// sentinel QObject binds to whichever thread FIRST calls this — the
// workflow progress hop calls from a scheduler worker, which would give
// the sentinel worker-thread affinity and silently kill every post
// (timers need an event loop). QCoreApplication::instance() is created
// on the main thread before any worker can post and lives until after
// every controller is gone — the correct owner for app-lifetime posts.
void post_next_turn(std::function<void()> fn) {
    auto* app = QCoreApplication::instance();
    if (app == nullptr) {
        return;  // no application: nowhere to marshal to; drop the post
    }
    QTimer::singleShot(0, app, [fn = std::move(fn)]() mutable { fn(); });
}

ProjectController::ProjectController(QObject* parent) : QObject(parent) {
    save_runner_ = std::make_unique<JobOwnerRunner>(this);
    host_.post_next_turn = post_next_turn;
}

ProjectController::~ProjectController() = default;

ProjectControllerCore& ProjectController::core() {
    if (core_ == nullptr) {
        core_ = std::make_unique<ProjectControllerCore>(
            host_, catalog_, services_, save_factory_, save_runner_.get());
    }
    return *core_;
}

void ProjectController::bind_dialogs(QWidget* parent) {
    host_.show_error = [parent](const std::string& title,
                                const std::string& message) {
        QMessageBox::warning(parent, QString::fromStdString(title),
                             QString::fromStdString(message));
    };
    host_.confirm = [parent](const std::string& title,
                             const std::string& message) {
        return QMessageBox::question(
                   parent, QString::fromStdString(title),
                   QString::fromStdString(message),
                   QMessageBox::StandardButton::Yes |
                       QMessageBox::StandardButton::No,
                   QMessageBox::StandardButton::No) ==
               QMessageBox::StandardButton::Yes;
    };
    host_.choose_open_project = [parent]() -> std::optional<fs::path> {
        const QString chosen = QFileDialog::getOpenFileName(
            parent, QStringLiteral("打开工程"), QString(),
            QString::fromLatin1(kProjectFilter));
        return chosen.isEmpty()
                   ? std::nullopt
                   : std::optional<fs::path>(chosen.toStdString());
    };
    host_.choose_save_project = [parent]() -> std::optional<fs::path> {
        const QString chosen = QFileDialog::getSaveFileName(
            parent, QStringLiteral("保存工程"), QString(),
            QString::fromLatin1(kProjectFilter));
        return chosen.isEmpty()
                   ? std::nullopt
                   : std::optional<fs::path>(chosen.toStdString());
    };
}

}  // namespace pwb::ui_controllers::qt
