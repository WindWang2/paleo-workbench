#pragma once

// CLOSURE-JOINT3D (06) — the product data-plane binder for the joint 3D
// host. Resolves the open project's REAL assets from the store snapshot
// (newest published PWBVOL1 volume; well-head / time-depth catalog
// entries) and binds them into the VizCJointHost: wells + TD tables
// synchronously (small text parses), the volume through the host's
// JobCenter-backed open. Project identity is set first so persisted
// joint state (fences, slices) is scoped per project and can never leak
// across projects.
#ifdef PWB_WITH_UI_WELLSEIS

#include <filesystem>
#include <string>

namespace pwb::data {
struct ProjectSnapshotV1;
}
namespace pwb::app::viz_c {
class VizCJointHost;
}

namespace pwb::app::closure_joint3d {

struct BindOutcome {
    bool volume_requested = false;
    int wells_bound = 0;
    int td_tables_bound = 0;
    // Human-readable summary of what was (not) bound — the caller shows
    // it honestly; an empty string means "nothing to report".
    std::string message;
};

BindOutcome bind_project_assets(
    viz_c::VizCJointHost& host,
    const pwb::data::ProjectSnapshotV1& snapshot,
    const std::filesystem::path& project_dir,
    const std::string& project_identity);

}  // namespace pwb::app::closure_joint3d

#endif  // PWB_WITH_UI_WELLSEIS
