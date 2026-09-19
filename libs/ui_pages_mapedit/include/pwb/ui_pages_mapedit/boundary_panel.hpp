// UI-08 — paleo_workbench/ui/pages/boundary_panel.py port: the right-hand
// form panel for initial facies boundary configuration.
#pragma once

#include <QFrame>

#include <QStringList>

class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QPushButton;

namespace pwb::ui_pages_mapedit {

// tokens.SMOOTHING_LEVELS — ["弱", "中", "强"].
inline QStringList smoothing_levels() {
    return {QStringLiteral("弱"), QStringLiteral("中"),
            QStringLiteral("强")};
}

class BoundaryPanel : public QFrame {
    Q_OBJECT
public:
    explicit BoundaryPanel(QWidget* parent = nullptr);

    // Widget handles (Python attribute parity).
    QLabel* title_label = nullptr;
    QLabel* threshold_label = nullptr;
    QDoubleSpinBox* threshold_spin = nullptr;
    QLabel* smoothing_label = nullptr;
    QComboBox* smoothing_combo = nullptr;
    QLabel* area_label = nullptr;
    QDoubleSpinBox* area_spin = nullptr;
    QLabel* facies_label = nullptr;
    QPushButton* generate_btn = nullptr;
};

}  // namespace pwb::ui_pages_mapedit
