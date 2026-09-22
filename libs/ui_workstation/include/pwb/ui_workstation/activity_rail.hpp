#pragma once

// Port of paleo_workbench/ui/workstation/activity_rail.py (UI-12).
// Stable object/workspace modes — the rail is the explorer's VIEW
// switcher, not page navigation (V11 01-ui-audit B1 tooltips say so).

#include <map>
#include <string>

#include <QButtonGroup>
#include <QFrame>
#include <QToolButton>

namespace pwb::ui_workstation {

class ActivityRail : public QFrame {
    Q_OBJECT
public:
    explicit ActivityRail(QWidget* parent = nullptr);

    // (key, label, icon_name) — Python _MODES order.
    static const std::vector<
        std::tuple<std::string, std::string, std::string>>&
    modes();
    // Python _MODE_TOOLTIPS.
    static const std::map<std::string, std::string>& mode_tooltips();

    void set_mode(const std::string& key);
    // Mirror the explorer collapsed state (left/right chevron +
    // tooltip + accessible name flip).
    void set_explorer_expanded(bool expanded);

    // Density hook (Python _rail_button_size / rail_width equivalents
    // are injected — the C++ token table lives outside this slice).
    void apply_metrics(int rail_width_px, int button_size_px);

    // 细图标轨（qt_ribbon_native prototype parity）: icon-only 34px
    // buttons, text moves to the tooltip. Default stays text-under-icon.
    void set_icon_only(bool icon_only);

signals:
    void mode_requested(const QString& mode);
    void settings_requested();
    void collapse_requested();

private:
    QButtonGroup* group_ = nullptr;
    std::map<std::string, QToolButton*> buttons_;
    QToolButton* settings_button_ = nullptr;
    QToolButton* collapse_button_ = nullptr;
};

}  // namespace pwb::ui_workstation
