#pragma once

// Qt shell over CompositeEditController (UI-13): the core controller is
// Qt-free and exposes CompositeControllerEvents (single-callback
// std::function sinks); this QObject forwards each event to a real Qt
// signal so widgets can multi-subscribe — the Python controller being a
// QObject with Signals parity.
//
// Ownership: non-owning view of the core. The host keeps the core alive
// and installs these callbacks itself if it needs raw access (installing
// this object claims the single-callback slots; chain manually if both
// are needed).

#include <pwb/domain/json.hpp>

#include <QObject>
#include <QString>
#include <QVariantList>

namespace pwb::ui_composite {

class CompositeEditController;

class CompositeEditControllerObject : public QObject {
    Q_OBJECT
public:
    explicit CompositeEditControllerObject(
        CompositeEditController* core, QObject* parent = nullptr);

    CompositeEditController* core() const { return core_; }

signals:
    void layers_changed();
    void content_changed(const QString& layer_id);
    void sessions_committed();
    void native_join_refused(const QString& message);
    void geology_blocked(const QVariantList& violations);
    void feature_captured(const QString& layer_id,
                          const QString& feature_id);
    void state_changed();

private:
    CompositeEditController* core_;
};

}  // namespace pwb::ui_composite
