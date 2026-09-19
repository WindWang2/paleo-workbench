#include "pwb/ui_widgets/interactive_qc_hub.hpp"

#include <QEvent>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QListWidgetItem>
#include <QSplitter>
#include <QToolButton>
#include <QVBoxLayout>

namespace pwb::ui_widgets {

namespace {

// Python str() parity for QVariant scalars (True/False/None casing).
QString py_variant_str(const QVariant& v) {
    if (!v.isValid() || v.isNull()) return QStringLiteral("None");
    if (v.typeId() == QMetaType::Bool) {
        return v.toBool() ? QStringLiteral("True") : QStringLiteral("False");
    }
    return v.toString();
}

QString issue_str(const QVariantMap& issue, const char* key) {
    return issue.contains(QString::fromLatin1(key))
               ? py_variant_str(issue.value(QString::fromLatin1(key)))
               : QStringLiteral("None");
}

// Python truthiness over QVariant (or-chains): invalid/null, false, 0 and
// "" are falsy.
bool variant_truthy(const QVariant& v) {
    if (!v.isValid() || v.isNull()) return false;
    switch (v.typeId()) {
        case QMetaType::Bool:
            return v.toBool();
        case QMetaType::Int:
        case QMetaType::UInt:
        case QMetaType::LongLong:
        case QMetaType::ULongLong:
            return v.toLongLong() != 0;
        case QMetaType::Double:
        case QMetaType::Float:
            return v.toDouble() != 0.0;
        case QMetaType::QString:
            return !v.toString().isEmpty();
        default:
            return true;
    }
}

// Python `issue.get(k1) or issue.get(k2) or fallback` falsy chain.
QString issue_or(const QVariantMap& issue, const char* k1, const char* k2,
                 const QString& fallback) {
    const QVariant a = issue.value(QString::fromLatin1(k1));
    if (variant_truthy(a)) return a.toString();
    const QVariant b = issue.value(QString::fromLatin1(k2));
    if (variant_truthy(b)) return b.toString();
    return fallback;
}

// Python `issue.get(k, default)`: absent -> default; present-but-null ->
// the stored None (renders "None" through f-string str()).
QString issue_get(const QVariantMap& issue, const char* key,
                  const QString& fallback) {
    const QString k = QString::fromLatin1(key);
    return issue.contains(k) ? py_variant_str(issue.value(k)) : fallback;
}

QVariantMap item_issue(QListWidgetItem* item) {
    if (item == nullptr) return {};
    return item->data(Qt::UserRole).toMap();
}

}  // namespace

// ---------------------------------------------------------------------------
// SmoothPanController
// ---------------------------------------------------------------------------

SmoothPanController::SmoothPanController(QObject* parent) : QObject(parent) {
    timer_ = new QTimer(this);
    timer_->setInterval(core::kPanTickMs);
    connect(timer_, &QTimer::timeout, this, &SmoothPanController::tick);
}

void SmoothPanController::pan_to_extent(PanCanvas canvas,
                                        const std::vector<double>& extent,
                                        double pad) {
    std::array<double, 4> target{};
    if (pad != 0.0) {
        target = core::padded_bbox(extent, pad);
    } else if (extent.size() == 4) {
        std::copy_n(extent.begin(), 4, target.begin());
    } else {
        target = {0.0, 0.0, 1.0, 1.0};
    }
    std::array<double, 4> current{0.0, 0.0, 1.0, 1.0};
    if (canvas.view_extent) {
        const auto got = canvas.view_extent();
        if (got.size() == 4) current = got;
    }
    canvas_ = std::move(canvas);
    start_ = current;
    target_ = target;
    has_target_ = true;
    elapsed_ = 0;
    timer_->start();
}

void SmoothPanController::cancel() {
    timer_->stop();
    canvas_ = PanCanvas{};
    has_target_ = false;
}

void SmoothPanController::tick() {
    if (!canvas_.set_extent || !has_target_) {
        timer_->stop();
        return;
    }
    elapsed_ += core::kPanTickMs;
    const double t =
        core::ease_in_out(double(elapsed_) / double(core::kPanDurationMs));
    std::array<double, 4> extent{};
    for (int i = 0; i < 4; ++i) {
        extent[i] = start_[i] + (target_[i] - start_[i]) * t;
    }
    const bool done = elapsed_ >= core::kPanDurationMs;
    // 历史只在末帧写一次；中间帧 coalesce 合并（D9）。
    canvas_.set_extent(done ? target_ : extent,
                       /*record_history=*/done, /*coalesce_history=*/true);
    if (done) {
        timer_->stop();
        canvas_ = PanCanvas{};
        has_target_ = false;
    }
}

// ---------------------------------------------------------------------------
// InteractiveQCHub
// ---------------------------------------------------------------------------

InteractiveQCHub::InteractiveQCHub(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("InteractiveQCHub"));
    fix_actions_ = [](const QString& rule) {
        return core::actions_for_rule(rule.toStdString());
    };
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(6, 6, 6, 6);
    layout->setSpacing(4);

    auto* top = new QHBoxLayout();
    auto* refresh_button = new QToolButton(this);
    refresh_button->setText(QStringLiteral("重新检查"));
    connect(refresh_button, &QToolButton::clicked, this,
            &InteractiveQCHub::refresh_requested);
    auto* filter_combo = new QComboBox(this);
    filter_combo->addItems({"全部", "错误", "警告", "可修复"});
    connect(filter_combo, &QComboBox::currentTextChanged, this,
            [this](const QString&) { reload(); });
    filter_combo->setObjectName(QStringLiteral("QCHubFilter"));
    filter_combo_ = filter_combo;
    counts_label = new QLabel(QStringLiteral("0 错误 · 0 警告"), this);
    counts_label->setObjectName(QStringLiteral("QCHubCounts"));
    top->addWidget(refresh_button);
    top->addWidget(filter_combo);
    top->addStretch(1);
    top->addWidget(counts_label);
    layout->addLayout(top);

    auto* splitter = new QSplitter(Qt::Horizontal, this);
    issue_list = new QListWidget(splitter);
    issue_list->setObjectName(QStringLiteral("QCHubIssueList"));
    connect(issue_list, &QListWidget::itemDoubleClicked, this,
            [this](QListWidgetItem* item) {
                emit issue_focused(item_issue(item));
            });
    connect(issue_list, &QListWidget::itemSelectionChanged, this,
            &InteractiveQCHub::on_selection);
    // 键盘流（S5-2）：列表上直接接 Enter（定位）与 F（修复）。
    issue_list->installEventFilter(this);
    splitter->addWidget(issue_list);

    detail_pane_ = new QWidget(splitter);
    auto* detail_layout = new QVBoxLayout(detail_pane_);
    detail_layout->setContentsMargins(6, 6, 6, 6);
    detail_title_ = new QLabel(QStringLiteral("选择一个问题查看详情"),
                               detail_pane_);
    detail_title_->setWordWrap(true);
    detail_meta_ = new QLabel(QString(), detail_pane_);
    detail_meta_->setWordWrap(true);
    locate_button_ = new QPushButton(QStringLiteral("定位"), detail_pane_);
    connect(locate_button_, &QPushButton::clicked, this,
            &InteractiveQCHub::locate_selected);
    detail_layout->addWidget(detail_title_);
    detail_layout->addWidget(detail_meta_);
    detail_layout->addWidget(locate_button_);
    fix_area_label_ = new QLabel(QStringLiteral("—— 快速修复 ——"), detail_pane_);
    detail_layout->addWidget(fix_area_label_);
    detail_layout->addStretch(1);
    splitter->addWidget(detail_pane_);
    splitter->setStretchFactor(0, 3);
    splitter->setStretchFactor(1, 2);
    layout->addWidget(splitter, 1);
}

void InteractiveQCHub::set_issues(const QString& source,
                                  const QList<QVariantMap>& issues) {
    sources_[source] = issues;
    reload();
}

void InteractiveQCHub::reload() {
    QList<QVariantMap> merged;
    for (const auto& [source, issues] : sources_) merged += issues;
    items_ = merged;
    int errors = 0, warnings = 0;
    for (const QVariantMap& issue : merged) {
        const QString sev = issue.value(QStringLiteral("severity")).toString();
        if (sev == "error") ++errors;
        if (sev == "warning") ++warnings;
    }
    counts_label->setText(QStringLiteral("%1 错误 · %2 警告")
                              .arg(errors)
                              .arg(warnings));
    issue_list->clear();
    // Python parity: the filter combo re-triggers reload() but does NOT
    // filter — the merged list always shows every issue (frozen quirk,
    // ledger P-QUIRK).
    for (const QVariantMap& issue : merged) {
        const QString label = issue_or(issue, "message", "rule", "?");
        const QString glyph =
            issue.value(QStringLiteral("severity")).toString() == "error"
                ? QStringLiteral("▲")
                : QStringLiteral("▼");
        const QString rule = issue_get(issue, "rule", QString());
        const bool fixable =
            fix_actions_ && !fix_actions_(rule).empty();
        const QString fixable_text =
            fixable ? QStringLiteral("修复可用") : QStringLiteral("—");
        auto* item = new QListWidgetItem(
            QStringLiteral("%1 %2  %3  %4  | %5")
                .arg(glyph,
                     issue_get(issue, "rule", QString()),
                     issue_get(issue, "feature_id", QString()),
                     fixable_text, label));
        item->setData(Qt::UserRole, issue);
        issue_list->addItem(item);
    }
}

void InteractiveQCHub::mark_resolved(const QVariantMap& issue) {
    const auto key = std::make_pair(issue_str(issue, "rule"),
                                    issue_str(issue, "feature_id"));
    for (auto& [source, issues] : sources_) {
        QList<QVariantMap> kept;
        for (const QVariantMap& i : issues) {
            if (std::make_pair(issue_str(i, "rule"),
                               issue_str(i, "feature_id")) != key) {
                kept.append(i);
            }
        }
        issues = kept;
    }
    reload();
}

void InteractiveQCHub::set_fix_gate(FixAvailabilityFn gate) {
    fix_gate_ = std::move(gate);
    refresh_detail();
}

void InteractiveQCHub::set_fix_actions(FixActionsFn actions) {
    if (actions) fix_actions_ = std::move(actions);
    reload();
}

void InteractiveQCHub::on_selection() { show_detail(issue_list->currentItem()); }

void InteractiveQCHub::show_detail(QListWidgetItem* item) {
    current_issue_ = item_issue(item);
    refresh_detail();
}

void InteractiveQCHub::refresh_detail() {
    const QVariantMap issue = current_issue_;
    if (issue.isEmpty()) {
        detail_title_->setText(QStringLiteral("选择一个问题查看详情"));
        detail_meta_->setText(QString());
        return;
    }
    detail_title_->setText(issue_or(issue, "message", "rule", QString()));
    detail_meta_->setText(
        QStringLiteral("图层：%1  要素：%2")
            .arg(issue_get(issue, "layer_id", QStringLiteral("—")),
                 issue_get(issue, "feature_id", QStringLiteral("—"))));
    for (QPushButton* button : fix_buttons_) button->hide();
    const QString rule = issue_get(issue, "rule", QString());
    const auto actions =
        fix_actions_ ? fix_actions_(rule)
                     : std::vector<core::QuickFixActionMeta>{};
    QVBoxLayout* detail_layout =
        qobject_cast<QVBoxLayout*>(detail_pane_->layout());
    for (const core::QuickFixActionMeta& action : actions) {
        const QString aid = QString::fromStdString(action.action_id);
        QPushButton* button = fix_buttons_.value(aid);
        if (button == nullptr) {
            button = new QPushButton(QString::fromStdString(action.title), this);
            button->setObjectName(QStringLiteral("QCHubFix_") + aid);
            connect(button, &QPushButton::clicked, this,
                    [this, aid]() { request_fix(aid); });
            fix_buttons_.insert(aid, button);
            // 挂到详情区（在 stretch 之前插入）。
            if (detail_layout != nullptr) {
                detail_layout->insertWidget(detail_layout->count() - 1,
                                            button);
            }
        }
        if (!fix_gate_) {
            button->setEnabled(false);
            button->setToolTip(QStringLiteral("无修复上下文（图层/会话不可用）"));
            current_availability_.insert(
                aid, {false, "无修复上下文（图层/会话不可用）"});
        } else {
            const auto verdict = fix_gate_(issue, aid);
            if (!verdict) {
                button->setEnabled(false);
                button->setToolTip(
                    QStringLiteral("无修复上下文（图层/会话不可用）"));
                current_availability_.insert(
                    aid, {false, "无修复上下文（图层/会话不可用）"});
            } else {
                const auto [ok, reason] = *verdict;
                button->setEnabled(ok);
                button->setToolTip(
                    ok ? QString::fromStdString(reason)
                       : QStringLiteral("不可修复：%1")
                             .arg(QString::fromStdString(reason)));
                current_availability_.insert(
                    aid, {ok, QString::fromStdString(reason)});
            }
        }
        button->show();
    }
}

QPushButton* InteractiveQCHub::fix_button(const QString& action_id) const {
    return fix_buttons_.value(action_id);
}

QVariantMap InteractiveQCHub::current_issue_dict() const {
    if (!current_issue_.isEmpty()) return current_issue_;
    return item_issue(issue_list->currentItem());
}

void InteractiveQCHub::request_fix(const QString& action_id) {
    const QVariantMap issue = current_issue_dict();
    if (!issue.isEmpty()) emit fix_requested(issue, action_id);
}

void InteractiveQCHub::locate_selected() {
    QListWidgetItem* item = issue_list->currentItem();
    if (item != nullptr) emit issue_focused(item_issue(item));
}

bool InteractiveQCHub::eventFilter(QObject* obj, QEvent* event) {
    if (obj == issue_list && event->type() == QEvent::KeyPress) {
        auto* key_event = static_cast<QKeyEvent*>(event);
        if (key_event->key() == Qt::Key_Return ||
            key_event->key() == Qt::Key_Enter) {
            locate_selected();
            return true;
        }
        if (key_event->key() == Qt::Key_F) {
            // F6（review）：键盘路径与按钮同门禁——只发首个可用动作。
            const QVariantMap issue = current_issue_dict();
            const QString rule = issue_get(issue, "rule", QString());
            const auto actions =
                fix_actions_ ? fix_actions_(rule)
                             : std::vector<core::QuickFixActionMeta>{};
            for (const core::QuickFixActionMeta& action : actions) {
                const QString aid = QString::fromStdString(action.action_id);
                const auto avail = current_availability_.value(aid);
                if (avail.first) {
                    emit fix_requested(issue, aid);
                    return true;
                }
            }
            return false;
        }
    }
    return QWidget::eventFilter(obj, event);
}

}  // namespace pwb::ui_widgets
