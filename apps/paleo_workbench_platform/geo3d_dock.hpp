#pragma once

// CONV-GEO3D — the native 3D geomodel viewer dock (platform wiring).
//
// Self-contained composition root for the C++ geo-viz runtime: the Qt6
// viewport + the workspace controller + the minimal tool surface (fit /
// clip sliders / measurement modes / object visibility / screenshot). All
// the Python page glue this replaces (geo3d_workspace.py + the 3D half of
// geological_modeling_3d_page.py) lives in the controller; this dock is
// product wiring only. Selection of wells is re-broadcast through
// well_selected() — the 2D map synchronization seam.

#include <QDockWidget>

#include <memory>

#include <pwb/geo3d_viz/geo3d_viewport_widget.hpp>
#include <pwb/geo3d_viz/workspace_controller.hpp>

class QListWidget;
class QLabel;
class QCheckBox;
class QSlider;
class QComboBox;

class Geo3DDock : public QDockWidget {
    Q_OBJECT

public:
    explicit Geo3DDock(QWidget* parent = nullptr);

    Geo3DViewportWidget* viewport() const { return viewport_; }
    Geo3DWorkspaceController* controller() const { return controller_.get(); }

signals:
    // 2D map synchronization seam (selected well name).
    void well_selected(const QString& well_name);

private slots:
    void refresh_objects();
    void show_status(const QString& message);

private:
    void build_toolbar(QWidget* toolbar);
    void sync_clip_ui();

    Geo3DViewportWidget* viewport_ = nullptr;
    std::unique_ptr<Geo3DWorkspaceController> controller_;
    QListWidget* object_list_ = nullptr;
    QLabel* status_label_ = nullptr;
    QCheckBox* clip_enabled_[3] = {nullptr, nullptr, nullptr};
    QSlider* clip_slider_[3] = {nullptr, nullptr, nullptr};
    QCheckBox* clip_invert_[3] = {nullptr, nullptr, nullptr};
    QComboBox* measure_combo_ = nullptr;
};
