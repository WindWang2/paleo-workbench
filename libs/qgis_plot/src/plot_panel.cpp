#include "pwb/qgis_plot/plot_panel.hpp"

#include <QActionGroup>
#include <QFileDialog>
#include <QVBoxLayout>

#include <qgsplottoolpan.h>
#include <qgsplottoolzoom.h>

#include "pwb/qgis_plot/plot_canvas.hpp"
#include "pwb/qgis_plot/plot_tools.hpp"

namespace pwb::qgis_plot {

PwbPlotPanel::PwbPlotPanel(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(2);

    toolbar_ = new QToolBar(this);
    toolbar_->setIconSize(QSize(16, 16));
    title_ = new QLabel(this);
    title_->setStyleSheet(QStringLiteral("font-weight: 600;"));
    title_->setVisible(false);
    provenance_ = new QLabel(this);
    provenance_->setStyleSheet(QStringLiteral("color: #777; font-size: 11px;"));
    provenance_->setVisible(false);
    toolbar_->addWidget(title_);
    toolbar_->addWidget(provenance_);
    layout->addWidget(toolbar_);

    tool_group_ = new QActionGroup(this);
    tool_group_->setExclusive(true);

    canvas_ = new PwbPlotCanvas(this);

    stack_ = new QStackedWidget(this);
    stack_->addWidget(canvas_);
    unavailable_ = new QLabel(this);
    unavailable_->setAlignment(Qt::AlignCenter);
    unavailable_->setWordWrap(true);
    unavailable_->setStyleSheet(QStringLiteral("color: #777;"));
    stack_->addWidget(unavailable_);
    stack_->setCurrentWidget(canvas_);
    layout->addWidget(stack_, 1);

    // Tool actions — exclusive; state lives in the QGIS tools themselves.
    auto make_tool_action = [this](const QString& text, const QString& tip) {
        QAction* a = toolbar_->addAction(text);
        a->setCheckable(true);
        a->setToolTip(tip);
        a->setActionGroup(tool_group_);
        return a;
    };

    // Chrome matches the platform's zh-CN UI language.
    act_identify_ = make_tool_action(tr("选点"), tr("单击或框选拾取图上点"));
    act_pan_ = make_tool_action(tr("平移"), tr("拖拽平移视图"));
    act_zoom_ = make_tool_action(tr("框选缩放"), tr("拖框放大;单击放大"));
    act_zoom_x_ = make_tool_action(tr("横向缩放"), tr("仅沿 X 轴框选缩放"));
    act_lasso_ = make_tool_action(tr("套索"), tr("自由圈选图点"));

    connect(act_identify_, &QAction::triggered, this,
            &PwbPlotPanel::activateIdentify);
    connect(act_pan_, &QAction::triggered, this, &PwbPlotPanel::activatePan);
    connect(act_zoom_, &QAction::triggered, this, [this] {
        if (!zoom_tool_)
            zoom_tool_ = new QgsPlotToolZoom(canvas_);
        canvas_->setTool(zoom_tool_);
    });
    connect(act_zoom_x_, &QAction::triggered, this, [this] {
        if (!zoom_x_tool_)
            zoom_x_tool_ = new PwbPlotToolXAxisZoom(canvas_);
        canvas_->setTool(zoom_x_tool_);
    });
    connect(act_lasso_, &QAction::triggered, this, &PwbPlotPanel::activateLasso);

    toolbar_->addSeparator();
    QAction* fit = toolbar_->addAction(tr("适应"));
    connect(fit, &QAction::triggered, canvas_, &PwbPlotCanvas::zoomFull);
    toolbar_->addSeparator();
    addExportActions();

    connect(canvas_, &PwbPlotCanvas::pointClicked, this,
            &PwbPlotPanel::pointClicked);
    connect(canvas_, &PwbPlotCanvas::viewChanged, this,
            &PwbPlotPanel::viewChanged);

    activatePan();
    act_pan_->setChecked(true);
}

PwbPlotPanel::~PwbPlotPanel() = default;

void PwbPlotPanel::setTitle(const QString& title) {
    title_->setText(title);
    title_->setVisible(!title.isEmpty());
}

void PwbPlotPanel::setProvenance(const QString& provenance) {
    provenance_->setText(provenance);
    provenance_->setVisible(!provenance.isEmpty());
}

void PwbPlotPanel::showPlot() {
    stack_->setCurrentWidget(canvas_);
}

void PwbPlotPanel::showUnavailable(const QString& reason) {
    unavailable_->setText(reason);
    stack_->setCurrentWidget(unavailable_);
}

PwbPlotToolIdentify* PwbPlotPanel::identifyTool() {
    if (!identify_tool_) {
        identify_tool_ = new PwbPlotToolIdentify(canvas_);
        connect(identify_tool_, &PwbPlotToolIdentify::pointPicked, this,
                &PwbPlotPanel::pointClicked);
    }
    return identify_tool_;
}

PwbPlotToolLasso* PwbPlotPanel::lassoTool() {
    if (!lasso_tool_)
        lasso_tool_ = new PwbPlotToolLasso(canvas_);
    return lasso_tool_;
}

void PwbPlotPanel::activatePan() {
    if (!pan_tool_)
        pan_tool_ = new QgsPlotToolPan(canvas_);
    canvas_->setTool(pan_tool_);
}

void PwbPlotPanel::activateIdentify() {
    canvas_->setTool(identifyTool());
}

void PwbPlotPanel::activateLasso() {
    canvas_->setTool(lassoTool());
}

void PwbPlotPanel::addExportActions(QToolBar* extra_bar) {
    QToolBar* bar = extra_bar ? extra_bar : toolbar_;
    auto add = [this, bar](const QString& text, const QString& suffix,
                           const QString& filter) {
        QAction* a = bar->addAction(text);
        connect(a, &QAction::triggered, this,
                [this, filter, suffix] { exportTo(filter, suffix); });
    };
    add(tr("PNG"), QStringLiteral("png"), tr("PNG images (*.png)"));
    add(tr("SVG"), QStringLiteral("svg"), tr("SVG images (*.svg)"));
    add(tr("PDF"), QStringLiteral("pdf"), tr("PDF documents (*.pdf)"));
}

void PwbPlotPanel::exportTo(const QString& filter, const QString& suffix) {
    const QString path = QFileDialog::getSaveFileName(
        this, tr("Export plot"), QString(), filter);
    if (path.isEmpty())
        return;
    QString final_path = path;
    if (!final_path.endsWith(QLatin1Char('.') + suffix, Qt::CaseInsensitive))
        final_path += QLatin1Char('.') + suffix;
    canvas_->exportTo(final_path);
}

}  // namespace pwb::qgis_plot
