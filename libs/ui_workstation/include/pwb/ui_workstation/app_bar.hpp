#pragma once

// Port of paleo_workbench/ui/workstation/app_bar.py (UI-12).
// Global-only actions + project context: brand, project menu, workspace
// preset combo, command input, view (theme/density) menu, task button,
// Agent button. Theme/density actions go through injected callbacks —
// the C++ ThemeService lives in platform_services, so this widget emits
// requests rather than owning the theme authority.

#include <functional>
#include <string>
#include <vector>

#include <QComboBox>
#include <QFrame>
#include <QLineEdit>
#include <QMenu>
#include <QToolButton>

namespace pwb::ui_workstation {

class WorkstationAppBar : public QFrame {
    Q_OBJECT
public:
    explicit WorkstationAppBar(QWidget* parent = nullptr);

    // (preset_id, label) pairs in menu order — Python list_presets()
    // parity; the combo always starts with 自定义 (id "").
    void set_workspace_presets(
        std::vector<std::pair<std::string, std::string>> presets);

    // 回写当前预设 without re-emitting (unknown/empty id → 自定义).
    void set_current_workspace(const std::string& preset_id);

    void set_project(const QString& name, const QString& region = "");
    void set_project_name(const QString& name);
    void set_task_count(int active);

    // Viewport policy: compact shrinks the command-input floor
    // (kCommandInputFloorCompact / kCommandInputFloorNormal).
    void set_command_input_floor(int floor_px);

    // View menu rows: (value, label) + current — emitted as
    // theme_requested(value) / density_requested(value); checkable and
    // resynced via sync_view_checks(current_theme, current_density).
    void set_theme_choices(
        const std::vector<std::pair<std::string, std::string>>& choices,
        const std::string& current);
    void set_density_choices(
        const std::vector<std::pair<std::string, std::string>>& choices,
        const std::string& current);
    void sync_view_checks(const std::string& current_theme,
                          const std::string& current_density);

    void focus_command();

    QLineEdit* command_input() const { return command_input_; }

signals:
    void new_project_requested();
    void open_project_requested();
    void open_sample_requested();
    void save_project_requested();
    void properties_requested();
    void command_submitted(const QString& text);
    void agent_requested();
    void task_center_requested();
    void workspace_preset_requested(const QString& preset_id);
    void about_requested();
    // View-menu requests (injected authority — not theme owners).
    void theme_requested(const QString& theme_value);
    void density_requested(const QString& density_value);

private:
    void submit_command();

    QToolButton* project_button_ = nullptr;
    QComboBox* workspace_combo_ = nullptr;
    QLineEdit* command_input_ = nullptr;
    QToolButton* task_button_ = nullptr;
    QToolButton* agent_button_ = nullptr;
    QMenu* view_menu_ = nullptr;
    QAction* theme_separator_ = nullptr;
    QAction* about_separator_ = nullptr;
    std::vector<std::string> workspace_ids_{""};
    QString project_region_;
    // View-menu action→value maps (no QActionGroup needed: the host
    // owns the current value, we just render check state).
    std::vector<std::pair<QAction*, std::string>> theme_actions_;
    std::vector<std::pair<QAction*, std::string>> density_actions_;
};

}  // namespace pwb::ui_workstation
