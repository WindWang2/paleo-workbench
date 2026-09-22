#include "workspace_compose.hpp"

// M3 workspace composition bodies — see the header for the contract.

#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <vector>

#include <QColor>
#include <QFrame>
#include <QHash>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QPixmap>
#include <QSplitter>
#include <QTabWidget>
#include <QVBoxLayout>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "factor_reference_strip.hpp"
#include "main_window.hpp"
#include "validation_workspace_page.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#if defined(PWB_WITH_SEISMIC_VIEWER)
#if defined(PWB_WITH_VIZ_B)
#include "viz_b_cross_well_dock.hpp"
#endif
#include <pwb/seismic_viewer/seismic_slice_widget.hpp>
#endif
#if defined(PWB_WITH_WELL_LOG)
#include <pwb/viz/well_log_host_widget.hpp>
#endif
#if defined(PWB_WITH_CLOSURE_MAPPING)
#include "closure_mapping_install.hpp"
#include <pwb/ui_pages_data/qt/preparation_page.hpp>
#endif
#if defined(PWB_WITH_CLOSURE_MAPPING) && defined(PWB_WITH_FACTOR_KERNEL)
#include "factor_prepare_production.hpp"
#endif

namespace pwb::app::workspace_compose {

namespace {

// A titled bottom-pane frame (header strip + content host).
QFrame* make_pane(const QString& title, QWidget* parent) {
    auto* frame = new QFrame(parent);
    frame->setObjectName(QStringLiteral("WorkspacePane_") + title);
    frame->setFrameShape(QFrame::StyledPanel);
    auto* layout = new QVBoxLayout(frame);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto* header = new QLabel(title, frame);
    header->setObjectName(QStringLiteral("WorkspacePaneHeader"));
    header->setStyleSheet(QStringLiteral(
        "QLabel#WorkspacePaneHeader { padding: 2px 6px; "
        "background: #E4E9ED; font-weight: 600; }"));
    layout->addWidget(header);
    auto* host = new QWidget(frame);
    host->setObjectName(QStringLiteral("WorkspacePaneHost"));
    new QVBoxLayout(host);
    layout->addWidget(host, 1);
    return frame;
}

void hide_hint(QWidget* page) {
    if (page == nullptr) return;
    if (auto* hint = page->findChild<QLabel*>(
            QStringLiteral("StageBottomHint"),
            Qt::FindDirectChildrenOnly)) {
        hint->hide();
    }
}

// ---------------------------------------------------------------------------
// ws1 — 地震剖面 + 测井轨道 两联 (P0-1)
// ---------------------------------------------------------------------------

void compose_prediction_bottom(AppShell* shell) {
    // ws1 底部阶段行「井震两联」dock —— 地震+测井 split 注入 dock
    // 宿主（PredictionPairHost），占位 hint 退役。
    auto* frame = shell->workstation();
    auto* pair_dock = frame != nullptr ? frame->dock("pair_link") : nullptr;
    QWidget* host = pair_dock != nullptr ? pair_dock->widget() : nullptr;
    if (host != nullptr) {
        if (auto* hint = host->findChild<QLabel*>(
                QStringLiteral("StageBottomHint"),
                Qt::FindDirectChildrenOnly)) {
            hint->hide();
        }
        auto* host_layout = qobject_cast<QVBoxLayout*>(host->layout());
        if (host_layout == nullptr) return;
        auto* split = new QSplitter(Qt::Horizontal);
        split->setObjectName(QStringLiteral("PredictionBottomSplit"));
#if defined(PWB_WITH_SEISMIC_VIEWER)
        auto* seismic_frame = make_pane(QStringLiteral("地震剖面"), split);
        auto* seismic =
            new pwb::seismic_viewer::SeismicSliceWidget(seismic_frame);
        seismic->setObjectName(QStringLiteral("WorkspaceSeismicPane"));
        seismic_frame->findChild<QWidget*>(
                         QStringLiteral("WorkspacePaneHost"))
            ->layout()
            ->addWidget(seismic);
        split->addWidget(seismic_frame);
#else
        {
            auto* seismic_frame =
                make_pane(QStringLiteral("地震剖面（构建未含地震查看器）"), split);
            auto* note = new QLabel(QStringLiteral("地震查看器切片未参与本次构建"),
                                    seismic_frame);
            seismic_frame->findChild<QWidget*>(QStringLiteral("WorkspacePaneHost"))
                ->layout()
                ->addWidget(note);
            split->addWidget(seismic_frame);
        }
#endif

#if defined(PWB_WITH_WELL_LOG)
        auto* well_frame = make_pane(QStringLiteral("测井轨道"), split);
        auto* well = new pwb::viz::WellLogHostWidget(well_frame);
        well->setObjectName(QStringLiteral("WorkspaceWellPane"));
        well_frame->findChild<QWidget*>(QStringLiteral("WorkspacePaneHost"))
            ->layout()
            ->addWidget(well);
        split->addWidget(well_frame);
#else
        {
            auto* well_frame =
                make_pane(QStringLiteral("测井轨道（构建未含测井引擎）"), split);
            auto* note = new QLabel(QStringLiteral("测井引擎切片未参与本次构建"),
                                    well_frame);
            well_frame->findChild<QWidget*>(QStringLiteral("WorkspacePaneHost"))
                ->layout()
                ->addWidget(note);
            split->addWidget(well_frame);
        }
#endif
        split->setStretchFactor(0, 1);
        split->setStretchFactor(1, 1);
        host_layout->addWidget(split);
    }
}

// ---------------------------------------------------------------------------
// ws2 — 连井剖面 tab (P0-2); 数据制备 tab is adopted by the shell itself
// ---------------------------------------------------------------------------

void compose_constraint_bottom(MainWindow* window, AppShell* shell) {
#if defined(PWB_WITH_VIZ_B)
    auto* dock = window != nullptr ? window->vizBCrossWellDock() : nullptr;
    auto* frame = shell != nullptr ? shell->workstation() : nullptr;
    if (dock == nullptr || frame == nullptr) return;
    // 连井剖面 dock 整体收编进底部阶段行（dock 化后不再抽内容塞进
    // 页签 —— 悬浮/停靠/复位都是原生 dock 语义）。
    frame->adopt_dock("crosswell", dock);
#else
    (void)window;
    (void)shell;
#endif
}

// ---------------------------------------------------------------------------
// ws3 — 单因素参考缩略图带 (P0-3)
// ---------------------------------------------------------------------------

#if defined(PWB_WITH_CLOSURE_MAPPING) && defined(PWB_WITH_FACTOR_KERNEL)

// One downsample per (task, fingerprint) — the cache makes repeated paints
// free and never re-parses the same big grid (F: 参考带内容虚拟化).
QPixmap render_factor_thumbnail(
    pwb::factor_production::LiveFactorGridStore* store,
    const pwb::domain::Json& task, const QSize& size,
    QHash<QString, QPixmap>& cache) {
    const auto id_it = task.find("id");
    if (id_it == task.end() || !id_it->is_string()) return {};
    const QString task_id =
        QString::fromStdString(id_it->get<std::string>());
    const auto entry = store != nullptr
                           ? store->peek(id_it->get<std::string>())
                           : std::nullopt;
    if (!entry.has_value() || entry->grid_z.empty() ||
        entry->grid_x.empty() || entry->grid_y.empty()) {
        return {};
    }
    const QString fingerprint =
        QString::fromStdString(entry->result_fingerprint);
    const QString key = task_id + QLatin1Char('|') + fingerprint +
                        QStringLiteral("@%1x%2")
                            .arg(size.width())
                            .arg(size.height());
    const auto cached = cache.constFind(key);
    if (cached != cache.constEnd()) return cached.value();

    const int nx = static_cast<int>(entry->grid_x.size());
    const int ny = static_cast<int>(entry->grid_y.size());
    double min_v = std::numeric_limits<double>::max();
    double max_v = std::numeric_limits<double>::lowest();
    for (const float v : entry->grid_z) {
        if (!std::isfinite(v)) continue;
        min_v = std::min(min_v, static_cast<double>(v));
        max_v = std::max(max_v, static_cast<double>(v));
    }
    const int w = std::max(size.width(), 8);
    const int h = std::max(size.height(), 8);
    QImage image(w, h, QImage::Format_ARGB32);
    image.fill(Qt::transparent);
    const double span = max_v - min_v;
    for (int py = 0; py < h; ++py) {
        const int gy = std::min(
            ny - 1, static_cast<int>(
                        static_cast<double>(py) * ny / h));
        for (int px = 0; px < w; ++px) {
            const int gx = std::min(
                nx - 1,
                static_cast<int>(static_cast<double>(px) * nx / w));
            const float v = entry->grid_z[static_cast<size_t>(gy) *
                                              static_cast<size_t>(nx) +
                                          static_cast<size_t>(gx)];
            if (!std::isfinite(v)) continue;
            const double t = span > 0 ? (v - min_v) / span : 0.5;
            // White -> theme blue (#0078D4) ramp.
            const int r = static_cast<int>(255 + (0x00 - 255) * t);
            const int g = static_cast<int>(255 + (0x78 - 255) * t);
            const int b = static_cast<int>(255 + (0xD4 - 255) * t);
            image.setPixelColor(px, py, QColor(r, g, b));
        }
    }
    if (cache.size() >= 64) cache.clear();  // bounded cache, simple reset
    const QPixmap pixmap = QPixmap::fromImage(image);
    cache.insert(key, pixmap);
    return pixmap;
}

#endif  // CLOSURE_MAPPING && FACTOR_KERNEL

void compose_compilation_bottom(MainWindow* window, AppShell* shell,
                                AppContext* context) {
    // ws3 底部阶段行「单因素参考」dock —— FactorReferenceStrip 注入
    // dock 宿主（StageBottomCompilationHome）。
    auto* frame = shell->workstation();
    auto* refs_dock = frame != nullptr ? frame->dock("factor_refs")
                                       : nullptr;
    QWidget* page = refs_dock != nullptr ? refs_dock->widget() : nullptr;
    if (page == nullptr) return;
    hide_hint(page);
    auto* layout = qobject_cast<QVBoxLayout*>(page->layout());
    if (layout == nullptr) return;

    auto* strip = new FactorReferenceStrip(page);
    layout->addWidget(strip);

#if defined(PWB_WITH_CLOSURE_MAPPING) && defined(PWB_WITH_FACTOR_KERNEL)
    // shared_ptr BY VALUE — the renderer lambda keeps the store alive.
    auto store = closure_mapping::factor_grid_store(window);
    // Cache lives on the install frame — bounded, task+fingerprint keyed.
    auto* cache = new QHash<QString, QPixmap>();
    strip->set_thumbnail_renderer(
        [store, cache](const pwb::domain::Json& task,
                       const QSize& size) -> QPixmap {
            return render_factor_thumbnail(store.get(), task, size, *cache);
        });
#endif

    auto refresh = [strip, context] {
        std::vector<pwb::domain::Json> tasks;
        const auto store =
            context != nullptr ? context->projectStore() : nullptr;
        if (store != nullptr) {
            const auto& root = store->document().root();
            const auto it = root.find("factor_map_tasks");
            if (it != root.end() && it->is_array()) {
                for (const auto& task : *it) {
                    if (task.is_object()) tasks.push_back(task);
                }
            }
        }
        strip->update_state(tasks);
    };
    refresh();

#if defined(PWB_WITH_CLOSURE_MAPPING)
    // The preparation page is the writer surface of factor_map_tasks —
    // its refresh notification re-reads the document (no polling, no
    // second data path).
    if (window != nullptr) {
        if (auto* preparation = closure_mapping::preparation_page(window);
            preparation != nullptr) {
            QObject::connect(preparation,
                             &pwb::ui_pages_data::qt::PreparationPage::
                                 factor_maps_updated,
                             shell, refresh);
        }
    }
#endif

    QObject::connect(strip, &FactorReferenceStrip::reference_selected, shell,
                     [shell](const pwb::domain::Json& task) {
                         const auto it = task.find("name");
                         const QString name =
                             it != task.end() && it->is_string()
                                 ? QString::fromStdString(
                                       it->get<std::string>())
                                 : QStringLiteral("（未命名）");
                         emit shell->status_message(
                             QStringLiteral("参考对象：%1（主成果未改动）")
                                 .arg(name));
                     });
    // 叠加 is explicit and routes through the ONE governed dispatch the
    // hub shelf uses — never a parallel overlay path.
    if (shell->composite() != nullptr) {
        auto* composite = shell->composite();
        QObject::connect(
            strip, &FactorReferenceStrip::overlay_requested, composite,
            [composite](const pwb::domain::Json&) {
                emit composite->stage_action_requested(
                    QStringLiteral("integrated_compilation"),
                    QStringLiteral("overlay_factor_results"));
            });
    }
}

// ---------------------------------------------------------------------------
// ws4 — validation seismic comparison pane (P0-4)
// ---------------------------------------------------------------------------

void compose_validation_page(AppShell* shell) {
    auto* page = shell->validation_page();
    if (page == nullptr) return;
    QObject::connect(page, &ValidationWorkspacePage::status_message, shell,
                     &AppShell::status_message);
#if defined(PWB_WITH_SEISMIC_VIEWER)
    auto* pane = new pwb::seismic_viewer::SeismicSliceWidget;
    pane->setObjectName(QStringLiteral("ValidationSeismicPane"));
    page->set_seismic_pane(pane);
#endif
}

}  // namespace

void compose(const Install& install) {
    if (install.shell == nullptr) return;
    auto* window = dynamic_cast<MainWindow*>(install.window);
    compose_prediction_bottom(install.shell);
    compose_constraint_bottom(window, install.shell);
    compose_compilation_bottom(window, install.shell, install.context);
    compose_validation_page(install.shell);
}

}  // namespace pwb::app::workspace_compose
