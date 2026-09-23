// QGIS-PLOT — offscreen smoke/interaction test for the QgsPlotCanvas
// infrastructure. Drives real QGIS plot tools (pan / marquee zoom / x-zoom /
// identify / lasso) through synthesized mouse events, exercises series
// binding -> domain-id resolution, multi-track linked axes, flipAxes
// well-log orientation, vector/raster export, and teardown safety.

#include <cmath>
#include <cstdio>
#include <memory>

#include <QApplication>
#include <QFile>
#include <QFileInfo>
#include <QImage>
#include <QMouseEvent>
#include <QTemporaryDir>
#include <QWheelEvent>

#include <qgslinechartplot.h>
#include <qgsplot.h>
#include <qgsplottoolpan.h>
#include <qgsplottoolzoom.h>
#include <qgssymbol.h>

#include <pwb/qgis_plot/domain_plots.hpp>
#include <pwb/qgis_plot/numeric_formats.hpp>
#include <pwb/qgis_plot/plot_canvas.hpp>
#include <pwb/qgis_plot/plot_item.hpp>
#include <pwb/qgis_plot/plot_panel.hpp>
#include <pwb/qgis_plot/plot_tools.hpp>

using namespace pwb::qgis_plot;

namespace {

int failures = 0;

void check(bool condition, const char* what) {
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    } else {
        std::fprintf(stdout, "PASS %s\n", what);
    }
}

QgsPlotData xyData(std::initializer_list<std::pair<double, double>> pts,
                   const QString& name = {}) {
    QgsPlotData data;
    auto* s = new QgsXyPlotSeries();
    QList<std::pair<double, double>> list;
    for (const auto& p : pts)
        list.append(p);
    s->setData(list);
    if (!name.isEmpty())
        s->setName(name);
    data.addSeries(s);
    return data;
}

std::unique_ptr<QgsLineChartPlot> linePlot() {
    auto plot = std::make_unique<QgsLineChartPlot>();
    plot->setMarkerSymbolAt(0, QgsMarkerSymbol::createSimple(
                                   QVariantMap{{u"name"_s, u"circle"_s},
                                               {u"size"_s, 2.0}})
                                   .release());
    plot->setLineSymbolAt(
        0, QgsLineSymbol::createSimple(
               QVariantMap{{u"line_color"_s, u"#2266cc"_s},
                           {u"line_width"_s, 0.4}})
               .release());
    return plot;
}

void sendMouse(QWidget* target, QEvent::Type type, QPoint pos,
               Qt::MouseButton button = Qt::LeftButton,
               Qt::MouseButtons buttons = Qt::NoButton,
               Qt::KeyboardModifiers mods = Qt::NoModifier) {
    QMouseEvent e(type, QPointF(pos), QPointF(pos), QPointF(pos), button,
                  buttons, mods);
    QCoreApplication::sendEvent(target, &e);
}

void drag(QWidget* vp, QPoint from, QPoint to,
          Qt::MouseButton button = Qt::LeftButton) {
    sendMouse(vp, QEvent::MouseButtonPress, from, button, button);
    sendMouse(vp, QEvent::MouseMove, to, Qt::NoButton, button);
    sendMouse(vp, QEvent::MouseButtonRelease, to, button, Qt::NoButton);
}

// Fraction of non-transparent pixels — blank-render detector.
double inkFraction(const QImage& img) {
    int ink = 0;
    for (int y = 0; y < img.height(); ++y)
        for (int x = 0; x < img.width(); ++x)
            if (qAlpha(img.pixel(x, y)) > 10)
                ++ink;
    return static_cast<double>(ink) / (img.width() * img.height());
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QTemporaryDir tmp;
    check(tmp.isValid(), "temp dir");

    // ------------------------------------------------------------------
    // 1. Construct, bind series, autofit, render non-blank.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(
            xyData({{0, 0}, {10, 5}, {20, 2}, {30, 8}}, u"s1"_s));
        canvas.zoomFull();
        QCoreApplication::processEvents();
        const QImage img = canvas.viewport()->grab().toImage();
        check(inkFraction(img) > 0.001, "line plot renders ink");
        const auto [xmin, xmax, ymin, ymax] = canvas.viewBounds();
        check(xmin < 0.0 && xmax > 30.0 && ymin < 0.0 && ymax > 8.0,
              "zoomFull pads data extent");
    }

    // ------------------------------------------------------------------
    // 2. Coordinate mapping round-trip.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {100, 100}}));
        canvas.zoomFull();
        canvas.viewport()->grab();  // force a paint so plotArea is real
        const QPointF c = item->plotToCanvas(50.0, 50.0);
        check(c.x() > 0 && c.y() > 0, "plotToCanvas inside canvas");
        double x = 0, y = 0;
        check(item->canvasToPlot(c, x, y), "canvasToPlot accepts");
        check(std::fabs(x - 50.0) < 1.0 && std::fabs(y - 50.0) < 1.0,
              "mapping round-trip");
    }

    // ------------------------------------------------------------------
    // 3. QGIS pan tool via real mouse events: drag right -> range left.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {100, 100}}));
        canvas.zoomFull();
        canvas.viewport()->grab();
        auto* pan = new QgsPlotToolPan(&canvas);
        canvas.setTool(pan);
        const double before = item->xRange().lower();
        drag(canvas.viewport(), QPoint(400, 200), QPoint(500, 200));
        check(item->xRange().lower() < before, "pan drag shifts window left");
        canvas.unsetTool(pan);
    }

    // ------------------------------------------------------------------
    // 4. Wheel zoom + marquee zoom via QgsPlotToolZoom.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {100, 100}}));
        canvas.zoomFull();
        canvas.viewport()->grab();
        const double span0 =
            item->xRange().upper() - item->xRange().lower();
        QWheelEvent wheel(QPointF(400, 200), QPointF(400, 200), QPoint(),
                          QPoint(0, 120), Qt::NoButton, Qt::NoModifier,
                          Qt::NoScrollPhase, false);
        QCoreApplication::sendEvent(canvas.viewport(), &wheel);
        const double span1 =
            item->xRange().upper() - item->xRange().lower();
        check(span1 < span0, "wheel zoom in shrinks span");

        auto* zoom = new QgsPlotToolZoom(&canvas);
        canvas.setTool(zoom);
        const QRectF area = item->plotArea();
        drag(canvas.viewport(), area.center().toPoint() - QPoint(50, 50),
             area.center().toPoint());
        const double span2 =
            item->xRange().upper() - item->xRange().lower();
        check(span2 < span1, "marquee zoom in shrinks span");
        canvas.unsetTool(zoom);
    }

    // ------------------------------------------------------------------
    // 5. Hover nearest point + domain-id resolution through bindings.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {10, 10}, {20, 0}}));
        canvas.zoomFull();
        canvas.viewport()->grab();
        SeriesBinding b;
        b.series_id = u"curve-1"_s;
        b.well_id = u"W-07"_s;
        b.point_domain_ids = {u"md-1000"_s, u"md-1010"_s, u"md-1020"_s};
        canvas.setSeriesBindings(0, {b});
        const QPointF pt = item->plotToCanvas(10.0, 10.0);
        const auto hit = canvas.nearestPoint(pt, 20.0);
        check(hit && hit->series_index == 0 && hit->point_index == 1,
              "nearestPoint finds vertex");
        check(hit && hit->domain_id == u"md-1010"_s,
              "hit resolves domain id");
        check(hit && hit->series_id == u"curve-1"_s, "hit resolves series id");

        // identifyRect covers two points in the left half.
        const auto hits = canvas.identifyRect(
            QRectF(item->plotArea().left(), item->plotArea().top(),
                   item->plotArea().width() * 0.6,
                   item->plotArea().height()));
        check(hits.size() >= 2, "identifyRect returns hits");
    }

    // ------------------------------------------------------------------
    // 6. Hover signal + crosshair + identify tool click pick.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {10, 10}, {20, 0}}));
        canvas.zoomFull();
        canvas.viewport()->grab();
        int hovered = 0;
        PointHit last;
        QObject::connect(&canvas, &PwbPlotCanvas::pointHovered, &canvas,
                         [&](const PointHit& h) {
                             ++hovered;
                             last = h;
                         });
        const QPointF pt = item->plotToCanvas(10.0, 10.0);
        sendMouse(canvas.viewport(), QEvent::MouseMove, pt.toPoint());
        check(hovered == 1 && last.point_index == 1, "hover emits point");
        sendMouse(canvas.viewport(), QEvent::MouseMove,
                  QPoint(int(item->plotArea().left()) + 2,
                         int(item->plotArea().bottom()) - 2));
        // may or may not land on a vertex — just ensure no crash and state ok
        auto* identify = new PwbPlotToolIdentify(&canvas);
        canvas.setTool(identify);
        int picked = 0;
        QObject::connect(identify, &PwbPlotToolIdentify::pointPicked, &canvas,
                         [&](const PointHit&) { ++picked; });
        drag(canvas.viewport(), pt.toPoint(), pt.toPoint());
        check(picked == 1, "identify click picks point");
        canvas.unsetTool(identify);
    }

    // ------------------------------------------------------------------
    // 7. Scatter with z-ramp + labels; column plot; depth format.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto scatter = std::make_unique<PwbScatterPlot>();
        scatter->setSeriesColors({QColor(200, 40, 40)});
        auto* scatter_ptr = scatter.get();
        auto* item = canvas.addPlot(std::move(scatter));
        QgsPlotData data;
        auto* s = new QgsXyPlotSeries();
        s->setData({{0, 0}, {1, 1}, {2, 0.5}, {3, 1.5}});
        data.addSeries(s);
        item->setPlotData(std::move(data));
        scatter_ptr->setSeriesZValues(0, {0.0, 0.5, 1.0, 0.2}, 0.0, 1.0,
                                      {QColor(68, 1, 84), QColor(33, 145, 140),
                                       QColor(253, 231, 37)});
        scatter_ptr->setPointLabels(0, {u"a"_s, u"b"_s, u"c"_s, u"d"_s});
        canvas.zoomFull();
        const QImage img = canvas.viewport()->grab().toImage();
        check(inkFraction(img) > 0.001, "z-ramp scatter renders");

        PwbDepthNumericFormat fmt;
        fmt.setNumberDecimalPlaces(0);
        fmt.setShowThousandsSeparator(false);
        check(fmt.formatDouble(-1500.0, QgsNumericFormatContext()) ==
                  u"1500"_s,
              "depth format prints |depth|");
    }

    // ------------------------------------------------------------------
    // 8. Multi-track: three items, shared-X pan links tracks.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(900, 400);
        QList<PwbPlotItem*> items;
        for (int i = 0; i < 3; ++i) {
            auto* it = canvas.addPlot(linePlot());
            it->setPlotData(xyData({{0, i * 1.0}, {50, i * 2.0}}));
            it->setShareY(false);  // well-log: X (bucket) shared, Y per track
            items.append(it);
        }
        canvas.zoomFull();
        canvas.viewport()->grab();
        check(items[0]->sceneRect().right() < items[1]->sceneRect().left(),
              "columns laid out side by side");
        const double x0 = items[0]->xRange().lower();
        const double x2 = items[2]->xRange().lower();
        check(std::fabs(x0 - x2) < 1e-9, "shared-X autofit union");
        canvas.panContentsBy(60, 0);
        check(std::fabs(items[0]->xRange().lower() -
                        items[2]->xRange().lower()) < 1e-9,
              "shared-X pan keeps tracks locked");
        const double y0 = items[0]->yRange().lower();
        const double y1 = items[1]->yRange().lower();
        check(std::fabs(y0 - y1) > 1e-6, "independent Y stays independent");
    }

    // ------------------------------------------------------------------
    // 8b. Interval-strip column + explicit full extent (no series data) +
    //     horizontal depth-cursor guide.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(900, 400);
        auto strip = std::make_unique<PwbIntervalStripPlot>();
        QVector<PwbIntervalStripPlot::IntervalBand> bands;
        bands.push_back({100.0, 200.0, u"Sand"_s, QColor(200, 170, 60), 140});
        bands.push_back({300.0, 450.0, u"Shale"_s, QColor(90, 110, 140), 140});
        strip->setBands(bands);
        strip->xAxis().setType(Qgis::PlotAxisType::Categorical);
        auto* item = canvas.addPlot(std::move(strip));
        item->setFullExtent(0.0, 1.0, -500.0, -50.0);
        canvas.zoomFull();  // uses the declared extent, not series data
        const QgsDoubleRange yr = item->yRange();
        check(yr.lower() < -500.0 && yr.upper() > -50.0,
              "interval strip: zoomFull honours declared extent");
        const QImage img = canvas.viewport()->grab().toImage();
        check(inkFraction(img) > 0.001, "interval strip renders bands");
        canvas.setHorizontalGuide(-275.0);
        canvas.setHorizontalGuide(std::nullopt);
        check(true, "horizontal guide set/clear");
    }

    // ------------------------------------------------------------------
    // 9. flipAxes: depth vertical (well-log orientation).
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(400, 600);
        auto plot = linePlot();
        plot->setFlipAxes(true);
        auto* item = canvas.addPlot(std::move(plot));
        // depth fed negated so it renders top-down; value on the Y data axis.
        item->setPlotData(xyData({{-100, 2.0}, {-500, 8.0}, {-900, 3.0}}));
        canvas.zoomFull();
        canvas.viewport()->grab();
        const QPointF shallow = item->plotToCanvas(-100.0, 2.0);
        const QPointF deep = item->plotToCanvas(-900.0, 2.0);
        check(shallow.y() < deep.y(), "flipAxes: shallow depth on top");
    }

    // ------------------------------------------------------------------
    // 10. Lasso tool emits a canvas polygon.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {100, 100}}));
        canvas.zoomFull();
        canvas.viewport()->grab();
        auto* lasso = new PwbPlotToolLasso(&canvas);
        canvas.setTool(lasso);
        QPolygonF got;
        QObject::connect(lasso, &PwbPlotToolLasso::lassoFinished, &canvas,
                         [&](const QPolygonF& p) { got = p; });
        auto* vp = canvas.viewport();
        sendMouse(vp, QEvent::MouseButtonPress, QPoint(200, 100),
                  Qt::LeftButton, Qt::LeftButton);
        sendMouse(vp, QEvent::MouseMove, QPoint(600, 100), Qt::NoButton,
                  Qt::LeftButton);
        sendMouse(vp, QEvent::MouseMove, QPoint(600, 300), Qt::NoButton,
                  Qt::LeftButton);
        sendMouse(vp, QEvent::MouseMove, QPoint(200, 300), Qt::NoButton,
                  Qt::LeftButton);
        sendMouse(vp, QEvent::MouseButtonRelease, QPoint(200, 300),
                  Qt::LeftButton, Qt::NoButton);
        check(got.size() >= 4, "lasso polygon emitted");
        canvas.unsetTool(lasso);
    }

    // ------------------------------------------------------------------
    // 11. Export PNG/SVG/PDF.
    // ------------------------------------------------------------------
    {
        PwbPlotCanvas canvas;
        canvas.resize(800, 400);
        auto* item = canvas.addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {10, 5}, {20, 2}}));
        item->setAxisTitles(u"MD (m)"_s, u"GR (API)"_s);
        canvas.zoomFull();
        canvas.viewport()->grab();
        const QString png = tmp.filePath(u"plot.png"_s);
        const QString svg = tmp.filePath(u"plot.svg"_s);
        const QString pdf = tmp.filePath(u"plot.pdf"_s);
        check(canvas.exportTo(png) && QFileInfo(png).size() > 500,
              "PNG export");
        check(canvas.exportTo(svg) && QFileInfo(svg).size() > 500,
              "SVG export");
        check(canvas.exportTo(pdf) && QFileInfo(pdf).size() > 200,
              "PDF export");
    }

    // ------------------------------------------------------------------
    // 12. Panel chrome + lifecycle: repeated open/close, clear, re-add.
    // ------------------------------------------------------------------
    {
        PwbPlotPanel panel;
        panel.resize(800, 400);
        panel.setTitle(u"QC"_s);
        panel.setProvenance(u"run-42"_s);
        panel.showPlot();
        auto* item = panel.canvas()->addPlot(linePlot());
        item->setPlotData(xyData({{0, 0}, {1, 1}}));
        panel.canvas()->zoomFull();
        panel.showUnavailable(u"no data"_s);
        panel.showPlot();
        // Teardown path: destroy canvas with tools active.
        {
            PwbPlotCanvas canvas2;
            canvas2.resize(400, 300);
            auto* i2 = canvas2.addPlot(linePlot());
            i2->setPlotData(xyData({{0, 0}, {1, 1}}));
            canvas2.zoomFull();
            auto* pan = new QgsPlotToolPan(&canvas2);
            canvas2.setTool(pan);
            canvas2.clearPlots();
            // tool dies with canvas — no UAF expected
        }
        check(true, "panel + canvas teardown");
    }

    std::fprintf(stderr, "%d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
