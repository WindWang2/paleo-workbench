#pragma once

// UI-09 — TaskPanelBase Qt shell (task_panel_base.py) + the two thin
// specializations used by this slice:
//   SeismicTaskPanel    object_name="SeismicTaskPanel"    title="地震预测任务"
//                       show_review_count=False
//   PredictionTaskPanel object_name="PredictionTaskPanel" title="测井预测任务"
//                       show_review_count=True
// Row text/keys/status tokens come from task_state.hpp — never re-derived.

#include <optional>
#include <vector>

#include <QFrame>
#include <QString>

#include <pwb/ui_wellseis/slices.hpp>

class QLabel;
class QListWidget;

namespace pwb::ui_wellseis::qt {

class TaskPanelBase : public QFrame {
    Q_OBJECT
public:
    TaskPanelBase(QWidget* parent, const QString& object_name,
                  const QString& title, bool show_review_count);

    // update_state parity — keyed reconcile keeps scroll/selection; the
    // active row follows the selected task (or the active_prediction_task
    // fallback) instead of a positional re-pick.
    void update_state(const std::vector<PredictionTaskSlice>& tasks,
                      std::optional<int> selected_index = std::nullopt);
    [[nodiscard]] const std::vector<PredictionTaskSlice>& tasks() const;
    [[nodiscard]] int current_row() const;

signals:
    void task_selected(int row);

protected:
    QListWidget* task_list_ = nullptr;

private:
    QLabel* name_value_ = nullptr;
    QLabel* adapter_value_ = nullptr;
    QLabel* status_badge_ = nullptr;
    QLabel* mean_probability_value_ = nullptr;
    QLabel* review_count_value_ = nullptr;  // nullptr when hidden
    std::vector<PredictionTaskSlice> tasks_;
    bool suppress_ = false;
};

class SeismicTaskPanel : public TaskPanelBase {
    Q_OBJECT
public:
    explicit SeismicTaskPanel(QWidget* parent = nullptr)
        : TaskPanelBase(parent, QStringLiteral("SeismicTaskPanel"),
                        QStringLiteral("地震预测任务"),
                        /*show_review_count=*/false) {}
};

class PredictionTaskPanel : public TaskPanelBase {
    Q_OBJECT
public:
    explicit PredictionTaskPanel(QWidget* parent = nullptr)
        : TaskPanelBase(parent, QStringLiteral("PredictionTaskPanel"),
                        QStringLiteral("测井预测任务"),
                        /*show_review_count=*/true) {}
};

}  // namespace pwb::ui_wellseis::qt
