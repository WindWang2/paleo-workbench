// CLOSURE-PREVIEW (task 04) — install/glue implementation. Pure adapters
// live in closure_preview_adapters.cpp; see closure_preview_install.hpp for
// the assembly contract.
#include "closure_preview_install.hpp"

#include "closure_preview_adapters.hpp"

#include "app_shell.hpp"
#include "job_center.hpp"

#include <pwb/ui_seqviz/qt/visualization_page.hpp>
#include "viz_e_install.hpp"

#include <pwb/ui_canvas/qt/preview_settings_dialog.hpp>

#include <pwb/ui_data_core/preview_provider.hpp>

#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_reader_panel.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>

#include <pwb/ui_pages_preview/preview_settings.hpp>
#include <pwb/ui_pages_preview/qt/geotiff_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/preview_settings_store.hpp>
#include <pwb/ui_seqviz/qt/preview_controller.hpp>
#include <pwb/ui_pages_preview/qt/json_tree_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/media_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/rich_text_preview_widget.hpp>
#include <pwb/ui_pages_preview/qt/seismic_preview_presenter.hpp>
#include <pwb/ui_pages_preview/qt/web_document_preview_widget.hpp>

#include <pwb/ingest/preview/registry.hpp>

#include <pwb/seismic_io/segy_reader.hpp>
#include <pwb/seismic_viewer/slice_selection.hpp>
#include <pwb/viz/seismic_volume.hpp>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>

#include <QDockWidget>
#include <QMainWindow>
#include <QPointer>

#include <map>
#include <mutex>
#include <optional>
#include <tuple>
#include <utility>

namespace pwb::closure_preview {
namespace {

namespace upd = pwb::ui_pages_data;
namespace updqt = pwb::ui_pages_data::qt;
namespace upv = pwb::ui_pages_preview;

// Shared PreviewSettingsStore (the platform default store; the dialog
// panel persists through it, readers apply from the same source). All
// access is serialized: the base preview builder loads on a worker
// thread while Apply saves on the GUI thread (QSettings is reentrant,
// not concurrent-safe per object).
std::mutex& settings_mutex() {
    static std::mutex m;
    return m;
}

upv::PreviewSettingsStore& settings_store() {
    static upv::PreviewSettingsStore store;
    return store;
}

upv::PreviewSettings load_settings() {
    std::lock_guard<std::mutex> lock(settings_mutex());
    return settings_store().load();
}

void save_settings(const upv::PreviewSettings& s) {
    std::lock_guard<std::mutex> lock(settings_mutex());
    save_settings(s);
}

// ---------------------------------------------------------------------------
// Process-level refresh registry (project open/switch notification). Same
// pattern as the presenter registry: process-scoped, guarded, weak refs.
// ---------------------------------------------------------------------------

struct RefreshEntry {
    QPointer<updqt::AssetSelectionBus> bus;
    std::function<std::shared_ptr<pwb::application::PwbDataStore>()> store;
};

std::mutex& refresh_mutex() {
    static std::mutex m;
    return m;
}

std::vector<RefreshEntry>& refresh_entries() {
    static std::vector<RefreshEntry> entries;
    return entries;
}

void refresh_locked(RefreshEntry& entry) {
    if (entry.bus.isNull()) return;
    auto store = entry.store ? entry.store() : nullptr;
    if (store == nullptr) {
        entry.bus->clear();  // honest empty state (未打开工程)
        return;
    }
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        entry.bus->clear();
        return;
    }
    entry.bus->set_assets(
        asset_rows_from_snapshot(snapshot.value()),
        QString::fromStdString(snapshot.value().project_file.string()));
}

// ---------------------------------------------------------------------------
// D→E seismic presenter registration (kind "seismic")
// ---------------------------------------------------------------------------

// Presenter lifetime: the create() closure hands the page to the reader
// panel; the presenter object rides a shared_ptr keyed by the page widget
// and is released when the page is destroyed (QObject::destroyed).
std::mutex& seismic_presenters_mutex() {
    static std::mutex m;
    return m;
}

std::map<QWidget*, std::shared_ptr<upv::qt::SeismicPreviewPresenter>>&
seismic_presenters() {
    static std::map<QWidget*, std::shared_ptr<upv::qt::SeismicPreviewPresenter>>
        map;
    return map;
}

bool is_segy_path(const QString& path) {
    const QString lower = path.toLower();
    return lower.endsWith(QStringLiteral(".sgy")) ||
           lower.endsWith(QStringLiteral(".segy"));
}

QWidget* create_seismic_page(const QString& path, QWidget* parent,
                             pwb::app::JobCenter* jobs) {
    auto presenter = upv::qt::make_seismic_preview_presenter();
    QWidget* page = presenter->make_page(pwb::viz::VolumeAxis::inline_);
    page->setParent(parent);
    {
        std::lock_guard<std::mutex> lock(seismic_presenters_mutex());
        seismic_presenters()[page] = std::move(presenter);
    }
    QObject::connect(page, &QObject::destroyed, page, [page] {
        std::lock_guard<std::mutex> lock(seismic_presenters_mutex());
        seismic_presenters().erase(page);
    });

    // The volume read is a full SEG-Y scan — off the GUI thread through the
    // JobCenter (synchronous only when no runtime exists). The page starts
    // in the presenter's honest no-volume state; a failed read keeps that
    // state (no fabricated volume).
    const std::string path_std = path.toStdString();
    auto bind = [page, path_std](pwb::viz::VolumeGeometryV1 geometry,
                       std::vector<float> samples) {
        std::shared_ptr<pwb::viz::ISeismicVolume> volume(
            pwb::viz::make_owning_volume(std::move(geometry),
                                         std::move(samples))
                .release());
        std::lock_guard<std::mutex> lock(seismic_presenters_mutex());
        const auto it = seismic_presenters().find(page);
        if (it == seismic_presenters().end()) return;
        it->second->set_volume(
            volume, pwb::seismic_viewer::VolumeIdentity{path_std, 1}, 1);
    };
    auto read_volume = [path_std]() -> std::optional<
        std::tuple<pwb::viz::VolumeGeometryV1, std::vector<float>>> {
        std::string error;
        auto volume = pwb::seismic_io::read_segy(path_std, &error);
        if (!volume) return std::nullopt;
        pwb::viz::VolumeGeometryV1 geometry;
        geometry.shape = {volume->ni, volume->nc, volume->ns};
        geometry.strides = {0, 0, 0};
        geometry.origin = {volume->iline_start, volume->xline_start, 0};
        geometry.step = {volume->iline_step, volume->xline_step,
                         volume->dt_ms};
        geometry.unit = volume->unit;
        return std::make_tuple(std::move(geometry),
                               std::move(volume->samples));
    };
    if (jobs != nullptr) {
        auto& owner = jobs->make_owner(nullptr);
        pwb::job::JobSpec spec;
        spec.kind = "preview.seismic_volume";
        spec.title = "读取地震体";
        spec.task_key = "preview.seismic_volume";
        spec.run = [read_volume](pwb::job::JobContext& ctx) -> std::any {
            ctx.check_cancelled();
            auto payload = read_volume();
            if (!payload) return std::string("SEG-Y 读取失败");
            return *payload;
        };
        const QPointer<QWidget> page_ref(page);
        owner.start(jobs->scheduler(), std::move(spec),
                    [bind = std::move(bind), page_ref](
                        const pwb::job::qtbridge::JobOutcome& o) {
                        if (!page_ref) return;
                        if (o.state == pwb::job::JobState::done ||
                            o.state == pwb::job::JobState::degraded) {
                            if (auto* payload = std::any_cast<std::tuple<
                                    pwb::viz::VolumeGeometryV1,
                                    std::vector<float>>>(&o.result)) {
                                bind(std::move(std::get<0>(*payload)),
                                     std::move(std::get<1>(*payload)));
                            }
                        }
                        // failed/cancelled: the page keeps its honest
                        // no-volume state.
                    });
    } else {
        if (auto payload = read_volume()) {
            bind(std::move(std::get<0>(*payload)),
                 std::move(std::get<1>(*payload)));
        }
    }
    return page;
}

void register_seismic_presenter(pwb::app::JobCenter* jobs) {
    viz_e::ExternalPresenter seismic;
    seismic.kind = "seismic";
    seismic.supports = [](const QString& asset_path) {
        return is_segy_path(asset_path);
    };
    seismic.note = "D SeismicPreviewPresenter (viz-d seam; sgy/segy)";
    seismic.create = [jobs](const QString& asset_path,
                            QWidget* parent) -> QWidget* {
        return create_seismic_page(asset_path, parent, jobs);
    };
    // First registration wins (process-wide contract); a second window's
    // install reuses the first registration by design.
    (void)viz_e::register_external_presenter(std::move(seismic));
}

// ---------------------------------------------------------------------------
// ui_pages_preview format targets → the reader panel (completing the page's
// format family: the native set already covers text/table/image/pdf).
// ---------------------------------------------------------------------------

void register_format_targets(updqt::DataReaderPanel* reader) {
    auto* json_tree = new upv::JsonTreePreviewWidget(reader);
    reader->register_target(QStringLiteral("json_tree_preview"), json_tree);
    reader->register_render_hook(
        QStringLiteral("json_tree_preview"),
        [](QWidget* w, const updqt::PreviewResultView& r) {
            auto* widget = qobject_cast<upv::JsonTreePreviewWidget*>(w);
            if (widget == nullptr) return;
            const auto* payload =
                static_cast<const domain::Json*>(r.payload);
            if (payload != nullptr) {
                widget->load_payload(*payload, !r.warning.empty());
            }
        });
    auto* rich_text = new upv::RichTextPreviewWidget(reader);
    reader->register_target(QStringLiteral("rich_text_preview"), rich_text);
    reader->register_render_hook(
        QStringLiteral("rich_text_preview"),
        [](QWidget* w, const updqt::PreviewResultView& r) {
            auto* widget = qobject_cast<upv::RichTextPreviewWidget*>(w);
            if (widget != nullptr) {
                widget->load_html(QString::fromStdString(r.rich_html));
            }
        });
    auto* web_document = new upv::WebDocumentPreviewWidget(reader);
    reader->register_target(QStringLiteral("web_document_preview"),
                            web_document);
    reader->register_render_hook(
        QStringLiteral("web_document_preview"),
        [](QWidget* w, const updqt::PreviewResultView& r) {
            auto* widget =
                qobject_cast<upv::WebDocumentPreviewWidget*>(w);
            if (widget != nullptr) {
                widget->load_document(QString::fromStdString(r.path),
                                      QString::fromStdString(r.rich_html));
            }
        });
    auto* geotiff = new upv::GeoTiffPreviewWidget(reader);
    reader->register_target(QStringLiteral("geotiff_preview"), geotiff);
    reader->register_render_hook(
        QStringLiteral("geotiff_preview"),
        [](QWidget* w, const updqt::PreviewResultView& r) {
            auto* widget = qobject_cast<upv::GeoTiffPreviewWidget*>(w);
            if (widget != nullptr) {
                widget->load(QString::fromStdString(r.path),
                             QString::fromStdString(r.revision), {},
                             {});
            }
        });
    auto* media = new upv::MediaPreviewWidget(reader);
    reader->register_target(QStringLiteral("media_preview"), media);
    reader->register_render_hook(
        QStringLiteral("media_preview"),
        [](QWidget* w, const updqt::PreviewResultView& r) {
            auto* widget = qobject_cast<upv::MediaPreviewWidget*>(w);
            if (widget != nullptr) {
                widget->set_media_path(
                    QString::fromStdString(r.media_path.empty() ? r.path
                                                                : r.media_path));
            }
        });
}

// ---------------------------------------------------------------------------
// Unified preview settings (UI-15 dialog over the shared store)
// ---------------------------------------------------------------------------

void wire_preview_settings(pwb::app::AppShell* shell) {
    QObject::connect(
        shell, &pwb::app::AppShell::preview_settings_requested, shell,
        [shell] {
            auto* store = &settings_store();
            pwb::ui_canvas::PreviewSettingsDialog dialog(shell, store);
            QObject::connect(
                &dialog,
                &pwb::ui_canvas::PreviewSettingsDialog::settings_applied,
                shell,
                [shell](const upv::PreviewSettings& s) {
                    save_settings(s);
                    if (shell->data_workspace() != nullptr) {
                        shell->data_workspace()
                            ->reader_panel()
                            ->apply_preview_settings(
                                s.show_metadata, s.font_size,
                                s.auto_fit_columns);
                    }
                    if (shell->visualization_page() != nullptr &&
                        shell->visualization_page()->preview_controller() !=
                            nullptr) {
                        shell->visualization_page()
                            ->preview_controller()
                            ->set_settings(to_core_settings(s));
                    }
                });
            dialog.exec();
        });
}

}  // namespace

// ---------------------------------------------------------------------------
// install / notify
// ---------------------------------------------------------------------------

pwb::viz_e::VizEDataPage* install(const Install& parts) {
    if (parts.shell == nullptr && parts.window == nullptr) return nullptr;

    pwb::viz_e::VizEDataPage* page = nullptr;
    if (parts.shell != nullptr) {
        // THE single data page: adopt the shell hub's bare management
        // workspace (the duplicate selection entry is removed, not shared).
        page = new pwb::viz_e::VizEDataPage(nullptr, parts.jobs,
                                            parts.shell->data_workspace());
        parts.shell->adopt_data_page(page);
    } else {
        page = viz_e::install_data_page(parts.window, parts.jobs);
    }

    // Single asset-selection state + catalog asset source.
    auto* bus = new updqt::AssetSelectionBus(page);
    page->bind_selection_bus(bus);

    // Parser-registry base preview (worker-thread build + cancel through
    // the page's generation guard).
    page->set_base_preview_builder(
        [](const upd::AssetRow& row,
           pwb::job::JobContext*) -> std::optional<updqt::PreviewResultView> {
            return build_registry_view(row, load_settings());
        });

    register_format_targets(page->workspace()->reader_panel());
    register_seismic_presenter(parts.jobs);

    if (parts.shell != nullptr) {
        wire_preview_settings(parts.shell);
        // VisualizationPage LocalVizProvider base seam: bind the real
        // parser-registry provider over the honest message stub.
        parts.shell->bind_visualization_preview(registry_preview_provider());
    }

    // Refresh entry (project open/switch notification path) + initial
    // population (no store → the honest empty state).
    {
        std::lock_guard<std::mutex> lock(refresh_mutex());
        refresh_entries().push_back(
            RefreshEntry{QPointer<updqt::AssetSelectionBus>(bus),
                         parts.store});
    }
    notify_project_store_changed();
    return page;
}

void notify_project_store_changed() {
    std::lock_guard<std::mutex> lock(refresh_mutex());
    for (auto& entry : refresh_entries()) {
        refresh_locked(entry);
    }
}

// Test seam: drop every refresh entry (production never calls this).
void reset_refresh_entries_for_tests() {
    std::lock_guard<std::mutex> lock(refresh_mutex());
    refresh_entries().clear();
}

}  // namespace pwb::closure_preview
