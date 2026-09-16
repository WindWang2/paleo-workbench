#pragma once

// B-side consumer interfaces (CPP-A contract §4). B (feat/cpp-data-project)
// owns the real implementation; the platform consumes these only. In this
// round the platform verifies wiring with test substitutes in
// tests/cpp/platform/ — reports must say "module-only", never "integrated".

#include <string>
#include <vector>

#include <pwb/qgis/edit_controller.hpp>

namespace pwb::application {

// Frozen semantics per protocol 接口握手 v1 (owned by B):
//   immutable snapshot; existing project/workspace/member IDs, version
//   bindings, CRS, layer URIs, original QGIS XML; carries diagnostics and
//   unknown fields.
struct ProjectSnapshotV1 {
    std::string project_id;
    std::string schema_version;
    std::vector<std::string> diagnostics;   // unknown-field / audit notes
};

// domain layer id + asset/version/kind; QGIS custom-property join key.
struct LayerBindingV1 {
    std::string layer_id;
    std::string asset_id;
    std::string version_id;
    std::string kind;

    pwb::qgis::LayerBinding to_qgis_binding() const {
        return pwb::qgis::LayerBinding{layer_id, asset_id, version_id, kind};
    }
};

// operation id idempotency; base version optimistic lock; staged asset
// path/hash; original version never overwritten.
struct CommitRequestV1 {
    std::string operation_id;
    std::string base_version;
    pwb::qgis::StagedAsset staged;
};

struct CommitReceiptV1 {
    bool ok = false;
    std::string new_version;
    std::string run_id;
    std::string error;
};

class IProjectStore {
public:
    virtual ~IProjectStore() = default;
    virtual ProjectSnapshotV1 open(const std::string& project_uri) = 0;
    virtual std::vector<LayerBindingV1> load_bindings() = 0;
    virtual CommitReceiptV1 commit(const CommitRequestV1& request) = 0;
};

}  // namespace pwb::application
