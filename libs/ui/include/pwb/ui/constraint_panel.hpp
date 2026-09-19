#pragma once

// CONV-27 — ConstraintPanel: read-side summary of the constraint-stage
// editing surface (物源/展布/岸线/相带边界/断层 lines + interpolation/
// mask boundaries). Lists the session's layers whose role is a constraint
// role (layer_roles.py vocabulary) with live feature counts from the QGIS
// authority; selecting a row activates that layer (the same domain id the
// layer tree activates). This panel never edits — it navigates.

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include <QDockWidget>
#include <QStringList>

#include <pwb/application/project_session.hpp>

class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui {

class ConstraintPanel : public QDockWidget {
    Q_OBJECT
public:
    // Domain facts lookup owned by the host (layer_id -> DomainLayerFacts);
    // the active layer's facts are the fallback when the host provides none.
    using FactsProvider =
        std::function<std::optional<pwb::application::DomainLayerFacts>(
            const std::string&)>;

    explicit ConstraintPanel(const FactsProvider& facts_provider = {},
                             QWidget* parent = nullptr);

    // Re-derives the constraint layer rows from the session (call after
    // layer add/remove/rename or edit state changes).
    void refresh(pwb::application::ProjectSession& session);

    // Test readback: "role_label|feature_count" rows in display order.
    QStringList constraint_rows() const;

signals:
    void activate_layer_requested(const QString& layer_id);

private:
    void on_row_activated(QTreeWidgetItem* item, int column);

    FactsProvider facts_provider_;
    QTreeWidget* tree_ = nullptr;
};

}  // namespace pwb::ui
