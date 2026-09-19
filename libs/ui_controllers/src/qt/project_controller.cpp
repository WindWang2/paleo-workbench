#include <pwb/ui_controllers/qt/project_controller.hpp>

#include <QFileDialog>
#include <QMessageBox>
#include <QTimer>
#include <QWidget>

#include <pwb/ui_controllers/qt/job_owner_runner.hpp>

namespace pwb::ui_controllers::qt {

namespace {

constexpr const char* kProjectFilter = "Paleo 工程 (*.paleo.json)";

// QTimer(0) parity — marshal onto the GUI thread's next event turn.
void post_next_turn(std::function<void()> fn) {
    QTimer::singleShot(0, [fn = std::move(fn)]() mutable { fn(); });
}

}  // namespace

ProjectController::ProjectController(job::JobScheduler& scheduler,
                                     QObject* parent)
    : QObject(parent), scheduler_(scheduler) {
    save_runner_ = std::make_unique<JobOwnerRunner>(scheduler_, this);
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
