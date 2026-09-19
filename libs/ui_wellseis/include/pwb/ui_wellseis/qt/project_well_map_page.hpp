#pragma once

// UI-09 — ProjectWellMapPage Qt shell (project_well_map_page.py).
// Left: search + filterable well list. Center: toolbar (缩放全部 / 缩放选中
// / 复位 / 参考图层 / 井名标注 + CRS + hover labels), the map surface
// (injected IWellMapSurface or built-in WellMapCanvas), CRS-warning banner,
// empty state. Semantics live in well_map.hpp — this is the Qt binding.

#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include <QWidget>

#include <pwb/ui_wellseis/slices.hpp>
#include <pwb/ui_wellseis/well_map.hpp>

class QLabel;
class QLineEdit;
class QListView;
class QPushButton;
class QSortFilterProxyModel;

namespace pwb::ui_wellseis::qt {

class IWellMapSurface;
class StringTableModel;
class WellMapCanvas;

class ProjectWellMapPage : public QWidget {
    Q_OBJECT
public:
    // `surface` may be nullptr → the built-in WellMapCanvas is used
    // (geo-viz fallback parity: a missing engine never blanks the page —
    // the fallback surface is provided, like Python's own fallback).
    explicit ProjectWellMapPage(QWidget* parent = nullptr,
                                IWellMapSurface* surface = nullptr);
    ~ProjectWellMapPage() override;

    // refresh_domain parity — rebuilds cached arrays + series.
    void set_project(const ProjectSlice& project);
    void clear();

    // Selection (select_well/select_wells parity — ids only).
    void select_well(const std::string& well_id, bool zoom = false,
                     bool emit_signal = false);
    void select_wells(const std::vector<std::string>& well_ids,
                      bool zoom = false, bool emit_single = false);
    [[nodiscard]] std::vector<std::string> selected_well_ids() const;
    void clear_selection();

    // Zoom helpers.
    void zoom_to_well(const std::string& well_id, double zoom_factor = 8.0);
    void zoom_to_selection();
    void zoom_to_all();
    void focus_well(const std::string& well_id);

    // Cross-view spatial cursor (scenario B).
    void show_spatial_cursor(double x, double y);
    void clear_spatial_cursor();
    [[nodiscard]] std::optional<std::pair<double, double>>
    spatial_cursor_position() const;

    // Reference-layer rings (host-side GDAL/service fetch is deferred; the
    // page applies the MAX_REFERENCE_VERTICES budget while drawing).
    void set_reference_rings(
        const std::vector<std::vector<std::pair<double, double>>>& rings);

    [[nodiscard]] IWellMapSurface* surface() const;
    [[nodiscard]] QString crs_warning_text() const;
    [[nodiscard]] QString crs_label_text() const;
    [[nodiscard]] QString coord_label_text() const;
    [[nodiscard]] bool empty_state_visible() const;
    [[nodiscard]] int well_list_count() const;

signals:
    void well_selected(const QString& well_id);
    void well_activated(const QString& well_id);

private:
    void rebuild_scene();
    void sync_list_selection();
    void on_list_selection_changed();
    void on_point_hovered(const std::string& series, int index, double x,
                          double y);
    void on_point_clicked(const std::string& series, int index, double x,
                          double y);
    [[nodiscard]] std::optional<std::string> well_id_for(
        const std::string& series, int index) const;
    [[nodiscard]] std::string display_name_for(const std::string& series,
                                               int index) const;
    // _list_model.row_for_well parity — list row or -1.
    [[nodiscard]] int model_row_for_well(const std::string& well_id) const;

    ProjectSlice project_;
    WellMapModel model_;
    std::set<std::string> selected_ids_;
    std::optional<std::pair<double, double>> spatial_cursor_;
    std::vector<std::vector<std::pair<double, double>>> reference_rings_;

    IWellMapSurface* surface_ = nullptr;      // borrowed or owned below
    std::unique_ptr<WellMapCanvas> owned_canvas_;
    QLineEdit* search_box_ = nullptr;
    QListView* well_list_ = nullptr;
    StringTableModel* list_model_ = nullptr;
    QSortFilterProxyModel* proxy_ = nullptr;
    std::vector<std::string> list_row_ids_;   // source row -> well id
    QPushButton* btn_zoom_all_ = nullptr;
    QPushButton* btn_zoom_selection_ = nullptr;
    QPushButton* btn_reset_ = nullptr;
    QPushButton* btn_reference_ = nullptr;
    QPushButton* btn_labels_ = nullptr;
    QLabel* crs_label_ = nullptr;
    QLabel* crs_warning_label_ = nullptr;
    QLabel* coord_label_ = nullptr;
    QLabel* empty_label_ = nullptr;
    bool syncing_selection_ = false;
};

}  // namespace pwb::ui_wellseis::qt
