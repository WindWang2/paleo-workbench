// VIZ-E — Qt widget smoke test (offscreen): the surviving domain-specific
// QPainter widgets (ColorbarWidget / SurfaceWidget, frozen Python source
// @0885195). The generic PlotWidget / CrossPlotWidget / qt-series layer was
// retired in the QGIS-plot convergence — interactive 2-D charts are covered
// by libs/qgis_plot's qgis_plot.smoke instead.

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
        auto* bar = new ColorbarWidget(parent);
        auto* surface = new SurfaceWidget(parent);
        bar->set_continuous_range(0.0, 1.0);
        surface->set_grid_data(std::vector<double>{0.0, 1.0, 2.0},
                               std::vector<double>{0.0, 1.0, 2.0},
                               std::vector<double>{0.0, 0.5, 1.0,
                                                   0.25, 0.75, 0.1,
                                                   0.9, 0.3, 0.6},
                               std::vector<double>{0.2, 0.5, 0.8});
        surface->add_control_point(1.0, 1.0, 0.5);
        bar->deleteLater();
        delete parent;  // destroys children via the QObject tree
        QCoreApplication::sendPostedEvents(nullptr, QEvent::DeferredDelete);
        QCoreApplication::processEvents();
        check(true, "teardown: parented delete + deferred delete clean");
    }

    std::fprintf(stdout, "%s (%d failures)\n",
                 failures == 0 ? "ALL PASS" : "FAILURES", failures);
    return failures == 0 ? 0 : 1;
}
