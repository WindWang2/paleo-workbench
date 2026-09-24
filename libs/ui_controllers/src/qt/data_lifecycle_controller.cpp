#include <pwb/ui_controllers/qt/data_lifecycle_controller.hpp>

#include <QDesktopServices>
#include <QFileDialog>
#include <QInputDialog>
#include <QUrl>
#include <QWidget>

#include <pwb/ui_controllers/qt/job_owner_runner.hpp>

namespace pwb::ui_controllers::qt {

DataLifecycleController::DataLifecycleController(
    ui_shell::OperationRegistry* operations, QObject* parent)
    : QObject(parent), operations_(operations) {
    catalog_job_ = std::make_unique<JobOwnerRunner>(this);
    verify_job_ = std::make_unique<JobOwnerRunner>(this);
}

DataLifecycleController::~DataLifecycleController() = default;

DataLifecycleCore& DataLifecycleController::core() {
    if (core_ == nullptr) {
        core_ = std::make_unique<DataLifecycleCore>(
            page_, catalog_, services_, dialogs_, catalog_job_.get(),
            verify_job_.get(), operations_);
    }
    return *core_;
}

void DataLifecycleController::bind_dialogs(QWidget* parent) {
    // TagInputDialog → QInputDialog::getText.
    dialogs_.tag_input =
        [parent](const std::string& title,
                 const std::string& label) -> std::optional<std::string> {
        bool ok = false;
        const QString text = QInputDialog::getText(
            parent, QString::fromStdString(title),
            QString::fromStdString(label), QLineEdit::Normal, QString(),
            &ok);
        if (!ok || text.isEmpty()) return std::nullopt;
        return text.toStdString();
    };
    // delivery path → QFileDialog::getSaveFileName.
    dialogs_.delivery =
        [parent](const std::string& asset_name,
                 const std::string& suggested)
        -> std::optional<std::filesystem::path> {
        const QString chosen = QFileDialog::getSaveFileName(
            parent, QStringLiteral("导出 / 交付"),
            QString::fromStdString(suggested));
        return chosen.isEmpty()
                   ? std::nullopt
                   : std::optional<std::filesystem::path>(
                         chosen.toStdString());
    };
    // QDesktopServices.openUrl(QUrl.fromLocalFile(path)).
    dialogs_.open_url = [](const std::filesystem::path& path) {
        QDesktopServices::openUrl(QUrl::fromLocalFile(
            QString::fromStdString(path.generic_string())));
    };
    // new_version / promote / confirm_trash_impact stay unset here — the
    // composite dialogs (ui_review widgets) bind in the integration slice.
}

}  // namespace pwb::ui_controllers::qt
