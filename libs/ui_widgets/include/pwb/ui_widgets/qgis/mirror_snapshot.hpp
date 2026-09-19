#pragma once

// UI-02 — snapshot → QGIS project mirror reconcile, ported from
// paleo_workbench/mapping/qgis_mirror.py (re-exported by
// ui/qgis_stack/mirror.py).
//
// The Python mirror pushes layer specs into the shared QgsProject via
// the render bridge; the native port reconciles the session project
// directly. Semantics preserved (qgis_mirror docstring / #1164):
//  - reconcile by "pwb/doc_id": unchanged layers keep their
//    QgsMapLayer object, tree state and renderer across publishes;
//  - duplicate doc_ids in one snapshot: first publishes, later
//    duplicates are refused with a diagnostic (one Paleo layer ==
//    exactly one QgsMapLayer);
//  - failures are collected and surfaced — a dropped/invalid layer
//    never leaves the mirror silently diverging from the document;
//  - ledger no-op: a layer whose publish tokens are unchanged ships
//    nothing (data_revision 0 disables the ledger);
//  - layers inside the edit window are NOT republished (the mirror is
//    where native edits live; republishing would stomp the buffer);
//  - groups=True skips the flat root-order push — group structure is
//    reconciled by the host's group controller on the same tree;
//  - raster/scalar layers: the scalar data pipeline (GDAL mirror) is
//    not part of this slice — they produce honest failure entries
//    (never silently dropped, never substituted with wrong pixels).

#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

#include <map>
#include <set>
#include <string>
#include <vector>

class QgsMapCanvas;
class QgsMapLayer;
class QgsProject;
class QgsVectorLayer;

namespace pwb::ui_widgets::qgis {

// One document layer's publish spec (the Python snapshot layer object:
// id/name/layer_type/features/metadata/style/visible/opacity/crs/
// data_revision/scale_range/source_path).
struct MirrorLayerSpec {
    QString id;
    QString name;
    QString layer_type = QStringLiteral("vector");  // vector|scalar_grid|raster_source
    // GeoJSON Feature dicts [{"type":"Feature","geometry":{...},
    // "properties":{...},"id":fid}]; the doc feature id is pushed as the
    // "__pwb_fid" property (memory provider keeps no fid authority).
    QVariantList features;
    QVariantMap metadata;   // {"geometry_kind": "point|line|polygon", ...}
    QVariantMap style;      // {"qgis_style": {"renderer_xml","labeling_xml"}, +legacy}
    bool visible = true;
    double opacity = 1.0;
    QString crs;            // auth id; "" -> snapshot project_crs
    // Declared layer extent [xmin,ymin,xmax,ymax] for the CRS-domain
    // check; empty -> feature bounds fallback (R5).
    std::vector<double> extent;
    int data_revision = 0;  // 0 = unknown -> ledger disabled
    double min_scale = 0.0; // scale_range token (0 = unset)
    double max_scale = 0.0;
    QString source_path;    // raster_source only
    // Provenance id (snapshot_source_version_ids parity); "" = unset.
    QString source_version_id;
};

struct MirrorSnapshot {
    std::vector<MirrorLayerSpec> layers;
    QString project_crs;
};

struct MirrorResult {
    QStringList mirrored_qgis_ids;  // published QGIS layer ids, snapshot order
    QStringList seen_doc_ids;       // doc ids published this pass
    QStringList failures;           // "layer <id>: <reason>" diagnostics
};

struct MirrorOptions {
    // V5 groups: skip the flat root-order push (host reconciles group
    // structure on the same tree).
    bool groups = false;
    // M0 §3 stop-publish window: layer ids whose data must not be
    // republished this pass (live edit buffers).
    std::set<QString> edit_frozen_ids;
    // Canvas whose render flag is held for the duration of the publish
    // (the Python tree_transaction window: N upserts share one native
    // refresh). nullptr = no window.
    QgsMapCanvas* refresh_window = nullptr;
};

// Per-doc-id publish ledger (the Python _MIRROR_LEDGER keyed by
// (stack, doc_id) — session lifetime makes a per-shim instance the
// same scope). Public so the shim owns it across publishes.
class MirrorLedger {
public:
    struct Tokens {
        int data_revision = 0;
        std::string style_sig;
        bool visible = false;
        double opacity = 0.0;
        std::string geom_kind;
        std::string name;
        double min_scale = 0.0;
        double max_scale = 0.0;
        std::string fields_json;
        std::string crs;
        bool operator==(const Tokens& o) const = default;
    };
    const Tokens* entry(const QString& doc_id) const;
    void store(const QString& doc_id, const QString& qgis_id,
               const Tokens& tokens);
    void erase(const QString& doc_id);
    void clear() { entries_.clear(); }

private:
    std::map<QString, std::pair<QString, Tokens>> entries_;
};

// Incremental reconcile of `project`'s mirror layers to `snapshot`.
// `ledger` persists no-op baselines across publishes (session-owned).
MirrorResult mirror_snapshot_to_project(
    QgsProject& project,
    const MirrorSnapshot& snapshot,
    const MirrorOptions& options,
    MirrorLedger& ledger,
    QStringList* diags = nullptr);

// The Python pwb/doc_id join key (QgsMapLayer custom property).
inline const char* kDocIdProperty = "pwb/doc_id";
inline const char* kPwbFidField = "__pwb_fid";

}  // namespace pwb::ui_widgets::qgis
