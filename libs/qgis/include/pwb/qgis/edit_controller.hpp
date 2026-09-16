#pragma once

// EditController — QGIS edit buffer is THE only mutable geometry state while
// editing (CPP-A contract §3). commit() validates topology first (GEOS),
// refuses illegal geometries (session kept), and on success produces the
// staged asset + EditDeltaV1 for the B-side commit protocol. This class
// never writes catalog.sqlite.

#include <cstdint>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

#include <QMetaObject>
#include <QObject>
#include <QString>

class QgsVectorLayer;

namespace pwb::qgis {

class MapSession;

struct GeometryChangeV1 {
    long long host_fid = 0;
    std::string geojson;   // GeoJSON geometry string
};

struct AttributeChangeV1 {
    long long host_fid = 0;
    std::map<std::string, std::string> attrs;
};

struct EditDeltaV1 {
    std::string source_layer_id;
    std::uint64_t base_revision = 0;
    std::vector<std::string> added_feature_geojson;
    std::vector<long long> removed_host_ids;
    std::vector<GeometryChangeV1> geometry_changes;
    std::vector<AttributeChangeV1> attribute_changes;
};

struct StagedAsset {
    std::filesystem::path geojson_path;
    std::string sha256;
    std::string source_layer_id;
    std::uint64_t base_revision = 0;
    std::uint64_t feature_count = 0;
};

class EditController {
public:
    explicit EditController(MapSession& session);
    ~EditController();

    EditController(const EditController&) = delete;
    EditController& operator=(const EditController&) = delete;

    // All methods return "" on success, else a user-readable reason.

    std::string start_editing(const std::string& layer_id);
    std::string roll_back(const std::string& layer_id);

    // One vertex move = one undoable edit command macro (QGIS undo stack is
    // the single undo authority; no second Python/C++ geometry undo stack).
    std::string move_vertex(const std::string& layer_id, long long fid,
                            int vertex_index, double x, double y);
    std::string add_feature_geojson(const std::string& layer_id,
                                    const std::string& geojson_feature);

    std::string undo(const std::string& layer_id);
    std::string redo(const std::string& layer_id);

    // Topology gate: GEOS validation over the edit buffer's changed
    // geometries; returns the error lines (empty = clean).
    std::vector<std::string> validate_topology(const std::string& layer_id);

    // Commit path: validate -> commitChanges -> staged asset (GeoJSON +
    // sha256) + captured delta. On validation/commit failure the session is
    // kept and the reason returned.
    std::string commit(const std::string& layer_id,
                       const std::filesystem::path& staged_dir,
                       StagedAsset* out_staged, EditDeltaV1* out_delta);

    // Project-level snapping configuration (single authority: QgsProject).
    std::string set_snapping(bool enabled, double tolerance_px = 12.0);

    bool editing(const std::string& layer_id) const;
    bool dirty(const std::string& layer_id) const;
    bool can_undo(const std::string& layer_id) const;
    bool can_redo(const std::string& layer_id) const;

private:
    QgsVectorLayer* editingLayerOrError(const std::string& layer_id,
                                        std::string* error) const;
    void captureCommittedDelta(const std::string& layer_id);
    void disconnectCapture(const std::string& layer_id);

    MapSession& session_;
    struct Capture {
        std::vector<QMetaObject::Connection> connections;
        EditDeltaV1 delta;
        bool armed = false;
    };
    std::map<std::string, Capture> captures_;
    std::map<std::string, std::uint64_t> base_revisions_;
};

}  // namespace pwb::qgis
