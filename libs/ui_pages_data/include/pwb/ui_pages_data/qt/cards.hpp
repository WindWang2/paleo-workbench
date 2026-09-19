// UI-06 — Qt shells for the home-page side column cards.
//
// activity_card.py / resource_summary.py / completeness_card.py /
// onboarding_report_card.py / start_guide_card.py / result_summary.py —
// label-driven cards whose display strings come from the Qt-free cores
// (activity.hpp, readiness.hpp, onboarding_report.hpp, qc_summary.hpp).
#pragma once

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QScrollArea>
#include <QVBoxLayout>
#include <QWidget>

#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_pages_data/activity.hpp>
#include <pwb/ui_pages_data/qc_summary.hpp>

class QPushButton;

namespace pwb::ui_pages_data::qt {

// activity_card.py :: RecentActivityCard
class RecentActivityCard : public QFrame {
    Q_OBJECT
public:
    explicit RecentActivityCard(QWidget* parent = nullptr);

    // state = dashboard_state-shaped dict; steps = ordered step list —
    // same contract as the Python update_state(state, steps).
    void update_state(const domain::Json& state,
                      const std::vector<ActivityStep>& steps);
    int entry_count() const { return entry_count_; }

private:
    int append_entry(const QString& when, const QString& description);
    void clear_entries();

    QVBoxLayout* entries_layout_;
    QLabel* empty_label_;
    std::vector<QWidget*> entry_widgets_;
    int entry_count_ = 0;
};

// resource_summary.py :: ResourceSummaryBar (single-line strip).
class ResourceSummaryBar : public QFrame {
    Q_OBJECT
public:
    explicit ResourceSummaryBar(QWidget* parent = nullptr);

    void update_state(const domain::Json& state);

private:
    QString status_qss() const;

    std::vector<QLabel*> count_labels_;   // kRequiredResourceTypes order
    QLabel* status_label_;
    // std::optional<bool> parity: -1 unknown, 0 false, 1 true.
    int ready_ = -1;
};

// completeness_card.py :: DataCompletenessCard.
class DataCompletenessCard : public QFrame {
    Q_OBJECT
public:
    explicit DataCompletenessCard(QWidget* parent = nullptr);

    void update_state(const domain::Json& state);

private:
    QString summary_qss() const;

    std::vector<QLabel*> count_labels_;   // kRequiredResourceTypes order
    std::vector<QLabel*> status_labels_;
    std::vector<int> row_ready_;          // -1/0/1 like `ready_`
    QLabel* summary_label_;
    QString summary_tone_;                // "" | "ok" | "missing"
};

// onboarding_report_card.py :: OnboardingReportCard.
class OnboardingReportCard : public QFrame {
    Q_OBJECT
public:
    explicit OnboardingReportCard(QWidget* parent = nullptr);

    // nullptr-equivalent: empty/falsy Json hides the card.
    void set_report(const domain::Json& report);

private:
    QLabel* source_label_;
    QLabel* summary_label_;
    QLabel* by_type_label_;
    QLabel* extent_label_;
    QLabel* issues_label_;
    QLabel* warnings_label_;
};

// start_guide_card.py :: StartGuideCard.
class StartGuideCard : public QFrame {
    Q_OBJECT
public:
    explicit StartGuideCard(QWidget* parent = nullptr);

    QPushButton* new_project_button() { return new_project_button_; }
    QPushButton* open_project_button() { return open_project_button_; }
    QPushButton* open_sample_button() { return open_sample_button_; }

Q_SIGNALS:
    void new_project_requested();
    void open_project_requested();
    void open_sample_requested();

private:
    QPushButton* new_project_button_;
    QPushButton* open_project_button_;
    QPushButton* open_sample_button_;
};

// result_summary.py :: ResultSummary.
class ResultSummary : public QFrame {
    Q_OBJECT
public:
    explicit ResultSummary(QWidget* parent = nullptr);

    // reports: [{rules: [str], issues: [..]}] (objects or dicts frozen to
    // Json by the caller); artifacts: [{format, output_path}].
    void update_state(const domain::Json& reports,
                      const domain::Json& artifacts);

private:
    void clear_export();
    void recolor(QLabel* label, const QString& token);

    QLabel* pass_label_;
    QLabel* warning_label_;
    QLabel* error_label_;
    QLabel* advisory_label_;
    QVBoxLayout* export_layout_;
};

}  // namespace pwb::ui_pages_data::qt
