#include "workspace_compose.hpp"

// M3 workspace composition bodies — see the header for the contract.

#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <vector>

#include <QAction>
#include <QCheckBox>
#include <QColor>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFrame>
#include <QHash>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QListWidget>
#include <QPixmap>
#include <QPushButton>
#include <QSplitter>
#include <QTabWidget>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>
#include <pwb/ui_map/display_map_canvas.hpp>

#include <qgsfeature.h>
#include <qgsfeatureiterator.h>
#include <qgsmaplayer.h>
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "factor_atlas_panel.hpp"
#include "factor_reference_strip.hpp"
#include "main_window.hpp"
#include "profile_settings_panel.hpp"
#include "validation_workspace_page.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/composite_document.hpp>
#include <pwb/ui_workstation/workstation_frame.hpp>

#if defined(PWB_WITH_VIZ_B)
#include "viz_b_cross_well_dock.hpp"
#endif
#if defined(PWB_WITH_SEISMIC_VIEWER)
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

// A titled bottom-pane frame (header strip + content host). The header
// is a row — the mockup puts per-pane controls (显示/色标 combos, 联动
// toggles) on the same strip as the title, so callers may append widgets
// to `PaneHeaderBar` before the stretch.
QFrame* make_pane(const QString& title, QWidget* parent) {
    auto* frame = new QFrame(parent);
    frame->setObjectName(QStringLiteral("WorkspacePane_") + title);
    frame->setFrameShape(QFrame::StyledPanel);
    auto* layout = new QVBoxLayout(frame);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);
    auto* header = new QWidget(frame);
    header->setObjectName(QStringLiteral("WorkspacePaneHeader"));
    header->setStyleSheet(QStringLiteral(
        "QWidget#WorkspacePaneHeader { padding: 2px 6px; "
        "background: #E4E9ED; }"));
    auto* header_row = new QHBoxLayout(header);
    header_row->setContentsMargins(0, 0, 0, 0);
    header_row->setSpacing(6);
    auto* title_label = new QLabel(title, header);
    title_label->setStyleSheet(QStringLiteral("font-weight: 600;"));
    header_row->addWidget(title_label);
    header_row->addStretch();
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
    // ws1 页内阶段窗格「井震两联」—— 地震+测井 split 注入页内宿主
    // （PredictionPairHost，中列底部固定区）；占位 hint 退役。
    QWidget* host = shell != nullptr ? shell->stage_pane_pair() : nullptr;
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
        auto* seismic_frame =
            make_pane(QStringLiteral("地震剖面（与地图联动）"), split);
        auto* seismic =
            new pwb::seismic_viewer::SeismicSliceWidget(seismic_frame);
        seismic->setObjectName(QStringLiteral("WorkspaceSeismicPane"));
        // 稿窗格题头行：显示 / 色标 下拉 —— 绑 SeismicSliceWidget 真缝
        // （display_mode / color_map）。稿中的剖面号线名（L03 等）由
        // 载入体决定，空载时题头不带线名。
        if (auto* bar = seismic_frame->findChild<QHBoxLayout*>()) {
            auto* display_label = new QLabel(
                QStringLiteral("显示"), seismic_frame);
            auto* display = new QComboBox(seismic_frame);
            display->addItem(QStringLiteral("变密度"),
                             static_cast<int>(
                                 pwb::seismic_viewer::DisplayMode::
                                     variable_density));
            display->addItem(QStringLiteral("波形"),
                             static_cast<int>(
                                 pwb::seismic_viewer::DisplayMode::wiggle));
            QObject::connect(
                display, &QComboBox::currentIndexChanged, seismic,
                [seismic, display](int index) {
                    seismic->set_display_mode(
                        static_cast<pwb::seismic_viewer::DisplayMode>(
                            display->itemData(index).toInt()));
                });
            auto* cmap_label = new QLabel(QStringLiteral("色标"),
                                          seismic_frame);
            auto* cmap = new QComboBox(seismic_frame);
            cmap->addItem(QStringLiteral("seismic"));
            cmap->addItem(QStringLiteral("seismic_r"));
            cmap->addItem(QStringLiteral("gray"));
            cmap->addItem(QStringLiteral("viridis"));
            QObject::connect(cmap, &QComboBox::currentTextChanged, seismic,
                             [seismic](const QString& name) {
                                 seismic->set_color_map(
                                     name.toStdString());
                             });
            bar->insertWidget(bar->count() - 1, display_label);
            bar->insertWidget(bar->count() - 1, display);
            bar->insertWidget(bar->count() - 1, cmap_label);
            bar->insertWidget(bar->count() - 1, cmap);
        }
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
        auto* well_frame =
            make_pane(QStringLiteral("测井轨道（与地图联动）"), split);
        auto* well = new pwb::viz::WellLogHostWidget(well_frame);
        well->setObjectName(QStringLiteral("WorkspaceWellPane"));
        // 稿窗格题头行：深度(m) 标注 + 联动 勾选。联动后端与 Ribbon
        // predict.link 同一状态 —— 当前未接入，诚实禁用。
        if (auto* bar = well_frame->findChild<QHBoxLayout*>()) {
            auto* depth = new QLabel(QStringLiteral("深度(m)"),
                                     well_frame);
            auto* link = new QCheckBox(QStringLiteral("联动"), well_frame);
            link->setChecked(true);
            link->setEnabled(false);
            link->setToolTip(QStringLiteral(
                "联动后端未接入 — 与 Ribbon「联动」命令同一状态"));
            bar->insertWidget(bar->count() - 1, depth);
            bar->insertWidget(bar->count() - 1, link);
        }
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

void compose_constraint_bottom(MainWindow* window, AppShell* shell,
                               AppContext* context) {
    QWidget* host =
        shell != nullptr ? shell->stage_pane_crosswell() : nullptr;
#if defined(PWB_WITH_VIZ_B)
    auto* dock = window != nullptr ? window->vizBCrossWellDock() : nullptr;
    if (dock == nullptr || host == nullptr) return;
    // 连井剖面收编进 ws2 页内阶段窗格（mockup：中列底部固定区，
    // 「连井剖面（与地图联动）」）—— 取 dock 的内容部件进页（dock
    // 壳退隐；部件仍由 dock 对象拥有，save/restore/井列 API 不变）。
    // 稿在窗格左内嵌「剖面设置」卡：剖面井勾选（→ dock 井列过滤）+
    // 显示设置（地层格架 → set_show_tops）。
    auto* content = dock->widget();
    if (content == nullptr) return;
    if (auto* hint = host->findChild<QLabel*>(
            QStringLiteral("StageBottomHint"),
            Qt::FindDirectChildrenOnly)) {
        hint->hide();
    }
    auto* layout = qobject_cast<QVBoxLayout*>(host->layout());
    if (layout == nullptr) return;
    auto* split = new QSplitter(Qt::Horizontal, host);
    split->setObjectName(QStringLiteral("CrossWellPaneSplit"));

    auto* settings = new ProfileSettingsPanel(split);
    settings->setMinimumWidth(150);
    settings->setMaximumWidth(220);
    split->addWidget(settings);
    split->addWidget(content);
    split->setStretchFactor(0, 0);
    split->setStretchFactor(1, 1);
    content->setParent(split);
    layout->addWidget(split);
    dock->hide();

    // 剖面设置 ↔ dock：井名清单跟 wells_changed 重建（保持勾选态），
    // 勾选集 → dock 画布过滤；地层格架 → tops 叠加开关。
    settings->set_well_names(dock->all_well_names());
    QObject::connect(dock, &VizBCrossWellDock::wells_changed, settings,
                     &ProfileSettingsPanel::set_well_names);
    QObject::connect(settings, &ProfileSettingsPanel::well_filter_changed,
                     dock, &VizBCrossWellDock::set_well_filter);
    QObject::connect(settings, &ProfileSettingsPanel::frame_toggled, dock,
                     &VizBCrossWellDock::set_show_frame);

    // ---- 联动开关（factor.link）：地图井选择 ↔ 剖面井过滤 双向投影 ----
    // 井名是稳定 join key（dock 的井 id 即井名——不新建第二份井选择
    // 权威）。选择变化经 150 ms 单发 QTimer 节流；程序化选择用
    // applying 布尔守卫阻断回环（selectionChanged 直连同步触发）。
    {
        auto* link_row = new QWidget(host);
        auto* link_layout = new QHBoxLayout(link_row);
        link_layout->setContentsMargins(6, 2, 6, 0);
        auto* link_action = new QAction(QStringLiteral("与地图联动"), window);
        link_action->setObjectName(QStringLiteral("FactorLinkToggle"));
        link_action->setCheckable(true);
        link_action->setToolTip(QStringLiteral(
            "地图上选中井 → 剖面只显示所选井（取消选择 = 全部）；"
            "剖面井勾选 → 地图高亮对应井要素"));
        auto* link_button = new QToolButton(link_row);
        link_button->setDefaultAction(link_action);
        link_layout->addWidget(link_button);
        link_layout->addStretch();
        layout->insertWidget(0, link_row);
        if (shell->ribbon() != nullptr) {
            shell->ribbon()->set_command_action(
                QStringLiteral("factor.link"), link_action);
        }

        auto* throttle = new QTimer(split);
        throttle->setSingleShot(true);
        throttle->setInterval(150);
        const auto applying = std::make_shared<bool>(false);
        // 记住联动触碰过的图层 id（清空选择时能找回井图层）。
        const auto linked_layer_ids =
            std::make_shared<QStringList>();

        // 井名候选字段（样例井位 GeoJSON 与通用井表的名列）。
        const auto feature_name = [](QgsVectorLayer* layer,
                                     const QgsFeature& feature) {
            static const char* kNameFields[] = {"name", "well",
                                                "well_name", "WELL",
                                                "井名"};
            for (const char* field : kNameFields) {
                const int index = layer->fields().indexOf(
                    QLatin1String(field));
                if (index < 0) continue;
                const QVariant value = feature.attribute(index);
                if (value.isValid() && !value.toString().isEmpty()) {
                    return value.toString();
                }
            }
            return QString();
        };

        // 地图 → 剖面：与 dock 井名求交的所选要素名投影为剖面过滤。
        const auto apply_map_to_section = [window, dock, settings,
                                           link_action, applying,
                                           feature_name]() {
            if (!link_action->isChecked() || *applying) return;
            const QStringList known = dock->all_well_names();
            if (known.isEmpty()) return;
            const QSet<QString> known_set(known.begin(), known.end());
            QSet<QString> selected;
            const QList<QgsVectorLayer*> layers =
                window->context()
                    .session()
                    .map()
                    .project()
                    ->layers<QgsVectorLayer*>();
            for (QgsVectorLayer* layer : layers) {
                if (layer == nullptr
                    || layer->selectedFeatureCount() == 0) {
                    continue;
                }
                QgsFeature feature;
                QgsFeatureIterator it = layer->getSelectedFeatures();
                while (it.nextFeature(feature)) {
                    const QString name = feature_name(layer, feature);
                    if (!name.isEmpty() && known_set.contains(name)) {
                        selected.insert(name);
                    }
                }
            }
            // 地图取消选择（或选中的都不是井）= 剖面回到全部井。
            dock->set_well_filter(selected);
            QSet<QString> visible = selected;
            if (visible.isEmpty()) {
                visible = known_set;
            }
            settings->set_well_filter(visible);
        };
        QObject::connect(throttle, &QTimer::timeout, split,
                         apply_map_to_section);

        // 剖面 → 地图：勾选变化把井要素选择到地图上。
        QObject::connect(
            settings, &ProfileSettingsPanel::well_filter_changed, split,
            [window, dock, link_action, applying, linked_layer_ids,
             feature_name](const QSet<QString>& filter) {
                if (!link_action->isChecked() || *applying) return;
                const QStringList known = dock->all_well_names();
                if (known.isEmpty()) return;
                QSet<QString> visible;
                if (filter.contains(QStringLiteral("__none__"))) {
                    // 全不显示 = 清空地图井选择。
                } else if (filter.isEmpty()) {
                    visible = QSet<QString>(known.begin(), known.end());
                } else {
                    visible = filter;
                }
                *applying = true;
                const QList<QgsVectorLayer*> layers =
                    window->context()
                        .session()
                        .map()
                        .project()
                        ->layers<QgsVectorLayer*>();
                for (QgsVectorLayer* layer : layers) {
                    if (layer == nullptr) continue;
                    QgsFeatureIds select;
                    if (!visible.isEmpty()) {
                        QgsFeature feature;
                        QgsFeatureIterator it = layer->getFeatures();
                        while (it.nextFeature(feature)) {
                            const QString name =
                                feature_name(layer, feature);
                            if (!name.isEmpty()
                                && visible.contains(name)) {
                                select.insert(feature.id());
                            }
                        }
                    }
                    if (!select.isEmpty()) {
                        layer->selectByIds(select);
                        if (!linked_layer_ids->contains(layer->id())) {
                            linked_layer_ids->append(layer->id());
                        }
                    } else if (visible.isEmpty()
                               && linked_layer_ids->contains(
                                   layer->id())) {
                        layer->removeSelection();
                    }
                }
                *applying = false;
            });

        // 订阅图层选择变化（现有 + 未来图层）。
        const auto hook_layer = [throttle](QgsMapLayer* map_layer) {
            if (auto* vector_layer =
                    qobject_cast<QgsVectorLayer*>(map_layer)) {
                QObject::connect(
                    vector_layer, &QgsVectorLayer::selectionChanged,
                    throttle,
                    [throttle]() { throttle->start(); },
                    Qt::UniqueConnection);
            }
        };
        const QList<QgsMapLayer*> current_layers =
            window->context().session().map().project()->mapLayers().values();
        for (QgsMapLayer* map_layer : current_layers) {
            hook_layer(map_layer);
        }
        QObject::connect(
            window->context().session().map().project(),
            &QgsProject::layersAdded, split,
            [hook_layer](const QList<QgsMapLayer*>& added) {
                for (QgsMapLayer* map_layer : added) {
                    hook_layer(map_layer);
                }
            });
    }
#else
    (void)window;
    (void)host;
#endif

    // ws2 右栏「单因素」签 —— 单因素图层清单喂数：project
    // .factor_map_tasks 同一权威（与 ws3 参考带同一份刷新 seam）。
    if (auto* atlas = shell->factor_atlas_panel(); atlas != nullptr) {
        auto refresh_atlas = [atlas, context] {
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
            atlas->update_state(tasks);
        };
        refresh_atlas();
#if defined(PWB_WITH_CLOSURE_MAPPING)
        if (window != nullptr) {
            if (auto* preparation =
                    closure_mapping::preparation_page(window);
                preparation != nullptr) {
                QObject::connect(
                    preparation,
                    &pwb::ui_pages_data::qt::PreparationPage::
                        factor_maps_updated,
                    atlas, refresh_atlas);
            }
        }
#endif
        // 勾选 → 治理通道（constraint_factor 阶段注册的
        // overlay_factor_results）——与参考带同一叠加路径。
        if (shell->composite() != nullptr) {
            auto* composite = shell->composite();
            QObject::connect(
                atlas, &FactorAtlasPanel::overlay_selected, composite,
                [composite](const pwb::domain::Json&) {
                    emit composite->stage_action_requested(
                        QStringLiteral("constraint_factor"),
                        QStringLiteral("overlay_factor_results"));
                });
        }
    }
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
    // ws3 页内阶段窗格「单因素参考 · 联动显示」—— FactorReferenceStrip
    // 注入页内宿主（StageBottomCompilationHome）。
    QWidget* page =
        shell != nullptr ? shell->stage_pane_factor() : nullptr;
    if (page == nullptr) return;
    hide_hint(page);
    auto* layout = qobject_cast<QVBoxLayout*>(page->layout());
    if (layout == nullptr) return;

    auto* strip = new FactorReferenceStrip(page);
    layout->addWidget(strip);

#if defined(PWB_WITH_CLOSURE_MAPPING) && defined(PWB_WITH_FACTOR_KERNEL)
    // shared_ptr BY VALUE — the renderer lambda keeps the store alive.
    auto store = closure_mapping::factor_grid_store(window);
    // Cache lives with the strip — bounded, task+fingerprint keyed.
    // (Review N5: the raw new leaked the hash + up to 64 pixmaps per
    // window; QObject-delete bound to the strip's destruction instead.)
    auto* cache = new QHash<QString, QPixmap>();
    QObject::connect(strip, &QObject::destroyed, strip,
                     [cache] { delete cache; });
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

void compose_validation_page(MainWindow* window, AppShell* shell) {
    auto* page = shell->validation_page();
    if (page == nullptr) return;
    QObject::connect(page, &ValidationWorkspacePage::status_message, shell,
                     &AppShell::status_message);
#if defined(PWB_WITH_SEISMIC_VIEWER)
    auto* pane = new pwb::seismic_viewer::SeismicSliceWidget;
    pane->setObjectName(QStringLiteral("ValidationSeismicPane"));
    page->set_seismic_pane(pane);
#endif
    // 验证画布喂数（locate 的前置）：把主工程矢量层镜像成
    // DisplayMapCanvas 的不可变快照（此前 locate 在空白画布上平移）。
    // 主画布仍是空间权威——这里只是只读投影，随报告刷新重建。要素
    // 上限防大图层拖垮 GUI 线程（超限截断）。
    if (window != nullptr && page->map_canvas() != nullptr) {
        const auto feed_validation_map = [window, page]() {
            auto* project = window->context().session().map().project();
            pwb::domain::Json snapshot = pwb::domain::Json::object();
            snapshot["project_crs"] =
                project->crs().authid().toStdString();
            pwb::domain::Json layers = pwb::domain::Json::array();
            const QList<QgsVectorLayer*> vector_layers =
                project->layers<QgsVectorLayer*>();
            constexpr int kMaxFeaturesPerLayer = 5000;
            for (QgsVectorLayer* layer : vector_layers) {
                if (layer == nullptr || !layer->isValid()) continue;
                pwb::domain::Json layer_json = pwb::domain::Json::object();
                layer_json["id"] = layer->id().toStdString();
                layer_json["name"] = layer->name().toStdString();
                layer_json["layer_type"] = "vector";
                layer_json["crs"] = layer->crs().authid().toStdString();
                pwb::domain::Json features = pwb::domain::Json::array();
                int count = 0;
                QgsFeature feature;
                QgsFeatureIterator it = layer->getFeatures();
                while (it.nextFeature(feature)
                       && count < kMaxFeaturesPerLayer) {
                    if (!feature.hasGeometry()) continue;
                    pwb::domain::Json geo;
                    try {
                        geo = pwb::domain::Json::parse(
                            feature.geometry().asJson().toStdString());
                    } catch (const pwb::domain::Json::exception&) {
                        continue;
                    }
                    features.push_back(std::move(geo));
                    ++count;
                }
                layer_json["features"] = std::move(features);
                layers.push_back(std::move(layer_json));
            }
            snapshot["layers"] = std::move(layers);
            page->map_canvas()->set_layer_snapshot(snapshot);
        };
        feed_validation_map();
        QObject::connect(
            page, &ValidationWorkspacePage::reports_refreshed, shell,
            [feed_validation_map]() { feed_validation_map(); },
            Qt::UniqueConnection);
    }
}

}  // namespace

void compose(const Install& install) {
    if (install.shell == nullptr) return;
    auto* window = dynamic_cast<MainWindow*>(install.window);
    compose_prediction_bottom(install.shell);
    compose_constraint_bottom(window, install.shell, install.context);
    compose_compilation_bottom(window, install.shell, install.context);
    compose_validation_page(window, install.shell);
}

// ---------------------------------------------------------------------------
// factor.crosswell_path / factor.link 的命令后端（P0-2 面的公共入口）。
// ---------------------------------------------------------------------------

bool run_crosswell_path_dialog(QMainWindow* window_as_qmain) {
#if defined(PWB_WITH_VIZ_B)
    auto* window = dynamic_cast<MainWindow*>(window_as_qmain);
    auto* dock =
        window != nullptr ? window->vizBCrossWellDock() : nullptr;
    if (dock == nullptr || dock->all_well_names().isEmpty()) {
        return false;
    }
    QDialog dialog(window_as_qmain);
    dialog.setWindowTitle(QStringLiteral("连井剖面路径（井序）"));
    dialog.setObjectName(QStringLiteral("CrosswellPathDialog"));
    auto* layout = new QVBoxLayout(&dialog);
    auto* list = new QListWidget(&dialog);
    list->setObjectName(QStringLiteral("CrosswellPathList"));
    const QStringList order = dock->current_well_order();
    for (const QString& name : order) {
        list->addItem(name);
    }
    list->setCurrentRow(0);
    layout->addWidget(list);

    auto* row = new QWidget(&dialog);
    auto* row_layout = new QHBoxLayout(row);
    row_layout->setContentsMargins(0, 0, 0, 0);
    auto* up = new QPushButton(QStringLiteral("上移"), row);
    auto* down = new QPushButton(QStringLiteral("下移"), row);
    auto* auto_pca = new QPushButton(QStringLiteral("自动排列（PCA）"), row);
    up->setObjectName(QStringLiteral("CrosswellPathUp"));
    down->setObjectName(QStringLiteral("CrosswellPathDown"));
    row_layout->addWidget(up);
    row_layout->addWidget(down);
    row_layout->addStretch();
    row_layout->addWidget(auto_pca);
    layout->addWidget(row);

    const auto move_selected = [list](int delta) {
        const int row = list->currentRow();
        const int target = row + delta;
        if (row < 0 || target < 0 || target >= list->count()) return;
        QListWidgetItem* item = list->takeItem(row);
        list->insertItem(target, item);
        list->setCurrentRow(target);
    };
    QObject::connect(up, &QPushButton::clicked, &dialog,
                     [move_selected] { move_selected(-1); });
    QObject::connect(down, &QPushButton::clicked, &dialog,
                     [move_selected] { move_selected(1); });
    // 自动排列先按当前井位坐标重排，结果回到对话框继续手工微调。
    QObject::connect(auto_pca, &QPushButton::clicked, &dialog,
                     [dock, list] {
                         dock->arrange_by_pca();
                         list->clear();
                         for (const QString& name :
                              dock->current_well_order()) {
                             list->addItem(name);
                         }
                         if (list->count() > 0) list->setCurrentRow(0);
                     });

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog,
                     &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog,
                     &QDialog::reject);
    layout->addWidget(buttons);

    if (dialog.exec() != QDialog::Accepted) return true;  // 取消=未改动
    QStringList ordered;
    for (int i = 0; i < list->count(); ++i) {
        ordered.append(list->item(i)->text());
    }
    dock->set_well_order(ordered);
    return true;
#else
    (void)window_as_qmain;
    return false;
#endif
}

bool crosswell_link_active(QMainWindow* window_as_qmain) {
    if (window_as_qmain == nullptr) return false;
    auto* action = window_as_qmain->findChild<QAction*>(
        QStringLiteral("FactorLinkToggle"));
    return action != nullptr && action->isChecked();
}

}  // namespace pwb::app::workspace_compose
