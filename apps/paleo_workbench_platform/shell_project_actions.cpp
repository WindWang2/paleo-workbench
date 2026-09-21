// cpp-close-12 — shell project-actions integration slice (see the header
// for the contract). GUI-thread only: every path here touches the live
// document / session, exactly like the openProject/newProject/saveEdits
// production bodies it composes.

#include "shell_project_actions.hpp"

#include <QFileDialog>
#include <QMessageBox>
#include <QString>
#include <QStringList>

#include <fstream>
#include <system_error>

#include <pwb/application/project_session.hpp>
#include <pwb/data/commit_coordinator.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/workspace/mutations.hpp>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/project/manager.hpp>

#include "app_context.hpp"
#include "main_window.hpp"

namespace pwb::app {

using pwb::application::PwbDataStore;

namespace {

// The frozen 8-well porosity fixture (same data as the reserved
// "builtin.sample_wells" layer source) rendered as a GeoJSON point
// FeatureCollection so it can flow through the real catalog publish
// lifecycle and materialize as an editable working-copy layer.
pwb::domain::Json sample_wells_geojson() {
    static constexpr struct {
        const char* id;
        const char* name;
        double x;
        double y;
        double porosity;
    } wells[] = {
        {"W1", "井-1", 114.10, 22.50, 18.5},
        {"W2", "井-2", 114.25, 22.52, 22.3},
        {"W3", "井-3", 114.38, 22.48, 15.2},
        {"W4", "井-4", 114.15, 22.65, 24.1},
        {"W5", "井-5", 114.30, 22.68, 19.8},
        {"W6", "井-6", 114.42, 22.62, 12.4},
        {"W7", "井-7", 114.20, 22.80, 26.5},
        {"W8", "井-8", 114.35, 22.82, 21.0},
    };
    pwb::domain::Json features = pwb::domain::Json::array();
    for (const auto& well : wells) {
        features.push_back(pwb::domain::Json{
            {"type", "Feature"},
            {"geometry",
             pwb::domain::Json{
                 {"type", "Point"},
                 {"coordinates", pwb::domain::Json{well.x, well.y}},
             }},
            {"properties",
             pwb::domain::Json{
                 {"well_id", well.id},
                 {"name", well.name},
                 {"孔隙度", well.porosity},
             }},
        });
    }
    return pwb::domain::Json{
        {"type", "FeatureCollection"},
        {"features", std::move(features)},
    };
}

int section_size(const pwb::project::ProjectDocument& document,
                 const char* key) {
    const pwb::domain::Json* section = document.find_section(key);
    if (section == nullptr || !section->is_array()) return 0;
    return static_cast<int>(section->size());
}

}  // namespace

namespace shell_project_actions {

QString save_open_project(MainWindow& window, QString* saved_to) {
    PwbDataStore* store = window.context().projectStore().get();
    if (store == nullptr) {
        // Python parity note: the Python controller falls into a Save-As
        // dialog here; the C++ shell keeps the one-session-per-window
        // contract, so there is no unsaved in-memory project to name — the
        // honest answer is "no open project".
        return QObject::tr("没有打开的工程");
    }

    // #1126 parity: an open edit session must reach the catalog before the
    // document write, or the persisted project would silently miss it
    // (same stage_commit path as the close-time Save branch; a failed
    // commit aborts the save and keeps the edits staged).
    if (window.anyDirtyEditSession()) {
        const std::filesystem::path staged_dir =
            std::filesystem::temp_directory_path() / "pwb-platform" / "staged";
        const QString commit_error = window.commitActiveLayer(staged_dir);
        if (!commit_error.isEmpty()) {
            return QObject::tr("编辑提交失败，工程未保存：%1").arg(commit_error);
        }
    }

    // BEGIN V14-QGIS-CONTROL
#ifdef PWB_WITH_CONV_27
    // Persist the live layer-control workspace state (desired tree,
    // memberships, stage view states) into the document before the save
    // pipeline serializes it.
    window.syncLayerControlOnSave();
#endif
    // END V14-QGIS-CONTROL
#ifdef PWB_WITH_STAGE_FLOW
    // V14 constraint authoring (#1446): harvest the constraint layers'
    // digitized features into the linked ConstraintLine coordinates
    // (+ content fingerprints) before the document write — the same
    // flush-then-harvest order as Python stage_save. Failures are
    // per-layer honest: an empty layer never wipes synced geometry.
    window.syncConstraintGeometryOnSave();
#endif
    pwb::project::ProjectManager manager(store->project_file());
    auto prepared = manager.prepare_save(store->document());
    if (!prepared.is_ok()) {
        return QString::fromStdString(prepared.error().message);
    }
    auto executed = manager.execute_save(prepared.value());
    if (!executed.is_ok()) {
        return QString::fromStdString(executed.error().message);
    }
    manager.commit_save(store->document(), prepared.value(),
                        executed.value());
    if (saved_to != nullptr) {
        *saved_to = QString::fromStdString(store->project_file().string());
    }
    return QString();
}

QString project_properties_text(MainWindow& window) {
    PwbDataStore* store = window.context().projectStore().get();
    if (store == nullptr) {
        // Python shows the dialog only with a project; the C++ entry keeps
        // an honest empty-project answer instead of a fabricated one.
        return QObject::tr("没有打开的工程");
    }
    const pwb::project::ProjectDocument& document = store->document();
    const auto meta = document.meta();
    // Python parity: "未保存" cannot occur here — a store-backed session
    // always has its .paleo.json on disk (the open/new flows guarantee it).
    const QString path =
        QString::fromStdString(store->project_file().string());
    QString display_crs = QStringLiteral("—");
    if (const pwb::domain::Json* coordinate =
            document.find_section("coordinate");
        coordinate != nullptr && coordinate->is_object()) {
        const auto it = coordinate->find("display_crs");
        if (it != coordinate->end() && it->is_string()) {
            display_crs = QString::fromStdString(it->get<std::string>());
        }
    }
    QStringList lines;
    const std::string region =
        meta.has_value() ? meta->region : std::string();
    lines << QObject::tr("工程名称: %1").arg(QString::fromStdString(
        meta.has_value() ? meta->name : std::string()));
    // Python parity: `region or '—'` (empty region renders the dash).
    lines << QObject::tr("区域: %1")
                 .arg(region.empty()
                          ? QStringLiteral("—")
                          : QString::fromStdString(region));
    lines << QObject::tr("工程文件: %1").arg(path);
    lines << QObject::tr("资源数量: %1").arg(section_size(document,
                                                          "resources"));
    lines << QObject::tr("导出图件: %1").arg(section_size(document,
                                                          "export_artifacts"));
    lines << QObject::tr("显示坐标系: %1").arg(display_crs);
    lines << QObject::tr("版本: %1").arg(QString::fromStdString(
        meta.has_value() ? meta->app_version : std::string()));
    return lines.join(QLatin1Char('\n'));
}

QString bootstrap_sample_project(MainWindow& window,
                                 const QString& sample_dir) {
    // One project session per window (the newProject/openProject contract;
    // the Python in-window replace has no C++ composition equivalent yet —
    // recorded in the line-12 findings).
    if (window.context().session().store() != nullptr) {
        return QObject::tr("已有工程打开（每窗口一个工程会话）");
    }

    // Real production bootstrap: document factory + empty catalog +
    // boundary asset through B's run lifecycle (the newProject body, which
    // also opens the created project).
    const QString open_error =
        window.newProject(sample_dir, QStringLiteral("惠西南样例工程"));
    if (!open_error.isEmpty()) {
        return open_error;
    }

    PwbDataStore* store = window.context().projectStore().get();
    if (store == nullptr) {
        // newProject succeeded but the session store is not attached — an
        // upstream contract break; never fabricate success.
        return QObject::tr("样例工程已创建，但会话未绑定数据存储");
    }

    // Publish the builtin sample wells through the same run lifecycle the
    // boundary bootstrap used (register → stage → publish).
    const std::filesystem::path project_dir =
        store->project_file().parent_path();
    const std::filesystem::path staged_geojson =
        project_dir / ".pwb-bootstrap" / "sample-wells-v1.geojson";
    std::error_code ec;
    std::filesystem::create_directories(staged_geojson.parent_path(), ec);
    if (ec) {
        return QObject::tr("样例井位暂存目录创建失败：%1")
            .arg(QString::fromStdString(ec.message()));
    }
    {
        std::ofstream out(staged_geojson, std::ios::binary);
        out << sample_wells_geojson().dump();
        if (!out.good()) {
            return QObject::tr("样例井位 GeoJSON 写入失败");
        }
    }
    const pwb::domain::RunId run_id{std::string("run_sample-wells-0001")};
    pwb::data::RunRegistrationV1 registration;
    registration.run_id = run_id;
    registration.operation = "bootstrap";
    registration.generator = "pwb-platform";
    auto registered = store->coordinator().register_run(registration);
    if (!registered.is_ok()) {
        return QString::fromStdString(registered.error().message);
    }
    pwb::data::PublishRequestV1 publish;
    publish.operation_id =
        pwb::domain::OperationId{std::string("pub_sample-wells-0001")};
    publish.run_id = run_id;
    publish.new_asset_name = "样例井位";
    publish.new_asset_type = "vector_wells";
    publish.stage = pwb::domain::DataStage::Raw;
    pwb::data::StagedAssetV1 staged;
    staged.source_path = staged_geojson;
    staged.format = "GeoJSON";
    publish.products.push_back(std::move(staged));
    publish.result_metadata = pwb::domain::Json::object();
    auto published =
        store->coordinator().publish_run_result(publish, store->document());
    if (!published.is_ok()) {
        return QString::fromStdString(published.error().message);
    }
    (void)store->export_manifest();

    // Persist the workspace binding so close/reopen materializes the layer
    // like any other bound catalog version (mutations are in-memory; the
    // save below carries them into the project file).
    const std::string version_id =
        published.value().new_version_id.str();
    pwb::workspace::MappingWorkspaceState state =
        pwb::workspace::MappingWorkspaceState::from_json(
            store->document().mapping_workspace(),
            store->document().diagnostics());
    pwb::workspace::LayerBinding binding;
    binding.layer_id = "sample.wells";
    binding.role = "well_source";
    binding.source_asset_id = published.value().asset_id.str();
    binding.source_version_id = version_id;
    binding.binding_kind = "catalog_version";
    (void)pwb::workspace::set_layer_binding(state, binding);
    pwb::workspace::write_mapping_workspace(store->document().root(), state);

    // The sample project is complete only once it is on disk (a bootstrap
    // that dies before the first save must not present itself as done).
    QString saved_to;
    const QString save_error = save_open_project(window, &saved_to);
    if (!save_error.isEmpty()) {
        return save_error;
    }

    // Surface the wells layer on the canvas through the same working-copy
    // materialization the project-open path uses. Any failure here is
    // reported (the project itself is already saved and recoverable via
    // reopen) — never a silent short-of-advertised success.
    auto snapshot = store->snapshot();
    if (!snapshot.is_ok()) {
        return QObject::tr("样例工程已保存，但图层物化失败：%1")
            .arg(QString::fromStdString(snapshot.error().message));
    }
    for (const auto& version : snapshot.value().catalog_versions) {
        if (version.id.str() != version_id || version.trashed) continue;
        const std::filesystem::path payload = project_dir / version.path;
        std::error_code copy_ec;
        if (!std::filesystem::exists(payload, copy_ec)) {
            return QObject::tr("样例工程已保存，但井位 payload 缺失");
        }
        const std::filesystem::path working_dir = project_dir / ".pwb-working";
        std::filesystem::create_directories(working_dir, copy_ec);
        const std::filesystem::path working = working_dir
            / (binding.layer_id + payload.extension().string());
        std::filesystem::copy_file(
            payload, working,
            std::filesystem::copy_options::overwrite_existing, copy_ec);
        if (copy_ec) {
            return QObject::tr("样例工程已保存，但工作副本创建失败：%1")
                .arg(QString::fromStdString(copy_ec.message()));
        }
        pwb::qgis::LayerBinding qbinding{binding.layer_id,
                                         binding.source_asset_id,
                                         binding.source_version_id, "vector"};
        std::string add_error;
        pwb::qgis::MapSession& map = window.context().session().map();
        if (map.addVectorLayer(working.string(), std::string("样例井位"),
                               qbinding, &add_error) == nullptr) {
            return QObject::tr("样例工程已保存，但图层加载失败：%1")
                .arg(QString::fromStdString(add_error));
        }
        pwb::application::DomainLayerFacts facts;
        facts.layer_id = binding.layer_id;
        facts.role = binding.role;
        facts.role_label = "样例井位";
        facts.artifact_maturity = "draft";
        // Working-copy grant: the bound catalog version authorizes
        // edits on the copy (openProject parity).
        facts.write_granted = true;
        window.noteDomainLayerFacts(facts);
        break;
    }
    return QString();
}

}  // namespace shell_project_actions

}  // namespace pwb::app
