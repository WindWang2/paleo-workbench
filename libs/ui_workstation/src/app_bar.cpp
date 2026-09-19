#include "pwb/ui_workstation/app_bar.hpp"

#include <QActionGroup>
#include <QHBoxLayout>
#include <QLabel>
#include <QSizePolicy>

#include <pwb/ui_shell/dock_registry.hpp>
#include <pwb/ui_shell/layout_presets.hpp>
#include <pwb/ui_widgets/icon_factory.hpp>

namespace pwb::ui_workstation {

WorkstationAppBar::WorkstationAppBar(QWidget* parent) : QFrame(parent) {
    setObjectName("WorkstationAppBar");
    setFixedHeight(46);  // comfortable density default; host may rebind

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(8, 0, 8, 0);
    layout->setSpacing(8);

    auto* brand_icon = new QLabel(this);
    brand_icon->setObjectName("WorkstationBrandIcon");
    brand_icon->setPixmap(
        ui_widgets::workstation_icon("seismic.svg").pixmap(20, 20));
    layout->addWidget(brand_icon);

    auto* brand_label = new QLabel("Paleo Workbench", this);
    brand_label->setObjectName("WorkstationBrand");
    layout->addWidget(brand_label);

    project_button_ = new QToolButton(this);
    project_button_->setObjectName("WorkstationProjectButton");
    project_button_->setToolButtonStyle(
        Qt::ToolButtonStyle::ToolButtonTextBesideIcon);
    project_button_->setPopupMode(
        QToolButton::ToolButtonPopupMode::InstantPopup);
    project_button_->setIcon(
        ui_widgets::workstation_icon("folder-open.svg"));
    auto* project_menu = new QMenu(project_button_);
    project_menu->addAction("新建工程", this,
                            [this] { emit new_project_requested(); });
    project_menu->addAction("打开工程", this,
                            [this] { emit open_project_requested(); });
    project_menu->addAction("打开示例", this,
                            [this] { emit open_sample_requested(); });
    project_menu->addSeparator();
    project_menu->addAction("保存工程", this,
                            [this] { emit save_project_requested(); });
    project_menu->addAction("工程属性", this,
                            [this] { emit properties_requested(); });
    project_button_->setMenu(project_menu);
    layout->addWidget(project_button_);

    // 工作区预设（B2）：「自定义」+ 注册表预设，选中有 id 的项才发射。
    workspace_combo_ = new QComboBox(this);
    workspace_combo_->setObjectName("WorkstationWorkspaceCombo");
    workspace_combo_->setToolTip("切换工作区布局预设");
    set_workspace_presets(ui_shell::preset_labels());
    connect(workspace_combo_, &QComboBox::currentIndexChanged, this,
            [this](int index) {
                if (index < 0 ||
                    index >= static_cast<int>(workspace_ids_.size())) {
                    return;
                }
                const std::string& id = workspace_ids_[index];
                if (!id.empty()) {
                    emit workspace_preset_requested(
                        QString::fromStdString(id));
                }
            });
    layout->addWidget(workspace_combo_);

    layout->addStretch(1);

    command_input_ = new QLineEdit(this);
    command_input_->setObjectName("WorkstationCommandInput");
    command_input_->setPlaceholderText(
        "搜索命令、数据或输入 Agent 指令 (Ctrl+K)");
    command_input_->setClearButtonEnabled(true);
    command_input_->setMinimumWidth(180);
    command_input_->setMaximumWidth(580);
    command_input_->setSizePolicy(QSizePolicy::Policy::Expanding,
                                  QSizePolicy::Policy::Fixed);
    connect(command_input_, &QLineEdit::returnPressed, this,
            &WorkstationAppBar::submit_command);
    layout->addWidget(command_input_, 2);

    layout->addStretch(1);

    // 视图菜单（B1/B16）：主题与密度的生产入口。
    auto* view_button = new QToolButton(this);
    view_button->setObjectName("WorkstationChromeButton");
    view_button->setIcon(
        ui_widgets::workstation_icon("rb-density-comfortable.svg"));
    view_button->setText("视图");
    view_button->setToolButtonStyle(
        Qt::ToolButtonStyle::ToolButtonTextBesideIcon);
    view_button->setPopupMode(
        QToolButton::ToolButtonPopupMode::InstantPopup);
    view_button->setToolTip("主题与界面密度");
    view_menu_ = new QMenu(view_button);
    view_button->setMenu(view_menu_);
    layout->addWidget(view_button);
    // Default rows (host may rebind via set_*_choices); separators act
    // as insertion anchors so rebinds keep the menu order.
    set_theme_choices({{"light", "浅色主题"},
                       {"dark", "深色主题"},
                       {"high_contrast", "高对比主题"}},
                      "light");
    theme_separator_ = view_menu_->addSeparator();
    set_density_choices(
        {{"compact", "紧凑密度"}, {"comfortable", "舒适密度"}},
        "comfortable");
    about_separator_ = view_menu_->addSeparator();
    view_menu_->addAction("关于", this,
                          [this] { emit about_requested(); });

    task_button_ = new QToolButton(this);
    task_button_->setObjectName("WorkstationTaskButton");
    task_button_->setIcon(ui_widgets::workstation_icon("rb-run.svg"));
    task_button_->setToolButtonStyle(
        Qt::ToolButtonStyle::ToolButtonTextBesideIcon);
    task_button_->setToolTip("打开任务中心");
    connect(task_button_, &QToolButton::clicked, this,
            [this] { emit task_center_requested(); });
    layout->addWidget(task_button_);
    set_task_count(0);

    agent_button_ = new QToolButton(this);
    agent_button_->setObjectName("WorkstationAgentButton");
    agent_button_->setIcon(
        ui_widgets::workstation_icon("visualization.svg"));
    agent_button_->setText("Agent");
    agent_button_->setToolButtonStyle(
        Qt::ToolButtonStyle::ToolButtonTextBesideIcon);
    agent_button_->setToolTip("打开上下文感知 Agent 工作区");
    connect(agent_button_, &QToolButton::clicked, this,
            [this] { emit agent_requested(); });
    layout->addWidget(agent_button_);

    set_project("未命名工程", "");
}

void WorkstationAppBar::set_workspace_presets(
    std::vector<std::pair<std::string, std::string>> presets) {
    workspace_combo_->blockSignals(true);
    workspace_combo_->clear();
    workspace_ids_.clear();
    workspace_ids_.push_back("");
    workspace_combo_->addItem("自定义");
    for (const auto& [id, label] : presets) {
        workspace_ids_.push_back(id);
        workspace_combo_->addItem(QString::fromStdString(label));
    }
    workspace_combo_->blockSignals(false);
}

void WorkstationAppBar::set_current_workspace(
    const std::string& preset_id) {
    int index = 0;
    for (std::size_t i = 0; i < workspace_ids_.size(); ++i) {
        if (workspace_ids_[i] == preset_id) {
            index = static_cast<int>(i);
            break;
        }
    }
    workspace_combo_->blockSignals(true);
    workspace_combo_->setCurrentIndex(index);
    workspace_combo_->blockSignals(false);
}

void WorkstationAppBar::set_project(const QString& name,
                                    const QString& region) {
    const QString project = name.isEmpty() ? "未命名工程" : name;
    QString area = region.trimmed();
    if (area.compare(project, Qt::CaseInsensitive) == 0) {
        area.clear();
    }
    project_region_ = area;
    project_button_->setText(
        area.isEmpty() ? project : project + "  /  " + area);
    project_button_->setToolTip("切换工程或打开工程操作");
}

void WorkstationAppBar::set_project_name(const QString& name) {
    set_project(name, project_region_);
}

void WorkstationAppBar::set_task_count(int active) {
    const int count = std::max(0, active);
    task_button_->setText(QString("任务 %1").arg(count));
    task_button_->setProperty("activeTasks", count > 0);
    task_button_->style()->unpolish(task_button_);
    task_button_->style()->polish(task_button_);
}

void WorkstationAppBar::set_command_input_floor(int floor_px) {
    command_input_->setMinimumWidth(floor_px);
}

void WorkstationAppBar::set_theme_choices(
    const std::vector<std::pair<std::string, std::string>>& choices,
    const std::string& current) {
    // Rebuild the theme block at the top of the view menu.
    for (auto& [action, _] : theme_actions_) {
        view_menu_->removeAction(action);
        action->deleteLater();
    }
    theme_actions_.clear();
    for (const auto& [value, label] : choices) {
        QAction* action = new QAction(QString::fromStdString(label),
                                      view_menu_);
        connect(action, &QAction::triggered, this, [this, value] {
            emit theme_requested(QString::fromStdString(value));
        });
        action->setCheckable(true);
        action->setChecked(value == current);
        // Theme block opens the menu; on the first call the separator
        // doesn't exist yet — appending is equivalent then.
        if (theme_separator_ != nullptr) {
            view_menu_->insertAction(theme_separator_, action);
        } else {
            view_menu_->addAction(action);
        }
        theme_actions_.emplace_back(action, value);
    }
}

void WorkstationAppBar::set_density_choices(
    const std::vector<std::pair<std::string, std::string>>& choices,
    const std::string& current) {
    for (auto& [action, _] : density_actions_) {
        view_menu_->removeAction(action);
        action->deleteLater();
    }
    density_actions_.clear();
    for (const auto& [value, label] : choices) {
        QAction* action = new QAction(QString::fromStdString(label),
                                      view_menu_);
        connect(action, &QAction::triggered, this, [this, value] {
            emit density_requested(QString::fromStdString(value));
        });
        action->setCheckable(true);
        action->setChecked(value == current);
        // Density block sits between the two separators; on the first
        // construction call the about separator doesn't exist yet —
        // appending puts the action in the same slot.
        if (about_separator_ != nullptr) {
            view_menu_->insertAction(about_separator_, action);
        } else {
            view_menu_->addAction(action);
        }
        density_actions_.emplace_back(action, value);
    }
}

void WorkstationAppBar::sync_view_checks(
    const std::string& current_theme, const std::string& current_density) {
    for (auto& [action, value] : theme_actions_) {
        action->setChecked(value == current_theme);
    }
    for (auto& [action, value] : density_actions_) {
        action->setChecked(value == current_density);
    }
}

void WorkstationAppBar::focus_command() {
    command_input_->setFocus(Qt::FocusReason::ShortcutFocusReason);
    command_input_->selectAll();
}

void WorkstationAppBar::submit_command() {
    const QString text = command_input_->text().trimmed();
    if (text.isEmpty()) return;
    command_input_->clear();
    emit command_submitted(text);
}

}  // namespace pwb::ui_workstation
