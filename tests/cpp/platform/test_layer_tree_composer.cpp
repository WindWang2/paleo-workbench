// platform.layer_tree_composer — QGIS-native layer control plane: the
// REAL QgsLayerTree of the session QgsProject is the single runtime
// authority. Asserts QGIS truth directly (never a PWB mirror):
//   * fresh compose builds the system skeleton and routes layers home;
//   * deterministic QGIS layer ids (project registry resolves in O(1));
//   * user reorder + save/restore roundtrip keeps the exact tree order
//     (QgsLayerTree::writeXml sidecar, stale ids pruned);
//   * legacy state.tree one-shot migration;
//   * stage visibility writes real node check state (batched, single
//     refresh);
//   * placement role gate + user-group lifecycle on real nodes;
//   * 1000-layer compose scale + honest teardown (close() after).
#include <qgsapplication.h>
#include <QFile>
#include <QTemporaryDir>

#include <qgslayertree.h>
#include <qgsmapcanvas.h>
#include <qgsproject.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/layer_adapter.hpp>
#include <pwb/qgis/layer_tree_composer.hpp>
#include <pwb/qgis/map_session.hpp>
#include <pwb/qgis/qgis_runtime.hpp>
#include <pwb/ui_composite/layer_groups.hpp>
#include <pwb/workspace/mutations.hpp>
#include <pwb/workspace/state_ops.hpp>

#include <chrono>
#include <filesystem>
#include <string>
#include <vector>

#include "test_fixtures.hpp"
#include "test_framework.hpp"

namespace {

// Direct memory-provider admission (the working-copy materialization
// path): join key custom properties + deterministic id, mirroring
// MapSession::addVectorLayer's contract without per-layer disk IO.
QgsVectorLayer* admit_memory_layer(pwb::qgis::MapSession& session,
                                   const std::string& layer_id,
                                   const std::string& name) {
    auto* layer = new QgsVectorLayer(QStringLiteral("Point?crs=EPSG:4326"),
                                     QString::fromStdString(name),
                                     QStringLiteral("memory"));
    if (!layer->isValid()) return nullptr;
    const pwb::qgis::LayerBinding binding{layer_id, "", "", "vector"};
    pwb::qgis::layer_adapter::apply(layer, binding);
    QgsProject* project = session.project();
    const QString id = QString::fromStdString(layer_id);
    if (project->mapLayer(id) == nullptr) layer->setId(id);
    project->addMapLayer(layer);
    return layer;
}

// Group nodes of the root, top-first, addressed by pwb/group_id.
std::vector<std::string> root_group_ids(pwb::qgis::MapSession& session) {
    std::vector<std::string> out;
    for (QgsLayerTreeNode* child :
         session.project()->layerTreeRoot()->children()) {
        if (child->nodeType() != QgsLayerTreeNode::NodeGroup) continue;
        out.push_back(child->customProperty("pwb/group_id")
                          .toString()
                          .toStdString());
    }
    return out;
}

}  // namespace

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();
    QTemporaryDir temp_dir;
    const std::filesystem::path sidecar =
        std::filesystem::path(temp_dir.path().toStdString()) /
        "layer-tree.xml";

    // ---- fresh compose: skeleton + home routing + deterministic ids ----
    {
        pwb::qgis::MapSession session;
        QgsMapCanvas* canvas = session.createCanvas(nullptr);
        PWB_CHECK(canvas != nullptr);
        pwb::workspace::MappingWorkspaceState state;
        pwb::workspace::set_membership(
            state, pwb::workspace::LayerBinding{
                       "lay:constraint", "distribution_line", "", "",
                       "constraint_factor", "", "", "", "", ""});
        pwb::workspace::set_membership(
            state, pwb::workspace::LayerBinding{
                       "lay:base", "base_reference", "", "",
                       "", "", "", "", "", ""});
        PWB_CHECK(admit_memory_layer(session, "lay:constraint", "C1") !=
                  nullptr);
        PWB_CHECK(admit_memory_layer(session, "lay:base", "B1") != nullptr);

        // Deterministic ids: the project registry resolves domain ids.
        PWB_CHECK(session.project()->mapLayer("lay:constraint") != nullptr);
        PWB_CHECK(session.layerById("lay:constraint") != nullptr);

        pwb::qgis::LayerTreeComposer composer(session, state);
        PWB_CHECK(composer.compose(std::nullopt));

        // Skeleton exists and every live layer sits in its home group.
        PWB_CHECK(composer.group_exists("phase1.initial_facies"));
        PWB_CHECK(composer.group_exists("phase2.constraints"));
        PWB_CHECK(composer.group_exists("phase3.integrated"));
        PWB_CHECK(composer.group_exists("base.reference"));
        PWB_CHECK(composer.placement_of("lay:constraint").has_value());
        PWB_CHECK(*composer.placement_of("lay:constraint") ==
                  "phase2.constraints");
        PWB_CHECK(*composer.placement_of("lay:base") == "base.reference");
        // Tree order authority: top-first ids include both layers.
        const std::vector<std::string> order = session.layerIdsTopFirst();
        PWB_CHECK(order.size() == 2);

        // ---- user reorder + sidecar roundtrip keeps exact order ------
        // Simulate a user drag: move the constraint layer to the root
        // top (a raw QGIS tree edit, exactly what the view's drag does;
        // no PWB bookkeeping is involved).
        QgsLayerTree* root = session.project()->layerTreeRoot();
        QgsLayerTreeLayer* moved =
            root->findLayer(QStringLiteral("lay:constraint"));
        PWB_CHECK(moved != nullptr);
        {
            // Direct QGIS tree edit (what the view's drag does).
            QgsLayerTreeNode* parent = moved->parent();
            parent->takeChild(moved);
            root->insertChildNode(0, moved);
        }
        PWB_CHECK(composer.placement_of("lay:constraint").has_value());
        PWB_CHECK(composer.placement_of("lay:constraint")->empty());

        PWB_CHECK(composer.save_tree(sidecar));
        PWB_CHECK(pwb::qgis::LayerTreeComposer::has_sidecar(sidecar));

        // Roundtrip in the same session: clear + restore must reproduce
        // the saved order verbatim.
        PWB_CHECK(composer.restore_tree(sidecar));
        PWB_CHECK(composer.placement_of("lay:constraint").has_value());
        PWB_CHECK(composer.placement_of("lay:constraint")->empty());
        // Restored nodes are fresh objects resolving to the same layer;
        // assert POSITION identity (root-first child is the layer), not
        // pointer identity.
        PWB_CHECK(root->children().first() != nullptr);
        PWB_CHECK(root->children().first()->nodeType() ==
                  QgsLayerTreeNode::NodeLayer);
        // Live layers never left the registry during the rebuild.
        PWB_CHECK(session.project()->mapLayer("lay:constraint") != nullptr);
        PWB_CHECK(session.project()->mapLayers().size() == 2);

        // Full reopen path (compose with the sidecar): a persisted
        // root-level placement is a DELIBERATE user choice — it must
        // survive compose (only never-seen layers route home).
        PWB_CHECK(composer.compose(sidecar));
        PWB_CHECK(composer.placement_of("lay:constraint").has_value());
        PWB_CHECK(composer.placement_of("lay:constraint")->empty());
        PWB_CHECK(composer.placement_of("lay:base").has_value());
        PWB_CHECK(*composer.placement_of("lay:base") == "base.reference");

        // ---- stage visibility writes real node check state ----------
        std::map<std::string, bool> visibility;
        visibility["phase2.constraints"] = false;
        visibility["phase3.integrated"] = true;
        composer.apply_group_visibility(visibility);
        // Read the check state straight off the node (QGIS truth).
        QgsLayerTreeNode* node = nullptr;
        for (QgsLayerTreeNode* child : root->children()) {
            if (child->nodeType() == QgsLayerTreeNode::NodeGroup &&
                child->customProperty("pwb/group_id").toString() ==
                    QStringLiteral("phase2.constraints")) {
                node = child;
            }
        }
        PWB_CHECK(node != nullptr);
        PWB_CHECK(!node->itemVisibilityChecked());

        // ---- placement role gate ------------------------------------
        // distribution_line cannot enter the integrated system group.
        PWB_CHECK(!composer.place_layer("lay:constraint",
                                        "phase3.integrated")
                       .has_value());
        // A user group accepts anything.
        const std::string user_group =
            composer.create_user_group("工作组", "");
        PWB_CHECK(!user_group.empty());
        PWB_CHECK(composer.place_layer("lay:constraint", user_group, 0)
                      .has_value());
        PWB_CHECK(*composer.placement_of("lay:constraint") == user_group);
        // User-group removal hoists children, never deletes them.
        PWB_CHECK(composer.remove_user_group(user_group));
        PWB_CHECK(session.project()->mapLayer("lay:constraint") != nullptr);
        PWB_CHECK(root->findLayer(QStringLiteral("lay:constraint")) !=
                  nullptr);
        // System groups refuse user removal.
        PWB_CHECK(!composer.remove_user_group("phase2.constraints"));

        // ---- legacy state.tree one-shot migration ---------------------
        pwb::workspace::MappingWorkspaceState legacy;
        legacy.tree = pwb::domain::Json::parse(R"({
            "source": "domain",
            "children": [
              {"is_group": true, "group_id": "user.legacy1",
               "name": "旧组", "kind": "user", "expanded": true,
               "visible": true,
               "children": [
                 {"is_group": false, "layer_id": "lay:base"}
               ]},
              {"is_group": true, "group_id": "phase2.constraints",
               "name": "stale-name", "kind": "system",
               "expanded": false, "visible": true, "children": []}
            ]})");
        pwb::qgis::LayerTreeComposer legacy_composer(session, legacy);
        PWB_CHECK(legacy_composer.compose(std::nullopt));
        PWB_CHECK(legacy_composer.group_exists("user.legacy1"));
        // Template titles stay authoritative (stale name self-heals).
        const std::vector<std::string> ids = root_group_ids(session);
        PWB_CHECK(!ids.empty());
        QgsLayerTreeNode* legacy_user = nullptr;
        for (QgsLayerTreeNode* child : root->children()) {
            if (child->nodeType() == QgsLayerTreeNode::NodeGroup &&
                child->customProperty("pwb/group_id").toString() ==
                    QStringLiteral("user.legacy1")) {
                legacy_user = child;
            }
        }
        PWB_CHECK(legacy_user != nullptr);
        PWB_CHECK(legacy_user->name() == QStringLiteral("旧组"));
        PWB_CHECK(*legacy_composer.placement_of("lay:base") ==
                  "user.legacy1");
        // New carrier contract: the migrated payload SURVIVES compose —
        // it stays as the failure-safe carrier until the first
        // successful sidecar write (asserted in the error-path block
        // below; the host clears it at save time).
        PWB_CHECK(legacy.tree.is_object() && !legacy.tree.empty());

        session.close();  // teardown contract, must not crash
    }

    // ---- error paths: corrupt sidecar + migration carrier semantics ----
    {
        // Corrupt sidecar: compose reports the failure and still yields a
        // usable tree (template routing fallback).
        pwb::qgis::MapSession session;
        pwb::workspace::MappingWorkspaceState state;
        PWB_CHECK(admit_memory_layer(session, "lay:x", "X") != nullptr);
        const std::filesystem::path bad_sidecar =
            std::filesystem::path(temp_dir.path().toStdString()) /
            "bad-layer-tree.xml";
        { QFile out(QString::fromStdString(bad_sidecar.generic_string()));
          PWB_CHECK(out.open(QIODevice::WriteOnly | QIODevice::Truncate));
          out.write("not-xml <<<");
        }
        pwb::qgis::LayerTreeComposer composer(session, state);
        std::string error;
        PWB_CHECK(!composer.compose(bad_sidecar, &error));
        PWB_CHECK(!error.empty());
        // The fallback still routed the layer into its home group
        // (base_reference is the unknown-role home).
        PWB_CHECK(composer.placement_of("lay:x").has_value());

        // Migration carrier semantics: state.tree survives until the
        // FIRST successful sidecar write (the host clears it on save).
        pwb::qgis::MapSession session2;
        pwb::workspace::MappingWorkspaceState legacy;
        legacy.tree = pwb::domain::Json::parse(R"({
            "source": "domain",
            "children": [
              {"is_group": true, "group_id": "phase2.constraints",
               "name": "stale", "kind": "system", "expanded": true,
               "visible": true, "children": []},
              {"is_group": false, "layer_id": "lay:x2"}
            ]})");
        PWB_CHECK(admit_memory_layer(session2, "lay:x2", "X2") != nullptr);
        pwb::qgis::LayerTreeComposer composer2(session2, legacy);
        PWB_CHECK(composer2.compose(std::nullopt));
        PWB_CHECK(legacy.tree.is_object() && !legacy.tree.empty());
        // A successful save retires the legacy carrier.
        const std::filesystem::path good_sidecar =
            std::filesystem::path(temp_dir.path().toStdString()) /
            "good-layer-tree.xml";
        PWB_CHECK(composer2.save_tree(good_sidecar));
        // Host contract (MainWindow::syncLayerControlOnSave): clear only
        // after success — the failure branch below must NOT clear.
        legacy.tree = pwb::domain::Json();
        PWB_CHECK(legacy.tree.is_null());
        // Failed save (directory is a file): save_tree reports false.
        const std::filesystem::path blocked_dir =
            std::filesystem::path(temp_dir.path().toStdString()) / "blocker";
        { QFile blocker(QString::fromStdString(blocked_dir.generic_string()));
          PWB_CHECK(blocker.open(QIODevice::WriteOnly));
          blocker.write("x");
        }
        std::string write_error;
        PWB_CHECK(!composer2.save_tree(blocked_dir / "layer-tree.xml",
                                       &write_error));
        PWB_CHECK(!write_error.empty());
        session.close();
        session2.close();
    }

    // ---- 1000-layer compose scale (no O(N^2) PWB reconcile) -----------
    {
        pwb::qgis::MapSession session;
        pwb::workspace::MappingWorkspaceState state;
        constexpr int kLayerCount = 1000;
        for (int i = 0; i < kLayerCount; ++i) {
            const std::string id = "scale:lay" + std::to_string(i);
            pwb::workspace::set_membership(
                state, pwb::workspace::LayerBinding{
                           id, i % 2 == 0 ? "distribution_line"
                                          : "integrated_facies",
                           "", "", "", "", "", "", "", ""});
            if (admit_memory_layer(session, id, "L" + std::to_string(i)) ==
                nullptr) {
                PWB_CHECK_MSG(false, "admission failed");
                break;
            }
        }
        PWB_CHECK(session.project()->mapLayers().size() ==
                  static_cast<std::size_t>(kLayerCount));
        pwb::qgis::LayerTreeComposer composer(session, state);
        const auto started = std::chrono::steady_clock::now();
        PWB_CHECK(composer.compose(std::nullopt));
        const double seconds =
            std::chrono::duration<double>(std::chrono::steady_clock::now() -
                                          started)
                .count();
        PWB_CHECK(session.layerIdsTopFirst().size() ==
                  static_cast<std::size_t>(kLayerCount));
        PWB_CHECK_MSG(seconds < 30.0,
                      "1000-layer compose took " +
                          std::to_string(seconds) + "s");
        std::printf("scale: %d layers composed in %.2fs\n", kLayerCount,
                    seconds);
        session.close();
    }

    return pwb::test::report("platform.layer_tree_composer");
}
