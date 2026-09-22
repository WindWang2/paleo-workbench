#include "pwb/ui_workstation/activity_rail.hpp"

#include <QSize>
#include <QVBoxLayout>

#include <pwb/ui_widgets/icon_factory.hpp>

namespace pwb::ui_workstation {

const std::vector<std::tuple<std::string, std::string, std::string>>&
ActivityRail::modes() {
    static const std::vector<
        std::tuple<std::string, std::string, std::string>>
        modes = {
            {"project", "项目", "home.svg"},
            {"data", "数据", "data.svg"},
            {"layers", "图层", "mapping.svg"},
            {"search", "搜索", "menu-search.svg"},
            {"history", "历史", "review.svg"},
            {"workspaces", "工作区", "visualization.svg"},
        };
    return modes;
}

const std::map<std::string, std::string>& ActivityRail::mode_tooltips() {
    static const std::map<std::string, std::string> tooltips = {
        {"project", "资源管理器 · 项目总览（井/工区/工程实体）"},
        {"data", "资源管理器 · 数据资源（按类型浏览数据资产）"},
        {"layers", "资源管理器 · 图层（编图文档与图层）"},
        {"search", "资源管理器 · 搜索（全工程资源检索）"},
        {"history", "资源管理器 · 历史（最近使用的资源）"},
        {"workspaces", "聚焦编图工作区（中央画布）"},
    };
    return tooltips;
}

ActivityRail::ActivityRail(QWidget* parent) : QFrame(parent) {
    setObjectName("WorkstationActivityRail");
    setFixedWidth(56);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(2, 4, 2, 4);
    layout->setSpacing(1);

    group_ = new QButtonGroup(this);
    group_->setExclusive(true);
    int index = 0;
    for (const auto& [key, label, icon_name] : modes()) {
        auto* button = new QToolButton(this);
        button->setObjectName("WorkstationActivityButton");
        button->setProperty("activityKey",
                            QString::fromStdString(key));
        button->setCheckable(true);
        button->setText(QString::fromStdString(label));
        button->setIcon(ui_widgets::workstation_icon(
            QString::fromStdString(icon_name)));
        button->setIconSize(QSize(18, 18));
        button->setToolButtonStyle(
            Qt::ToolButtonStyle::ToolButtonTextUnderIcon);
        const auto tip_it = mode_tooltips().find(key);
        const QString tip =
            tip_it != mode_tooltips().end()
                ? QString::fromStdString(tip_it->second)
                : QString::fromStdString(label);
        button->setToolTip(tip);
        button->setAccessibleName(tip);
        button->setFixedSize(QSize(52, 56));
        connect(button, &QToolButton::clicked, this,
                [this, key](bool /*checked*/) {
                    emit mode_requested(QString::fromStdString(key));
                });
        group_->addButton(button, index++);
        buttons_[key] = button;
        layout->addWidget(button);
    }

    layout->addStretch(1);

    settings_button_ = new QToolButton(this);
    settings_button_->setObjectName("WorkstationActivityButton");
    settings_button_->setText("设置");
    settings_button_->setIcon(
        ui_widgets::workstation_icon("menu-preview-settings.svg"));
    settings_button_->setIconSize(QSize(18, 18));
    settings_button_->setToolButtonStyle(
        Qt::ToolButtonStyle::ToolButtonTextUnderIcon);
    settings_button_->setToolTip("工作站设置");
    settings_button_->setFixedSize(QSize(52, 56));
    connect(settings_button_, &QToolButton::clicked, this,
            [this] { emit settings_requested(); });
    layout->addWidget(settings_button_);

    collapse_button_ = new QToolButton(this);
    collapse_button_->setObjectName("WorkstationRailCollapseButton");
    collapse_button_->setAccessibleDescription(
        "折叠或展开左侧资源管理器面板");
    connect(collapse_button_, &QToolButton::clicked, this,
            [this] { emit collapse_requested(); });
    layout->addWidget(collapse_button_);

    set_explorer_expanded(true);
    set_mode("project");
}

void ActivityRail::set_mode(const std::string& key) {
    const auto it = buttons_.find(key);
    if (it != buttons_.end()) it->second->setChecked(true);
}

void ActivityRail::set_explorer_expanded(bool expanded) {
    if (expanded) {
        collapse_button_->setIcon(
            ui_widgets::workstation_icon("chevrons-left.svg"));
        collapse_button_->setToolTip("折叠资源管理器");
        collapse_button_->setAccessibleName("折叠资源管理器");
    } else {
        collapse_button_->setIcon(
            ui_widgets::workstation_icon("chevrons-right.svg"));
        collapse_button_->setToolTip("展开资源管理器");
        collapse_button_->setAccessibleName("展开资源管理器");
    }
}

void ActivityRail::apply_metrics(int rail_width_px,
                                 int button_size_px) {
    setFixedWidth(rail_width_px);
    const QSize size(button_size_px, button_size_px + 4);
    for (auto& [_, button] : buttons_) button->setFixedSize(size);
    if (settings_button_ != nullptr) settings_button_->setFixedSize(size);
}

void ActivityRail::set_icon_only(bool icon_only) {
    const auto style = icon_only ? Qt::ToolButtonStyle::ToolButtonIconOnly
                                 : Qt::ToolButtonStyle::
                                       ToolButtonTextUnderIcon;
    const QSize size = icon_only ? QSize(30, 30) : QSize(52, 56);
    setFixedWidth(icon_only ? 34 : 56);
    for (auto& [_, button] : buttons_) {
        button->setToolButtonStyle(style);
        button->setFixedSize(size);
    }
    if (settings_button_ != nullptr) {
        settings_button_->setToolButtonStyle(style);
        settings_button_->setFixedSize(size);
    }
}

}  // namespace pwb::ui_workstation
