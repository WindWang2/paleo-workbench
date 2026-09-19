#pragma once

// Qt signal shell over UIContextService (UI-12). Python parity:
// context_changed fires only on real snapshot change; late emissions
// during teardown are swallowed (a destroyed receiver is unreachable —
// Qt handles that; a destroyed SERVICE mid-refresh can't happen because
// refresh runs on the GUI thread only).

#include <QObject>

#include <pwb/ui_workstation/ui_context.hpp>

namespace pwb::ui_workstation {

class UIContextServiceQt : public QObject {
    Q_OBJECT
public:
    explicit UIContextServiceQt(QObject* parent = nullptr)
        : QObject(parent) {
        service_.set_change_listener(
            [this](const UIContextSnapshot& snap) {
                emit context_changed(snap);
            });
    }

    UIContextService& service() { return service_; }
    const UIContextService& service() const { return service_; }

    // Same contract as the core: register/replace a field adapter.
    void set_provider(const std::string& name,
                      UIContextService::Provider fn) {
        service_.set_provider(name, std::move(fn));
    }

    UIContextSnapshot snapshot() const { return service_.snapshot(); }
    UIContextSnapshot current() const { return service_.current(); }
    UIContextSnapshot refresh() { return service_.refresh(); }

signals:
    void context_changed(const pwb::ui_workstation::UIContextSnapshot&
                             snapshot);

private:
    UIContextService service_;
};

}  // namespace pwb::ui_workstation
