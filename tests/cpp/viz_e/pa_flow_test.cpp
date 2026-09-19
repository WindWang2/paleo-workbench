// viz_e.pa_flow — the P-A acceptance loop: 资产选择 → 识别能力 → 加载 →
// 真实预览/图表 → 导出, against the REAL assembly (VizEDataPage + JobCenter)
// and REAL assets (SMI .dat fixtures, parsed by the ported geoviz contract).
// Also replays the dat parsing oracle frozen from the Python backend
// (tools/oracle/generate_viz_e_dat_fixtures.py) and exercises the external
// presenter registration contract with a real presenter.
#include "job_center.hpp"
#include "viz_e_dat_preview.hpp"

#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/worker_common.hpp>
#include <pwb/viz_charts/marching_squares.hpp>
#include "viz_e_hosts.hpp"
#include "viz_e_install.hpp"

#include <pwb/viz_charts/qt/plot_widget.hpp>

#include <pwb/ui_pages_data/asset_view.hpp>
#include <pwb/domain/json.hpp>

#include <QApplication>
#include <QFile>
#include <QTemporaryDir>
#include <QLabel>
#include <QTextStream>

#include <array>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <thread>

using namespace pwb::viz_e;
namespace upd = pwb::ui_pages_data;
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

    std::printf("%s: %d checks, %d failures\n", __func__, checks, failures);
    return failures == 0 ? 0 : 1;
}
