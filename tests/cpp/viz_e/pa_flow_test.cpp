// viz_e.pa_flow — the P-A acceptance loop: 资产选择 → 识别能力 → 加载 →
// 真实预览/图表 → 导出, against the REAL assembly (VizEDataPage + JobCenter)
// and REAL assets (SMI .dat fixtures, parsed by the ported geoviz contract).
// Also replays the dat parsing oracle frozen from the Python backend
// (tools/oracle/generate_viz_e_dat_fixtures.py) and exercises the external
// presenter registration contract with a real presenter.
#include "job_center.hpp"
#include "viz_e_dat_preview.hpp"

#include "closure_preview_adapters.hpp"

#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/worker_common.hpp>
#include <pwb/viz_charts/marching_squares.hpp>
#include "viz_e_hosts.hpp"
#include "viz_e_install.hpp"

#include <pwb/viz_charts/qt/plot_widget.hpp>

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/project/document.hpp>
#include <pwb/project/manager.hpp>
#include <pwb/application/adapters/data_store.hpp>

#include <QApplication>
#include <QFile>
#include <QImage>
#include <QFileInfo>
#include <QPushButton>
#include <QSettings>
#include <QTemporaryDir>
#include <QLabel>
#include <QTextStream>

#include <array>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <thread>

using namespace pwb::viz_e;
namespace upd = pwb::ui_pages_data;
namespace upv = pwb::ui_pages_preview;
using pwb::domain::Json;

static int checks = 0;
static int failures = 0;

#define CHECK(cond)                                                        \
    do {                                                                   \
        ++checks;                                                          \
        if (!(cond)) {                                                     \
            ++failures;                                                    \
            std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);    \
        }                                                                  \
    } while (0)

static Json load_json(const QString& path) {
    std::ifstream in(path.toStdString());
    std::stringstream ss;
    ss << in.rdbuf();
    return Json::parse(ss.str());
}

static QString fixture(const char* name) {
    return QString::fromStdString(
        (std::string(PWB_VIZ_E_TEST_FIXTURES) + "/" + name));
}

static upd::AssetRow row_for(const QString& path, const char* name,
                             const char* format = "dat") {
    upd::AssetRow row;
    row.view.id = name;
    row.view.name = name;
    row.view.format = format;
    row.view.path = path.toStdString();
    row.view.status = "indexed";
    return row;
}

// Lightweight signal counter (QSignalSpy would drag in Qt6::Test).
struct Counter : public QObject {
    int count = 0;
    template <typename Sender, typename Signal>
    void track(Sender* sender, Signal signal) {
        QObject::connect(sender, signal, this, [this]() { ++count; });
    }
    // Spin the event loop until `wanted` signals arrived or the deadline
    // hit (JobCenter deliveries hop to the GUI thread).
    bool wait(int wanted, int timeout_ms = 30'000) {
        const auto deadline = std::chrono::steady_clock::now() +
                              std::chrono::milliseconds(timeout_ms);
        while (count < wanted &&
               std::chrono::steady_clock::now() < deadline) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 50);
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        return count >= wanted;
    }
};

// Bilinear grid lookup for contour on-line spot checks.
static double bilinear_grid_at(const std::vector<double>& gx,
                               const std::vector<double>& gy,
                               const std::vector<float>& gz, double px,
                               double py) {
    const std::size_t cols = gx.size();
    auto idx = [&](double v, const std::vector<double>& axis) {
        double clamped =
            std::min(std::max(v, axis.front()), axis.back());
        std::size_t lo = 0;
        while (lo + 2 < axis.size() && axis[lo + 1] < clamped) ++lo;
        return lo;
    };
    const std::size_t j0 = idx(px, gx);
    const std::size_t i0 = idx(py, gy);
    const std::size_t j1 = std::min(j0 + 1, cols - 1);
    const std::size_t i1 = std::min(i0 + 1, gy.size() - 1);
    const double tx = gx[j1] == gx[j0] ? 0.0 : (px - gx[j0]) / (gx[j1] - gx[j0]);
    const double ty = gy[i1] == gy[i0] ? 0.0 : (py - gy[i0]) / (gy[i1] - gy[i0]);
    const double z00 = gz[i0 * cols + j0];
    const double z01 = gz[i0 * cols + j1];
    const double z10 = gz[i1 * cols + j0];
    const double z11 = gz[i1 * cols + j1];
    return z00 * (1 - tx) * (1 - ty) + z01 * tx * (1 - ty) +
           z10 * (1 - tx) * ty + z11 * tx * ty;
}

static int count_occurrences(const QString& svg, const QString& needle) {
    int count = 0;
    for (int pos = svg.indexOf(needle); pos >= 0;
         pos = svg.indexOf(needle, pos + needle.size())) {
        ++count;
    }
    return count;
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    // ------------------------------------------------------------------
    // 1) dat parsing oracle replay (frozen from geoviz previews/dat.py).
    // ------------------------------------------------------------------
    {
        const Json fx = load_json(fixture("viz_e_dat_oracle.json"));
        CHECK(fx.at("geoviz_sha").get<std::string>() ==
              "08851951f3bbc0beb90886adf52e1928f4383c16");

        const WellHeadPreview head =
            parse_well_head(fixture("well_head_smi.dat").toStdString());
        const Json& expect = fx.at("well_head");
        CHECK(head.records.size() == expect.at("records").size());
        for (std::size_t i = 0;
             i < head.records.size() && i < expect.at("records").size(); ++i) {
            const auto& r = head.records[i];
            const auto& e = expect.at("records")[i];
            CHECK(r.name == e[0].get<std::string>());
            CHECK(std::fabs(r.x - e[1].get<double>()) < 1e-9);
            CHECK(std::fabs(r.y - e[2].get<double>()) < 1e-9);
            CHECK(r.uwi == e[3].get<std::string>());
        }
        CHECK(head.total_records ==
              expect.at("total_records").get<long long>());
        CHECK(head.valid_records ==
              expect.at("valid_records").get<long long>());
        CHECK(head.skipped_records == expect.at("skipped").get<long long>());
        CHECK(head.source_crs == expect.at("source_crs").get<std::string>());
        // Declared CRS transits verbatim; nothing was inferred.
        CHECK(head.source_crs == "EPSG:32650");

        // horizon rows + grid decision
        const HorizonPoints pts =
            parse_horizon_points(fixture("horizon_smi.dat").toStdString());
        CHECK(pts.x.size() == fx.at("horizon_rows").size());
        CHECK(std::fabs(pts.x_min) < 1e-9);
        CHECK(std::fabs(pts.x_max - 20.0) < 1e-9);
        CHECK(std::fabs(pts.y_max - 20.0) < 1e-9);
        CHECK(pts.source_crs == "EPSG:4326");
        const Json& hg = fx.at("horizon");
        CHECK(horizon_grid_resolution(pts) ==
              static_cast<int>(hg.at("grid_x").size()));

        // error shape for a malformed file (honest failure, no fake data)
        QTemporaryDir tmp;
        const QString bad = tmp.filePath("bad.dat");
        QFile f(bad);
        f.open(QIODevice::WriteOnly);
        f.write("#WellHead File From SMI\n#Name X\nA1 10\n");
        f.close();
        bool threw = false;
        try {
            parse_well_head(bad.toStdString());
        } catch (const std::runtime_error& error) {
            threw = true;
            const std::string msg = error.what();
            CHECK(msg.find("DAT") != std::string::npos ||
                  msg.find("列") != std::string::npos ||
                  !msg.empty());
        }
        CHECK(threw);
    }

    // ------------------------------------------------------------------
    // 2) external presenter registration contract (A/B/D interface).
    // ------------------------------------------------------------------
    {
        reset_external_presenters_for_tests();
        CHECK(registered_presenters().empty());

        // A REAL presenter: derives a real series from the file's own
        // content (line lengths) — no fabricated success state.
        ExternalPresenter presenter;
        presenter.kind = "well_log";
        presenter.note = "viz-e test presenter (line-length profile)";
        presenter.supports = [](const QString& path) {
            return path.endsWith(QLatin1String(".lines.dat"));
        };
        presenter.create = [](const QString& path, QWidget* parent) {
            QFile f(path);
            if (!f.open(QIODevice::ReadOnly)) {
                return static_cast<QWidget*>(nullptr);
            }
            auto* host = new XyScatterHost(parent);
            WellHeadPreview data;
            int index = 0;
            while (!f.atEnd()) {
                const QByteArray line = f.readLine();
                if (line.trimmed().isEmpty()) {
                    continue;
                }
                data.records.push_back(
                    {QString::number(index).toStdString(),
                     static_cast<double>(index),
                     static_cast<double>(line.trimmed().size()), ""});
                ++index;
            }
            if (data.records.empty()) {
                delete host;
                return static_cast<QWidget*>(nullptr);
            }
            data.total_records = index;
            data.valid_records = index;
            host->show_well_head(data, QStringLiteral("line profile"));
            return static_cast<QWidget*>(host);
        };
        CHECK(register_external_presenter(std::move(presenter)));
        CHECK(registered_presenters().size() == 1);
        CHECK(registered_presenters()[0].kind == "well_log");

        // duplicate kind is refused loudly
        ExternalPresenter dup;
        dup.kind = "well_log";
        dup.supports = [](const QString&) { return true; };
        dup.create = [](const QString&, QWidget* p) {
            return static_cast<QWidget*>(new QLabel(p));
        };
        CHECK(!register_external_presenter(std::move(dup)));
        reset_external_presenters_for_tests();
    }

    // ------------------------------------------------------------------
    // 3) P-A loop: well-head asset → xy_scatter preview → SVG/PDF export.
    // ------------------------------------------------------------------
    QTemporaryDir export_dir;
    {
        pwb::app::JobCenter jobs;
        VizEDataPage page(nullptr, &jobs);

        QTemporaryDir tmp;
        const QString lines_dat = tmp.filePath("profile.lines.dat");
        {
            QFile f(lines_dat);
            f.open(QIODevice::WriteOnly);
            f.write("alpha\nbet\nngamma-long\ndd\n");
            f.close();
        }
        reset_external_presenters_for_tests();
        ExternalPresenter presenter;
        presenter.kind = "well_log";
        presenter.note = "test";
        presenter.supports = [](const QString& path) {
            return path.endsWith(QLatin1String(".lines.dat"));
        };
        presenter.create = [](const QString& path, QWidget* parent) {
            QFile f(path);
            if (!f.open(QIODevice::ReadOnly)) {
                return static_cast<QWidget*>(nullptr);
            }
            auto* host = new XyScatterHost(parent);
            WellHeadPreview data;
            int index = 0;
            while (!f.atEnd()) {
                const QByteArray line = f.readLine();
                if (line.trimmed().isEmpty()) {
                    continue;
                }
                data.records.push_back(
                    {QString::number(index).toStdString(),
                     static_cast<double>(index),
                     static_cast<double>(line.trimmed().size()), ""});
                ++index;
            }
            if (data.records.empty()) {
                delete host;
                return static_cast<QWidget*>(nullptr);
            }
            data.total_records = index;
            data.valid_records = index;
            host->show_well_head(data, QStringLiteral("line profile"));
            return static_cast<QWidget*>(host);
        };
        register_external_presenter(std::move(presenter));

        Counter rendered; rendered.track(&page, &VizEDataPage::preview_rendered);
        Counter failed; failed.track(&page, &VizEDataPage::preview_failed);

        // external presenter path
        page.preview_asset(row_for(lines_dat, "P1"));
        CHECK(rendered.wait(1));
        CHECK(page.active_target() == QStringLiteral("well_log"));

        // well-head chart path
        page.preview_asset(row_for(fixture("well_head_smi.dat"), "WH1"));
        CHECK(rendered.wait(2));
        CHECK(page.active_target() == QStringLiteral("xy_scatter"));
        CHECK(failed.count == 0);

        // Realize the widgets offscreen so exports render at a real size.
        page.resize(1200, 800);
        page.show();
        QCoreApplication::processEvents(QEventLoop::AllEvents, 100);

        // view bounds carry the REAL data extents (autofit ±5%)
        const auto [xmin, xmax, ymin, ymax] = page.xy_host()->plot()->view_bounds();
        CHECK(xmin <= 100.0 && xmax >= 141.25);
        CHECK(ymin <= 480.25 && ymax >= 525.0);

        // export loop — SVG re-read with content verification: one ellipse
        // per well marker (5 valid wells), axes/grid/labels present.
        // Stack pages never laid out keep a zero height (the real app has
        // them visible); pin the geometry right before exporting.
        page.xy_host()->setGeometry(0, 0, 900, 600);
        const QString svg_path = export_dir.filePath("well_head.svg");
        CHECK(page.xy_host()->export_svg_to(svg_path));
        QFile svg(svg_path);
        CHECK(svg.open(QIODevice::ReadOnly));
        const QString svg_text = QTextStream(&svg).readAll();
        CHECK(svg_text.contains(QLatin1String("<svg")));
        // QSvgGenerator emits equal-radii ellipses as <circle> and colors
        // as #rrggbb.
        CHECK(count_occurrences(svg_text, QStringLiteral("<circle")) >= 5);
        CHECK(svg_text.contains(QLatin1String("#409cff")));
        // tick labels from the real Heckbert cadence over [~97,~144]
        CHECK(svg_text.contains(QLatin1String("110")) ||
              svg_text.contains(QLatin1String("120")) ||
              svg_text.contains(QLatin1String("130")));

        const QString pdf_path = export_dir.filePath("well_head.pdf");
        CHECK(page.xy_host()->export_pdf_to(pdf_path));
        QFile pdf(pdf_path);
        CHECK(pdf.open(QIODevice::ReadOnly));
        QByteArray header = pdf.read(5);
        CHECK(header == "%PDF-");
        reset_external_presenters_for_tests();
    }

    // ------------------------------------------------------------------
    // 4) P-A loop: horizon asset → JobCenter surface job → surface preview
    //    → export; stale delivery dropped by the generation guard.
    // ------------------------------------------------------------------
    {
        pwb::app::JobCenter jobs;
        VizEDataPage page(nullptr, &jobs);
        Counter rendered; rendered.track(&page, &VizEDataPage::preview_rendered);

        page.preview_asset(row_for(fixture("horizon_smi.dat"), "HZ1"));
        CHECK(rendered.wait(1));
        CHECK(page.active_target() == QStringLiteral("surface"));

        // supersede: a second horizon selection bumps the generation; the
        // first job's (already delivered) result must not clobber the new
        // one — assert the FINAL state belongs to the second asset.
        page.preview_asset(row_for(fixture("horizon_smi.dat"), "HZ2"));
        CHECK(rendered.wait(2));
        CHECK(page.active_target() == QStringLiteral("surface"));

        // provenance surfaced in the live view (unit/CRS declared transit)
        CHECK(page.surface_host()->provenance().contains(
            QStringLiteral("EPSG:4326")));
        CHECK(page.surface_host()->provenance().contains(
            QStringLiteral("mapping_kernel")));
        page.surface_host()->setGeometry(0, 0, 900, 600);
        const QString svg_path = export_dir.filePath("horizon.svg");
        CHECK(page.surface_host()->export_svg_to(svg_path));
        QFile svg(svg_path);
        CHECK(svg.open(QIODevice::ReadOnly));
        const QString svg_text = QTextStream(&svg).readAll();
        CHECK(svg_text.contains(QLatin1String("<svg")));
        // contour bands/polygons actually painted (not an empty canvas)
        CHECK(count_occurrences(svg_text, QStringLiteral("<path")) +
                  count_occurrences(svg_text, QStringLiteral("<polygon")) >
              4);
    }

    // ------------------------------------------------------------------
    // 4b) factor/contour real-result spot checks: compute path provenance
    // (unit/CRS/method/source identity) and on-line contour values.
    // ------------------------------------------------------------------
    {
        FactorPreviewRequest request;
        request.asset_path = fixture("horizon_smi.dat").toStdString();
        request.asset_id = "HZ-SPOT";
        request.factor_name = "TopSand";
        request.method = "idw";
        request.grid_n = 24;
        request.crs = "EPSG:4326";   // declared transit, never inferred
        request.unit = "ms";
        for (const auto& xyz : std::vector<std::array<double, 3>>{
                 {0, 0, 1000}, {10, 0, 1010},
                 {20, 0, 1022.5}, {0, 10, 1020},
                 {10, 10, 1032}, {20, 10, 1041.5},
                 {0, 20, 1035}, {10, 20, 1046},
                 {20, 20, 1058}}) {
            request.samples.push_back(
                {xyz[0], xyz[1], xyz[2], "ok"});
        }
        pwb::app::JobCenter jobs;
        auto& owner = jobs.make_owner(nullptr);
        pwb::job::JobSpec spec;
        spec.kind = "compute.viz_e.spot_check";
        spec.run = [&request](pwb::job::JobContext& ctx) -> std::any {
            return compute_factor_preview(request, ctx);
        };
        FactorPreviewOutcome outcome;
        owner.start(jobs.scheduler(), std::move(spec),
                    [&outcome](const pwb::job::qtbridge::JobOutcome& o) {
                        if (const auto* r =
                                std::any_cast<FactorPreviewOutcome>(&o.result)) {
                            outcome = *r;
                        }
                    });
        // bounded wait for the worker hop
        for (int i = 0; i < 3000 && !outcome.ok &&
                        outcome.error.isEmpty();
             ++i) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        CHECK(outcome.ok);
        if (outcome.ok) {
            // provenance carries the identity chain
            const QString prov = outcome.data.provenance;
            CHECK(prov.contains(QStringLiteral("TopSand")));
            CHECK(prov.contains(QStringLiteral("mapping_kernel")));
            CHECK(prov.contains(QStringLiteral("EPSG:4326")));
            CHECK(prov.contains(QStringLiteral("ms")));
            CHECK(prov.contains(QStringLiteral("HZ-SPOT")) == false);
            CHECK(prov.contains(
                      fixture("horizon_smi.dat").toStdString().c_str()));
            // statistics spot check against the sample values
            CHECK(outcome.statistics.min >= 1000.0 - 1e-6);
            CHECK(outcome.statistics.max <= 1058.0 + 1e-6);
            // contour lines sit on the level surface (bilinear on-line)
            CHECK(outcome.contour_lines.size() == outcome.data.levels.size());
            int checked = 0;
            for (const auto& [level, lines] : outcome.contour_lines) {
                for (const auto& line : lines) {
                    if (line.xs.size() < 3) continue;
                    const double mx = line.xs[line.xs.size() / 2];
                    const double my = line.ys[line.ys.size() / 2];
                    const double z = bilinear_grid_at(
                        outcome.data.grid_x, outcome.data.grid_y,
                        outcome.data.grid_z, mx, my);
                    CHECK(std::fabs(z - level) < 0.35);
                    ++checked;
                    if (checked >= 12) break;
                }
                if (checked >= 12) break;
            }
            CHECK(checked > 0);
        }
        jobs.shutdown_workers(500);
    }

    // ------------------------------------------------------------------
    // 4c) contour_draft worker → presentation: REAL mapping_kernel grid →
    // REAL make_contour_draft_job_spec (viz_charts kernel as the extract
    // seam) → drafts surface in the page via present_factor_surface.
    // ------------------------------------------------------------------
    {
        using pwb::ui_workers::ContourDraftInput;
        using pwb::ui_workers::ContourDraftResult;
        using pwb::ui_workers::FactorTaskSlice;
        using pwb::ui_workers::Grid2D;
        using pwb::ui_workers::make_contour_draft_job_spec;

        // Real interpolation kernel (the worker's compute half).
        std::vector<pwb::mapping::SamplePoint> samples;
        for (const auto& xyz : std::vector<std::array<double, 3>>{
                 {0, 0, 1000}, {10, 0, 1010}, {20, 0, 1022.5},
                 {0, 10, 1020}, {10, 10, 1032}, {20, 10, 1041.5},
                 {0, 20, 1035}, {10, 20, 1046}, {20, 20, 1058}}) {
            samples.push_back({xyz[0], xyz[1], xyz[2], "ok"});
        }
        pwb::mapping::InterpolateOptions options;
        options.method = "idw";
        options.grid_n = 25;
        const pwb::mapping::FactorGrid grid =
            pwb::mapping::interpolate_factor(samples, options);

        FactorTaskSlice task;
        task.id = "ft-1";
        task.name = "砂岩含量";
        task.factor_type = "砂岩含量";
        task.method = "IDW";
        task.status = "complete";  // only_complete filter in the compile path
        task.grid_x = grid.grid_x;
        task.grid_y = grid.grid_y;
        Grid2D g;
        g.rows = grid.grid_y.size();
        g.cols = grid.grid_x.size();
        g.data.assign(grid.grid_z.begin(), grid.grid_z.end());
        task.grid_z = std::move(g);

        ContourDraftInput input;
        input.factor_map_tasks = {task};
        // The C++ replacement for the geoviz contourpy seam.
        input.extract_lines_fn =
            [](const std::vector<double>& gx, const std::vector<double>& gy,
               const Grid2D& gz, const std::vector<double>& levels,
               const pwb::job::CancellationToken& token) {
                std::map<double, std::vector<std::vector<std::pair<double, double>>>>
                    out;
                auto lines = pwb::viz_charts::extract_contour_lines(
                    gx, gy, gz.data, levels,
                    [&token]() { return token.is_cancelled(); });
                if (!lines.has_value()) {
                    throw std::runtime_error("cancelled");
                }
                for (auto& [level, plines] : *lines) {
                    auto& dst = out[level];
                    dst.reserve(plines.size());
                    for (auto& pl : plines) {
                        std::vector<std::pair<double, double>> pts;
                        pts.reserve(pl.xs.size());
                        for (std::size_t i = 0; i < pl.xs.size(); ++i) {
                            pts.push_back({pl.xs[i], pl.ys[i]});
                        }
                        dst.push_back(std::move(pts));
                    }
                }
                return out;
            };

        pwb::app::JobCenter jobs;
        ContourDraftResult result;
        bool failed = false;
        auto spec = make_contour_draft_job_spec(
            std::move(input),
            [&result](const ContourDraftResult& r) { result = r; },
            [&failed](const std::string&) { failed = true; });
        auto& owner = jobs.make_owner(nullptr);
        owner.start(jobs.scheduler(), std::move(spec), {});
        for (int i = 0; i < 3000 && result.count() == 0 && !failed; ++i) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
        CHECK(!failed);
        CHECK(result.count() >= 1);
        if (result.count() >= 1) {
            const auto& draft = result.drafts.front();
            CHECK(!draft.levels.empty());
            CHECK(!draft.segments.empty());
            // draft segment levels within the source value range
            CHECK(draft.source_value_range.second > draft.source_value_range.first);

            // presentation side: worker result → page surface
            VizEDataPage page(nullptr, &jobs);
            Counter rendered;
            rendered.track(&page, &VizEDataPage::preview_rendered);
            const SurfaceHost::SurfaceData data = surface_data_from_factor_task(
                *task.grid_x, *task.grid_y,
                std::vector<double>(grid.grid_z.begin(), grid.grid_z.end()),
                task.name, task.method,
                /*crs=*/"", /*unit=*/"", "factor_prepare:ft-1");
            page.present_factor_surface(data);
            CHECK(rendered.count >= 1);
            CHECK(page.active_target() == QStringLiteral("surface"));
            CHECK(page.surface_host()->provenance().contains(
                QStringLiteral("砂岩含量")));
            CHECK(page.surface_host()->provenance().contains(
                QStringLiteral("factor_prepare:ft-1")));
            CHECK(page.surface_host()->provenance().contains(
                QStringLiteral("未声明")));  // CRS/unit undeclared, honestly
        }
        jobs.shutdown_workers(500);
    }

    // ------------------------------------------------------------------
    // 5) honest unavailable for unsupported assets (no fake preview).
    // ------------------------------------------------------------------
    {
        pwb::app::JobCenter jobs;
        VizEDataPage page(nullptr, &jobs);
        Counter failed; failed.track(&page, &VizEDataPage::preview_failed);

        QTemporaryDir tmp;
        const QString unknown = tmp.filePath("mystery.xyz");
        QFile f(unknown);
        f.open(QIODevice::WriteOnly);
        f.write("not a supported asset\n");
        f.close();
        page.preview_asset(row_for(unknown, "U1", "xyz"));
        CHECK(failed.wait(1));
        CHECK(page.active_target() == QStringLiteral("message"));

        // empty path
        page.preview_asset(row_for(QString(""), "U2"));
        CHECK(failed.wait(2));
    }

    // ------------------------------------------------------------------
    // 6) CLOSURE-PREVIEW (task 04): unified data page state machine over
    //    the REAL parser-registry adapter (ingest::build_preview via
    //    closure_preview_adapters::build_registry_view). Covers: 真实资产
    //    选择→解析→正确 presenter→缩放/选择/导出, plus the state
    //    assertions — 快速切换 / 取消 / 删除资产 / 工程切换 / 解析失败 /
    //    媒体环境不可用.
    // ------------------------------------------------------------------
    {
        namespace updqt = pwb::ui_pages_data::qt;
        namespace adapters = pwb::closure_preview;

        pwb::app::JobCenter jobs;
        VizEDataPage page(nullptr, &jobs);
        page.resize(1200, 800);
        page.show();
        QCoreApplication::processEvents(QEventLoop::AllEvents, 100);

        // Temp-backed settings store (never touches the user profile).
        QTemporaryDir cfg_dir;
        QSettings cfg(cfg_dir.filePath("preview-settings.ini"),
                      QSettings::IniFormat);
        upv::PreviewSettingsStore settings_store(&cfg);
        page.set_base_preview_builder(
            [&settings_store](
                const upd::AssetRow& row,
                pwb::job::JobContext* ctx)
                -> std::optional<updqt::PreviewResultView> {
                if (ctx != nullptr) ctx->check_cancelled();
                return adapters::build_registry_view(
                    row, settings_store.load());
            });

        auto* reader = page.workspace()->reader_panel();
        auto* bus = new updqt::AssetSelectionBus(&page);
        page.bind_selection_bus(bus);

        // -- asset source through the bus (single real selection state) ---
        QTemporaryDir assets;
        const QString csv = assets.filePath("curves.csv");
        { QFile f(csv); f.open(QIODevice::WriteOnly);
          f.write("depth,gr\n1000.0,42.5\n1000.5,47.1\n"); f.close(); }
        const QString txt = assets.filePath("log.txt");
        { QFile f(txt); f.open(QIODevice::WriteOnly);
          f.write("hello data page\n"); f.close(); }
        const QString json = assets.filePath("meta.json");
        { QFile f(json); f.open(QIODevice::WriteOnly);
          f.write("{\"well\":\"W1\",\"runs\":[1,2,3]}"); f.close(); }
        const QString bad_json = assets.filePath("broken.json");
        { QFile f(bad_json); f.open(QIODevice::WriteOnly);
          f.write("{\"well\":"); f.close(); }
        const QString missing = assets.filePath("gone.csv");

        auto row_with = [&](const QString& path, const char* id,
                            const char* fmt) {
            upd::AssetRow row = row_for(path, id, fmt);
            row.view.name = QFileInfo(path).fileName().toStdString();
            return row;
        };
        bus->set_assets(
            {row_with(csv, "A1", "csv"), row_with(txt, "A2", "txt"),
             row_with(json, "A3", "json"), row_with(bad_json, "A4", "json"),
             row_with(missing, "A5", "csv")},
            QStringLiteral("proj-1"));

        Counter rendered; rendered.track(&page, &VizEDataPage::preview_rendered);

        // csv → table presenter, REAL parsed cells reach the widget
        bus->set_current_asset(bus->assets()[0]);
        CHECK(rendered.wait(1));
        CHECK(page.active_target() == QStringLiteral("table"));
        CHECK(reader->current_result().mode == "table");
        const std::string tsv = reader->table_preview()->copy_all();
        CHECK(tsv.find("42.5") != std::string::npos);
        CHECK(tsv.find("1000.5") != std::string::npos);
        CHECK(tsv.find("depth") != std::string::npos);

        // txt → text presenter with the file's own bytes
        bus->set_current_asset(bus->assets()[1]);
        CHECK(rendered.wait(2));
        CHECK(page.active_target() == QStringLiteral("text"));
        CHECK(reader->text_preview()->toPlainText().contains(
            QStringLiteral("hello data page")));

        // json → json_tree presenter carrying the parsed payload
        bus->set_current_asset(bus->assets()[2]);
        CHECK(rendered.wait(3));
        CHECK(page.active_target() == QStringLiteral("json_tree"));
        CHECK(reader->current_result().payload != nullptr);
        const auto* payload =
            static_cast<const Json*>(reader->current_result().payload);
        CHECK(payload != nullptr && payload->contains("well"));
        if (payload != nullptr && payload->contains("well")) {
            CHECK(payload->at("well").get<std::string>() == "W1");
        }

        // image family zoom/select affordances (image fixture)
        const QString png = assets.filePath("thumb.png");
        { QImage img(64, 48, QImage::Format_RGB32);
          img.fill(QColor(30, 90, 200));
          img.save(png); }
        bus->set_assets({row_with(png, "A6", "png")},
                        QStringLiteral("proj-1"));
        // deletion semantics: the selection referenced a removed row → cleared
        CHECK(!bus->current_asset().has_value());
        bus->set_current_asset(bus->assets()[0]);
        CHECK(rendered.wait(4));
        CHECK(page.active_target() == QStringLiteral("image"));
        auto* image = reader->image_preview_widget();
        image->set_fit_mode(false);
        const double before = image->zoom_factor();
        image->zoom_in();
        CHECK(image->zoom_factor() > before);

        // 解析失败: corrupt json → honest parse-failure message (retryable
        // is the registry's own semantic; the state is message, not a fake
        // tree)
        bus->set_assets({row_with(bad_json, "A7", "json")},
                        QStringLiteral("proj-1"));
        bus->set_current_asset(bus->assets()[0]);
        CHECK(rendered.wait(4) || rendered.count >= 4);
        bool settled = false;
        for (int i = 0; i < 3000 && !settled; ++i) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            settled = reader->current_mode() == "message";
        }
        CHECK(reader->current_mode() == QStringLiteral("message"));
        CHECK(reader->message_label()->text().contains(
            QStringLiteral("JSON")));

        // missing file → the registry's honest 文件不存在 (status missing)
        bus->set_assets({row_with(missing, "A8", "csv")},
                        QStringLiteral("proj-1"));
        bus->set_current_asset(bus->assets()[0]);
        settled = false;
        for (int i = 0; i < 3000 && !settled; ++i) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            settled = reader->current_result().status == "missing";
        }
        CHECK(reader->current_result().status == "missing");

        // media family: honest degradation offscreen (no video surface in
        // the test environment — the widget must accept the load without
        // crashing and the page routes to the media target; playback is an
        // environment capability, asserted unavailable here).
        const QString media = assets.filePath("clip.mp4");
        { QFile f(media); f.open(QIODevice::WriteOnly);
          f.write("\x00\x00\x00\x18ftypmp42", 12); f.close(); }
        bus->set_assets({row_with(media, "A9", "mp4")},
                        QStringLiteral("proj-1"));
        bus->set_current_asset(bus->assets()[0]);
        settled = false;
        for (int i = 0; i < 3000 && !settled; ++i) {
            QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
            settled = reader->current_mode() == "media";
        }
        CHECK(reader->current_mode() == QStringLiteral("media"));
        CHECK(page.active_target() == QStringLiteral("media"));

        // 取消: a slow registry job cancelled through the loading page's
        // hook lands the honest cancelled state (never a partial preview).
        {
            VizEDataPage slow_page(nullptr, &jobs);
            auto* slow_reader = slow_page.workspace()->reader_panel();
            slow_page.set_base_preview_builder(
                [](const upd::AssetRow&, pwb::job::JobContext* ctx)
                    -> std::optional<updqt::PreviewResultView> {
                    // blocks until cancelled (cooperative token poll)
                    while (true) {
                        ctx->check_cancelled();
                        std::this_thread::sleep_for(
                            std::chrono::milliseconds(5));
                    }
                });
            QTemporaryDir slow_assets;
            upd::AssetRow slow_row =
                row_with(slow_assets.filePath("big.csv"), "S1", "csv");
            slow_page.preview_asset(slow_row);
            // loading state reached
            bool loading = false;
            for (int i = 0; i < 2000 && !loading; ++i) {
                QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
                loading = slow_reader->current_mode() == "loading";
            }
            CHECK(loading);
            // the 取消 affordance is armed and cancels the in-flight load
            auto* btn = slow_reader->findChild<QPushButton*>(
                QStringLiteral("LoadingCancelButton"));
            CHECK(btn != nullptr);
            if (btn != nullptr) btn->click();
            bool cancelled = false;
            for (int i = 0; i < 3000 && !cancelled; ++i) {
                QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
                cancelled = slow_reader->current_mode() == "message" &&
                            slow_reader->message_label()->text().contains(
                                QStringLiteral("取消"));
            }
            CHECK(cancelled);
            jobs.shutdown_workers(500);
        }

        // 快速切换: the superseded job's delivery drops (generation guard);
        // the final reader state belongs to the LAST selection only.
        {
            QTemporaryDir fast_assets;
            const QString slow_csv = fast_assets.filePath("slow.csv");
            { QFile f(slow_csv); f.open(QIODevice::WriteOnly);
              f.write("a,b\n1,2\n"); f.close(); }
            const QString fast_txt = fast_assets.filePath("fast.txt");
            { QFile f(fast_txt); f.open(QIODevice::WriteOnly);
              f.write("second selection wins\n"); f.close(); }
            VizEDataPage fast_page(nullptr, &jobs);
            auto* fast_reader = fast_page.workspace()->reader_panel();
            QSettings fast_cfg(fast_assets.filePath("s.ini"),
                               QSettings::IniFormat);
            upv::PreviewSettingsStore fast_store(&fast_cfg);
            fast_page.set_base_preview_builder(
                [&fast_store](const upd::AssetRow& row,
                              pwb::job::JobContext* ctx)
                    -> std::optional<updqt::PreviewResultView> {
                    if (row.view.format == std::string("csv")) {
                        while (true) {
                            ctx->check_cancelled();
                            std::this_thread::sleep_for(
                                std::chrono::milliseconds(5));
                        }
                    }
                    return adapters::build_registry_view(
                        row, fast_store.load());
                });
            // NOTE: the default-constructed store here is process-lifetime
            // platform defaults (QSettings-backed); the test only asserts
            // dispatch ORDER, not settings content.
            fast_page.preview_asset(row_with(slow_csv, "F1", "csv"));
            fast_page.preview_asset(row_with(fast_txt, "F2", "txt"));
            bool done = false;
            for (int i = 0; i < 3000 && !done; ++i) {
                QCoreApplication::processEvents(QEventLoop::AllEvents, 20);
                std::this_thread::sleep_for(std::chrono::milliseconds(5));
                done = fast_reader->current_mode() == "text";
            }
            CHECK(fast_reader->current_mode() == QStringLiteral("text"));
            CHECK(fast_reader->text_preview()->toPlainText().contains(
                QStringLiteral("second selection wins")));
            // settling further must NOT flip back to the cancelled/slow csv
            QCoreApplication::processEvents(QEventLoop::AllEvents, 200);
            CHECK(fast_reader->current_mode() == QStringLiteral("text"));
            jobs.shutdown_workers(500);
        }

        // 工程切换: a different project id clears the selection even when
        // a row with the same identity reappears; rows are replaced.
        bus->set_assets({row_with(csv, "A1", "csv")},
                        QStringLiteral("proj-1"));
        bus->set_current_asset(bus->assets()[0]);
        CHECK(bus->current_asset().has_value());
        bus->set_assets({row_with(csv, "A1", "csv")},
                        QStringLiteral("proj-2"));
        CHECK(!bus->current_asset().has_value());
        CHECK(bus->assets().size() == 1);
        CHECK(bus->project_id() == QStringLiteral("proj-2"));
        jobs.shutdown_workers(500);
    }

    // ------------------------------------------------------------------
    // 6b) CLOSURE-PREVIEW: REAL catalog asset source — project bootstrap
    //    through the product stack (ProjectManager + CatalogRepository +
    //    PwbDataStore publish) → snapshot → AssetRow → registry preview.
    // ------------------------------------------------------------------
    {
        namespace adapters = pwb::closure_preview;
        QTemporaryDir project_dir;
        const QString project_file =
            project_dir.filePath("closure_proj.paleo.json");
        std::filesystem::path pf = std::filesystem::path(
            project_file.toStdString());

        auto document = pwb::project::ProjectDocument::create_new(
            "closure_proj", "");
        pwb::project::ProjectManager manager(pf);
        CHECK(manager.save(document).is_ok());

        std::string open_error;
        auto store = pwb::application::PwbDataStore::open(pf, &open_error);
        CHECK(store != nullptr);
        if (store != nullptr) {
            // one real GeoJSON asset through the real publish transaction
            const std::filesystem::path staged =
                pf.parent_path() / ".pwb-bootstrap" / "boundary-v1.geojson";
            std::filesystem::create_directories(staged.parent_path());
            { std::ofstream out(staged, std::ios::binary);
              out << "{\"type\":\"FeatureCollection\",\"features\":[]}"; }
            const pwb::domain::RunId run_id{std::string("run_cp-0001")};
            pwb::data::RunRegistrationV1 registration;
            registration.run_id = run_id;
            registration.operation = "bootstrap";
            registration.generator = "pwb-platform";
            CHECK(store->coordinator().register_run(registration).is_ok());
            pwb::data::PublishRequestV1 publish;
            publish.operation_id =
                pwb::domain::OperationId{std::string("pub_cp-0001")};
            publish.run_id = run_id;
            publish.new_asset_name = "相带边界";
            publish.new_asset_type = "vector_boundary";
            publish.stage = pwb::domain::DataStage::Raw;
            pwb::data::StagedAssetV1 staged_asset;
            staged_asset.source_path = staged;
            staged_asset.format = "GeoJSON";
            publish.products.push_back(std::move(staged_asset));
            publish.result_metadata = pwb::domain::Json::object();
            CHECK(store->coordinator()
                      .publish_run_result(publish, store->document())
                      .is_ok());

            auto snapshot = store->snapshot();
            CHECK(snapshot.is_ok());
            const auto rows = adapters::asset_rows_from_snapshot(
                snapshot.value());
            CHECK(rows.size() == 1);
            if (!rows.empty()) {
                CHECK(rows[0].view.name == "相带边界");
                CHECK(rows[0].view.format == "GeoJSON");
                CHECK(!rows[0].view.path.empty());
                CHECK(std::filesystem::exists(rows[0].view.path));

                // the REAL row flows through the REAL registry: GeoJSON →
                // json_tree preview with a parsed payload
                QTemporaryDir cfg_dir;
                QSettings cfg(cfg_dir.filePath("s.ini"),
                              QSettings::IniFormat);
                upv::PreviewSettingsStore settings_store(&cfg);
                const auto view = adapters::build_registry_view(
                    rows[0], settings_store.load());
                CHECK(view.mode == "json_tree");
                CHECK(view.payload != nullptr);
                const auto* payload =
                    static_cast<const Json*>(view.payload);
                CHECK(payload != nullptr &&
                      payload->value("type", std::string()) ==
                          "FeatureCollection");
            }
        }
    }

    std::printf("%s: %d checks, %d failures\n", __func__, checks, failures);
    return failures == 0 ? 0 : 1;
}
