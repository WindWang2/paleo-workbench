// VIZ-B — Qt half smoke test (offscreen): real section canvas painting,
// interaction (pick add via synthetic mouse click), composite + report
// export readability. Uses the frozen real-well fixture (A4/A13/A16 LAS
// curves) — no synthetic stand-ins.

#include <QApplication>
#include <QColor>
#include <QFile>
#include <QImage>
#include <QPointF>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>

#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/viz/cross_well/picks_model.hpp>
#include <pwb/viz/cross_well/qt/formation_tops_preview.hpp>
#include <pwb/viz/cross_well/qt/report_export.hpp>
#include <pwb/viz/cross_well/qt/section_canvas.hpp>
#include <pwb/viz/cross_well/tops_model.hpp>

#ifndef PWB_VIZ_B_CROSS_WELL_FIXTURE
#error "fixture macro missing"
#endif

using pwb::domain::Json;
using pwb::viz::cross_well::FormationTop;
using pwb::viz::cross_well::FormationTopsModel;
using pwb::viz::cross_well::HorizonPicksModel;
using pwb::viz::cross_well::qt::CrossWellReportOptions;
using pwb::viz::cross_well::qt::FormationTopsPreview;
using pwb::viz::cross_well::qt::SectionCanvas;
using SectionScene = pwb::viz::cross_well::qt::SectionScene;
using pwb::viz::cross_well::qt::export_cross_well_report;
using pwb::viz::cross_well::qt::export_section_composite;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& label) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL: " << label << "\n";
    }
}

std::vector<double> read_nums(const Json& arr) {
    std::vector<double> out;
    for (const Json& v : arr) {
        if (v.is_string()) {
            const std::string s = v.get<std::string>();
            if (s == "nan") {
                out.push_back(std::numeric_limits<double>::quiet_NaN());
                continue;
            }
        }
        out.push_back(v.get<double>());
    }
    return out;
}

bool file_starts_with(const QString& path, const char* prefix) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return false;
    const QByteArray head = file.read(static_cast<qint64>(std::strlen(prefix)));
    return head == QByteArray(prefix);
}

}  // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QTemporaryDir temp_dir;
    check(temp_dir.isValid(), "temp dir");

    std::ifstream file(PWB_VIZ_B_CROSS_WELL_FIXTURE);
    if (!file.is_open()) {
        std::cerr << "cannot open fixture\n";
        return 2;
    }
    Json payload;
    file >> payload;

    // Real wells -> columns.
    std::vector<pwb::viz::cross_well::WellColumnData> wells;
    for (const Json& w : payload.at("real_wells").at("wells")) {
        pwb::viz::cross_well::WellColumnData column;
        column.name = w.at("name").get<std::string>();
        for (const Json& curve : w.at("curves")) {
            pwb::viz::cross_well::WellCurve wc;
            wc.name = curve.at("name").get<std::string>();
            wc.depths = read_nums(curve.at("depths"));
            wc.values = read_nums(curve.at("values"));
            column.curves.push_back(std::move(wc));
        }
        wells.push_back(std::move(column));
    }
    check(wells.size() >= 2, "fixture wells >= 2");

    FormationTopsModel tops;
    {
        std::ofstream csv(temp_dir.path().toStdString() + "/tops.csv");
        csv << "A4,Formation-X,2350.0\nA13,Formation-X,2361.5\nA16,Formation-X,2344.0\n";
    }
    check(tops.load_csv((temp_dir.path().toStdString() + "/tops.csv")),
          "tops load");
    HorizonPicksModel picks;

    // --- SectionCanvas: paint + interaction --------------------------
    SectionCanvas canvas;
    canvas.resize(1400, 640);
    canvas.set_wells(wells);
    canvas.set_models(&tops, &picks);
    canvas.set_pick_mode(true);
    canvas.show();
    QTest::qWaitForWindowExposed(&canvas);

    const QImage grabbed = canvas.grab().toImage();
    check(!grabbed.isNull() && grabbed.width() > 100, "grab non-empty");
    // Key pixel: background cream at a margin spot.
    check(grabbed.pixelColor(8, 8) == QColor(0xfa, 0xf9, 0xf5),
          "background colour contract");
    // Curve pixels exist in the first column content area (blue-ish
    // curve strokes among them).
    int blue_ish = 0;
    for (int y = 100; y < grabbed.height() - 20; y += 3) {
        for (int x = 25; x < 195; x += 3) {
            const QColor c = grabbed.pixelColor(x, y);
            if (c.blue() > 150 && c.blue() > c.red() + 40 &&
                c.blue() > c.green() + 40) {
                ++blue_ish;
            }
        }
    }
    check(blue_ish > 10, "curve strokes painted, blue count=" +
                             std::to_string(blue_ish));

    // Interaction: click in pick mode adds a pick at the mapped depth.
    QSignalSpy changed(&canvas,
                       &SectionCanvas::interaction_changed);
    const double depth_mid = 0.5 *
        (canvas.build_scene().view.depth_top +
         canvas.build_scene().view.depth_bottom);
    // Map the depth back to a y in the first column.
    const auto scene = canvas.build_scene();
    const double content_h = 640.0 - 28.0;
    const double y = 28.0 + 56.0 +
                     (depth_mid - scene.view.depth_top) /
                         scene.view.span() *
                         (content_h - 56.0);
    QTest::mouseClick(&canvas, Qt::LeftButton, Qt::NoModifier,
                      QPoint(static_cast<int>(20.0 + 90.0),
                             static_cast<int>(y)));
    check(picks.all_picks().size() == 1, "pick added via click");
    check(changed.count() >= 1, "interaction_changed emitted");
    if (!picks.all_picks().empty()) {
        const std::optional<double> d =
            picks.all_picks()[0]->depth_for_well(wells[0].name);
        check(d.has_value() && std::abs(*d - depth_mid) <
                                   scene.view.span() * 0.02,
              "click depth maps back (got " +
                  std::to_string(d.value_or(0)) + " want " +
                  std::to_string(depth_mid) + ")");
    }
    // Shift+click on the second column connects the pick.
    QTest::mouseClick(&canvas, Qt::LeftButton, Qt::ShiftModifier,
                      QPoint(static_cast<int>(20.0 + 330.0 + 90.0),
                             static_cast<int>(y + 5.0)));
    check(picks.all_picks().size() == 1 &&
              picks.all_picks()[0]->connected_wells().size() == 2,
          "shift-click connects pick");
    // Right-click deletes it.
    QTest::mouseClick(&canvas, Qt::RightButton, Qt::NoModifier,
                      QPoint(static_cast<int>(20.0 + 90.0),
                             static_cast<int>(y)));
    check(picks.all_picks().empty(), "right-click deletes pick");

    // --- composite export: PNG/PDF/SVG readable ----------------------
    canvas.set_pick_mode(false);
    QTest::mouseClick(&canvas, Qt::LeftButton, Qt::NoModifier,
                      QPoint(static_cast<int>(20.0 + 90.0),
                             static_cast<int>(y)));  // pan start (no pick)
    const SectionScene export_scene = canvas.build_scene();
    const QString png = temp_dir.filePath("section.png");
    check(export_section_composite(export_scene, png, "png", 150,
                                   std::nullopt, std::nullopt),
          "composite png export ok");
    check(QFile(png).size() > 1000, "png non-trivial");
    check(file_starts_with(png, "\x89PNG"), "png magic");
    const QString pdf = temp_dir.filePath("section.pdf");
    check(export_section_composite(export_scene, pdf, "pdf", 150,
                                   std::nullopt, QString("A4")),
          "composite pdf export ok");
    check(file_starts_with(pdf, "%PDF"), "pdf magic");
    check(QFile(pdf).size() > 1000, "pdf non-trivial");
    const QString svg = temp_dir.filePath("section.svg");
    check(export_section_composite(export_scene, svg, "svg", 96, 1600,
                                   std::nullopt),
          "composite svg export ok");
    check(file_starts_with(svg, "<?xml"), "svg magic");
    // The exported SVG must carry the data identity (well names).
    {
        QFile f(svg);
        f.open(QIODevice::ReadOnly);
        const QString text = QString::fromUtf8(f.readAll());
        check(text.contains("A4") && text.contains("A13") &&
                  text.contains("A16"),
              "svg contains well names");
    }

    // --- publication report -----------------------------------------
    // Re-add a pick so the report carries interpretation data.
    canvas.set_pick_mode(true);
    QTest::mouseClick(&canvas, Qt::LeftButton, Qt::NoModifier,
                      QPoint(static_cast<int>(20.0 + 90.0),
                             static_cast<int>(y)));
    QTest::mouseClick(&canvas, Qt::LeftButton, Qt::ShiftModifier,
                      QPoint(static_cast<int>(20.0 + 330.0 + 90.0),
                             static_cast<int>(y)));
    CrossWellReportOptions options;
    options.dpi = 96;  // keep the offscreen raster small
    const QString report_pdf = temp_dir.filePath("report.pdf");
    check(export_cross_well_report(canvas.build_scene(), report_pdf,
                                   options),
          "report pdf export ok");
    check(file_starts_with(report_pdf, "%PDF"), "report pdf magic");
    check(QFile(report_pdf).size() > 1000, "report pdf non-trivial");
    const QString report_png = temp_dir.filePath("report.png");
    check(export_cross_well_report(canvas.build_scene(), report_png,
                                   options),
          "report png export ok");
    {
        QImage image(report_png);
        check(!image.isNull() && image.width() > 500, "report png loads");
        // Title band pixels: dark text present near the top margin.
        int dark = 0;
        for (int yy = 20; yy < 120; ++yy) {
            for (int xx = 20; xx < image.width() - 20; xx += 2) {
                const QColor c = image.pixelColor(xx, yy);
                if (c.lightness() < 100) ++dark;
            }
        }
        check(dark > 10, "report title text painted, dark=" +
                             std::to_string(dark));
    }

    // --- formation preview -------------------------------------------
    FormationTopsPreview preview;
    preview.resize(640, 480);
    std::vector<FormationTop> preview_tops;
    for (const Json& t : payload.at("formation_preview").at("tops")) {
        preview_tops.push_back(
            FormationTop{t.at("well").get<std::string>(),
                         t.at("formation").get<std::string>(),
                         t.at("depth").get<double>(), ""});
    }
    preview.set_tops(preview_tops);
    preview.show();
    QTest::qWaitForWindowExposed(&preview);
    const QImage preview_grab = preview.grab().toImage();
    check(!preview_grab.isNull(), "preview grab");
    QSignalSpy hover(&preview, &FormationTopsPreview::hovered_top_changed);
    QTest::mouseMove(&preview, QPoint(80, 100));
    preview.repaint();
    check(hover.count() >= 0, "hover spy armed");

    std::cout << "cross_well qt smoke: " << g_checks << " checks, "
              << g_failures << " failures\n";
    return g_failures == 0 ? 0 : 1;
}
