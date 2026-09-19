#include "pwb/ui_pages_mapedit/map_edit_toolbar.hpp"

#include "pwb/ui_shell/style_registry.hpp"

#include <QButtonGroup>
#include <QFrame>
#include <QHBoxLayout>
#include <QPushButton>

#include <algorithm>
#include <stdexcept>

namespace pwb::ui_pages_mapedit {
namespace {

// tokens.SPACE_*/CONTROL_HEIGHT_* are palette keys in the C++ theme table.
int tok_int(const char* key, int fallback) {
    const auto& p = ui_shell::style_palette();
    const auto it = p.find(key);
    if (it == p.end()) {
        return fallback;
    }
    bool ok = false;
    const int v = QString::fromStdString(it->second).toInt(&ok);
    return ok ? v : fallback;
}

// tokens.control_height(density): comfortable 30 / compact 26.
int control_height() {
    const auto& density = ui_shell::style_registry().current_density();
    return density == "compact" ? 26 : 30;
}

QPushButton* make_button(const QString& text, QWidget* parent,
                         bool checkable = false) {
    auto* btn = new QPushButton(text, parent);
    btn->setObjectName(QStringLiteral("SecondaryButton"));
    ui_shell::style_track_control_height(btn);
    if (checkable) {
        btn->setCheckable(true);
    }
    return btn;
}

}  // namespace

QString tool_label(const QString& tool_id) {
    static const std::map<QString, QString> labels = {
        {QStringLiteral("select"), QStringLiteral("选择")},
        {QStringLiteral("move"), QStringLiteral("移动")},
        {QStringLiteral("vertex"), QStringLiteral("节点")},
        {QStringLiteral("facies"), QStringLiteral("相带")},
        {QStringLiteral("line"), QStringLiteral("线")},
        {QStringLiteral("label"), QStringLiteral("注记")},
    };
    const auto it = labels.find(tool_id);
    return it != labels.end() ? it->second : QString();
}

MapEditToolbar::MapEditToolbar(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("MapEditToolbar"));

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(tok_int("SPACE_2", 8), tok_int("SPACE_1", 4),
                               tok_int("SPACE_2", 8), tok_int("SPACE_1", 4));
    layout->setSpacing(tok_int("SPACE_1", 4));

    tool_group_ = new QButtonGroup(this);
    tool_group_->setExclusive(true);

    for (const QString& tool_id : tool_ids()) {
        QPushButton* btn = make_button(tool_label(tool_id), this, true);
        btn->setProperty("tool_id", tool_id);
        tool_group_->addButton(btn);
        layout->addWidget(btn);
        tool_buttons_[tool_id] = btn;
        if (tool_id == QLatin1String("vertex") ||
            tool_id == QLatin1String("label")) {
            add_separator(layout);
        }
    }

    select_btn()->setChecked(true);
    connect(tool_group_, &QButtonGroup::buttonClicked, this,
            [this](QAbstractButton* b) { on_tool_clicked(b); });

    snap_btn = make_button(QStringLiteral("捕捉"), this, true);
    connect(snap_btn, &QPushButton::toggled, this,
            [this](bool on) { emit snap_toggled(on); });
    layout->addWidget(snap_btn);

    undo_btn = make_button(QStringLiteral("撤销"), this);
    connect(undo_btn, &QPushButton::clicked, this,
            [this]() { emit undo_requested(); });
    layout->addWidget(undo_btn);

    redo_btn = make_button(QStringLiteral("重做"), this);
    connect(redo_btn, &QPushButton::clicked, this,
            [this]() { emit redo_requested(); });
    layout->addWidget(redo_btn);
    add_separator(layout);

    preview_btn = make_button(QStringLiteral("图面预览"), this, true);
    preview_btn->setToolTip(QStringLiteral(
        "切换 PaleoMapCanvas 图面预览（含图例/指北针/比例尺）"));
    connect(preview_btn, &QPushButton::toggled, this,
            [this](bool on) { emit preview_toggled(on); });
    layout->addWidget(preview_btn);

    canvas_priority_btn = make_button(QStringLiteral("画布优先"), this, true);
    canvas_priority_btn->setToolTip(
        QStringLiteral("最大化编辑画布，折叠侧边面板"));
    connect(canvas_priority_btn, &QPushButton::toggled, this,
            [this](bool on) { emit canvas_priority_toggled(on); });
    layout->addWidget(canvas_priority_btn);
    add_separator(layout);

    topology_btn = make_button(QStringLiteral("重建拓扑"), this);
    topology_btn->setToolTip(
        QStringLiteral("共享节点捕捉 + 自交/邻接校验"));
    connect(topology_btn, &QPushButton::clicked, this,
            [this]() { emit topology_rebuild_requested(); });
    layout->addWidget(topology_btn);

    merge_btn = make_button(QStringLiteral("合并相带"), this);
    merge_btn->setToolTip(QStringLiteral("合并选中的两个相带多边形"));
    connect(merge_btn, &QPushButton::clicked, this,
            [this]() { emit merge_facies_requested(); });
    layout->addWidget(merge_btn);

    split_btn = make_button(QStringLiteral("分割相带"), this);
    split_btn->setToolTip(
        QStringLiteral("用选中的线分割选中的一个相带"));
    connect(split_btn, &QPushButton::clicked, this,
            [this]() { emit split_facies_requested(); });
    layout->addWidget(split_btn);
    add_separator(layout);

    layout->addStretch(1);

    generate_demo_draft_btn =
        make_button(QStringLiteral("生成演示草稿"), this);
    generate_demo_draft_btn->setToolTip(QStringLiteral(
        "从预测相带区域生成可编辑的演示级编图草稿"));
    connect(generate_demo_draft_btn, &QPushButton::clicked, this,
            [this]() { emit generate_demo_draft_requested(); });
    layout->addWidget(generate_demo_draft_btn);

    save_draft_btn = new QPushButton(QStringLiteral("保存编图草稿"), this);
    save_draft_btn->setObjectName(QStringLiteral("PrimaryButton"));
    save_draft_btn->setMinimumHeight(tok_int("CONTROL_HEIGHT_LG", 34));
    connect(save_draft_btn, &QPushButton::clicked, this,
            [this]() { emit save_draft_requested(); });
    layout->addWidget(save_draft_btn);
}

QFrame* MapEditToolbar::add_separator(QHBoxLayout* layout) {
    auto* sep = new QFrame(this);
    sep->setObjectName(QStringLiteral("ToolbarSeparator"));
    sep->setFixedWidth(1);
    sep->setMinimumHeight(std::max(1, control_height() - 4));
    layout->addWidget(sep);
    return sep;
}

QPushButton* MapEditToolbar::tool_button(const QString& tool_id) const {
    const auto it = tool_buttons_.find(tool_id);
    return it != tool_buttons_.end() ? it->second : nullptr;
}

void MapEditToolbar::set_preview_mode(bool enabled) {
    // Toggle the preview button + disable exclusive edit tools while
    // preview is on.
    preview_mode_ = enabled;
    if (preview_btn->isChecked() != enabled) {
        preview_btn->blockSignals(true);
        preview_btn->setChecked(enabled);
        preview_btn->blockSignals(false);
    }
    for (const auto& [id, btn] : tool_buttons_) {
        btn->setEnabled(!enabled);
    }
    snap_btn->setEnabled(!enabled);
    topology_btn->setEnabled(!enabled);
    merge_btn->setEnabled(!enabled);
    split_btn->setEnabled(!enabled);
}

void MapEditToolbar::set_tool(const QString& tool_id) {
    QPushButton* btn = tool_button(tool_id);
    if (btn == nullptr) {
        throw std::invalid_argument("Unknown tool: " + tool_id.toStdString());
    }
    if (!btn->isChecked()) {
        btn->setChecked(true);
    }
    apply_tool(tool_id);
}

void MapEditToolbar::on_tool_clicked(QAbstractButton* button) {
    apply_tool(button->property("tool_id").toString());
}

void MapEditToolbar::apply_tool(const QString& tool_id) {
    if (tool_id == current_tool_) {
        return;
    }
    current_tool_ = tool_id;
    emit tool_changed(tool_id);
}

}  // namespace pwb::ui_pages_mapedit
