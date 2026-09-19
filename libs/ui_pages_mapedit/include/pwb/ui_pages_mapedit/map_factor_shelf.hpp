// UI-08 — paleo_workbench/ui/pages/map_factor_shelf.py port: the mapping
// bottom-tab shelf — factor cards + geological factor mapping actions.
#pragma once

#include "pwb/domain/json.hpp"

#include <QPointF>
#include <QVariantMap>
#include <QWidget>

#include <vector>

class QPushButton;

namespace pwb::ui_pages_mapedit {

class FactorPreviewGrid;

class MapFactorShelf : public QWidget {
    Q_OBJECT
public:
    explicit MapFactorShelf(QWidget* parent = nullptr);

    void update_state(const std::vector<domain::Json>& tasks);

    void set_view_state(const QVariantMap& state) { view_state_ = state; }
    QVariantMap view_state() const { return view_state_; }
    void set_cursor_position(const QPointF& xy) { cursor_position_ = xy; }
    QPointF cursor_position() const { return cursor_position_; }

    // Widget handles (Python attribute parity).
    QPushButton* create_factor_map_btn = nullptr;
    QPushButton* contour_draft_btn = nullptr;
    QPushButton* fault_interpretation_btn = nullptr;
    QPushButton* map_product_btn = nullptr;
    FactorPreviewGrid* grid = nullptr;

signals:
    void contour_draft_requested();
    void factor_overlay_requested(const QString& overlay_id);
    void create_factor_map_requested();
    void fault_interpretation_requested();
    void map_product_requested();

private:
    void on_card_clicked(const domain::Json& task);

    QVariantMap view_state_ = {
        {QStringLiteral("center"), QVariantList{0.0, 0.0}},
        {QStringLiteral("scale"), 1.0},
    };
    QPointF cursor_position_ = {0.0, 0.0};
};

}  // namespace pwb::ui_pages_mapedit
