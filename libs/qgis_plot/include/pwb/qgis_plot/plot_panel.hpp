// QGIS-plot convergence — the stock panel chrome.
//
// PwbPlotPanel is the drop-in replacement for the retired viz_charts_qt
// widgets: one PwbPlotCanvas + a tool-action toolbar wired to QGIS plot tools
// (pan / marquee zoom / x-axis zoom / identify) + autofit + export actions.
// State lives in the canvas and the QgsPlotTool instances — the panel only
// composes; it holds no second plot state machine.
#pragma once

#include <memory>

#include <QLabel>
#include <QStackedWidget>
#include <QToolBar>
#include <QWidget>

#include "pwb/qgis_plot/series_binding.hpp"

class QAction;
class QgsPlotToolPan;
class QgsPlotToolZoom;

namespace pwb::qgis_plot {

class PwbPlotCanvas;
class PwbPlotToolIdentify;
class PwbPlotToolLasso;
class PwbPlotToolXAxisZoom;

class PwbPlotPanel : public QWidget {
    Q_OBJECT
public:
    explicit PwbPlotPanel(QWidget* parent = nullptr);
    ~PwbPlotPanel() override;

    PwbPlotCanvas* canvas() const { return canvas_; }

    // Chrome.
    void setTitle(const QString& title);
    void setProvenance(const QString& provenance);  // read-only caption text
    void showPlot();                                // ready state
    void showUnavailable(const QString& reason);    // honest-failure state

    // Tools — created lazily; consumers may connect their signals. All are
    // children of the canvas.
    PwbPlotToolIdentify* identifyTool();
    PwbPlotToolLasso* lassoTool();
    // The default tool when nothing else is active.
    void activatePan();
    void activateIdentify();
    void activateLasso();

    // Export actions are wired to canvas()->exportTo() with a file dialog.
    void addExportActions(QToolBar* extra_bar = nullptr);

Q_SIGNALS:
    void pointClicked(const pwb::qgis_plot::PointHit& hit);
    void viewChanged(double xmin, double xmax, double ymin, double ymax);

private:
    void exportTo(const QString& filter, const QString& suffix);

    PwbPlotCanvas* canvas_ = nullptr;
    QToolBar* toolbar_ = nullptr;
    QLabel* title_ = nullptr;
    QLabel* provenance_ = nullptr;
    QStackedWidget* stack_ = nullptr;
    QLabel* unavailable_ = nullptr;

    QAction* act_pan_ = nullptr;
    QAction* act_zoom_ = nullptr;
    QAction* act_zoom_x_ = nullptr;
    QAction* act_identify_ = nullptr;
    QAction* act_lasso_ = nullptr;
    class QActionGroup* tool_group_ = nullptr;

    QgsPlotToolPan* pan_tool_ = nullptr;
    QgsPlotToolZoom* zoom_tool_ = nullptr;
    PwbPlotToolIdentify* identify_tool_ = nullptr;
    PwbPlotToolLasso* lasso_tool_ = nullptr;
    PwbPlotToolXAxisZoom* zoom_x_tool_ = nullptr;
};

}  // namespace pwb::qgis_plot
