// VIZ-E — Qt widget smoke test (offscreen): instantiate the four ported
// QPainter widgets (PlotWidget / CrossPlotWidget / ColorbarWidget /
// SurfaceWidget, frozen Python source @0885195) and drive their primary
// entry points: render grabs with pixel-level sanity checks, view-bounds
// round trips and exception parity, lasso selection signaling, contour band
// coloring, SVG/PDF vector exports, and teardown safety.

#include <QApplication>
#include <QByteArray>
#include <QFile>
#include <QImage>
#include <QPixmap>
#include <QPointF>
#include <QPolygonF>
#include <QTemporaryDir>
#include <QVector>
#include <QWidget>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

#include <pwb/viz_charts/qt/colorbar_widget.hpp>
#include <pwb/viz_charts/qt/cross_plot_widget.hpp>
#include <pwb/viz_charts/qt/plot_widget.hpp>
#include <pwb/viz_charts/qt/series.hpp>
#include <pwb/viz_charts/qt/surface_widget.hpp>

using namespace pwb::viz_charts::qt;

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

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QTemporaryDir tmp;
    check(tmp.isValid(), "temp dir");

    // ------------------------------------------------------------------
    // PlotWidget — series, autofit, grab, SVG/PDF export
    // ------------------------------------------------------------------
    {
        PlotWidget w;
        w.resize(800, 600);

        std::vector<double> lx;
        std::vector<double> ly;
        for (int i = 0; i <= 40; ++i) {
            lx.push_back(i * 0.25);
            ly.push_back(std::sin(i * 0.3) * 4.0 + 2.0);
        }
        w.add_series(std::make_unique<LineSeriesData>(lx, ly, "line1"));

        // Line with NaN breaks (polyline must flush at the gaps).
        std::vector<double> bx;
        std::vector<double> by;
        for (int i = 0; i <= 30; ++i) {
            bx.push_back(i * 0.2 + 1.0);
            by.push_back(i % 7 == 3
                             ? std::numeric_limits<double>::quiet_NaN()
                             : std::cos(i * 0.21) * 3.0 - 1.0);
        }
        w.add_series(std::make_unique<LineSeriesData>(bx, by, "line_nan"));

        auto scat = std::make_unique<ScatterSeriesData>(
            std::vector<double>{0.5, 1.5, 2.5, 3.5, 4.5, 5.5},
            std::vector<double>{1.0, 2.0, 1.5, 2.5, 0.5, 1.2}, "scat");
        scat->labels = {QStringLiteral("a"), QStringLiteral("b"),
                        QStringLiteral("c"), QStringLiteral("d"),
                        QStringLiteral("e"), QStringLiteral("f")};
        w.add_series(std::move(scat));

        w.autofit();
        w.show();
        QApplication::processEvents();

        const QPixmap grabbed = w.grab();
        check(!grabbed.isNull(), "plot: grab non-null");
        const QImage img = grabbed.toImage();
        // Plot interior (center) must differ from the outer margin bg.
        check(img.pixel(400, 300) != img.pixel(5, 5),
              "plot: plot-area pixel differs from margin background");

        // SVG export: real vector file with a meaningful payload.
        const QString svg_path = tmp.filePath(QStringLiteral("plot.svg"));
        w.export_svg(svg_path);
        QFile svg_file(svg_path);
        check(svg_file.open(QIODevice::ReadOnly), "plot: svg file readable");
        const QByteArray svg = svg_file.readAll();
        check(svg.contains("<svg") && svg.size() > 1024,
              "plot: export_svg writes >1KB <svg> document");

        // PDF export: header parity.
        const QString pdf_path = tmp.filePath(QStringLiteral("plot.pdf"));
        w.export_pdf(pdf_path);
        QFile pdf_file(pdf_path);
        check(pdf_file.open(QIODevice::ReadOnly), "plot: pdf file readable");
        check(pdf_file.read(5) == QByteArray("%PDF-"),
              "plot: export_pdf starts with %PDF-");
    }

    // ------------------------------------------------------------------
    // PlotWidget — view bounds round trip + exception parity
    // ------------------------------------------------------------------
    {
        PlotWidget w;
        w.add_series(std::make_unique<LineSeriesData>(
            std::vector<double>{0.0, 1.0, 2.0},
            std::vector<double>{0.0, 1.0, 0.0}, "s"));
        w.set_view_bounds(1.0, 2.0, 3.0, 4.0);
        const auto [xmin, xmax, ymin, ymax] = w.view_bounds();
        check(std::abs(xmin - 1.0) < 1e-12 && std::abs(xmax - 2.0) < 1e-12 &&
                  std::abs(ymin - 3.0) < 1e-12 && std::abs(ymax - 4.0) < 1e-12,
              "plot: view bounds round trip");

        bool threw = false;
        try {
            w.set_view_bounds(2.0, 1.0, 0.0, 1.0);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, "plot: xmin>=xmax throws invalid_argument");

        threw = false;
        try {
            w.set_view_bounds(std::numeric_limits<double>::quiet_NaN(), 1.0,
                              0.0, 1.0);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, "plot: non-finite bounds throw invalid_argument");

        threw = false;
        try {
            w.set_selected_point(QStringLiteral("nope"), 0);
        } catch (const std::invalid_argument&) {
            threw = true;
        }
        check(threw, "plot: unknown series throws invalid_argument");

        threw = false;
        try {
            w.set_selected_point(QStringLiteral("s"), 99);
        } catch (const std::out_of_range&) {
            threw = true;
        }
        check(threw, "plot: index out of range throws out_of_range");
    }

    // ------------------------------------------------------------------
    // ColorbarWidget
    // ------------------------------------------------------------------
    {
        ColorbarWidget w;
        w.resize(65, 300);
        w.set_continuous_range(0.0, 100.0);
        const QImage img = w.grab().toImage();
        check(!img.isNull(), "colorbar: grab non-null");
        // Gradient bar spans x∈[10,30]; top and bottom of the bar must map
        // to different viridis stops.
        check(img.pixel(20, 25) != img.pixel(20, 260),
              "colorbar: gradient ends differ");

        w.set_discrete_swatches(
            {{QStringLiteral("Sand"), QColor(120, 200, 90)},
             {QStringLiteral("Shale"), QColor(90, 110, 140)}});
        check(!w.grab().isNull(), "colorbar: discrete grab non-null");
    }

    // ------------------------------------------------------------------
    // CrossPlotWidget — z coloring + lasso selection signaling
    // ------------------------------------------------------------------
    {
        CrossPlotWidget w;
        w.resize(800, 600);
        std::vector<double> x;
        std::vector<double> y;
        std::vector<double> z;
        for (int i = 0; i < 50; ++i) {
            x.push_back(i * 0.1);
            y.push_back(std::sin(i * 0.3));
            z.push_back(i);
        }
        w.set_scatter_data(x, y, z, QStringLiteral("Por"),
                           QStringLiteral("Perm"), QStringLiteral("Facies"));
        check(!w.grab().isNull(), "cross: grab non-null");

        int emitted = 0;
        int selected_count = -1;
        QObject::connect(
            &w, &CrossPlotWidget::points_selected, &w,
            [&](const QVector<int>& indices, double, double, double, double) {
                ++emitted;
                selected_count = indices.size();
            });
        // Lasso polygon in DATA coordinates enclosing x∈(-0.5, 2.5).
        QVector<QPointF> lasso;
        lasso << QPointF(-0.5, -1.5) << QPointF(2.5, -1.5) << QPointF(2.5, 1.5)
              << QPointF(-0.5, 1.5);
        w.apply_lasso_polygon(lasso);
        check(emitted == 1 && selected_count > 0,
              "cross: lasso emits non-empty selection");
    }

    // ------------------------------------------------------------------
    // SurfaceWidget — filled contour bands + export
    // ------------------------------------------------------------------
    {
        SurfaceWidget w;
        w.resize(800, 600);
        constexpr int cols = 21;  // grid_x nodes
        constexpr int rows = 17;  // grid_y nodes (z is rows×cols row-major)
        std::vector<double> gx;
        std::vector<double> gy;
        for (int c = 0; c < cols; ++c) {
            gx.push_back(c * 0.5);
        }
        for (int r = 0; r < rows; ++r) {
            gy.push_back(r * 0.5);
        }
        std::vector<double> gz(static_cast<std::size_t>(rows * cols));
        for (int r = 0; r < rows; ++r) {
            for (int c = 0; c < cols; ++c) {
                gz[static_cast<std::size_t>(r * cols + c)] =
                    std::sin(gx[static_cast<std::size_t>(c)] * 0.7) *
                    std::cos(gy[static_cast<std::size_t>(r)] * 0.6);
            }
        }
        std::vector<double> levels;
        for (int i = 0; i < 6; ++i) {
            levels.push_back(-1.0 + 2.0 * i / 5.0);
        }
        w.set_grid_data(gx, gy, gz, levels);
        w.autofit();
        w.show();
        QApplication::processEvents();

        const QImage img = w.grab().toImage();
        check(!img.isNull(), "surface: grab non-null");

        // Count colors covering a meaningful area inside the plot rect
        // (x∈[65,775], y∈[25,550]); filled bands must produce at least two
        // distinct frequent colors.
        std::map<QRgb, int> histogram;
        for (int yy = 30; yy < 540; ++yy) {
            for (int xx = 70; xx < 770; ++xx) {
                ++histogram[img.pixel(xx, yy)];
            }
        }
        int distinct = 0;
        for (const auto& [color, count] : histogram) {
            if (count > 50) {
                ++distinct;
            }
        }
        check(distinct >= 2, "surface: at least two distinct band colors");

        const QString svg_path = tmp.filePath(QStringLiteral("surface.svg"));
        w.export_svg(svg_path);
        QFile svg_file(svg_path);
        check(svg_file.open(QIODevice::ReadOnly), "surface: svg readable");
        check(svg_file.readAll().contains("<svg"),
              "surface: export_svg non-empty svg");
    }

    // ------------------------------------------------------------------
    // teardown safety — parented destruction, deferred deletes
    // ------------------------------------------------------------------
    {
        auto* parent = new QWidget;
        auto* plot = new PlotWidget(parent);
        auto* cross = new CrossPlotWidget(parent);
        auto* bar = new ColorbarWidget(parent);
        auto* surface = new SurfaceWidget(parent);
        plot->add_series(std::make_unique<LineSeriesData>(
            std::vector<double>{0.0, 1.0}, std::vector<double>{0.0, 1.0},
            "t"));
        plot->autofit();
        cross->set_scatter_data(std::vector<double>{0.0, 1.0},
                                std::vector<double>{0.0, 1.0});
        bar->set_continuous_range(0.0, 1.0);
        surface->set_grid_data(std::vector<double>{0.0, 1.0, 2.0},
                               std::vector<double>{0.0, 1.0, 2.0},
                               std::vector<double>{0.0, 0.5, 1.0,
                                                   0.25, 0.75, 0.1,
                                                   0.9, 0.3, 0.6},
                               std::vector<double>{0.2, 0.5, 0.8});
        surface->add_control_point(1.0, 1.0, 0.5);
        plot->deleteLater();
        delete parent;  // destroys children via the QObject tree
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        QCoreApplication::processEvents();
        check(true, "teardown: parented delete + deferred delete clean");
    }

    std::fprintf(stdout, "%s (%d failures)\n",
                 failures == 0 ? "ALL PASS" : "FAILURES", failures);
    return failures == 0 ? 0 : 1;
}
