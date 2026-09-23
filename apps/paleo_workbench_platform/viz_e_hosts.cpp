// viz_e_hosts.cpp — implementation half of the VIZ-E preview hosts.
// See viz_e_hosts.hpp for the frozen-source map (geoviz/previews/dat.py
// @0885195, gitlink 08851951f3bbc0beb90886adf52e1928f4383c16).
//
// Export contract shared by both hosts: the canvas export call returns
// bool; success additionally requires the target file to exist with a
// non-zero size (QFile::exists + QFileInfo::size > 0).

#include "viz_e_hosts.hpp"

#include <QAction>
#include <QActionGroup>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QToolBar>
#include <QVBoxLayout>

#include <pwb/viz_charts/qt/colorbar_widget.hpp>
#include <pwb/viz_charts/qt/surface_widget.hpp>

#include <pwb/qgis_plot/domain_plots.hpp>
#include <pwb/qgis_plot/plot_canvas.hpp>
#include <pwb/qgis_plot/plot_item.hpp>
#include <pwb/qgis_plot/plot_tools.hpp>
#include <pwb/qgis_plot/series_binding.hpp>

#include <qgsplot.h>
#include <qgsplottoolpan.h>
#include <qgsplottoolzoom.h>

#include <algorithm>
#include <functional>
#include <memory>
#include <utility>

namespace pwb::viz_e {
namespace {

// 成功判定：QFile::exists + QFileInfo::size > 0。
bool export_file_written(const QString& path) {
    const QFileInfo info(path);
    return info.exists() && info.size() > 0;
}

QToolBar* make_export_toolbar(QWidget* parent, QWidget* host_context,
                              const std::function<void(bool)>& on_export,
                              const std::function<void()>& on_reset) {
    auto* toolbar = new QToolBar(parent);
    toolbar->setObjectName(QStringLiteral("viz-e-preview-toolbar"));
    auto* svg_action = toolbar->addAction(QStringLiteral("导出 SVG"));
    auto* pdf_action = toolbar->addAction(QStringLiteral("导出 PDF"));
    toolbar->addSeparator();
    auto* reset_action = toolbar->addAction(QStringLiteral("重置视图"));
    QObject::connect(svg_action, &QAction::triggered, host_context,
                     [on_export] { on_export(true); });
    QObject::connect(pdf_action, &QAction::triggered, host_context,
                     [on_export] { on_export(false); });
    QObject::connect(reset_action, &QAction::triggered, host_context,
                     [on_reset] { on_reset(); });
    return toolbar;
}

QString ask_export_path(QWidget* parent, bool svg) {
    return QFileDialog::getSaveFileName(
        parent, svg ? QStringLiteral("导出 SVG") : QStringLiteral("导出 PDF"),
        QString(),
        svg ? QStringLiteral("SVG (*.svg)") : QStringLiteral("PDF (*.pdf)"));
}

}  // namespace

// ---- XyScatterHost -----------------------------------------------------------

namespace {
// A chart host that never became visible (hidden stack page, headless
// export) has no laid-out size; the explicit-canvas export overloads then
// fall back to a default canvas instead of a zero-height file. Visible
// widgets keep their live size.
QSize export_canvas_of(const QWidget* chart) {
    if (chart != nullptr && chart->width() > 0 && chart->height() > 0) {
        return chart->size();
    }
    return QSize(900, 600);
}
}  // namespace

XyScatterHost::XyScatterHost(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("viz-e-xy-scatter-host"));
    auto* layout = new QVBoxLayout(this);
    toolbar_ = make_export_toolbar(
        this, this, [this](bool svg) { run_toolbar_export(svg); },
        [this] { canvas_->zoomFull(); });

    // Plot tools are stock QGIS: one state machine, owned by the canvas.
    tool_group_ = new QActionGroup(this);
    tool_group_->setExclusive(true);
    auto* pan_action =
        toolbar_->addAction(QStringLiteral("平移"));
    pan_action->setCheckable(true);
    pan_action->setChecked(true);
    pan_action->setActionGroup(tool_group_);
    auto* zoom_action = toolbar_->addAction(QStringLiteral("框选缩放"));
    zoom_action->setCheckable(true);
    zoom_action->setActionGroup(tool_group_);
    auto* identify_action = toolbar_->addAction(QStringLiteral("选点"));
    identify_action->setCheckable(true);
    identify_action->setActionGroup(tool_group_);

    title_label_ = new QLabel(this);
    title_label_->setWordWrap(true);
    canvas_ = new pwb::qgis_plot::PwbPlotCanvas(this);
    canvas_->setEqualAspect(true);  // location map convention
    auto scatter = std::make_unique<pwb::qgis_plot::PwbScatterPlot>();
    scatter_ = scatter.get();
    canvas_->addPlot(std::move(scatter));
    message_label_ = new QLabel(this);
    message_label_->setWordWrap(true);
    message_label_->setAlignment(Qt::AlignCenter);
    message_label_->hide();
    layout->addWidget(toolbar_);
    layout->addWidget(title_label_);
    layout->addWidget(canvas_, 1);
    layout->addWidget(message_label_, 1);

    QObject::connect(pan_action, &QAction::triggered, this, [this] {
        if (!pan_tool_)
            pan_tool_ = new QgsPlotToolPan(canvas_);
        canvas_->setTool(pan_tool_);
    });
    QObject::connect(zoom_action, &QAction::triggered, this, [this] {
        if (!zoom_tool_)
            zoom_tool_ = new QgsPlotToolZoom(canvas_);
        canvas_->setTool(zoom_tool_);
    });
    QObject::connect(identify_action, &QAction::triggered, this, [this] {
        if (!identify_tool_)
            identify_tool_ =
                new pwb::qgis_plot::PwbPlotToolIdentify(canvas_);
        canvas_->setTool(identify_tool_);
    });
    pan_action->trigger();
}

void XyScatterHost::show_well_head(const WellHeadPreview& data,
                                   const QString& title) {
    message_label_->hide();
    toolbar_->show();
    title_label_->show();
    canvas_->show();

    // dat.py:1039-1045 — clear, axis labels with the declared unit suffix.
    const QString unit_suffix =
        data.coordinate_units.empty()
            ? QString()
            : QStringLiteral(" (%1)").arg(
                  QString::fromStdString(data.coordinate_units));

    // dat.py:1046 — one scatter series named by the preview title; well-name
    // labels stay (workbench addition), now drawn by PwbScatterPlot.
    QgsPlotData plot_data;
    auto* series = new QgsXyPlotSeries();
    series->setName(title);
    QList<std::pair<double, double>> points;
    QStringList labels;
    QVector<QString> point_ids;
    points.reserve(static_cast<qsizetype>(data.records.size()));
    labels.reserve(static_cast<qsizetype>(data.records.size()));
    for (const WellHeadRecord& record : data.records) {
        points.append({record.x, record.y});
        labels.append(QString::fromStdString(record.name));
        point_ids.append(QString::fromStdString(record.name));
    }
    series->setData(points);
    plot_data.addSeries(series);

    auto* item = canvas_->plotItems().value(0);
    item->setPlotData(std::move(plot_data));
    item->setAxisTitles(QStringLiteral("X%1").arg(unit_suffix),
                        QStringLiteral("Y%1").arg(unit_suffix));
    scatter_->setSeriesColors({QColor(64, 156, 255)});
    scatter_->setMarkerSizePx(6.0);
    scatter_->setPointLabels(0, labels);

    pwb::qgis_plot::SeriesBinding binding;
    binding.series_id = QStringLiteral("xy_scatter");
    binding.name = title;
    binding.axis_role = QStringLiteral("xy");
    binding.style_role = QStringLiteral("scatter");
    binding.unit = QString::fromStdString(data.coordinate_units);
    binding.point_domain_ids = point_ids;
    canvas_->setSeriesBindings(0, {binding});

    canvas_->zoomFull();

    // Provenance summary: dat.py:979-995 warning vocabulary plus the
    // dat.py:1000-1003 summary rows.
    QStringList parts;
    parts << (data.source_crs.empty()
                  ? QStringLiteral("CRS 未声明")
                  : QStringLiteral("SourceCRS: %1").arg(
                        QString::fromStdString(data.source_crs)));
    parts << (data.coordinate_units.empty()
                  ? QStringLiteral("坐标单位未知")
                  : QStringLiteral("坐标单位: %1").arg(
                        QString::fromStdString(data.coordinate_units)));
    parts << QStringLiteral("有效井位 %1/%2")
                 .arg(data.valid_records)
                 .arg(data.total_records);
    if (data.skipped_records > 0) {
        parts << QStringLiteral("%1 行已跳过").arg(data.skipped_records);
    }
    title_label_->setText(
        QStringLiteral("<b>%1</b> · %2")
            .arg(title.toHtmlEscaped(), parts.join(QStringLiteral(" · "))));
}

void XyScatterHost::show_unavailable(const QString& reason) {
    toolbar_->hide();
    title_label_->hide();
    canvas_->hide();
    message_label_->setText(reason);
    message_label_->show();
}

pwb::qgis_plot::PwbPlotCanvas* XyScatterHost::canvas() const {
    return canvas_;
}

bool XyScatterHost::export_svg_to(const QString& path) {
    if (path.isEmpty()) {
        return false;
    }
    if (!canvas_->exportTo(path, export_canvas_of(canvas_))) {
        return false;
    }
    return export_file_written(path);
}

bool XyScatterHost::export_pdf_to(const QString& path) {
    if (path.isEmpty()) {
        return false;
    }
    if (!canvas_->exportTo(path, export_canvas_of(canvas_))) {
        return false;
    }
    return export_file_written(path);
}

void XyScatterHost::run_toolbar_export(bool svg) {
    const QString path = ask_export_path(this, svg);
    if (path.isEmpty()) {
        return;  // 用户取消对话框
    }
    if (svg ? export_svg_to(path) : export_pdf_to(path)) {
        Q_EMIT export_requested(path);
    }
}

// ---- SurfaceHost ---------------------------------------------------------------

SurfaceHost::SurfaceHost(QWidget* parent) : QWidget(parent) {
    setObjectName(QStringLiteral("viz-e-surface-host"));
    auto* layout = new QVBoxLayout(this);
    toolbar_ = make_export_toolbar(
        this, this, [this](bool svg) { run_toolbar_export(svg); },
        // SurfaceWidget has no reset_view(); autofit() is its exact-view
        // reset (dat.py:1135 fits the grid min/max with no padding).
        [this] { surface_->autofit(); });
    title_label_ = new QLabel(this);
    title_label_->setWordWrap(true);
    surface_ = new pwb::viz_charts::qt::SurfaceWidget(this);
    message_label_ = new QLabel(this);
    message_label_->setWordWrap(true);
    message_label_->setAlignment(Qt::AlignCenter);
    message_label_->hide();

    auto* bottom_row = new QHBoxLayout();
    colorbar_ = new pwb::viz_charts::qt::ColorbarWidget(this);
    provenance_label_ = new QLabel(this);
    provenance_label_->setWordWrap(true);
    provenance_label_->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
    bottom_row->addWidget(colorbar_);
    bottom_row->addWidget(provenance_label_, 1);

    layout->addWidget(toolbar_);
    layout->addWidget(title_label_);
    layout->addWidget(surface_, 1);
    layout->addLayout(bottom_row);
    layout->addWidget(message_label_, 1);
}

void SurfaceHost::show_surface(const SurfaceData& data) {
    has_surface_ = true;
    message_label_->hide();
    toolbar_->show();
    title_label_->show();
    surface_->show();
    colorbar_->show();
    provenance_label_->show();

    title_label_->setText(
        QStringLiteral("<b>%1</b>").arg(data.title.toHtmlEscaped()));
    provenance_label_->setText(data.provenance);

    // dat.py:1128-1135 — set_grid_data(payload) + autofit. grid_z arrives
    // as float (workbench grids); the widget consumes double.
    std::vector<double> grid_z(data.grid_z.begin(), data.grid_z.end());
    surface_->set_grid_data(data.grid_x, data.grid_y, std::move(grid_z),
                            data.levels);
    surface_->autofit();

    if (!data.levels.empty()) {
        const auto bounds = std::minmax_element(data.levels.begin(),
                                                data.levels.end());
        colorbar_->set_continuous_range(*bounds.first, *bounds.second);
    }
}

void SurfaceHost::show_unavailable(const QString& reason) {
    has_surface_ = false;
    toolbar_->hide();
    title_label_->hide();
    surface_->hide();
    colorbar_->hide();
    provenance_label_->hide();
    message_label_->setText(reason);
    message_label_->show();
}

pwb::viz_charts::qt::SurfaceWidget* SurfaceHost::surface() const {
    return surface_;
}

QString SurfaceHost::provenance() const {
    return has_surface_ ? provenance_label_->text() : QString();
}

bool SurfaceHost::export_svg_to(const QString& path) {
    if (path.isEmpty()) {
        return false;
    }
    try {
        surface_->export_svg(path, export_canvas_of(surface_));
    } catch (...) {
        return false;
    }
    return export_file_written(path);
}

bool SurfaceHost::export_pdf_to(const QString& path) {
    if (path.isEmpty()) {
        return false;
    }
    try {
        surface_->export_pdf(path, export_canvas_of(surface_));
    } catch (...) {
        return false;
    }
    return export_file_written(path);
}

void SurfaceHost::run_toolbar_export(bool svg) {
    const QString path = ask_export_path(this, svg);
    if (path.isEmpty()) {
        return;  // 用户取消对话框
    }
    if (svg ? export_svg_to(path) : export_pdf_to(path)) {
        Q_EMIT export_requested(path);
    }
}

}  // namespace pwb::viz_e
