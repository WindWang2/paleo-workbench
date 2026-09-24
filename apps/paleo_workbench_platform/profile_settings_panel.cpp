#include "profile_settings_panel.hpp"

#include <QCheckBox>
#include <QFrame>
#include <QLabel>
#include <QVBoxLayout>

namespace pwb::app {

ProfileSettingsPanel::ProfileSettingsPanel(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ProfileSettingsPanel"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(6, 6, 6, 6);
    outer->setSpacing(4);

    auto* wells_title = new QLabel(QStringLiteral("剖面井"), this);
    wells_title->setObjectName(QStringLiteral("ProfileSettingsWellsTitle"));
    outer->addWidget(wells_title);

    auto* wells_host = new QWidget(this);
    wells_box_ = new QVBoxLayout(wells_host);
    wells_box_->setContentsMargins(0, 0, 0, 0);
    wells_box_->setSpacing(2);
    outer->addWidget(wells_host, 1);

    auto* rule = new QFrame(this);
    rule->setFrameShape(QFrame::HLine);
    rule->setStyleSheet(QStringLiteral("color:#d0d0d0;"));
    outer->addWidget(rule);

    auto* display_title = new QLabel(QStringLiteral("显示设置"), this);
    display_title->setObjectName(
        QStringLiteral("ProfileSettingsDisplayTitle"));
    outer->addWidget(display_title);

    auto* frame_check = new QCheckBox(QStringLiteral("地层格架"), this);
    frame_check->setObjectName(QStringLiteral("ProfileSettingFrame"));
    frame_check->setChecked(true);
    connect(frame_check, &QCheckBox::toggled, this,
            &ProfileSettingsPanel::frame_toggled);
    outer->addWidget(frame_check);

    // 沉积相/测井曲线轨道由剖面渲染器固定输出 —— 勾选只表达「常开」
    // 状态，禁用防止误以为可关（诚实缺席：无开关 seam）。
    for (const QString& label :
         {QStringLiteral("沉积相"), QStringLiteral("测井曲线")}) {
        auto* check = new QCheckBox(label, this);
        check->setChecked(true);
        check->setEnabled(false);
        check->setToolTip(QStringLiteral("剖面渲染器固定输出，无显示开关"));
        outer->addWidget(check);
    }
}

void ProfileSettingsPanel::set_well_names(const QStringList& names) {
    names_ = names;
    // 新井默认勾选；已消失的井连同勾选态一并丢弃。
    QSet<QString> alive(names.begin(), names.end());
    for (const QString& name : names) {
        if (!checked_.contains(name)) checked_.insert(name);
    }
    checked_.intersect(alive);

    syncing_ = true;
    while (QLayoutItem* item = wells_box_->takeAt(0)) {
        delete item->widget();
        delete item;
    }
    if (names.isEmpty()) {
        auto* empty = new QLabel(
            QStringLiteral("未加载井数据 — 经「选井」或井数据载入"),
            wells_box_->parentWidget());
        empty->setObjectName(QStringLiteral("ProfileSettingsEmpty"));
        empty->setWordWrap(true);
        wells_box_->addWidget(empty);
    }
    for (const QString& name : names) {
        auto* check = new QCheckBox(name, wells_box_->parentWidget());
        check->setChecked(checked_.contains(name));
        connect(check, &QCheckBox::toggled, this,
                [this, name](bool on) {
                    if (on) {
                        checked_.insert(name);
                    } else {
                        checked_.remove(name);
                    }
                    emit_filter();
                });
        wells_box_->addWidget(check);
    }
    syncing_ = false;
    emit_filter();
}

void ProfileSettingsPanel::emit_filter() {
    if (syncing_) return;
    // 全勾 = 空过滤器（dock 语义）；全不勾也发全集子集（空集会让
    // dock 误读为「全部」——用显式不可能名占位表达「全不显示」）。
    QSet<QString> filter;
    if (checked_.size() == names_.size()) {
        // 全勾：空 filter 即可。
    } else if (checked_.isEmpty()) {
        filter.insert(QStringLiteral("__none__"));
    } else {
        filter = checked_;
    }
    emit well_filter_changed(filter);
}

}  // namespace pwb::app
