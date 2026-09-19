#include <pwb/ui_composite/mapping_stage_bar.hpp>

#include <pwb/ui_widgets/ui_context.hpp>

#include <algorithm>

#include <QHBoxLayout>
#include <QKeyEvent>
#include <QMouseEvent>

namespace pwb::ui_composite {

namespace {

using pwb::tool_policy::MappingStage;

QString badge_tone(const QString& badge) {
    if (badge.contains('!')) return QStringLiteral("error");
    if (badge.contains('~')) return QStringLiteral("warn");
    if (badge.contains(QChar(0x2713))) return QStringLiteral("ok");  // ✓
    return QStringLiteral("info");
}

int stage_order(MappingStage stage) {
    for (size_t i = 0; i < pwb::tool_policy::kStageOrder.size(); ++i) {
        if (pwb::tool_policy::kStageOrder[i] == stage) {
            return static_cast<int>(i);
        }
    }
    return -1;
}

}  // namespace

StageSegment::StageSegment(MappingStage stage, QWidget* parent)
    : QFrame(parent), stage(stage) {
    setObjectName("MappingStageSegment");
    setCursor(Qt::PointingHandCursor);
    setFocusPolicy(Qt::TabFocus);
    setAttribute(Qt::WA_Hover, true);
    setToolTip(QString::fromUtf8(
        pwb::tool_policy::stage_description(stage)));
    setAccessibleName(QString::fromUtf8(
        pwb::tool_policy::stage_label(stage)));

    auto* row = new QHBoxLayout(this);
    row->setContentsMargins(4, 2, 6, 2);
    row->setSpacing(6);

    index_ = new QLabel(QString::number(stage_order(stage) + 1), this);
    index_->setObjectName("MappingStageIndex");
    index_->setAlignment(Qt::AlignCenter);
    index_->setFixedSize(18, 18);
    row->addWidget(index_, 0);

    name_ = new QLabel(
        QString::fromUtf8(pwb::tool_policy::stage_short_label(stage)),
        this);
    name_->setObjectName("MappingStageName");
    row->addWidget(name_, 0);

    badge_label_ = new QLabel(QString(), this);
    badge_label_->setObjectName("MappingStageBadge");
    badge_label_->hide();
    row->addWidget(badge_label_, 0);

    refresh();
}

QString StageSegment::text() const {
    QString out = name_->text();
    if (!badge_.isEmpty()) out += QStringLiteral("  ") + badge_;
    return out;
}

void StageSegment::set_active(bool active) {
    active_ = active;
    refresh();
}

void StageSegment::set_badge(const QString& badge) {
    badge_ = badge;
    refresh();
}

void StageSegment::mouseReleaseEvent(QMouseEvent* event) {
    if (event->button() == Qt::LeftButton) emit clicked();
    QFrame::mouseReleaseEvent(event);
}

void StageSegment::keyPressEvent(QKeyEvent* event) {
    if (event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter ||
        event->key() == Qt::Key_Space) {
        emit clicked();
        event->accept();
        return;
    }
    QFrame::keyPressEvent(event);
}

void StageSegment::refresh() {
    setProperty("active", active_);
    setProperty("stageIndex", stage_order(stage));
    if (!badge_.isEmpty()) {
        badge_label_->setText(badge_);
        badge_label_->setProperty("tone", badge_tone(badge_));
        badge_label_->show();
    } else {
        badge_label_->hide();
        badge_label_->setText(QString());
    }
    pwb::ui_widgets::repolish(this);
}

// ---------------------------------------------------------------------------

MappingStageBar::MappingStageBar(QWidget* parent) : QFrame(parent) {
    setObjectName("MappingStageBar");

    auto* row = new QHBoxLayout(this);
    row->setContentsMargins(8, 2, 8, 2);
    row->setSpacing(6);

    horizon_label = new QLabel(QStringLiteral("层位"), this);
    horizon_label->setObjectName("MappingStageMetaLabel");
    row->addWidget(horizon_label);
    horizon_combo = new QComboBox(this);
    horizon_combo->setObjectName("MappingHorizonCombo");
    horizon_combo->setEditable(false);
    horizon_combo->setInsertPolicy(QComboBox::NoInsert);
    horizon_combo->setMinimumWidth(130);
    horizon_combo->setMaximumWidth(130);
    horizon_combo->setPlaceholderText(QStringLiteral("选择层位"));
    horizon_combo->setAccessibleName(QStringLiteral("层位"));
    horizon_combo->setToolTip(QStringLiteral(
        "编图层位：从工程层序格架或导入的层位数据中选择（相图按层位进行）"));
    connect(horizon_combo, &QComboBox::currentIndexChanged, this,
            [this](int) { commit_horizon(); });
    row->addWidget(horizon_combo, 0);

    auto* divider = new QFrame(this);
    divider->setObjectName("MappingStageDivider");
    divider->setFixedSize(1, 18);
    row->addWidget(divider);

    const auto& order = pwb::tool_policy::kStageOrder;
    for (size_t index = 0; index < order.size(); ++index) {
        const MappingStage stage = order[index];
        auto* segment = new StageSegment(stage, this);
        connect(segment, &StageSegment::clicked, this,
                [this, stage]() {
                    emit stage_requested(QString::fromUtf8(
                        pwb::tool_policy::stage_value(stage)));
                });
        buttons_[stage] = segment;
        row->addWidget(segment, 0);
        if (index + 1 < order.size()) {
            auto* track = new QFrame(this);
            track->setObjectName("MappingStageTrack");
            track->setFixedSize(20, 2);
            row->addWidget(track, 0, Qt::AlignVCenter);
            tracks_.push_back(track);
        }
    }
    // 无尾 stretch：阶段条 sizeHint 必须等于内容宽（V7 同行契约）。
}

void MappingStageBar::set_current_stage(const std::string& stage_value) {
    const auto stage = pwb::tool_policy::stage_from_value(stage_value);
    for (auto& [button_stage, button] : buttons_) {
        button->set_active(stage.has_value() && button_stage == *stage);
    }
    const int current_order =
        stage.has_value() ? stage_order(*stage) : -1;
    for (size_t index = 0; index < tracks_.size(); ++index) {
        tracks_[index]->setProperty("complete",
                                    static_cast<int>(index) < current_order);
        pwb::ui_widgets::repolish(tracks_[index]);
    }
}

void MappingStageBar::set_stage_badge(MappingStage stage,
                                      const QString& badge) {
    auto it = buttons_.find(stage);
    if (it != buttons_.end()) it->second->set_badge(badge);
}

void MappingStageBar::refresh_badges(
    const std::map<std::string, QString>& badges) {
    for (const auto& [value, badge] : badges) {
        const auto stage = pwb::tool_policy::stage_from_value(value);
        if (stage.has_value()) set_stage_badge(*stage, badge);
    }
}

QString MappingStageBar::current_horizon() const {
    return horizon_combo->currentText().trimmed();
}

void MappingStageBar::set_horizon_state(
    const QString& horizon, const std::vector<QString>& options) {
    const QString target = horizon.trimmed();
    std::vector<QString> choices;
    for (const QString& name : options) {
        const QString text = name.trimmed();
        if (!text.isEmpty() &&
            std::find(choices.begin(), choices.end(), text) ==
                choices.end()) {
            choices.push_back(text);
        }
    }
    if (!target.isEmpty() &&
        std::find(choices.begin(), choices.end(), target) ==
            choices.end()) {
        choices.insert(choices.begin(), target);
    }
    suppress_horizon_ = true;
    horizon_combo->clear();
    for (const QString& choice : choices) horizon_combo->addItem(choice);
    if (!target.isEmpty()) {
        int index = horizon_combo->findText(target);
        if (index < 0) {
            horizon_combo->insertItem(0, target);
            index = 0;
        }
        horizon_combo->setCurrentIndex(index);
    } else {
        horizon_combo->setCurrentIndex(-1);
    }
    last_committed_horizon_ = target;
    suppress_horizon_ = false;
}

void MappingStageBar::commit_horizon() {
    if (suppress_horizon_) return;
    const QString text = current_horizon();
    if (text == last_committed_horizon_) return;
    last_committed_horizon_ = text;
    emit horizon_requested(text);
}

}  // namespace pwb::ui_composite
