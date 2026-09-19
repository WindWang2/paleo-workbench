// UI-08 — paleo_workbench/ui/pages/factor_preview_grid.py port: the center
// panel grid of completed factor map preview cards.
//
// Task objects are domain::Json attribute bags (the Python duck-typed
// getattr reads: status/factor_type/name/quality_metrics/target_horizon/
// method/output_resource_ids/id).
#pragma once

#include "pwb/domain/json.hpp"

#include <QFrame>
#include <QMetaType>
#include <QMouseEvent>
#include <QWidget>

#include <vector>

class QGridLayout;
class QLabel;
class QScrollArea;
class QVBoxLayout;

namespace pwb::ui_pages_mapedit {

class FactorPreviewCard : public QFrame {
    Q_OBJECT
public:
    explicit FactorPreviewCard(const domain::Json& task,
                               QWidget* parent = nullptr);

    domain::Json task;
    // Python public attributes.
    QLabel* name_label = nullptr;
    QLabel* range_label = nullptr;
    QLabel* rsquared_label = nullptr;
    QLabel* dup_label = nullptr;

signals:
    void clicked(const domain::Json& task);

protected:
    void mouseReleaseEvent(QMouseEvent* event) override;
};

class FactorPreviewGrid : public QWidget {
    Q_OBJECT
public:
    explicit FactorPreviewGrid(QWidget* parent = nullptr);

    // update_state(tasks): keep the ``status == "complete"`` cards.
    void update_state(const std::vector<domain::Json>& tasks);

    QScrollArea* scroll_area() const { return scroll_; }
    QLabel* header_label() const { return header_label_; }
    QGridLayout* grid_layout() const { return grid_layout_; }

signals:
    void card_clicked(const domain::Json& task);

private:
    void clear_grid();

    QLabel* header_label_ = nullptr;
    QScrollArea* scroll_ = nullptr;
    QWidget* grid_container_ = nullptr;
    QGridLayout* grid_layout_ = nullptr;
    QLabel* empty_label_ = nullptr;
};

}  // namespace pwb::ui_pages_mapedit

Q_DECLARE_METATYPE(pwb::domain::Json)
