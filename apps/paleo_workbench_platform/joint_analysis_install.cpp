// joint_analysis_install.cpp — see joint_analysis_install.hpp for the
// wiring contract. Every hook below runs a native kernel that already
// existed at this HEAD; this install is product wiring only.
#include "joint_analysis_install.hpp"

#ifdef PWB_WITH_UI_WELLSEIS

#include <QDialog>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QMessageBox>
#include <QTextBrowser>
#include <QVBoxLayout>

#include <cmath>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/advisor_contract.hpp>
#include <pwb/geo3d_viz/joint/joint_scene.hpp>
#include <pwb/geo3d_viz/joint/registration.hpp>
#include <pwb/geo3d_viz/scene_object_manager.hpp>
#include <pwb/job_runtime/qt/job_bridge.hpp>
#include <pwb/seismic_viewer/crossplot_core.hpp>
#include <pwb/seismic_viewer/horizon_core.hpp>
#include <pwb/ui_workers/geological_modeling.hpp>
#include <pwb/ui_wellseis/joint_state.hpp>
#include <pwb/viz/well_tie/auto_tie.hpp>
#include <pwb/viz/well_tie/synthetic.hpp>

#include "geo3d_dock.hpp"
#include "job_center.hpp"
#include "viz_c_joint_host.hpp"

namespace pwb::app::joint_analysis {
namespace {

using pwb::domain::Json;
using pwb::geo3d_viz::ObjectKind;
using pwb::geo3d_viz::ObjectMode;
using pwb::geo3d_viz::Rgba;
using pwb::geo3d_viz::SceneObject;
using pwb::geo3d_viz::SceneObjectManager;
using Page = pwb::ui_wellseis::qt::GeologicalModeling3DPage;
using pwb::ui_wellseis::qt::Geo3DAnalysisHooks;
using pwb::ui_workers::Grid2D;
using Registration = pwb::geo3d_viz::joint::VolumeRegistration;

constexpr const char* kStratalOverlayPrefix = "analysis:stratal-";
constexpr const char* kRgbOverlayName = "analysis:rgb";
// Python stratal footprint color (0.85, 0.45, 0.95) purple at 0.8 alpha.
constexpr Rgba kStratalColor{0.85f, 0.45f, 0.95f, 0.8f};

// ---- sidecar persistence (cross_well_workspace.json pattern) --------------

QString sidecar_path(const JointAnalysisInstall& deps) {
    const QString dir =
        deps.project_directory ? deps.project_directory() : QString();
    if (dir.isEmpty()) {
        return QString();
    }
    return dir + QStringLiteral("/joint_analysis.json");
}

std::optional<pwb::ui_wellseis::JointAnalysisSlice> read_stored_state(
    const JointAnalysisInstall& deps) {
    const QString path = sidecar_path(deps);
    if (path.isEmpty() || !QFileInfo::exists(path)) {
        return std::nullopt;
    }
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        return std::nullopt;
    }
    try {
        return pwb::ui_wellseis::joint_state_from_json(
            Json::parse(file.readAll().toStdString()));
    } catch (const std::exception&) {
        return std::nullopt;  // corrupt sidecar never blocks a project open
    }
}

void write_stored_state(const JointAnalysisInstall& deps,
                        const pwb::ui_wellseis::JointAnalysisSlice& state) {
    const QString path = sidecar_path(deps);
    if (path.isEmpty()) {
        return;
    }
    QFile file(path);
    if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        return;
    }
    file.write(QByteArray::fromStdString(
        pwb::ui_wellseis::joint_state_to_json(state).dump(2)));
}

// ---- bh placeholder records (Python _sync_bh_raw_from_joint_scene) --------

Json borehole_records(const pwb::app::viz_c::VizCJointHost* host) {
    Json out = Json::array();
    if (host == nullptr) {
        return out;
    }
    for (const auto& well : host->scene().wells()) {
        if (well.total_depth_m <= 0) {
            continue;
        }
        Json record = Json::object();
        record["name"] = well.name;
        record["x"] = well.x;
        record["y"] = well.y;
        record["total_depth"] = well.total_depth_m;
        record["layers"] = Json::array({Json::object(
            {{"top", 0.0},
             {"bottom", well.total_depth_m},
             {"lithology", "未分层"}})});
        out.push_back(std::move(record));
    }
    return out;
}

// ---- analysis overlays ------------------------------------------------------

// One colored quad-grid mesh overlay from a sample-index surface grid
// (rows = preview inlines, cols = preview crosslines). With a
// registration the XY comes from the survey and z from the time axis;
// the demo path places the grid on the ±80 demo footprint instead.
void add_stratal_overlay(SceneObjectManager& manager, const std::string& label,
                         const Grid2D& surface, const Registration* reg) {
    SceneObject object;
    object.name = kStratalOverlayPrefix + label;
    object.kind = ObjectKind::Horizon;
    object.mode = ObjectMode::Mesh;
    object.opacity = 0.8f;
    object.color = kStratalColor;
    object.pickable = false;
    constexpr double kDemoSpan = 80.0;
    const double demo_k = 40.0 / 32.0;  // demo volume sample span
    object.verts.reserve(surface.rows * surface.cols);
    for (std::size_t i = 0; i < surface.rows; ++i) {
        for (std::size_t x = 0; x < surface.cols; ++x) {
            const double s = surface.at(i, x);
            double wx = 0.0;
            double wy = 0.0;
            double wz = 0.0;
            if (reg != nullptr) {
                const auto [il, xl] = reg->volume_idx_to_il_xl(
                    static_cast<double>(i), static_cast<double>(x));
                const auto [sx, sy] =
                    reg->survey().il_xl_to_xy(il, xl);
                wx = sx;
                wy = sy;
                wz = reg->sample_idx_to_time_ms(s);
            } else {
                wx = surface.cols > 1
                         ? -kDemoSpan +
                               2.0 * kDemoSpan * static_cast<double>(x) /
                                   static_cast<double>(surface.cols - 1)
                         : 0.0;
                wy = surface.rows > 1
                         ? -kDemoSpan +
                               2.0 * kDemoSpan * static_cast<double>(i) /
                                   static_cast<double>(surface.rows - 1)
                         : 0.0;
                wz = -s * demo_k;
            }
            object.verts.push_back({static_cast<float>(wx),
                                    static_cast<float>(wy),
                                    static_cast<float>(wz)});
        }
    }
    for (std::size_t i = 0; i + 1 < surface.rows; ++i) {
        for (std::size_t x = 0; x + 1 < surface.cols; ++x) {
            const std::int64_t a = static_cast<std::int64_t>(
                i * surface.cols + x);
            const std::int64_t b = a + 1;
            const std::int64_t c =
                a + static_cast<std::int64_t>(surface.cols);
            const std::int64_t d = c + 1;
            const auto finite = [&](std::int64_t idx) {
                return std::isfinite(object.verts[static_cast<std::size_t>(
                                             idx)][2]);
            };
            if (!(finite(a) && finite(b) && finite(c) && finite(d))) {
                continue;
            }
            object.faces.push_back({a, b, c});
            object.faces.push_back({b, d, c});
        }
    }
    if (object.faces.empty()) {
        return;  // all-NaN surface: nothing honest to draw
    }
    manager.add(std::move(object));
}

void clear_stratal_overlays(SceneObjectManager* manager) {
    if (manager == nullptr) {
        return;
    }
    for (const std::string& name : manager->names()) {
        if (name.rfind(kStratalOverlayPrefix, 0) == 0) {
            manager->remove(name);
        }
    }
}

// demo.rgb_fusion_geometry (40x40) — deterministic port of
// paleo_workbench/viz/geomodel/demo.py:62-96; channel blending is the
// min-max + constant alpha form of geoviz blend_rgba
// (geoviz_seismic/attributes.py:260).
void add_rgb_fusion_overlay(SceneObjectManager& manager) {
    constexpr int kN = 40;
    constexpr double kSpan = 80.0;
    std::vector<double> ch_r(static_cast<std::size_t>(kN) * kN);
    std::vector<double> ch_g(ch_r.size());
    std::vector<double> ch_b(ch_r.size());
    SceneObject object;
    object.name = kRgbOverlayName;
    object.kind = ObjectKind::Horizon;
    object.mode = ObjectMode::Mesh;
    object.opacity = 0.85f;
    object.pickable = false;
    object.verts.reserve(ch_r.size());
    for (int j = 0; j < kN; ++j) {
        const double y =
            -kSpan + 2.0 * kSpan * j / (kN - 1);
        for (int i = 0; i < kN; ++i) {
            const double x =
                -kSpan + 2.0 * kSpan * i / (kN - 1);
            const double z =
                -40.0 + 2.0 * std::sin(x / 10.0) * std::cos(y / 10.0);
            const std::size_t idx =
                static_cast<std::size_t>(j) * kN + i;
            object.verts.push_back({static_cast<float>(x),
                                    static_cast<float>(y),
                                    static_cast<float>(z)});
            ch_r[idx] = std::sin(x / 12.0) * std::cos(y / 12.0) + 1.0;
            ch_g[idx] = std::cos(x / 8.0) * std::sin(y / 8.0) + 1.0;
            ch_b[idx] = std::sin(x / 5.0 + y / 5.0) + 1.0;
        }
    }
    const auto minmax = [](std::vector<double>& channel) {
        double lo = channel.front();
        double hi = channel.front();
        for (double v : channel) {
            lo = std::min(lo, v);
            hi = std::max(hi, v);
        }
        if (hi - lo < 1e-8) {
            std::fill(channel.begin(), channel.end(), 0.0);
            return;
        }
        for (double& v : channel) {
            v = (v - lo) / (hi - lo);
        }
    };
    minmax(ch_r);
    minmax(ch_g);
    minmax(ch_b);
    object.face_colors.reserve(
        static_cast<std::size_t>(kN - 1) * (kN - 1) * 2);
    for (int j = 0; j + 1 < kN; ++j) {
        for (int i = 0; i + 1 < kN; ++i) {
            const std::int64_t idx = static_cast<std::int64_t>(j) * kN + i;
            const std::size_t src = static_cast<std::size_t>(idx);
            const Rgba color{static_cast<float>(ch_r[src]),
                             static_cast<float>(ch_g[src]),
                             static_cast<float>(ch_b[src]), 0.85f};
            object.faces.push_back({idx, idx + 1, idx + kN});
            object.faces.push_back({idx + 1, idx + kN + 1, idx + kN});
            object.face_colors.push_back(color);
            object.face_colors.push_back(color);
        }
    }
    manager.add(std::move(object));
}

// ---- .dat horizon → preview-aligned sample-index grids ---------------------

// Port of the stratal_adapter.build_stratal_grids data path: parse the
// .dat onto the survey axes (seismic_viewer parse_horizon_text —
// HorizonParser parity), nearest-fill gaps, then sample the stride
// lattice and convert ms → preview sample indices through the
// registration. Exact on the lattice; NaN propagates.
std::optional<std::pair<Grid2D, Grid2D>> build_preview_grids(
    const std::string& top_path, const std::string& bottom_path,
    const Registration& reg, std::string& error) {
    const auto& survey = reg.survey();
    pwb::seismic_viewer::horizon::HorizonAxes axes;
    axes.ilines.reserve(static_cast<std::size_t>(survey.n_inlines));
    axes.xlines.reserve(static_cast<std::size_t>(survey.n_crosslines));
    for (std::int64_t il = 0; il < survey.n_inlines; ++il) {
        axes.ilines.push_back(survey.iline_start + il * survey.iline_step);
    }
    for (std::int64_t xl = 0; xl < survey.n_crosslines; ++xl) {
        axes.xlines.push_back(survey.xline_start + xl * survey.xline_step);
    }

    const auto load =
        [&](const std::string& path) -> std::optional<Grid2D> {
        QFile file(QString::fromStdString(path));
        if (!file.open(QIODevice::ReadOnly)) {
            error = "无法读取 horizon 文件：" + path;
            return std::nullopt;
        }
        const QByteArray text = file.readAll();
        const auto parsed =
            pwb::seismic_viewer::horizon::parse_horizon_text(
                text.toStdString(), axes);
        if (parsed.points_read == 0) {
            error = "horizon 文件无有效数据点：" + path;
            return std::nullopt;
        }
        const auto filled =
            pwb::seismic_viewer::horizon::fill_nearest(parsed.grid, 0.0);
        Grid2D out;
        out.rows = static_cast<std::size_t>(reg.n_inline());
        out.cols = static_cast<std::size_t>(reg.n_crossline());
        out.data.assign(out.rows * out.cols,
                        std::numeric_limits<double>::quiet_NaN());
        const auto strides = reg.strides();
        for (std::size_t i = 0; i < out.rows; ++i) {
            const std::int64_t native_i =
                static_cast<std::int64_t>(i) * strides[0];
            if (native_i >= survey.n_inlines) {
                continue;
            }
            for (std::size_t x = 0; x < out.cols; ++x) {
                const std::int64_t native_x =
                    static_cast<std::int64_t>(x) * strides[1];
                if (native_x >= survey.n_crosslines) {
                    continue;
                }
                const double ms = filled.at(native_i, native_x);
                if (!std::isfinite(ms)) {
                    continue;
                }
                out.at(i, x) = reg.time_ms_to_sample_idx(ms);
            }
        }
        return out;
    };

    auto top = load(top_path);
    if (!top) {
        return std::nullopt;
    }
    auto bottom = load(bottom_path);
    if (!bottom) {
        return std::nullopt;
    }
    return std::make_pair(std::move(*top), std::move(*bottom));
}

// ---- report dialogs ---------------------------------------------------------

void show_report_dialog(QWidget* parent, const QString& title,
                        const QString& html) {
    auto* dialog = new QDialog(parent);
    dialog->setWindowTitle(title);
    dialog->setModal(false);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->resize(560, 420);
    auto* layout = new QVBoxLayout(dialog);
    auto* browser = new QTextBrowser(dialog);
    browser->setHtml(html);
    layout->addWidget(browser);
    dialog->show();
    dialog->raise();
    dialog->activateWindow();
}

// advisor report shape: {checked_*: N, issues: [{type, <who>, message}],
// status: PASS|FAIL} — who key varies (name/well/fault).
QString issue_row(const Json& issue) {
    QString who;
    for (auto it = issue.begin(); it != issue.end(); ++it) {
        if (it.key() != "type" && it.key() != "message" &&
            it.value().is_string()) {
            who = QString::fromStdString(it.value().get<std::string>());
            break;
        }
    }
    const std::string type = issue.value("type", "");
    const std::string msg = issue.value("message", "");
    const QString badge =
        type == "error" ? QStringLiteral("<b>FAIL</b>")
                        : QStringLiteral("WARNING");
    return QStringLiteral("<tr><td>%1</td><td>%2</td><td>%3</td></tr>")
        .arg(badge, who, QString::fromStdString(msg));
}

QString report_table(const Json& report, const QString& checked_key) {
    if (!report.is_object()) {
        return QStringLiteral("<p>（无报告）</p>");
    }
    QString rows;
    if (report.contains("issues") && report["issues"].is_array()) {
        for (const auto& issue : report["issues"]) {
            rows += issue_row(issue);
        }
    }
    QString out = QStringLiteral(
                      "<p>检查对象：%1　状态：%2</p>")
                      .arg(report.value(checked_key.toStdString(),
                                        std::string("—"))
                               .c_str())
                      .arg(report.value("status", "—").c_str());
    if (!rows.isEmpty()) {
        out += QStringLiteral(
            "<table border='1' cellspacing='0' cellpadding='3' "
            "width='100%'><tr><th>级别</th><th>对象</th><th>详情</th></tr>"
            "%1</table>")
                   .arg(rows);
    } else {
        out += QStringLiteral("<p>未发现问题。</p>");
    }
    return out;
}

}  // namespace

std::optional<pwb::ui_wellseis::JointAnalysisSlice> load_stored(
    const QString& project_directory) {
    JointAnalysisInstall deps;
    deps.project_directory =
        [&project_directory]() { return project_directory; };
    return read_stored_state(deps);
}

Geo3DAnalysisHooks make_hooks(const JointAnalysisInstall& deps) {
    auto state = std::make_shared<JointAnalysisInstall>(deps);

    Geo3DAnalysisHooks hooks;

    // ---- persistence -------------------------------------------------------
    hooks.stored_state = [state] { return read_stored_state(*state); };
    hooks.save_state = [state](const auto& slice) {
        write_stored_state(*state, slice);
    };

    // ---- horizon sources ---------------------------------------------------
    hooks.pick_horizon_file = [state](const QString& title) {
        return QFileDialog::getOpenFileName(
            state->dialog_parent, title, QString(),
            QStringLiteral("Horizon (*.dat);;所有文件 (*)"));
    };
    // Versioned interpretation entries are not yet carried by the native
    // project store schema (horizon_interpretations lives in the Python
    // project document); the .dat browse path covers the native product
    // flow and this seam stays honestly empty rather than fabricated.
    hooks.horizon_interpretations =
        [](const QString&) {
            return std::vector<std::pair<std::string, std::string>>{};
        };

    // ---- stratal -----------------------------------------------------------
    hooks.generate_stratal =
        [state](const std::string& top_entry,
                const std::string& bottom_entry,
                const std::vector<double>& fractions, bool demo) {
            Page* the_page = state->page;
            if (the_page == nullptr) {
                return;
            }
            const auto fail = [the_page](const QString& text) {
                the_page->set_stratal_status(text);
            };
            if (state->jobs == nullptr) {
                fail(QStringLiteral("任务运行时不可用，无法生成地层切片。"));
                return;
            }
            pwb::ui_workers::StratalInput input;
            input.demo = demo;
            input.fractions = fractions;
            const Registration* reg =
                state->host != nullptr
                    ? state->host->scene().registration()
                    : nullptr;
            if (!demo) {
                if (top_entry.empty() || bottom_entry.empty()) {
                    fail(QStringLiteral(
                        "请先选择顶部与底部 horizon（.dat 或解释版本）。"));
                    return;
                }
                if (reg == nullptr) {
                    fail(QStringLiteral(
                        "survey/registration 不可用或体数据未就绪，无法对齐 "
                        "horizon。"));
                    return;
                }
                const auto trim = [](const std::string& entry) {
                    const std::string prefix = "interp:";
                    return entry.rfind(prefix, 0) == 0
                               ? entry.substr(prefix.size())
                               : entry;
                };
                std::string error;
                auto grids = build_preview_grids(
                    trim(top_entry), trim(bottom_entry), *reg, error);
                if (!grids) {
                    fail(QString::fromStdString(error));
                    return;
                }
                input.preview_grids = std::move(grids);
                input.n_i_prev =
                    static_cast<std::size_t>(reg->n_inline());
                input.n_x_prev =
                    static_cast<std::size_t>(reg->n_crossline());
                input.n_s_prev =
                    static_cast<std::size_t>(reg->n_sample());
            }
            auto& owner =
                state->jobs->make_owner(state->dialog_parent);
            the_page->set_stratal_status(
                demo ? QStringLiteral("正在生成演示地层切片…")
                     : QStringLiteral("正在计算比例地层切片…"));
            auto spec = pwb::ui_workers::make_stratal_job_spec(
                std::move(input),
                [state, demo](const pwb::ui_workers::StratalResult& result) {
                    // Overlays are scene state, not page state: add them
                    // regardless of the page (a null page only drops the
                    // status line — the test rig drives the same path).
                    if (state->scene_objects == nullptr) {
                        if (state->page != nullptr) {
                            state->page->set_stratal_status(QStringLiteral(
                                "3D 视口尚未就绪，无法预览。"));
                        }
                        return;
                    }
                    const Registration* reg =
                        !demo && state->host != nullptr
                            ? state->host->scene().registration()
                            : nullptr;
                    clear_stratal_overlays(state->scene_objects);
                    for (std::size_t k = 0;
                         k < result.surfaces.size() &&
                         k < result.labels.size();
                         ++k) {
                        add_stratal_overlay(*state->scene_objects,
                                            result.labels[k],
                                            result.surfaces[k], reg);
                    }
                    if (state->page != nullptr) {
                        state->page->set_stratal_status(
                            demo
                                ? QStringLiteral(
                                      "已用合成演示体生成 %1 张比例切片（演示"
                                      "预览模式）。")
                                      .arg(result.surfaces.size())
                                : QStringLiteral("已生成 %1 张比例地层切片。")
                                      .arg(result.surfaces.size()));
                    }
                },
                [the_page](const std::string& error) {
                    if (the_page != nullptr) {
                        the_page->set_stratal_status(
                            QString::fromStdString(error));
                    }
                });
            owner.start(state->jobs->scheduler(), std::move(spec),
                        [](const pwb::job::qtbridge::JobOutcome&) {});
        };
    hooks.clear_stratal = [state] {
        clear_stratal_overlays(state->scene_objects);
        if (state->page != nullptr) {
            state->page->set_stratal_status(
                QStringLiteral("已清除地层切片。"));
        }
    };

    // ---- well tie ----------------------------------------------------------
    // Python parity: the joint page builds placeholder single-layer
    // records ("未分层" → lithology defaults), so the synthetic is
    // constant and the tie fails honestly. Real well tie runs on the
    // VIZ-B dock with actual LAS logs (calibration + auto-tie + export).
    auto tie_freq = std::make_shared<int>(30);
    hooks.tie_params_changed = [tie_freq](int freq, int shift) {
        Q_UNUSED(shift);
        *tie_freq = freq;
    };
    hooks.run_auto_tie = [state, tie_freq] {
        QWidget* parent = state->dialog_parent;
        const Json wells = borehole_records(state->host);
        if (wells.empty()) {
            QMessageBox::information(
                parent, QStringLiteral("提示"),
                QStringLiteral("联合场景中没有井数据，无法进行井震标定。"));
            return;
        }
        QMessageBox::information(
            parent, QStringLiteral("提示"),
            QStringLiteral(
                "联合页井数据为占位记录（未分层，无声波/密度曲线），无法生成"
                "合成地震记录。请使用连井标定页进行真实井震标定。"));
    };

    // ---- facies ------------------------------------------------------------
    hooks.run_rgb_fusion = [state] {
        if (state->scene_objects == nullptr) {
            if (state->page != nullptr) {
                state->page->set_status_text(QStringLiteral(
                    "3D 视口尚未就绪，无法叠加 RGB 融合切片。"));
            }
            return;
        }
        add_rgb_fusion_overlay(*state->scene_objects);
        if (state->page != nullptr) {
            state->page->set_status_text(QStringLiteral(
                "RGB 三频率（15/35/55Hz）属性融合切片已叠加至三维视口"));
        }
    };
    hooks.run_crossplot = [state] {
        QWidget* parent = state->dialog_parent;
        const Json wells = borehole_records(state->host);
        if (wells.empty()) {
            QMessageBox::information(
                parent, QStringLiteral("提示"),
                QStringLiteral("联合场景中没有井数据，无法进行岩性交会。"));
            return;
        }
        // Deterministic sampling (the Python demo adds PCG64 noise; the
        // native side samples the lithology-table values exactly — no
        // invented jitter). GR vs 声波阻抗 AI per layer.
        std::vector<double> gr;
        std::vector<double> ai;
        std::vector<std::string> labels;
        const auto& gr_table = pwb::geomodel::litho_gr();
        const auto& ai_table = pwb::geomodel::litho_ai();
        const auto lookup =
            [](const std::vector<std::pair<std::string, double>>& table,
               const std::string& lith, double fallback) {
                for (const auto& [name, value] : table) {
                    if (name == lith) {
                        return value;
                    }
                }
                return fallback;
            };
        for (const auto& well : wells) {
            const std::string lith = well.contains("layers") &&
                                             well["layers"].is_array() &&
                                             !well["layers"].empty()
                                         ? well["layers"][0].value(
                                               "lithology",
                                               std::string("未分层"))
                                         : std::string("未分层");
            gr.push_back(
                lookup(gr_table, lith, pwb::geomodel::kDefaultGR));
            ai.push_back(
                lookup(ai_table, lith, pwb::geomodel::kDefaultAI));
            labels.push_back(lith);
        }
        const auto result =
            pwb::seismic_viewer::crossplot::analyze_lithology_crossplot(gr, ai, labels);
        QString rows;
        for (const auto& [lith, cluster] : result.clusters) {
            rows += QStringLiteral(
                        "<tr><td>%1</td><td>%2</td><td>%3 ± %4</td>"
                        "<td>%5 ± %6</td></tr>")
                        .arg(QString::fromStdString(lith))
                        .arg(cluster.count)
                        .arg(cluster.mean_gr, 0, 'f', 1)
                        .arg(cluster.std_gr, 0, 'f', 1)
                        .arg(cluster.mean_ai, 0, 'f', 0)
                        .arg(cluster.std_ai, 0, 'f', 0);
        }
        show_report_dialog(
            parent, QStringLiteral("岩性交会图 (GR vs AI)"),
            QStringLiteral(
                "<p>GR 与声波阻抗 AI 交会统计（确定性采样，逐层岩性表值）："
                "%1 口井。</p>"
                "<table border='1' cellspacing='0' cellpadding='3' "
                "width='100%'><tr><th>岩性</th><th>样本</th>"
                "<th>GR 均值 ± std</th><th>AI 均值 ± std</th></tr>%2</table>")
                .arg(wells.size())
                .arg(rows));
    };

    // ---- export / advisor ---------------------------------------------------
    hooks.run_export = [state] {
        QWidget* parent = state->dialog_parent;
        if (state->jobs == nullptr || state->page == nullptr) {
            return;
        }
        QString selected;
        const QString path = QFileDialog::getSaveFileName(
            parent, QStringLiteral("保存数值模拟网格模型"),
            QStringLiteral("geological_numerical_model"),
            QStringLiteral("FLAC3D 网格 (*.f3grid);;Abaqus 输入文件 (*.inp)"),
            &selected);
        if (path.isEmpty()) {
            return;
        }
        const bool flac =
            path.endsWith(QStringLiteral(".f3grid"), Qt::CaseInsensitive) ||
            selected.startsWith(QStringLiteral("FLAC3D"));
        pwb::ui_workers::ExportInput input;
        input.filename = path.toStdString();
        input.mode = flac ? "flac3d" : "abaqus";
        // Python visible-flow defaults (hidden card spinboxes 20/20/15 ×
        // 10/10/8).
        input.grid_spec = {20, 20, 15, 10.0, 10.0, 8.0};
        state->page->set_export_status(QStringLiteral("正在导出…"));
        auto& owner = state->jobs->make_owner(parent);
        Page* the_page = state->page;
        auto spec = pwb::ui_workers::make_export_job_spec(
            std::move(input),
            [the_page](const pwb::ui_workers::ExportResult& result) {
                the_page->set_export_status(
                    QStringLiteral("导出成功：%1")
                        .arg(QString::fromStdString(result.filename)));
            },
            [the_page](const std::string& error) {
                the_page->set_export_status(
                    QStringLiteral("网格模型导出失败：%1")
                        .arg(QString::fromStdString(error)));
            });
        owner.start(state->jobs->scheduler(), std::move(spec),
                    [](const pwb::job::qtbridge::JobOutcome&) {});
    };
    hooks.run_advisor = [state] {
        QWidget* parent = state->dialog_parent;
        if (state->jobs == nullptr || state->page == nullptr) {
            return;
        }
        pwb::ui_workers::AdvisorInput input;
        input.boreholes = borehole_records(state->host);
        if (input.boreholes.empty()) {
            QMessageBox::information(
                parent, QStringLiteral("提示"),
                QStringLiteral("联合场景中没有井数据，无法进行一致性诊断。"));
            return;
        }
        input.faults = Json::array();  // Python parity: never populated
        Page* the_page = state->page;
        the_page->set_export_status(QStringLiteral("正在诊断…"));
        auto& owner = state->jobs->make_owner(parent);
        auto spec = pwb::ui_workers::make_advisor_job_spec(
            std::move(input),
            [parent, the_page](
                const pwb::ui_workers::AdvisorResult& result) {
                the_page->set_export_status(
                    QStringLiteral("一致性诊断完成"));
                show_report_dialog(
                    parent, QStringLiteral("一致性诊断报告"),
                    QStringLiteral("<h3>钻孔检查</h3>%1<h3>断层共面检查</h3>%2")
                        .arg(report_table(result.bh_report,
                                          QStringLiteral("checked_boreholes")),
                             report_table(result.fault_report,
                                          QStringLiteral("checked_faults"))));
            },
            [the_page](const std::string& error) {
                the_page->set_export_status(
                    QStringLiteral("一致性复核诊断失败：%1")
                        .arg(QString::fromStdString(error)));
            });
        owner.start(state->jobs->scheduler(), std::move(spec),
                    [](const pwb::job::qtbridge::JobOutcome&) {});
    };

    return hooks;
}

void install(const JointAnalysisInstall& deps) {
    Page* page = deps.page;
    if (page == nullptr) {
        return;
    }
    page->set_analysis_hooks(make_hooks(deps));
}

}  // namespace pwb::app::joint_analysis

#endif  // PWB_WITH_UI_WELLSEIS
