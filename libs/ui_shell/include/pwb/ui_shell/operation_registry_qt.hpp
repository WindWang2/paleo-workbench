#pragma once

// Qt bridge over the Qt-free OperationRegistry (UI-01): re-emits the
// injected on_changed/on_removed callbacks as QObject signals so widgets
// connect with typed slots. Mirrors Python operations.py where the
// registry emits Qt signals directly.

#include <QObject>

#include <pwb/ui_shell/operation_registry.hpp>

namespace pwb::ui_shell {

class OperationRegistryQt : public QObject {
    Q_OBJECT
public:
    explicit OperationRegistryQt(QObject* parent = nullptr);

    OperationRegistry& registry() { return registry_; }
    const OperationRegistry& registry() const { return registry_; }

    // Shell binding parity (Python bind_registry_to_shell): a fresh
    // registry whose records/jump callbacks never outlive the shell that
    // owns them.
    static OperationRegistryQt* bind_to_shell(QObject* shell);

signals:
    void changed(const QString& op_id);
    void removed(const QString& op_id);

private:
    OperationRegistry registry_;
};

}  // namespace pwb::ui_shell
