#include <pwb/ui/stage_dock.hpp>

#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QStackedWidget>
#include <QVBoxLayout>
#include <QWidget>

namespace pwb::ui {
namespace {

// Readiness glyph ladder (state_language.py readiness vocabulary).
const char* status_glyph(ReadinessItemStatus status) {
    switch (status) {
        case ReadinessItemStatus::Ok: return "✓";
        case ReadinessItemStatus::Warning: return "!";
        case ReadinessItemStatus::Error: return "✗";
        case ReadinessItemStatus::Info: return "·";
    }
    return "·";
}

}  // namespace

StageDock::StageDock(QWidget* parent) : QDockWidget(parent) {
    setObjectName(QStringLiteral("stage-dock"));
    setWindowTitle(QObject::tr("编图阶段"));

    auto* root = new QWidget(this);
    auto* root_layout = new QVBoxLayout(root);
    root_layout->setContentsMargins(4, 4, 4, 4);

    // Stage switcher: one button per stage, checked = authoritative stage.
    auto* switcher = new QHBoxLayout;
    int index = 0;
    for (const pwb::tool_policy::MappingStage stage :
         pwb::tool_policy::kStageOrder) {
        auto* button = new QPushButton(
            QString::fromUtf8(pwb::tool_policy::stage_short_label(stage)), root);
        button->setCheckable(true);
        const int slot = index++;
        stage_buttons_[slot] = button;
        connect(button, &QPushButton::clicked, this,
                [this, stage]() { on_stage_button_clicked(stage); });
        switcher->addWidget(button);
    }
    root_layout->addLayout(switcher);

    pages_ = new QStackedWidget(root);
    for (const pwb::tool_policy::MappingStage stage :
         pwb::tool_policy::kStageOrder) {
        build_stage_page(stage);
    }
    root_layout->addWidget(pages_, /*stretch*/ 1);

    setWidget(root);
    set_current_stage(pwb::tool_policy::MappingStage::FaciesCalibration);
}

void StageDock::build_stage_page(pwb::tool_policy::MappingStage stage) {
    const int slot = static_cast<int>(stage);
    auto* page = new QWidget(pages_);
    auto* layout = new QVBoxLayout(page);

    stage_descriptions_[slot] = new QLabel(
        QString::fromUtf8(pwb::tool_policy::stage_description(stage)), page);
    stage_descriptions_[slot]->setWordWrap(true);
    layout->addWidget(stage_descriptions_[slot]);

    readiness_lists_[slot] = new QListWidget(page);
    // Side-bar list must not push the dock's minimum width open (Python
    // _narrow_list contract).
    readiness_lists_[slot]->setMinimumWidth(0);
    readiness_lists_[slot]->setHorizontalScrollBarPolicy(
        Qt::ScrollBarAlwaysOff);
    readiness_lists_[slot]->setWordWrap(true);
    readiness_lists_[slot]->setTextElideMode(Qt::ElideRight);
    layout->addWidget(readiness_lists_[slot], /*stretch*/ 1);

    status_labels_[slot] = new QLabel(page);
    layout->addWidget(status_labels_[slot]);

    pages_->addWidget(page);
}

void StageDock::on_stage_button_clicked(
    pwb::tool_policy::MappingStage stage) {
    emit stage_change_requested(
        QString::fromUtf8(pwb::tool_policy::stage_value(stage)));
}

void StageDock::set_current_stage(pwb::tool_policy::MappingStage stage) {
    current_stage_ = stage;
    int index = 0;
    for (const pwb::tool_policy::MappingStage entry :
         pwb::tool_policy::kStageOrder) {
        const int slot = index++;
        if (stage_buttons_[slot] != nullptr) {
            // Authoritative state only — no signal loops (clicked is user
            // only; setChecked does not emit clicked).
            stage_buttons_[slot]->setChecked(entry == stage);
        }
    }
    pages_->setCurrentIndex(static_cast<int>(stage));
}

void StageDock::set_readiness(pwb::tool_policy::MappingStage stage,
                              const StageReadiness& readiness) {
    const int slot = static_cast<int>(stage);
    QListWidget* list = readiness_lists_[slot];
    if (list == nullptr) return;
    list->clear();
    for (const ReadinessItem& item : readiness.sorted_items()) {
        QString row = QString::fromUtf8(status_glyph(item.status))
            + QStringLiteral("  ")
            + QString::fromStdString(item.title);
        if (!item.detail.empty()) {
            row += QStringLiteral(" — ") + QString::fromStdString(item.detail);
        }
        list->addItem(row);
        // Tooltip carries the click-through target when present.
        if (!item.target.empty()) {
            list->item(list->count() - 1)
                ->setToolTip(QString::fromStdString(item.target));
        }
    }
    if (status_labels_[slot] != nullptr) {
        const std::size_t warning_count = readiness.warnings().size();
        status_labels_[slot]->setText(
            QString::fromUtf8(readiness.label()) + QStringLiteral("（%1 项提醒）")
                .arg(static_cast<qsizetype>(warning_count)));
    }
}

QStringList StageDock::readiness_rows() const {
    QStringList rows;
    const QListWidget* list = readiness_lists_[static_cast<int>(current_stage_)];
    if (list == nullptr) return rows;
    const int count = static_cast<int>(list->count());
    for (int i = 0; i < count; ++i) {
        const QListWidgetItem* item = list->item(i);
        if (item != nullptr) rows.append(item->text());
    }
    return rows;
}

}  // namespace pwb::ui
