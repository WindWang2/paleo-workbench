#pragma once

// UI-10 — Qt Widgets shells for the visualization side panels:
//   * visualization_summary_panel.py → VisualizationSummaryPanel (QFrame)
//   * visualization_trace_panel.py   → VisualizationTracePanel (QFrame)
//
// Asset entries / counts / trace views / export caps come from the
// Qt-free viz_page_state core; item reconciliation goes through
// ui_widgets::reconcile_widget_items (stable keys — no clear+rebuild).

#include <QFrame>
#include <QLabel>

#include <memory>
#include <pwb/ui_seqviz/viz_page_state.hpp>
#include <set>
#include <vector>

class QListWidget;
class QListWidgetItem;
class QPushButton;

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// visualization_summary_panel.py — "可视化总览": counts + keyed asset list.
// asset_selected carries the activated entry's VizRefSlice.
// ---------------------------------------------------------------------------
class VisualizationSummaryPanel : public QFrame {
    Q_OBJECT
public:
    explicit VisualizationSummaryPanel(QWidget* parent = nullptr);

    // update_state(resources, prediction_tasks, map_documents) parity.
    void update_state(const std::vector<ui_data_core::ResourceItem>&
                          resources,
                      const std::vector<PredictionTaskSlice>&
                          prediction_tasks,
                      const std::vector<MapDocSlice>& map_documents);

    QListWidget* asset_list() const { return asset_list_; }
    const std::vector<VizAssetEntry>& entries() const { return entries_; }

signals:
    void asset_selected(const pwb::ui_seqviz::VizRefSlice& ref);

private:
    void on_item_activated(QListWidgetItem* item);

    QLabel* prediction_count_value_ = nullptr;
    QLabel* map_count_value_ = nullptr;
    QLabel* resource_count_value_ = nullptr;
    QListWidget* asset_list_ = nullptr;
    std::vector<VizAssetEntry> entries_;
};

// ---------------------------------------------------------------------------
// visualization_trace_panel.py — "视图追踪": task/map/source/label/kind/
// path values + refresh + PNG/SVG/PDF export buttons.
// ---------------------------------------------------------------------------
class VisualizationTracePanel : public QFrame {
    Q_OBJECT
public:
    explicit VisualizationTracePanel(QWidget* parent = nullptr);

    // update_state(prediction_tasks, map_documents) parity — global
    // actives (last entry wins).
    void update_state(
        const std::vector<PredictionTaskSlice>& prediction_tasks,
        const std::vector<MapDocSlice>& map_documents);
    // update_ref(ref, payload) parity — nullptr ref resets to "—".
    void update_ref(const VizRefSlice* ref, const UiVizPayload* payload);
    // set_export_capabilities({"PNG","SVG","PDF"}) parity.
    void set_export_capabilities(const std::set<std::string>& formats);

    QPushButton* refresh_btn() const { return refresh_btn_; }
    QPushButton* export_png_btn() const { return export_btn_; }
    QPushButton* export_svg_btn() const { return export_svg_btn_; }
    QPushButton* export_pdf_btn() const { return export_pdf_btn_; }

signals:
    void refresh_requested();
    void export_requested(const QString& format);  // PNG | SVG | PDF

private:
    QLabel* task_value_ = nullptr;
    QLabel* map_value_ = nullptr;
    QLabel* source_value_ = nullptr;
    QLabel* label_value_ = nullptr;
    QLabel* kind_value_ = nullptr;
    QLabel* path_value_ = nullptr;
    QPushButton* refresh_btn_ = nullptr;
    QPushButton* export_btn_ = nullptr;
    QPushButton* export_svg_btn_ = nullptr;
    QPushButton* export_pdf_btn_ = nullptr;
};

}  // namespace pwb::ui_seqviz::qt
