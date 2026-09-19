#include <pwb/ui_composite/mapping_stage_panel.hpp>

#include <pwb/ui_composite/roles.hpp>
#include <pwb/ui_composite/stage_vocabulary.hpp>
#include <pwb/ui_widgets/ui_context.hpp>
#include <pwb/ui_workstation/state_language.hpp>

#include <QGridLayout>
#include <QHBoxLayout>
#include <QListWidgetItem>
#include <QPushButton>
#include <QSizePolicy>
#include <QVBoxLayout>

namespace pwb::ui_composite {

namespace {

using pwb::tool_policy::MappingStage;
using pwb::ui::ReadinessItemStatus;
using pwb::ui_workstation::state_token;

QString status_glyph(ReadinessItemStatus status) {
    switch (status) {
        case ReadinessItemStatus::Ok:
            return QString::fromUtf8(state_token("readiness", "ok").glyph);
        case ReadinessItemStatus::Warning:
            return QString::fromUtf8(
                state_token("readiness", "warning").glyph);
        case ReadinessItemStatus::Error:
            return QString::fromUtf8(state_token("readiness", "error").glyph);
        case ReadinessItemStatus::Info:
            return QString::fromUtf8(state_token("readiness", "info").glyph);
    }
    return QStringLiteral("·");
}

// 侧栏清单不得用长文本撑开 dock 最小宽度。
void narrow_list(QListWidget* widget) {
    widget->setMinimumWidth(0);
    widget->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    widget->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    widget->setWordWrap(true);
    widget->setTextElideMode(Qt::ElideRight);
    widget->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    widget->setAlternatingRowColors(false);
}

QPushButton* fill_button(const QString& title, QWidget* parent,
                         const QString& tooltip = QString()) {
    auto* button = new QPushButton(title, parent);
    button->setObjectName("WorkstationContextButton");
    button->setToolTip(tooltip.isEmpty() ? title : tooltip);
    button->setMinimumWidth(0);
    button->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Fixed);
    button->setCursor(Qt::PointingHandCursor);
    return button;
}

// (constraint_kind value, 中文标题) — ConstraintKind 枚举序 parity。
const std::vector<std::pair<std::string, QString>>& constraint_actions() {
    static const std::vector<std::pair<std::string, QString>> actions = {
        {std::string(constraint_kind::kProvenanceLine),
         QStringLiteral("物源线")},
        {std::string(constraint_kind::kSourceDirection),
         QStringLiteral("物源方向")},
        {std::string(constraint_kind::kDistributionLine),
         QStringLiteral("展布线")},
        {std::string(constraint_kind::kPaleoShoreline),
         QStringLiteral("古岸线")},
        {std::string(constraint_kind::kFaciesBoundary),
         QStringLiteral("相带边界")},
        {std::string(constraint_kind::kFault), QStringLiteral("断层")},
        {std::string(constraint_kind::kMask), QStringLiteral("掩膜")},
    };
    return actions;
}

}  // namespace

// ---------------------------------------------------------------------------
// StageReadinessList
// ---------------------------------------------------------------------------

StageReadinessList::StageReadinessList(QWidget* parent)
    : QListWidget(parent) {
    setObjectName("StageReadinessList");
    narrow_list(this);
    setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    connect(this, &QListWidget::itemClicked, this,
            [this](QListWidgetItem* item) {
                const QString target =
                    item->data(Qt::UserRole).toString();
                if (!target.isEmpty()) emit item_located(target);
            });
}

QSize StageReadinessList::minimumSizeHint() const {
    const QSize hint = QListWidget::minimumSizeHint();
    return {0, hint.height()};
}

void StageReadinessList::show_readiness(
    const pwb::ui::StageReadiness* readiness) {
    clear();
    if (readiness == nullptr) return;
    for (const pwb::ui::ReadinessItem& item : readiness->sorted_items()) {
        QString label = QStringLiteral("%1  %2")
                            .arg(status_glyph(item.status),
                                 QString::fromStdString(item.title));
        if (!item.detail.empty()) {
            label += QStringLiteral(" — %1")
                         .arg(QString::fromStdString(item.detail));
        }
        auto* row = new QListWidgetItem(label, this);
        row->setData(Qt::UserRole, QString::fromStdString(item.target));
        row->setToolTip(QString::fromStdString(
            item.detail.empty() ? item.title : item.detail));
    }
}

// ---------------------------------------------------------------------------
// StageCommandList
// ---------------------------------------------------------------------------

StageCommandList::StageCommandList(
    const std::vector<std::pair<std::string, std::string>>& commands,
    QWidget* parent)
    : QListWidget(parent) {
    setObjectName("StageCommandList");
    narrow_list(this);
    setCursor(Qt::PointingHandCursor);
    connect(this, &QListWidget::itemClicked, this,
            [this](QListWidgetItem* item) {
                // V11：禁用行点击是 no-op（ItemIsEnabled 移除已挡 UI
                // 路径，此处再护程序化触发）。
                if (!(item->flags() & Qt::ItemIsEnabled)) return;
                const QString id = item->data(Qt::UserRole).toString();
                if (!id.isEmpty()) emit action_requested(id);
            });
    for (const auto& [action_id, title] : commands) {
        auto* row =
            new QListWidgetItem(QString::fromStdString(title), this);
        row->setData(Qt::UserRole, QString::fromStdString(action_id));
        row->setToolTip(QString::fromStdString(title));
    }
}

void StageCommandList::set_action_availability(
    const ActionAvailability& availability) {
    const QString token = pwb::ui_widgets::palette_token("TEXT_DISABLED");
    const QColor disabled_color =
        token.isEmpty()
            ? palette().color(QPalette::Disabled, QPalette::Text)
            : QColor(token);
    for (int row = 0; row < count(); ++row) {
        QListWidgetItem* item = this->item(row);
        const std::string action_id =
            item->data(Qt::UserRole).toString().toStdString();
        auto it = availability.find(action_id);
        const bool enabled =
            it == availability.end() ? true : it->second.first;
        const std::string reason =
            it == availability.end() ? "" : it->second.second;
        if (enabled) {
            item->setFlags(item->flags() | Qt::ItemIsEnabled);
            item->setData(Qt::ForegroundRole, QVariant());
            item->setToolTip(item->text());
        } else {
            item->setFlags(item->flags() & ~Qt::ItemIsEnabled);
            item->setData(Qt::ForegroundRole, disabled_color);
            item->setToolTip(
                reason.empty()
                    ? QStringLiteral("不可用")
                    : QStringLiteral("不可用：%1")
                          .arg(QString::fromStdString(reason)));
        }
    }
}

QSize StageCommandList::sizeHint() const {
    const int rows = count();
    if (rows <= 0) return {0, 0};
    const int row_h = std::max(sizeHintForRow(0), 22);
    return {0, rows * row_h + 2 * frameWidth() + 4};
}

QSize StageCommandList::minimumSizeHint() const {
    const QSize hint = sizeHint();
    return {0, hint.height()};
}

// ---------------------------------------------------------------------------
// StagePage
// ---------------------------------------------------------------------------

StagePage::StagePage(
    MappingStage stage,
    const std::vector<std::pair<std::string, std::string>>& actions,
    QWidget* parent)
    : QFrame(parent), stage(stage) {
    setObjectName("PanelCard");
    setMinimumWidth(0);
    setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(6);

    auto* header = new QLabel(
        QString::fromUtf8(pwb::tool_policy::stage_label(stage)), this);
    header->setObjectName("WorkstationPanelHeader");
    header->setWordWrap(true);
    header->setMinimumWidth(0);
    header->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    layout->addWidget(header);

    auto* ready_row = new QHBoxLayout();
    ready_row->setContentsMargins(0, 0, 0, 0);
    auto* readiness_label = new QLabel(QStringLiteral("就绪度"), this);
    readiness_label->setObjectName("WorkstationPanelFootnote");
    readiness_status = new QLabel(QString(), this);
    readiness_status->setObjectName("WorkstationPanelFootnote");
    readiness_status->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
    ready_row->addWidget(readiness_label);
    ready_row->addStretch(1);
    ready_row->addWidget(readiness_status);
    layout->addLayout(ready_row);

    readiness = new StageReadinessList(this);
    connect(readiness, &StageReadinessList::item_located, this,
            &StagePage::locate_requested);
    layout->addWidget(readiness, 1);

    if (!actions.empty()) {
        auto* actions_label =
            new QLabel(QStringLiteral("阶段动作"), this);
        actions_label->setObjectName("WorkstationPanelFootnote");
        layout->addWidget(actions_label);
        this->actions = new StageCommandList(actions, this);
        connect(this->actions, &StageCommandList::action_requested, this,
                &StagePage::action_requested);
        layout->addWidget(this->actions, 0);
    }

    auto* footer = new QLabel(
        QString::fromUtf8(pwb::tool_policy::stage_description(stage)),
        this);
    footer->setObjectName("WorkstationPanelFootnote");
    footer->setWordWrap(true);
    footer->setMinimumWidth(0);
    footer->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    layout->addWidget(footer);
}

void StagePage::show_readiness(const pwb::ui::StageReadiness* r) {
    readiness->show_readiness(r);
    if (r != nullptr) {
        readiness_status->setText(QString::fromUtf8(r->label()));
    }
}

void StagePage::set_action_availability(
    const ActionAvailability& availability) {
    if (actions != nullptr) actions->set_action_availability(availability);
}

// ---------------------------------------------------------------------------
// MappingStagePanel
// ---------------------------------------------------------------------------

MappingStagePanel::MappingStagePanel(QWidget* parent) : QWidget(parent) {
    setObjectName("MappingStagePanel");
    setMinimumWidth(0);
    setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);

    stack = new QStackedWidget(this);
    stack->setMinimumWidth(0);
    stack->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    for (const MappingStage stage : pwb::tool_policy::kStageOrder) {
        const auto& actions = stage_context_actions(stage);
        auto* page = new StagePage(stage, actions, this);
        const QString stage_value = QString::fromUtf8(
            pwb::tool_policy::stage_value(stage));
        connect(page, &StagePage::action_requested, this,
                [this, stage_value](const QString& action) {
                    emit action_requested(stage_value, action);
                });
        connect(page, &StagePage::locate_requested, this,
                [this, stage_value](const QString& target) {
                    emit locate_requested(stage_value, target);
                });
        pages_[stage] = page;
        stack->addWidget(page);
    }
    layout->addWidget(stack, 1);

    build_constraints_row(layout);
    update_constraints_visibility(MappingStage::FaciesCalibration);
}

void MappingStagePanel::build_constraints_row(QVBoxLayout* layout) {
    auto* box = new QFrame(this);
    box->setObjectName("PanelCard");
    box->setMinimumWidth(0);
    auto* row = new QVBoxLayout(box);
    row->setContentsMargins(8, 6, 8, 6);
    auto* label = new QLabel(QStringLiteral("新建地质约束"), box);
    label->setObjectName("WorkstationPanelFootnote");
    row->addWidget(label);
    auto* buttons = new QGridLayout();
    buttons->setContentsMargins(0, 0, 0, 0);
    buttons->setSpacing(4);
    const auto& actions = constraint_actions();
    for (size_t index = 0; index < actions.size(); ++index) {
        const auto& [kind, title] = actions[index];
        const QString kind_q = QString::fromStdString(kind);
        const QString tooltip = QStringLiteral("新建 %1（%2）")
                                    .arg(QString::fromStdString(
                                             constraint_kind_label(kind)),
                                         QString::fromStdString(
                                             constraint_kind_geometry_kind(
                                                 kind)));
        QPushButton* button = fill_button(title, box, tooltip);
        connect(button, &QPushButton::clicked, this,
                [this, kind_q]() { emit constraint_requested(kind_q); });
        buttons->addWidget(button, static_cast<int>(index) / 2,
                           static_cast<int>(index) % 2);
    }
    row->addLayout(buttons);
    layout->addWidget(box);
    constraints_row_ = box;
}

void MappingStagePanel::update_constraints_visibility(MappingStage stage) {
    if (constraints_row_ != nullptr) {
        constraints_row_->setVisible(stage == MappingStage::ConstraintFactor);
    }
}

void MappingStagePanel::set_stage(const std::string& stage_value) {
    const auto stage = pwb::tool_policy::stage_from_value(stage_value);
    if (!stage.has_value()) return;
    auto it = pages_.find(*stage);
    if (it != pages_.end()) stack->setCurrentWidget(it->second);
    update_constraints_visibility(*stage);
}

void MappingStagePanel::set_action_availability(
    const ActionAvailability& availability,
    const std::string& stage_value) {
    QWidget* page = nullptr;
    if (!stage_value.empty()) {
        const auto stage = pwb::tool_policy::stage_from_value(stage_value);
        auto it = stage.has_value() ? pages_.find(*stage) : pages_.end();
        if (it != pages_.end()) page = it->second;
    }
    if (page == nullptr) page = stack->currentWidget();
    if (auto* stage_page = qobject_cast<StagePage*>(page)) {
        stage_page->set_action_availability(availability);
    }
}

void MappingStagePanel::show_readiness(
    MappingStage stage, const pwb::ui::StageReadiness* readiness) {
    auto it = pages_.find(stage);
    if (it != pages_.end()) it->second->show_readiness(readiness);
}

}  // namespace pwb::ui_composite
