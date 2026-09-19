#include <pwb/ui_wellseis/qt/task_panel_base.hpp>

#include <QLabel>
#include <QListWidget>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/json_helpers.hpp>
#include <pwb/ui_wellseis/task_state.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

QLabel* add_value(QVBoxLayout* layout, const QString& label_text,
                  const QString& value_text, QWidget* parent) {
    auto* label = new QLabel(label_text, parent);
    label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(label);
    auto* value = new QLabel(value_text, parent);
    value->setObjectName(QStringLiteral("WorkFieldValue"));
    layout->addWidget(value);
    return value;
}

}  // namespace

TaskPanelBase::TaskPanelBase(QWidget* parent, const QString& object_name,
                             const QString& title, bool show_review_count)
    : QFrame(parent) {
    setObjectName(object_name);
    setMinimumWidth(200);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);
    layout->setSpacing(4);

    auto* title_label = new QLabel(title, this);
    title_label->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title_label);

    name_value_ = add_value(layout, QStringLiteral("当前任务"),
                            QStringLiteral("未选择预测任务"), this);
    adapter_value_ =
        add_value(layout, QStringLiteral("适配器"), QStringLiteral("—"), this);
    auto* status_label = new QLabel(QStringLiteral("状态"), this);
    status_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(status_label);
    status_badge_ = new QLabel(QStringLiteral("待开始"), this);
    status_badge_->setObjectName(QStringLiteral("PwbBadge"));
    layout->addWidget(status_badge_);
    mean_probability_value_ = add_value(layout, QStringLiteral("平均概率"),
                                        QStringLiteral("—"), this);
    review_count_value_ =
        show_review_count
            ? add_value(layout, QStringLiteral("待复核区"),
                        QStringLiteral("0 个"), this)
            : nullptr;

    auto* list_label = new QLabel(QStringLiteral("任务列表"), this);
    list_label->setObjectName(QStringLiteral("WorkFieldLabel"));
    layout->addWidget(list_label);
    task_list_ = new QListWidget(this);
    task_list_->setObjectName(QStringLiteral("WorkListWidget"));
    connect(task_list_, &QListWidget::currentRowChanged, this,
            [this](int row) {
                if (!suppress_ && row >= 0) {
                    emit task_selected(row);
                }
            });
    layout->addWidget(task_list_, 1);
}

void TaskPanelBase::update_state(
    const std::vector<PredictionTaskSlice>& tasks,
    std::optional<int> selected_index) {
    tasks_ = tasks;
    const int active_row_core = task_panel_active_row(tasks, selected_index);
    const PredictionTaskSlice* task =
        active_row_core >= 0 ? &tasks[active_row_core] : nullptr;

    name_value_->setText(
        task != nullptr && !task->name.empty()
            ? qs(task->name)
            : QStringLiteral("未选择预测任务"));
    adapter_value_->setText(
        task != nullptr && !task->adapter_kind.empty()
            ? qs(task->adapter_kind)
            : QStringLiteral("—"));
    const TaskStatusToken token =
        task_status_token(task != nullptr ? task->status : "");
    status_badge_->setText(qs(token.label));
    status_badge_->setProperty("tone", qs(badge_tone_of(token.tone)));
    if (task != nullptr) {
        const std::string probability =
            json_str(task->probability_summary, "mean_probability", "");
        mean_probability_value_->setText(
            probability.empty() ? QStringLiteral("—") : qs(probability));
    } else {
        mean_probability_value_->setText(QStringLiteral("—"));
    }
    if (review_count_value_ != nullptr) {
        review_count_value_->setText(
            QString::number(task != nullptr ? task->review_area_count : 0) +
            QStringLiteral(" 个"));
    }

    // Keyed reconcile: rebuild rows but keep selection stable by task key —
    // the active task's key wins; else the previous selection's key.
    suppress_ = true;
    const QString previous_key =
        task_list_->currentItem() != nullptr
            ? task_list_->currentItem()->data(Qt::UserRole).toString()
            : QString();
    task_list_->clear();
    int active_row = -1;
    int previous_row = -1;
    const QString active_key =
        task != nullptr ? qs(task_key(*task)) : QString();
    for (std::size_t i = 0; i < tasks.size(); ++i) {
        const PredictionTaskSlice& item = tasks[i];
        const QString key = qs(task_key(item));
        auto* row_item = new QListWidgetItem(task_list_);
        row_item->setData(Qt::UserRole, key);
        row_item->setText(qs(task_row_text(item)));
        row_item->setToolTip(qs(task_row_tooltip(item)));
        if (!active_key.isEmpty() && key == active_key && active_row < 0) {
            active_row = static_cast<int>(i);
        }
        if (!previous_key.isEmpty() && key == previous_key &&
            previous_row < 0) {
            previous_row = static_cast<int>(i);
        }
    }
    const int row_to_select =
        active_row >= 0 ? active_row : previous_row;
    if (row_to_select >= 0) {
        task_list_->setCurrentRow(row_to_select);
    }
    suppress_ = false;
}

const std::vector<PredictionTaskSlice>& TaskPanelBase::tasks() const {
    return tasks_;
}

int TaskPanelBase::current_row() const {
    return task_list_->currentRow();
}

}  // namespace pwb::ui_wellseis::qt
