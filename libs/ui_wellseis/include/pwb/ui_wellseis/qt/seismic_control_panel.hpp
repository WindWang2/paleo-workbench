#pragma once

// UI-09 — SeismicControlPanel Qt shell (seismic_control_panel.py).
// Right-hand analysis summary: status/shape/horizon/output-nature/
// attribute fields, display-mode combo, well-tie toggle, 发送编图 action.
// Controls enable exactly when a task is bound (seismic_controls_enabled).

#include <array>
#include <cstdint>
#include <optional>
#include <string>

#include <QFrame>
#include <QString>

#include <pwb/ui_wellseis/slices.hpp>

class QComboBox;
class QLabel;
class QPushButton;

namespace pwb::ui_wellseis::qt {

class SeismicControlPanel : public QFrame {
    Q_OBJECT
public:
    explicit SeismicControlPanel(QWidget* parent = nullptr);

    // update_state parity — task may be nullptr.
    void update_state(const PredictionTaskSlice* task,
                      std::optional<std::array<std::int64_t, 3>> volume_shape);
    void set_attribute_label(const QString& label);
    void set_controls_enabled(bool enabled);
    void set_display_mode(const QString& mode);   // suppressed
    void set_well_tie_checked(bool checked);      // suppressed
    [[nodiscard]] QString display_mode() const;

signals:
    void send_requested();
    void display_mode_changed(const QString& mode);
    void well_tie_toggled(bool checked);

private:
    QLabel* status_value_ = nullptr;
    QLabel* shape_value_ = nullptr;
    QLabel* horizon_value_ = nullptr;
    QLabel* mock_value_ = nullptr;
    QLabel* attribute_value_ = nullptr;
    QComboBox* mode_combo_ = nullptr;
    QPushButton* well_tie_btn_ = nullptr;
    QPushButton* send_btn_ = nullptr;
    bool suppress_ = false;
};

}  // namespace pwb::ui_wellseis::qt
