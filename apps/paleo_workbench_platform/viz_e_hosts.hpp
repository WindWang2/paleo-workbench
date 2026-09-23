#pragma once

// viz_e_hosts — VIZ-E preview line: well-head xy_scatter and horizon
// surface host widgets for the paleo workbench platform.
//
// Rendering contracts are 1:1 with the frozen Python backends
// (geoviz/previews/dat.py @0885195, gitlink
// 08851951f3bbc0beb90886adf52e1928f4383c16):
//   * XyScatterHost::show_well_head mirrors XYScatterBackend.render
//     (dat.py:1036-1047): clear → "X{ (unit)}"/"Y{ (unit)}" axis labels
//     from payload.coordinate_units → one scatter series named by the
//     preview title → autofit. Python has no per-point labels here and no
//     equal-aspect lock; both are task-mandated workbench additions
//     (labels = well names, set_equal_aspect(true) for location maps).
//   * SurfaceHost::show_surface mirrors HorizonSurfaceBackend.render
//     (dat.py:1128-1135): set_grid_data(grid_x, grid_y, grid_z, levels) →
//     autofit — no explicit clear (set_grid_data rebinds the grid).
//   * The provenance line reuses the XYScatterBackend.prepare warning
//     vocabulary (dat.py:979-995: "SourceCRS 未声明", "坐标单位未知",
//     skipped-row counts) plus the summary rows ("有效井数", "源记录",
//     dat.py:1000-1003).
//   * The QToolBar export chrome (导出 SVG / 导出 PDF / 重置视图) is
//     workbench-side; xy_scatter exports go through PwbPlotCanvas::exportTo
//     (QGIS Plot), surface exports through the retained domain
//     SurfaceWidget port.

#include <QString>
#include <QWidget>
#include <vector>

#include "viz_e_dat_preview.hpp"

class QLabel;
class QToolBar;

namespace pwb::viz_charts::qt {
class ColorbarWidget;
class SurfaceWidget;
}  // namespace pwb::viz_charts::qt

namespace pwb::qgis_plot {
class PwbPlotCanvas;
class PwbScatterPlot;
class PwbPlotToolIdentify;
}  // namespace pwb::qgis_plot

class QActionGroup;
class QgsPlotToolPan;
class QgsPlotToolZoom;

namespace pwb::viz_e {

// 井位 xy_scatter 宿主：QGIS Plot 画布 + 工具栏
// （pan/zoom/identify 经 QGIS plot tools，导出 SVG / 导出 PDF / 重置视图）。
// The generic viz_charts PlotWidget is retired here; interaction state lives
// in QgsPlotTool instances on the canvas, not in a second state machine.
class XyScatterHost : public QWidget {
    Q_OBJECT
public:
    explicit XyScatterHost(QWidget* parent = nullptr);

    // Renders one well-head preview. Title label shows the preview title
    // plus a provenance summary (CRS / units / valid-vs-total records;
    // "CRS 未声明" when undeclared).
    void show_well_head(const WellHeadPreview& data, const QString& title);

    // 诚实降级：消息标签占满整个宿主区域。
    void show_unavailable(const QString& reason);

    pwb::qgis_plot::PwbPlotCanvas* canvas() const;

    // 测试直连导出（不经对话框）；成功写入文件返回 true。不 emit
    // export_requested（该信号只属于用户工具栏导出）。
    bool export_svg_to(const QString& path);
    bool export_pdf_to(const QString& path);

Q_SIGNALS:
    // 用户经工具栏导出成功后发出。
    void export_requested(const QString& path);

private:
    void run_toolbar_export(bool svg);

    QLabel* title_label_ = nullptr;
    QLabel* message_label_ = nullptr;
    QToolBar* toolbar_ = nullptr;
    QActionGroup* tool_group_ = nullptr;
    pwb::qgis_plot::PwbPlotCanvas* canvas_ = nullptr;
    pwb::qgis_plot::PwbScatterPlot* scatter_ = nullptr;  // owned by the item
    QgsPlotToolPan* pan_tool_ = nullptr;
    QgsPlotToolZoom* zoom_tool_ = nullptr;
    pwb::qgis_plot::PwbPlotToolIdentify* identify_tool_ = nullptr;
};

// 层面 surface 宿主（与 XyScatterHost 同构）：SurfaceWidget + 工具栏 +
// 底部 ColorbarWidget/来源摘要行。
class SurfaceHost : public QWidget {
    Q_OBJECT
public:
    explicit SurfaceHost(QWidget* parent = nullptr);

    struct SurfaceData {
        std::vector<double> grid_x, grid_y;
        std::vector<float> grid_z;          // row-major ny*nx, NaN = nodata
        std::vector<double> levels;
        QString title, provenance;          // provenance 多行摘要（因子名/方法/单位/CRS/统计/来源资产）
    };

    void show_surface(const SurfaceData& data);
    void show_unavailable(const QString& reason);

    pwb::viz_charts::qt::SurfaceWidget* surface() const;
    // Provenance text of the last shown surface (empty when unavailable).
    QString provenance() const;

    bool export_svg_to(const QString& path);
    bool export_pdf_to(const QString& path);

Q_SIGNALS:
    void export_requested(const QString& path);

private:
    void run_toolbar_export(bool svg);

    QLabel* title_label_ = nullptr;
    QLabel* message_label_ = nullptr;
    QLabel* provenance_label_ = nullptr;
    QToolBar* toolbar_ = nullptr;
    pwb::viz_charts::qt::SurfaceWidget* surface_ = nullptr;
    bool has_surface_ = false;
    pwb::viz_charts::qt::ColorbarWidget* colorbar_ = nullptr;
};

}  // namespace pwb::viz_e
