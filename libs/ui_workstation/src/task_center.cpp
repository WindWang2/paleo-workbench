#include "pwb/ui_workstation/task_center.hpp"

#include <algorithm>
#include <chrono>

#include <QApplication>
#include <QClipboard>
#include <QDialog>
#include <QDialogButtonBox>
#include <QHeaderView>
#include <QLabel>
#include <QMenu>
#include <QPainter>
#include <QPlainTextEdit>
#include <QScrollBar>
#include <QStyle>
#include <QStyleOptionButton>
#include <QStyleOptionProgressBar>
#include <QVBoxLayout>

#include <pwb/job_runtime/job_contract.hpp>

namespace pwb::ui_workstation {

// ---------------------------------------------------------------- model

TaskTableModel::TaskTableModel(QObject* parent)
    : QAbstractTableModel(parent) {}

int TaskTableModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(rows_.size());
}

int TaskTableModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : kTaskColumnCount;
}

const TaskRow* TaskTableModel::row_at(int row) const {
    return (0 <= row && row < static_cast<int>(rows_.size()))
               ? &rows_[row]
               : nullptr;
}

QVariant TaskTableModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid()) return {};
    const TaskRow* row = row_at(index.row());
    if (row == nullptr) return {};
    if (role == Qt::UserRole) {
        return index.row();  // delegate resolves through row_at()
    }
    if (role == Qt::DisplayRole) {
        switch (index.column()) {
        case kTaskColTitle:
            return QString::fromStdString(task_title_text(*row));
        case kTaskColState:
            // 状态列必须给模型文本 — ResizeToContents 以模型数据计宽。
            return QString::fromStdString(task_state_text(*row));
        case kTaskColElapsed:
            return QString::fromStdString(format_task_elapsed(
                task_row_elapsed(*row, last_now_)));
        default:
            return {};
        }
    }
    if (role == Qt::ToolTipRole && index.column() == kTaskColTitle) {
        return QString::fromStdString(task_tooltip_text(*row));
    }
    return {};
}

QVariant TaskTableModel::headerData(int section,
                                    Qt::Orientation orientation,
                                    int role) const {
    if (role == Qt::DisplayRole &&
        orientation == Qt::Orientation::Horizontal) {
        static const char* titles[] = {"状态", "任务", "进度", "用时",
                                       "操作"};
        if (0 <= section && section < kTaskColumnCount) {
            return titles[section];
        }
    }
    return {};
}

void TaskTableModel::refresh(std::vector<TaskRow> rows, double now) {
    last_now_ = now;
    // 1) Remove vanished rows back-to-front.
    for (int row = static_cast<int>(rows_.size()) - 1; row >= 0; --row) {
        const std::string& id = rows_[row].task_id;
        const bool still = std::any_of(
            rows.begin(), rows.end(),
            [&](const TaskRow& r) { return r.task_id == id; });
        if (!still) {
            beginRemoveRows(QModelIndex(), row, row);
            signatures_.erase(rows_[row].task_id);
            rows_.erase(rows_.begin() + row);
            endRemoveRows();
        }
    }
    // 2) Insert new rows at their sorted position.
    for (std::size_t pos = 0; pos < rows.size(); ++pos) {
        const std::string& id = rows[pos].task_id;
        const bool exists = std::any_of(
            rows_.begin(), rows_.end(),
            [&](const TaskRow& r) { return r.task_id == id; });
        if (!exists) {
            beginInsertRows(QModelIndex(), static_cast<int>(pos),
                            static_cast<int>(pos));
            rows_.insert(rows_.begin() + pos, rows[pos]);
            endInsertRows();
        }
    }
    // 3) In-place updates: only changed columns emit dataChanged;
    //    elapsed-second changes touch only the elapsed column.
    for (int row = 0; row < static_cast<int>(rows_.size()); ++row) {
        // Refresh the stored row content from the SNAPSHOT (review R2-6:
        // the comment promised overwrite-by-id but bound rows_[row] — the
        // stale stored copy — so after first insert no state/progress/
        // message ever updated; terminal rows stayed "运行中" with a live
        // cancel button). Look the row up by id in the incoming rows and
        // overwrite the stored copy.
        const std::string& row_id = rows_[row].task_id;
        auto fresh_it = std::find_if(
            rows.begin(), rows.end(),
            [&](const TaskRow& r) { return r.task_id == row_id; });
        if (fresh_it == rows.end()) continue;  // defensively removed above
        rows_[row] = *fresh_it;
        const TaskRow& fresh = rows_[row];
        auto core = std::make_tuple(
            std::string(job::to_string(fresh.state)),
            static_cast<int>(fresh.progress * 1000 + 0.5),
            fresh.message.value_or(""),
            fresh.error.value_or(""),
            static_cast<int>(task_row_elapsed(fresh, now)));
        auto it = signatures_.find(fresh.task_id);
        const bool core_changed =
            it == signatures_.end() ||
            std::get<0>(it->second) != std::get<0>(core) ||
            std::get<1>(it->second) != std::get<1>(core) ||
            std::get<2>(it->second) != std::get<2>(core) ||
            std::get<3>(it->second) != std::get<3>(core);
        const bool elapsed_changed =
            it != signatures_.end() &&
            std::get<4>(it->second) != std::get<4>(core);
        signatures_[fresh.task_id] = core;
        if (core_changed) {
            emit dataChanged(index(row, 0),
                             index(row, kTaskColumnCount - 1));
        } else if (elapsed_changed) {
            emit dataChanged(index(row, kTaskColElapsed),
                             index(row, kTaskColElapsed));
        }
    }
}

// ------------------------------------------------------------- delegate

void TaskRowDelegate::paint(QPainter* painter,
                            const QStyleOptionViewItem& option,
                            const QModelIndex& index) const {
    const TaskRow* row = model_->row_at(index.row());
    if (row == nullptr) {
        QStyledItemDelegate::paint(painter, option, index);
        return;
    }
    if (index.column() == kTaskColProgress) {
        // 手绘进度单元（视觉 QA 09）— no resident QProgressBar.
        painter->save();
        const QRect rect = option.rect.adjusted(4, 4, -4, -4);
        const int progress =
            std::max(0, std::min(100,
                                 static_cast<int>(row->progress * 100 +
                                                  0.5)));
        const auto state = row->state;
        if (state == job::JobState::failed) {
            painter->setPen(option.palette.color(
                QPalette::ColorRole::BrightText));
            painter->drawText(rect, Qt::AlignmentFlag::AlignCenter,
                              "失败");
        } else if (state == job::JobState::cancelled) {
            painter->setPen(option.palette.color(
                QPalette::ColorRole::Text));
            painter->drawText(rect, Qt::AlignmentFlag::AlignCenter,
                              "已取消");
        } else if (state == job::JobState::degraded) {
            painter->setPen(option.palette.color(
                QPalette::ColorRole::Link));
            painter->drawText(rect, Qt::AlignmentFlag::AlignCenter,
                              "降级完成");
        } else {
            QStyleOptionProgressBar bar;
            bar.rect = rect;
            bar.minimum = 0;
            bar.maximum = 100;
            bar.progress = progress;
            bar.text = QString("%1%").arg(progress);
            bar.textVisible = true;
            bar.textAlignment = Qt::AlignmentFlag::AlignCenter;
            option.widget->style()->drawControl(
                QStyle::ControlElement::CE_ProgressBar, &bar, painter,
                option.widget);
        }
        painter->restore();
        return;
    }
    if (index.column() == kTaskColAction &&
        (row->state == job::JobState::queued ||
         row->state == job::JobState::running)) {
        QStyleOptionButton button;
        button.rect = option.rect.adjusted(2, 2, -2, -2);
        button.text = "取消";
        button.state = option.state | QStyle::StateFlag::State_Enabled;
        button.direction = option.direction;
        button.fontMetrics = option.fontMetrics;
        button.palette = option.palette;
        option.widget->style()->drawControl(
            QStyle::ControlElement::CE_PushButton, &button, painter,
            option.widget);
        return;
    }
    QStyledItemDelegate::paint(painter, option, index);
}

bool TaskRowDelegate::editorEvent(QEvent* event,
                                  QAbstractItemModel* model,
                                  const QStyleOptionViewItem& option,
                                  const QModelIndex& index) {
    if (event->type() != QEvent::Type::MouseButtonRelease) {
        return QStyledItemDelegate::editorEvent(event, model, option,
                                                index);
    }
    const TaskRow* row = model_->row_at(index.row());
    if (row == nullptr || index.column() != kTaskColAction) {
        return QStyledItemDelegate::editorEvent(event, model, option,
                                                index);
    }
    if (row->cancellable()) {
        emit cancel_requested(index.row());
    }
    return true;
}

// ------------------------------------------------------------ the panel

WorkstationTaskCenter::WorkstationTaskCenter(QWidget* parent)
    : QFrame(parent) {
    setObjectName("WorkstationTaskCenter");

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(8, 8, 8, 8);
    outer->setSpacing(6);

    model_ = new TaskTableModel(this);
    tree_ = new QTableView(this);
    tree_->setObjectName("WorkstationTaskTree");
    tree_->setModel(model_);
    auto* delegate = new TaskRowDelegate(model_, tree_);
    tree_->setItemDelegate(delegate);
    connect(delegate, &TaskRowDelegate::cancel_requested, this,
            [this](int row) {
                if (const TaskRow* r = model_->row_at(row)) {
                    run_cancel(*r);
                }
            });
    tree_->setEditTriggers(
        QAbstractItemView::EditTrigger::NoEditTriggers);
    tree_->setSelectionBehavior(
        QAbstractItemView::SelectionBehavior::SelectRows);
    tree_->setSelectionMode(
        QAbstractItemView::SelectionMode::SingleSelection);
    tree_->setShowGrid(false);
    tree_->setWordWrap(false);
    tree_->verticalHeader()->setVisible(false);
    tree_->horizontalHeader()->setStretchLastSection(false);
    auto* header = tree_->horizontalHeader();
    header->setSectionResizeMode(
        kTaskColState, QHeaderView::ResizeMode::ResizeToContents);
    header->setSectionResizeMode(kTaskColTitle,
                                 QHeaderView::ResizeMode::Stretch);
    header->setSectionResizeMode(kTaskColProgress,
                                 QHeaderView::ResizeMode::Fixed);
    header->resizeSection(kTaskColProgress, 150);
    header->setSectionResizeMode(
        kTaskColElapsed, QHeaderView::ResizeMode::ResizeToContents);
    header->setSectionResizeMode(kTaskColAction,
                                 QHeaderView::ResizeMode::Fixed);
    header->resizeSection(kTaskColAction, 64);
    tree_->setContextMenuPolicy(
        Qt::ContextMenuPolicy::CustomContextMenu);
    connect(tree_, &QTableView::customContextMenuRequested, this,
            &WorkstationTaskCenter::show_context_menu);
    connect(tree_, &QTableView::doubleClicked, this,
            [this](const QModelIndex& index) {
                const TaskRow* row = model_->row_at(index.row());
                if (row != nullptr && row->registry_op && row->has_jump &&
                    row->is_terminal()) {
                    run_jump(*row);
                }
            });
    connect(tree_->selectionModel(), &QItemSelectionModel::selectionChanged,
            this, [this](const QItemSelection&, const QItemSelection&) {
                remember_selection();
            });
    outer->addWidget(tree_, 1);

    // V5-C9 empty state (PwbEmptyState parity — simple overlay label).
    empty_state_ = new QWidget(tree_);
    auto* empty_layout = new QVBoxLayout(empty_state_);
    auto* empty_title = new QLabel("暂无任务", empty_state_);
    empty_title->setAlignment(Qt::AlignmentFlag::AlignCenter);
    auto* empty_hint = new QLabel(
        "提交制备 / 预测 / 转码等任务后将在此显示进度与状态",
        empty_state_);
    empty_hint->setAlignment(Qt::AlignmentFlag::AlignCenter);
    empty_hint->setWordWrap(true);
    empty_layout->addStretch(1);
    empty_layout->addWidget(empty_title);
    empty_layout->addWidget(empty_hint);
    empty_layout->addStretch(1);
    empty_state_->setAttribute(
        Qt::WidgetAttribute::WA_TransparentForMouseEvents);
    empty_state_->hide();
    connect(model_, &QAbstractItemModel::rowsInserted, this,
            [this] { update_empty_state(); });
    connect(model_, &QAbstractItemModel::rowsRemoved, this,
            [this] { update_empty_state(); });
    connect(model_, &QAbstractItemModel::modelReset, this,
            [this] { update_empty_state(); });

    timer_ = new QTimer(this);
    timer_->setInterval(400);
    connect(timer_, &QTimer::timeout, this,
            &WorkstationTaskCenter::refresh);
    timer_->start();

    registry_timer_ = new QTimer(this);
    registry_timer_->setSingleShot(true);
    registry_timer_->setInterval(100);
    connect(registry_timer_, &QTimer::timeout, this,
            &WorkstationTaskCenter::refresh);

    refresh();
}

void WorkstationTaskCenter::set_snapshot_provider(
    SnapshotProvider fn) {
    snapshots_ = std::move(fn);
}

void WorkstationTaskCenter::set_operation_provider(
    OperationProvider fn) {
    operations_ = std::move(fn);
}

void WorkstationTaskCenter::set_cancel_task(CancelFn fn) {
    cancel_task_ = std::move(fn);
}

void WorkstationTaskCenter::set_cancel_operation(CancelFn fn) {
    cancel_operation_ = std::move(fn);
}

void WorkstationTaskCenter::set_retry_task(RetryFn fn) {
    retry_task_ = std::move(fn);
}

void WorkstationTaskCenter::set_record_lookup(RecordLookup fn) {
    record_lookup_ = std::move(fn);
}

void WorkstationTaskCenter::schedule_refresh() {
    if (registry_timer_ != nullptr) registry_timer_->start();
}

void WorkstationTaskCenter::refresh() {
    std::vector<job::JobSnapshot> jobs =
        snapshots_ ? snapshots_() : std::vector<job::JobSnapshot>{};
    std::vector<const ui_shell::OperationRecord*> ops =
        operations_
            ? operations_()
            : std::vector<const ui_shell::OperationRecord*>{};
    auto rows = build_task_rows(jobs, ops);

    const int active = active_task_count(rows);
    if (active != last_active_) {
        last_active_ = active;
        emit active_count_changed(active);
    }

    const int scroll_before = tree_->verticalScrollBar()->value();
    const bool at_top = scroll_before == 0;
    const double now =
        std::chrono::duration<double>(
            std::chrono::steady_clock::now().time_since_epoch())
            .count();
    model_->refresh(std::move(rows), now);
    restore_selection();
    update_empty_state();
    if (!at_top) {
        tree_->verticalScrollBar()->setValue(
            std::min(scroll_before,
                     tree_->verticalScrollBar()->maximum()));
    }
}

void WorkstationTaskCenter::shutdown() {
    timer_->stop();
    if (registry_timer_ != nullptr) registry_timer_->stop();
}

void WorkstationTaskCenter::update_empty_state() {
    if (model_->rowCount() == 0) {
        empty_state_->setGeometry(tree_->viewport()->rect());
        empty_state_->show();
        empty_state_->raise();
    } else {
        empty_state_->hide();
    }
}

void WorkstationTaskCenter::remember_selection() {
    const auto rows = tree_->selectionModel()->selectedRows(kTaskColTitle);
    const TaskRow* row =
        rows.isEmpty() ? nullptr : model_->row_at(rows.first().row());
    if (row != nullptr) {
        selected_task_id_ = row->task_id;
    } else {
        selected_task_id_.reset();
    }
}

void WorkstationTaskCenter::restore_selection() {
    if (!selected_task_id_.has_value()) return;
    for (int row = 0; row < model_->rowCount(); ++row) {
        if (model_->row_at(row)->task_id == *selected_task_id_) {
            tree_->selectRow(row);
            return;
        }
    }
}

void WorkstationTaskCenter::run_cancel(const TaskRow& row) {
    if (row.registry_op) {
        if (cancel_operation_) cancel_operation_(row.op_id);
    } else if (cancel_task_) {
        cancel_task_(row.task_id);
    }
}

void WorkstationTaskCenter::run_jump(const TaskRow& row) {
    if (!record_lookup_) return;
    const auto* record = record_lookup_(row.op_id);
    if (record != nullptr && record->jump) {
        try {
            record->jump();
        } catch (...) {
            // 目标页面已销毁（迟到跳转）— never fault the menu path.
        }
    }
}

void WorkstationTaskCenter::show_context_menu(const QPoint& pos) {
    const QModelIndex index = tree_->indexAt(pos);
    const TaskRow* row =
        index.isValid() ? model_->row_at(index.row()) : nullptr;
    if (row == nullptr) return;
    const TaskRow copy = *row;  // rows may be re-projected mid-menu
    QMenu menu(this);
    for (const auto& item : task_menu_items(copy)) {
        QAction* action =
            menu.addAction(QString::fromStdString(item.label));
        action->setEnabled(item.enabled);
        if (!item.tooltip.empty()) {
            action->setToolTip(QString::fromStdString(item.tooltip));
        }
        switch (item.action) {
        case TaskMenuAction::Cancel:
            connect(action, &QAction::triggered, this,
                    [this, copy] { run_cancel(copy); });
            break;
        case TaskMenuAction::JumpToResult:
            connect(action, &QAction::triggered, this,
                    [this, copy] { run_jump(copy); });
            break;
        case TaskMenuAction::Retry:
            connect(action, &QAction::triggered, this, [this, copy] {
                if (retry_task_) retry_task_(copy);
            });
            break;
        case TaskMenuAction::CopyTaskId:
            connect(action, &QAction::triggered, this, [copy] {
                QApplication::clipboard()->setText(
                    QString::fromStdString(copy.task_id));
            });
            break;
        case TaskMenuAction::Details:
            connect(action, &QAction::triggered, this, [this, copy] {
                auto* dialog = new QDialog(this);
                dialog->setWindowTitle(QString::fromStdString(
                    "任务详情 — " + copy.title));
                auto* layout = new QVBoxLayout(dialog);
                auto* body = new QPlainTextEdit(dialog);
                body->setReadOnly(true);
                body->setPlainText(QString::fromStdString(
                    task_details_text(copy)));
                layout->addWidget(body);
                auto* buttons = new QDialogButtonBox(
                    QDialogButtonBox::StandardButton::Close, dialog);
                connect(buttons, &QDialogButtonBox::rejected, dialog,
                        &QDialog::reject);
                connect(buttons, &QDialogButtonBox::accepted, dialog,
                        &QDialog::accept);
                layout->addWidget(buttons);
                dialog->resize(520, 360);
                dialog->setAttribute(Qt::WA_DeleteOnClose);
                dialog->show();
            });
            break;
        }
    }
    menu.exec(tree_->viewport()->mapToGlobal(pos));
}

}  // namespace pwb::ui_workstation
