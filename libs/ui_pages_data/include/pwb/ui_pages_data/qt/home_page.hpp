// UI-06 — home_page.py :: HomePage Qt shell.
//
// Composition: map centerpiece + right onboarding column (start guide /
// onboarding report), module-relationship diagram, bottom row (activity /
// contract / completeness). Map canvas, workflow-contract panel, legend,
// empty-state and the domain-signature seam are injected.
#pragma once

#include <QPointF>
#include <QStackedWidget>
#include <QWidget>

#include <functional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_pages_data/home_model.hpp>
#include <pwb/ui_pages_data/module_map.hpp>

class QFrame;
class QHBoxLayout;
class QLabel;
class QSplitter;

namespace pwb::ui_pages_data::qt {

class DataCompletenessCard;
class ModuleRelationshipWidget;
class OnboardingReportCard;
class RecentActivityCard;
class StartGuideCard;

// Map canvas seam (unified_map_canvas / QgisCanvasShim — other slice).
// Coordinates are (x, y) map doubles; screen coords in pixels.
class HomeMapCanvasApi : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    virtual void set_layer_snapshot(const pwb::domain::Json& snapshot) = 0;
    virtual void set_extent(const pwb::domain::Json& extent) = 0;
    virtual QPointF map_to_screen(double x, double y, bool* ok) = 0;
    virtual void shutdown() {}
    // overlay provider seam — called by the canvas each repaint.
    void set_overlay_provider(std::function<pwb::domain::Json()> fn) {
        overlay_provider_ = std::move(fn);
    }
    pwb::domain::Json overlay_state() const {
        return overlay_provider_ ? overlay_provider_()
                                 : pwb::domain::Json::object();
    }
Q_SIGNALS:
    void map_clicked(double x, double y);

private:
    std::function<pwb::domain::Json()> overlay_provider_;
};

// WorkflowContractPanel seam (other slice).
class WorkflowContractPanelApi : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    virtual void set_project(void* project) = 0;
    virtual void set_contract_id(const QString& contract_id) = 0;
    virtual QWidget* dev_button() = 0;
};

class HomePage : public QWidget {
    Q_OBJECT
public:
    explicit HomePage(QWidget* parent = nullptr);

    // Seams.
    void set_map_canvas(HomeMapCanvasApi* canvas);
    void set_contract_panel(WorkflowContractPanelApi* panel);
    void set_legend_widget(QWidget* legend);
    // domain_signature(project) — opaque signature; equal Jsons mean
    // "unchanged" (the Python object-identity/tuple signature collapses
    // to a comparable value here).
    void set_domain_signature_fn(
        std::function<pwb::domain::Json(void* project)> fn);
    // build_workarea_map_snapshot(project) → snapshot Json; the canvas
    // and pick path both read it.
    void set_snapshot_fn(
        std::function<pwb::domain::Json(void* project)> fn);
    // workarea_view_extent(snapshot) → extent Json or null.
    void set_extent_fn(
        std::function<pwb::domain::Json(const pwb::domain::Json&)> fn);
    // snapshot_has_map_content(snapshot).
    void set_has_content_fn(
        std::function<bool(const pwb::domain::Json&)> fn);
    // workarea_crs_warnings(project) → warning strings.
    void set_crs_warnings_fn(
        std::function<std::vector<std::string>(void* project)> fn);

    void shutdown_workers();
    // update_state(state, steps, project): steps carry step_type+status
    // (the two fields the Python reads off step objects).
    void update_state(const pwb::domain::Json& state,
                      const std::vector<ui_pages_data::StepLike>& steps,
                      void* project = nullptr);

    StartGuideCard* start_guide_card() { return start_guide_card_; }
    OnboardingReportCard* onboarding_report_card() {
        return onboarding_report_card_;
    }
    RecentActivityCard* activity_card() { return activity_card_; }
    DataCompletenessCard* completeness_card() {
        return completeness_card_;
    }
    ModuleRelationshipWidget* relationship_widget() {
        return relationship_widget_;
    }
    QLabel* crs_warning_label() { return crs_warning_label_; }
    QStackedWidget* map_stack() { return map_stack_; }

Q_SIGNALS:
    void navigation_requested(int index);
    void new_project_requested();
    void open_project_requested();
    void open_sample_requested();
    void well_activated(const QString& well_id);

private:
    QFrame* build_empty_state();
    pwb::domain::Json map_overlay_state();
    void refresh_map(void* project);
    void update_crs_banner(void* project);
    void on_map_clicked(double x, double y);
    // Well pick points from the snapshot (wells + flagged layers, in
    // Python's iteration order).
    std::vector<ui_pages_data::WellPickPoint> screen_points(
        const pwb::domain::Json& snapshot);

    void* project_ = nullptr;
    pwb::domain::Json map_snapshot_;
    pwb::domain::Json map_signature_;  // null = unbound sentinel
    bool signature_bound_ = false;

    QStackedWidget* map_stack_;
    QHBoxLayout* bottom_layout_ = nullptr;
    HomeMapCanvasApi* map_canvas_ = nullptr;
    QLabel* crs_warning_label_;
    QWidget* side_column_;
    StartGuideCard* start_guide_card_;
    OnboardingReportCard* onboarding_report_card_;
    ModuleRelationshipWidget* relationship_widget_;
    WorkflowContractPanelApi* contract_panel_ = nullptr;
    RecentActivityCard* activity_card_;
    DataCompletenessCard* completeness_card_;

    std::function<pwb::domain::Json(void*)> domain_signature_fn_;
    std::function<pwb::domain::Json(void*)> snapshot_fn_;
    std::function<pwb::domain::Json(const pwb::domain::Json&)> extent_fn_;
    std::function<bool(const pwb::domain::Json&)> has_content_fn_;
    std::function<std::vector<std::string>(void*)> crs_warnings_fn_;
};

}  // namespace pwb::ui_pages_data::qt
