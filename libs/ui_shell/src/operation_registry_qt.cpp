#include "pwb/ui_shell/operation_registry_qt.hpp"

namespace pwb::ui_shell {

OperationRegistryQt::OperationRegistryQt(QObject* parent)
    : QObject(parent) {
    registry_.on_changed = [this](const std::string& op_id) {
        emit changed(QString::fromStdString(op_id));
    };
    registry_.on_removed = [this](const std::string& op_id) {
        emit removed(QString::fromStdString(op_id));
    };
}

OperationRegistryQt* OperationRegistryQt::bind_to_shell(QObject* shell) {
    // Parented to the shell: records and jump callbacks die with it and
    // never leak into the next project.
    return new OperationRegistryQt(shell);
}

}  // namespace pwb::ui_shell
