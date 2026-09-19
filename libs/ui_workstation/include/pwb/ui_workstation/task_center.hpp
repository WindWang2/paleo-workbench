#pragma once

// Qt shell over task_projection (UI-12) — port of
// paleo_workbench/ui/workstation/task_center.py's widget layer:
// incremental QAbstractTableModel (insert/removeRows for structure,
// dataChanged only for changed cells; elapsed-second changes emit only
// the elapsed column), delegate-painted progress + cancel button
// (zero resident widgets), selection/scroll preservation, context
// menu, empty state, 400 ms poll.
//
// Scheduler + OperationRegistry access is INJECTED: providers return
// snapshots; cancel/retry/jump run injected callbacks — the widget
// never reaches for a global authority.

#include <functional>
#include <map>
#include <optional>

#include <QAbstractTableModel>
#include <QFrame>
#include <QStyledItemDelegate>
#include <QTableView>
#include <QTimer>

#include <pwb/ui_workstation/task_projection.hpp>

namespace pwb::ui_workstation {

// Columns: 状态/任务/进度/用时/操作.
inline constexpr int kTaskColState = 0;
inline constexpr int kTaskColTitle = 1;
inline constexpr int kTaskColProgress = 2;
inline constexpr int kTaskColElapsed = 3;
inline constexpr int kTaskColAction = 4;
inline constexpr int kTaskColumnCount = 5;

class TaskTableModel : public QAbstractTableModel {
    Q_OBJECT
public:
    explicit TaskTableModel(QObject* parent = nullptr);

    int rowCount(const QModelIndex& parent = {}) const override;
    int columnCount(const QModelIndex& parent = {}) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;

    const TaskRow* row_at(int row) const;
    // Diff-apply a fresh snapshot (order + cap already applied).
    void refresh(std::vector<TaskRow> rows, double now);

private:
    std::vector<TaskRow> rows_;
    double last_now_ = 0.0;
    // Per-row content signature + last rendered elapsed second.
    std::map<std::string, std::tuple<std::string, int, std::string,
                                     std::string, int>>
        signatures_;
};

class TaskRowDelegate : public QStyledItemDelegate {
    Q_OBJECT
public:
    explicit TaskRowDelegate(TaskTableModel* model,
                             QObject* parent = nullptr)
        : QStyledItemDelegate(parent), model_(model) {}

    void paint(QPainter* painter, const QStyleOptionViewItem& option,
               const QModelIndex& index) const override;
    bool editorEvent(QEvent* event, QAbstractItemModel* model,
                     const QStyleOptionViewItem& option,
                     const QModelIndex& index) override;

signals:
    void cancel_requested(int row) const;

private:
    TaskTableModel* model_;
};

class WorkstationTaskCenter : public QFrame {
    Q_OBJECT
public:
    explicit WorkstationTaskCenter(QWidget* parent = nullptr);

    // Injected authorities.
    using SnapshotProvider =
        std::function<std::vector<job::JobSnapshot>()>;
    using OperationProvider = std::function<
        std::vector<const ui_shell::OperationRecord*>()>;
    using CancelFn = std::function<bool(const std::string& id)>;
    using RetryFn = std::function<void(const TaskRow&)>;
    using JumpFn = std::function<void(const ui_shell::OperationRecord&)>;

    void set_snapshot_provider(SnapshotProvider fn);
    // Also re-arm the 100 ms coalescing refresh timer provider for
    // registry change signals — the host calls schedule_refresh()
    // from operation_changed/removed.
    void set_operation_provider(OperationProvider fn);
    void set_cancel_task(CancelFn fn);      // scheduler rows
    void set_cancel_operation(CancelFn fn); // registry rows
    void set_retry_task(RetryFn fn);
    // Registry record lookup for jump rows (op_id → record*).
    using RecordLookup = std::function<const ui_shell::OperationRecord*(
        const std::string& op_id)>;
    void set_record_lookup(RecordLookup fn);

    // Coalescing refresh entry (registry change signals → 100 ms
    // single-shot; Python _schedule_registry_refresh parity).
    void schedule_refresh();
    void refresh();
    void shutdown();

    TaskTableModel* model() const { return model_; }

signals:
    void active_count_changed(int count);

private:
    void show_context_menu(const QPoint& pos);
    void run_cancel(const TaskRow& row);
    void run_jump(const TaskRow& row);
    void update_empty_state();
    void remember_selection();
    void restore_selection();

    TaskTableModel* model_ = nullptr;
    QTableView* tree_ = nullptr;
    QWidget* empty_state_ = nullptr;
    QTimer* timer_ = nullptr;
    QTimer* registry_timer_ = nullptr;
    int last_active_ = -1;
    std::optional<std::string> selected_task_id_;

    SnapshotProvider snapshots_;
    OperationProvider operations_;
    CancelFn cancel_task_;
    CancelFn cancel_operation_;
    RetryFn retry_task_;
    RecordLookup record_lookup_;
};

}  // namespace pwb::ui_workstation
