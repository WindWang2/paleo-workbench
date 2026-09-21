// V14-DATA-LINEAGE (P4 product wiring) — closure_data_workspace impl.
// See closure_data_workspace.hpp for the module contract. Threading: all
// slots run on the GUI thread (the refresh path already does); the ingest
// execute is synchronous under a wait cursor (brief-sanctioned honesty —
// the job-runtime offload is a registered follow-up, same as the 09-line
// ingest dialog host).
#include "closure_data_workspace.hpp"


#include <pwb/application/adapters/data_store.hpp>
#include <pwb/catalog/document_index.hpp>
#include <pwb/catalog/impact.hpp>
#include <pwb/catalog/lineage_graph.hpp>
#include <pwb/catalog/models.hpp>
#include <pwb/catalog/repository.hpp>
#include <pwb/data/entity_workspace.hpp>
#include <pwb/data/ingest_exec.hpp>
#include <pwb/data/ingest_plan.hpp>
#include <pwb/data/role_registry.hpp>
#include <pwb/data/session.hpp>
#include <pwb/domain/stage.hpp>
#include <pwb/project/paths.hpp>
#include <pwb/ui_pages_data/ingest_plan_rows.hpp>
#include <pwb/ui_pages_data/qt/asset_selection_bus.hpp>
#include <pwb/ui_pages_data/qt/data_toolbar.hpp>
#include <pwb/ui_pages_data/qt/data_workspace.hpp>
#include <pwb/ui_pages_data/qt/ingest_plan_dialog.hpp>
#include <pwb/ui_pages_data/qt/navigation_tree_widget.hpp>
#include <pwb/ui_wellseis/qt/well_detail_panel.hpp>

#include <QApplication>
#include <QPointer>
#include <QFileDialog>
#include <QMessageBox>
#include <QVBoxLayout>

#include <fstream>
#include <map>
#include <stdexcept>
#include <utility>

namespace pwb::app::v14_lineage {
namespace {

namespace upd = pwb::ui_pages_data;
namespace updqt = pwb::ui_pages_data::qt;

std::string json_str(const domain::Json& node, const char* key,
                     const char* default_value = "") {
    if (!node.is_object()) return default_value;
    const auto it = node.find(key);
    if (it == node.end() || it->is_null()) return default_value;
    if (it->is_string()) return it->get<std::string>();
    return default_value;
}

const domain::Json* json_array(const domain::Json& root, const char* key) {
    if (!root.is_object()) return nullptr;
    const auto it = root.find(key);
    if (it == root.end() || !it->is_array()) return nullptr;
    return &*it;
}

// Project file → parsed JSON root (best effort; malformed/missing →
// empty object — the callers degrade to "no links", never a crash).
domain::Json read_project_json(const std::filesystem::path& project_file) {
    domain::Json root = domain::Json::object();
    std::ifstream in(project_file);
    if (!in) return root;
    try {
        in >> root;
    } catch (const std::exception&) {
        return domain::Json::object();
    }
    return root;
}

std::vector<pwb::catalog::ImpactService::EntityLink> impact_entity_links(
    const domain::Json& project_root) {
    std::vector<pwb::catalog::ImpactService::EntityLink> links;
    if (const domain::Json* nodes =
            json_array(project_root, "entity_asset_links")) {
        for (const auto& node : *nodes) {
            pwb::catalog::ImpactService::EntityLink link;
            link.entity_type = json_str(node, "entity_type", "well");
            link.entity_id = json_str(node, "entity_id");
            link.asset_id = json_str(node, "asset_id");
            if (link.entity_id.empty() || link.asset_id.empty()) continue;
            links.push_back(std::move(link));
        }
    }
    return links;
}

std::string join_strings(const std::vector<std::string>& parts,
                         const char* sep) {
    std::string out;
    for (const auto& part : parts) {
        if (!out.empty()) out += sep;
        out += part;
    }
    return out;
}

}  // namespace

// ---- 1. navigation tree ------------------------------------------------------

upd::NavProjectView build_nav_project_view(const domain::Json& project_root) {
    upd::NavProjectView view;

    if (const domain::Json* wells = json_array(project_root, "wells")) {
        for (const auto& node : *wells) {
            upd::NavEntity well;
            well.id = json_str(node, "id");
            if (well.id.empty()) continue;  // unindexed nodes never render
            well.name = json_str(node, "name");
            well.uwi = json_str(node, "uwi");
            // schema defaults: coordinate_status "missing" (only "ok" is
            // clean → ⚠坐标 flag), spatial_scope "workarea".
            well.coordinate_status =
                json_str(node, "coordinate_status", "missing");
            well.spatial_scope = json_str(node, "spatial_scope", "workarea");
            view.wells.push_back(std::move(well));
        }
    }
    if (const domain::Json* surveys =
            json_array(project_root, "seismic_surveys")) {
        for (const auto& node : *surveys) {
            upd::NavEntity survey;
            survey.id = json_str(node, "id");
            if (survey.id.empty()) continue;
            survey.name = json_str(node, "name");
            view.seismic_surveys.push_back(std::move(survey));
        }
    }
    if (const domain::Json* entities =
            json_array(project_root, "geological_entities")) {
        for (const auto& node : *entities) {
            upd::NavEntity entity;
            entity.id = json_str(node, "id");
            if (entity.id.empty()) continue;
            entity.name = json_str(node, "name");
            view.geological_entities.push_back(std::move(entity));
        }
    }
    if (const domain::Json* links =
            json_array(project_root, "entity_asset_links")) {
        for (const auto& node : *links) {
            upd::NavEntityLink link;
            link.entity_type = json_str(node, "entity_type", "well");
            link.entity_id = json_str(node, "entity_id");
            link.asset_id = json_str(node, "asset_id");
            link.role = json_str(node, "role", "other");
            const auto it = node.find("unresolved");
            if (it != node.end() && it->is_boolean())
                link.unresolved = it->get<bool>();
            if (link.entity_id.empty() || link.asset_id.empty()) continue;
            view.entity_asset_links.push_back(std::move(link));
        }
    }
    return view;
}

void populate_nav_tree(upd::NavTreeModel& model,
                       const domain::Json& project_root) {
    // The "unported" role seams (nav_tree_model.hpp) now bind to the REAL
    // data-suite registry: roles_for_entity_type supplies the grouping
    // order (registry order, "other" last), role_display the zh label
    // (well vocabulary preferred — the registry's default lookup).
    model.set_role_order_fn([](const std::string& entity_type) {
        std::vector<std::string> roles;
        for (auto role : pwb::data::roles_for_entity_type(entity_type)) {
            roles.emplace_back(role);
        }
        return roles;
    });
    model.set_role_display_fn(
        [](const std::string& role) { return pwb::data::role_display(role); });
    model.set_project(build_nav_project_view(project_root));
}

// ---- 2. well detail ----------------------------------------------------------

pwb::ui_wellseis::WellDataViewSlice well_detail_slice(
    const pwb::data::EntityDataView& view) {
    pwb::ui_wellseis::WellDataViewSlice slice;
    slice.well_name = view.name;
    slice.uwi = view.uwi;
    slice.role_slots.reserve(view.role_slots.size());
    for (const auto& slot : view.role_slots) {
        pwb::ui_wellseis::RoleSlotSlice slot_slice;
        slot_slice.role = slot.role;
        slot_slice.unresolved = !slot.unresolved.empty();
        slot_slice.members.reserve(slot.members.size());
        for (const auto& member : slot.members) {
            pwb::ui_wellseis::RoleMemberSlice member_slice;
            member_slice.name = member.name;
            member_slice.is_primary = member.is_primary;
            member_slice.version_count = member.version_count;
            member_slice.current_version_id = member.current_version_id;
            slot_slice.members.push_back(std::move(member_slice));
        }
        slice.role_slots.push_back(std::move(slot_slice));
    }
    slice.stale_items.reserve(view.stale_items.size());
    for (const auto& stale : view.stale_items) {
        pwb::ui_wellseis::StaleItemSlice stale_slice;
        // StaleLite carries reason/pinned only — the stage stays empty
        // (honest degrade; the panel renders the version/pin without it).
        stale_slice.version_id = stale.version_id;
        stale_slice.pinned = stale.pinned;
        slice.stale_items.push_back(std::move(stale_slice));
    }
    slice.uncommitted_edits.reserve(view.uncommitted_edits.size());
    for (const auto& edit : view.uncommitted_edits) {
        pwb::ui_wellseis::UncommittedEditSlice edit_slice;
        edit_slice.state = edit.state;
        edit_slice.source_version_id = edit.source_version_id;
        slice.uncommitted_edits.push_back(std::move(edit_slice));
    }
    slice.missing_source_asset_ids = view.missing_source_asset_ids;
    return slice;
}

WellDetailHost::WellDetailHost(pwb::ui_wellseis::qt::WellDetailPanel* panel)
    : panel_(panel) {}

void WellDetailHost::reconfigure(const domain::Json* project_root,
                                 const std::filesystem::path& sqlite_path,
                                 const std::filesystem::path& project_dir) {
    service_.reset();
    source_.reset();
    project_root_.reset();
    if (panel_ == nullptr) return;
    if (project_root == nullptr) {
        panel_->clear();
        return;
    }
    project_root_ = *project_root;  // owned copy — the service keeps a ref
    source_ = std::make_unique<pwb::data::RepositoryWorkspaceSource>(
        sqlite_path, project_dir);
    service_ = std::make_unique<pwb::data::EntityWorkspaceService>(
        *project_root_, source_.get());
}

bool WellDetailHost::update(const std::string& well_id) {
    if (panel_ == nullptr) return false;
    if (service_ == nullptr || well_id.empty()) {
        panel_->clear();
        return false;
    }
    // with_stale=true: the panel's 过期成果 card is the point of the view
    // (document-snapshot cost class — one well, bounded).
    auto view = service_->well_view(well_id, true);
    if (!view.has_value()) {
        panel_->clear();
        return false;
    }
    panel_->set_view(well_detail_slice(*view), true);
    return true;
}

// ---- 3. lineage / impact -----------------------------------------------------

LineageQueryResult lineage_rows(const std::filesystem::path& project_file,
                                const std::string& version_id,
                                const std::string& direction) {
    LineageQueryResult out;
    out.direction = direction;
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) {
        out.error = "目录库打开失败: " + document.error().message;
        return out;
    }
    pwb::catalog::DocumentIndex index(document.value());
    auto chain = pwb::catalog::build_lineage_chain(document.value(), index,
                                                   version_id, direction);
    if (!chain.is_ok()) {
        out.error = chain.error().message;
        return out;
    }
    out.ok = true;
    out.node_count = chain.value().node_count;
    out.truncated = chain.value().truncated;
    // Pre-order flattening (depth kept for indentation).
    std::function<void(const pwb::catalog::LineageChainNode&, int)> walk =
        [&](const pwb::catalog::LineageChainNode& node, int depth) {
            LineageRow row;
            row.depth = depth;
            row.asset_id = node.asset_id;
            row.asset_name = node.asset_name;
            row.stage = std::string(domain::to_string(node.stage));
            row.version_id = node.version_id;
            row.version_number = node.version_number;
            row.path = node.path;
            if (node.run_id.has_value()) row.run_id = *node.run_id;
            out.rows.push_back(std::move(row));
            for (const auto& child : node.children) walk(child, depth + 1);
        };
    walk(chain.value().root, 0);
    return out;
}

ImpactSummary delete_impact_summary(
    const std::filesystem::path& project_file,
    const std::optional<std::string>& version_id,
    const std::optional<std::string>& asset_id) {
    ImpactSummary out;
    pwb::catalog::CatalogRepository repository(
        pwb::project::catalog_sqlite_for(project_file));
    auto document = repository.open_read_only();
    if (!document.is_ok()) {
        out.error = "目录库打开失败: " + document.error().message;
        return out;
    }
    pwb::catalog::DocumentIndex index(document.value());
    pwb::catalog::ImpactService service(document.value(), index);

    // Entity links from the project document (the cascade advice covers
    // entity↔asset bindings; unknown ids are skipped by the service).
    const auto entity_links =
        impact_entity_links(read_project_json(project_file));

    auto impact = service.delete_impact(
        version_id, asset_id,
        entity_links.empty() ? nullptr : &entity_links);
    out.ok = true;
    out.live_descendants = static_cast<int>(impact.live_descendants.size());
    out.broken_edges = impact.broken_lineage_edges;
    out.linked_entities = static_cast<int>(impact.linked_entities.size());
    out.lines.reserve(impact.cascade_advice.size() + 4);
    out.lines.push_back("受影响版本: " +
                        std::to_string(impact.target_version_ids.size()));
    out.lines.push_back("存活下游: " + std::to_string(out.live_descendants));
    out.lines.push_back("断裂血缘边: " + std::to_string(out.broken_edges));
    out.lines.push_back("关联实体: " + std::to_string(out.linked_entities));
    for (const auto& advice : impact.cascade_advice) {
        out.lines.push_back(advice);  // service-supplied Chinese advice
    }
    return out;
}

// ---- 4. workspace install ----------------------------------------------------

std::string execute_folder_ingest(
    const std::filesystem::path& project_file,
    const pwb::data::IngestPlan& plan,
    const std::vector<upd::PlanItemRow>& rows) {
    auto session = pwb::data::WritableSession::open(project_file);
    if (!session.is_ok()) {
        throw std::runtime_error("工程以只读/损坏状态打开: " +
                                 session.error().message);
    }
    pwb::data::IngestPlan reviewed = plan;  // copy — review applied here
    upd::apply_plan_rows(reviewed, rows);
    auto report = pwb::data::execute_ingest_plan(reviewed, session.value());
    const auto save =
        session.value().manager().save(session.value().document());
    if (!save.is_ok()) {
        throw std::runtime_error("工程文档保存失败: " + save.error().message);
    }
    std::string summary = "导入 " +
                          std::to_string(report.imported_version_ids.size()) +
                          " 个版本 · 绑定 " +
                          std::to_string(report.bound_links) + " 条链接";
    if (report.created_entities > 0) {
        summary += " · 新建实体 " + std::to_string(report.created_entities);
    }
    if (!report.skipped.empty()) {
        summary += " · 跳过 " + std::to_string(report.skipped.size());
    }
    if (!report.issues.empty()) {
        summary += "\n问题: " + join_strings(report.issues, "; ");
    }
    return summary;
}

WorkspaceWiring install_data_workspace(updqt::DataWorkspace& workspace,
                                       updqt::AssetSelectionBus* bus,
                                       StoreProvider store,
                                       QWidget* dialog_parent,
                                       std::function<void()> refresh_notify) {
    WorkspaceWiring wiring;

    // Toolbar at the top of the workspace's CENTER column (the first
    // production host of DataToolbar — its 计划导入 button drives the
    // two-phase ingest). The workspace's own layout is a QHBoxLayout over
    // the main splitter; the center column is splitter index 1 and owns a
    // QVBoxLayout, so walk that structure instead of casting the outer
    // layout (which is horizontal and would never match).
    auto* toolbar = new updqt::DataToolbar(&workspace);
    bool toolbar_placed = false;
    if (auto* outer = qobject_cast<QHBoxLayout*>(workspace.layout())) {
        if (auto* splitter =
                qobject_cast<QSplitter*>(outer->itemAt(0)->widget())) {
            if (splitter->count() > 1) {
                if (auto* center =
                        qobject_cast<QWidget*>(splitter->widget(1))) {
                    if (auto* center_layout =
                            qobject_cast<QVBoxLayout*>(center->layout())) {
                        center_layout->insertWidget(0, toolbar);
                        toolbar_placed = true;
                    }
                }
            }
        }
    }
    if (!toolbar_placed) {
        toolbar->setParent(&workspace);  // owned fallback (unplaced)
    }
    wiring.toolbar = toolbar;

    // Well detail: the panel takes the workspace's well-detail slot; the
    // host owns one workspace service per open project (deleted with the
    // panel — the presenters-map pattern from closure_preview_install).
    auto* panel = new pwb::ui_wellseis::qt::WellDetailPanel(&workspace);
    workspace.set_well_detail_panel(panel);
    wiring.well_detail = panel;
    auto* host = new WellDetailHost(panel);
    wiring.well_detail_host = host;
    QObject::connect(panel, &QObject::destroyed, panel, [host] {
        delete host;
    });
    QObject::connect(
        panel, &pwb::ui_wellseis::qt::WellDetailPanel::close_requested,
        panel, [&workspace]() { workspace.show_well_detail(false); });

    // Nav tree: entity selection drives the well-detail view.
    if (auto* tree = workspace.navigation_tree()) {
        QObject::connect(
            tree, &updqt::NavigationTree::entity_activated, tree,
            [host, &workspace](const QString& entity_id) {
                // Non-well entities (surveys/geological) honestly clear
                // the panel — well_view() only resolves wells.
                if (host->update(entity_id.toStdString())) {
                    // The detail lives on a hidden stack page until the
                    // workspace switches to it (index 2).
                    workspace.show_well_detail(true);
                }
            });
    }

    // Refresh path: closure_preview pushes bus rows on every project
    // open/switch; that signal is where the nav tree + well host + label
    // seam rebind to the CURRENT store document.
    if (bus != nullptr) {
        QObject::connect(
            // QPointer, not a raw reference: the workspace can be adopted
            // and reparented (viz_e_install) and may die before the
            // shell-owned bus emits again — a dangling &workspace would
            // crash the next refresh.
            bus, &updqt::AssetSelectionBus::assets_changed, bus,
            [workspace_guard = QPointer<updqt::DataWorkspace>(&workspace),
             host, store](const std::vector<upd::AssetRow>& rows,
                          const QString& project_id) {
                (void)rows;
                (void)project_id;
                auto* workspace = workspace_guard.data();
                if (workspace == nullptr) return;
                auto opened = store ? store() : nullptr;
                auto* tree = workspace->navigation_tree();
                if (opened == nullptr) {
                    if (tree != nullptr) tree->clear_project();
                    host->reconfigure(nullptr, {}, {});
                    return;
                }
                // Label seam: catalog names for the per-well role children.
                auto labels =
                    std::make_shared<std::map<std::string, std::string>>();
                auto snapshot = opened->snapshot();
                if (snapshot.is_ok()) {
                    for (const auto& asset : snapshot.value().catalog_assets) {
                        (*labels)[asset.id.str()] = asset.name;
                    }
                }
                if (tree != nullptr) {
                    tree->model().set_asset_label_fn(
                        [labels](const std::string& asset_id) {
                            const auto it = labels->find(asset_id);
                            return it != labels->end() ? it->second
                                                       : asset_id;
                        });
                    tree->model().set_role_order_fn(
                        [](const std::string& entity_type) {
                            std::vector<std::string> roles;
                            for (auto role :
                                 pwb::data::roles_for_entity_type(
                                     entity_type)) {
                                roles.emplace_back(role);
                            }
                            return roles;
                        });
                    tree->model().set_role_display_fn(
                        [](const std::string& role) {
                            return pwb::data::role_display(role);
                        });
                    tree->set_project(
                        build_nav_project_view(opened->document().root()));
                }
                host->reconfigure(&opened->document().root(),
                                  pwb::project::catalog_sqlite_for(
                                      opened->project_file()),
                                  opened->project_file().parent_path());
            });
    }

    // Two-phase ingest: folder pick → build (pure) → review dialog →
    // execute on the writable session (synchronous under a wait cursor —
    // honest simplicity; the job-runtime offload is a follow-up).
    QObject::connect(
        toolbar, &updqt::DataToolbar::plan_import_requested, toolbar,
        [store, dialog_parent, refresh_notify]() {
            auto opened = store ? store() : nullptr;
            if (opened == nullptr) {
                QMessageBox::warning(
                    dialog_parent, QStringLiteral("导入计划"),
                    QStringLiteral("尚未打开工程，无法规划导入。"));
                return;
            }
            const QString folder = QFileDialog::getExistingDirectory(
                dialog_parent, QStringLiteral("选择导入文件夹"));
            if (folder.isEmpty()) return;

            // Duplicate detection needs a catalog snapshot (read-only;
            // honest degrade to "no matching" when the store won't open).
            std::optional<pwb::catalog::CatalogDocument> catalog_document;
            std::string catalog_error;
            {
                pwb::catalog::CatalogRepository repository(
                    pwb::project::catalog_sqlite_for(
                        opened->project_file()));
                auto document = repository.open_read_only();
                if (document.is_ok()) {
                    catalog_document = std::move(document.value());
                } else {
                    catalog_error = document.error().message;
                }
            }

            pwb::data::IngestPlan plan;
            {
                QApplication::setOverrideCursor(Qt::WaitCursor);
                pwb::data::IngestPlanOptions options;
                if (catalog_document.has_value()) {
                    options.catalog = &*catalog_document;
                }
                plan = pwb::data::build_ingest_plan(
                    std::filesystem::path(folder.toStdString()),
                    opened->document(), options);
                QApplication::restoreOverrideCursor();
            }
            if (plan.items.empty()) {
                QMessageBox::information(
                    dialog_parent, QStringLiteral("导入计划"),
                    plan.issues.empty()
                        ? QStringLiteral("所选文件夹没有可导入的文件。")
                        : QStringLiteral("没有可导入的文件:\n%1")
                              .arg(QString::fromStdString(
                                  join_strings(plan.issues, "\n"))));
                return;
            }

            const auto project_file = opened->project_file();
            updqt::IngestPlanDialog dialog(
                upd::ingest_plan_rows(plan),
                [plan, project_file, catalog_error, refresh_notify](
                    const std::vector<upd::PlanItemRow>& rows) -> std::string {
                    try {
                        return execute_folder_ingest(project_file, plan,
                                                     rows);
                    } catch (const std::exception& error) {
                        throw std::runtime_error(
                            std::string(error.what()) +
                            (catalog_error.empty()
                                 ? std::string()
                                 : "（目录快照不可用: " + catalog_error +
                                       "）"));
                    }
                },
                [] {}, dialog_parent);
            QObject::connect(
                &dialog, &updqt::IngestPlanDialog::executed, &dialog,
                [dialog_parent](const QString& summary) {
                    if (!summary.isEmpty()) {
                        QMessageBox::information(
                            dialog_parent, QStringLiteral("导入完成"),
                            summary);
                    }
                });
            dialog.exec();
            // New assets/links landed: run the closure refresh (the bus
            // slot above repopulates the nav tree from the saved doc).
            if (refresh_notify) refresh_notify();
        });

    return wiring;
}

}  // namespace pwb::app::v14_lineage
