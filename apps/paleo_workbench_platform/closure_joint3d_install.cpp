// CLOSURE-JOINT3D (06) — product data-plane binder (see the header).
#include "closure_joint3d_install.hpp"

#ifdef PWB_WITH_UI_WELLSEIS

#include <algorithm>
#include <fstream>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <vector>

#include <pwb/catalog/models.hpp>
#include <pwb/data/facade.hpp>
#include <pwb/geo3d_viz/joint/depth_transform.hpp>
#include <pwb/geo3d_viz/joint/joint_types.hpp>

#include "viz_c_joint_host.hpp"

namespace pwb::app::closure_joint3d {

namespace {

using pwb::geo3d_viz::joint::TimeDepthTable;
using pwb::geo3d_viz::joint::WellHead;

// SMI well-head text: `name x y kb td bx by` per line, '#' comments.
// Mirrors paleo_workbench/viz/joint_well_parsers.parse_well_heads (the
// record-parsing half; the identity registry is a Python-only reconcile).
std::vector<WellHead> parse_well_heads_file(const std::filesystem::path& path) {
    std::vector<WellHead> heads;
    std::ifstream in(path);
    if (!in.is_open()) return heads;
    std::string line;
    while (std::getline(in, line)) {
        const std::size_t hash = line.find('#');
        if (hash != std::string::npos) line = line.substr(0, hash);
        std::istringstream row(line);
        std::string name;
        double x = 0, y = 0, kb = 0, td = 0, bx = 0, by = 0;
        if (!(row >> name)) continue;
        if (!(row >> x >> y >> kb >> td >> bx >> by)) continue;
        if (name.empty()) continue;
        WellHead head;
        head.name = name;
        head.id = name;  // stable text identity (name-keyed registry parity)
        head.x = x;
        head.y = y;
        head.kb_m = kb;
        head.total_depth_m = td;
        head.bottom_x = bx;
        head.bottom_y = by;
        heads.push_back(std::move(head));
    }
    return heads;
}

// SMI TD dat: `TIME TVDSS TVD MD ...` per line (0-based columns 0/3),
// optional `# Well : NAME` comment names the well. Mirrors
// parse_td_table from the frozen Python parser.
std::optional<TimeDepthTable> parse_td_file(const std::filesystem::path& path) {
    std::ifstream in(path);
    if (!in.is_open()) return std::nullopt;
    std::string name = path.stem().string();
    std::vector<double> times;
    std::vector<double> mds;
    std::string line;
    while (std::getline(in, line)) {
        const std::string trimmed = [] (std::string s) {
            while (!s.empty() && (s.front() == ' ' || s.front() == '\t' ||
                                  s.front() == '\r')) {
                s.erase(s.begin());
            }
            while (!s.empty() && (s.back() == ' ' || s.back() == '\t' ||
                                  s.back() == '\r')) {
                s.pop_back();
            }
            return s;
        }(line);
        if (trimmed.empty()) continue;
        if (trimmed[0] == '#') {
            // "# Well : A1" — the well name is the token right after the
            // colon attached to "Well" (label comments must not hijack).
            const std::size_t colon = trimmed.find(':');
            if (colon == std::string::npos) continue;
            const std::string left = trimmed.substr(0, colon);
            std::istringstream left_stream(left);
            std::string token;
            std::string last;
            while (left_stream >> token) last = token;
            std::istringstream right_stream(trimmed.substr(colon + 1));
            std::string first_right;
            if (right_stream >> first_right && last == "Well") {
                name = first_right;
            }
            continue;
        }
        std::istringstream row(trimmed);
        double t = 0, v1 = 0, v2 = 0, md = 0;
        if (!(row >> t >> v1 >> v2 >> md)) continue;
        times.push_back(t);
        mds.push_back(md);
    }
    if (times.size() < 2) return std::nullopt;
    return TimeDepthTable(name, times, mds);
}

}  // namespace

BindOutcome bind_project_assets(
    viz_c::VizCJointHost& host,
    const pwb::data::ProjectSnapshotV1& snapshot,
    const std::filesystem::path& project_dir,
    const std::string& project_identity) {
    BindOutcome outcome;

    // Identity FIRST: persisted fences/slices rebind to the project's
    // own state (save old → restore new inside the host).
    host.set_project_identity(project_identity);

    // Index assets by id (type lookup), versions by asset id.
    std::map<std::string, const pwb::catalog::DataAsset*> assets;
    for (const auto& asset : snapshot.catalog_assets) {
        assets[asset.id.str()] = &asset;
    }
    std::map<std::string, std::vector<const pwb::catalog::DataVersion*>>
        versions_by_asset;
    for (const auto& version : snapshot.catalog_versions) {
        if (version.trashed) continue;
        versions_by_asset[version.asset_id.str()].push_back(&version);
    }

    // ---- TD tables (asset type "time_depth") ---------------------------
    std::map<std::string, TimeDepthTable> td_tables;
    for (const auto& [asset_id, versions] : versions_by_asset) {
        const auto asset_it = assets.find(asset_id);
        if (asset_it == assets.end() ||
            asset_it->second->type != "time_depth") {
            continue;
        }
        for (const pwb::catalog::DataVersion* version : versions) {
            const std::filesystem::path payload = project_dir / version->path;
            auto table = parse_td_file(payload);
            if (table.has_value()) {
                // Both the well name and the file stem register (parity
                // with load_td_tables' dual keying), first one wins.
                td_tables.emplace(table->well_name(), *table);
                td_tables.emplace(
                    payload.stem().string(), std::move(*table));
            }
        }
    }
    outcome.td_tables_bound = static_cast<int>(td_tables.size());

    // ---- wells (asset type "well_head") --------------------------------
    std::vector<WellHead> heads;
    for (const auto& [asset_id, versions] : versions_by_asset) {
        const auto asset_it = assets.find(asset_id);
        if (asset_it == assets.end() ||
            asset_it->second->type != "well_head") {
            continue;
        }
        // Newest version of the asset only.
        const pwb::catalog::DataVersion* newest = nullptr;
        for (const pwb::catalog::DataVersion* version : versions) {
            if (newest == nullptr ||
                version->created_at > newest->created_at) {
                newest = version;
            }
        }
        if (newest == nullptr) continue;
        auto parsed = parse_well_heads_file(project_dir / newest->path);
        heads.insert(heads.end(), parsed.begin(), parsed.end());
    }
    outcome.wells_bound = static_cast<int>(heads.size());
    if (!heads.empty()) {
        // TD tables apply to wells by NAME (a table keyed only by its
        // file stem binds when the stem matches a well name — drop the
        // stem-only aliases that no well claims).
        std::map<std::string, TimeDepthTable> well_keyed;
        for (const auto& head : heads) {
            const auto it = td_tables.find(head.name);
            if (it != td_tables.end()) {
                well_keyed.emplace(head.name, it->second);
            }
        }
        host.set_wells(std::move(heads), std::move(well_keyed));
    }

    // ---- volume (newest non-trashed PWBVOL1) ----------------------------
    const pwb::catalog::DataVersion* newest_volume = nullptr;
    for (const auto& version : snapshot.catalog_versions) {
        if (version.trashed || version.format != "PWBVOL1") continue;
        if (newest_volume == nullptr ||
            version.created_at > newest_volume->created_at) {
            newest_volume = &version;
        }
    }
    if (newest_volume != nullptr) {
        const std::filesystem::path payload =
            project_dir / newest_volume->path;
        // The open job captures its own fresh service instance — its
        // lifetime is the job's, never the caller's member.
        auto service =
            std::make_shared<pwb::seismic_service::SeismicVolumeService>();
        QString error;
        if (host.open_volume(service, payload, &error)) {
            outcome.volume_requested = true;
        } else {
            outcome.message = "体打开被拒绝：" + error.toStdString();
        }
    }

    // Honest summary (never a fake success when nothing was bound).
    if (outcome.message.empty()) {
        std::vector<std::string> parts;
        if (outcome.volume_requested) parts.push_back("体已后台装载");
        if (outcome.wells_bound > 0) {
            parts.push_back(std::to_string(outcome.wells_bound) + " 口井");
        }
        if (outcome.td_tables_bound > 0) {
            parts.push_back(std::to_string(outcome.td_tables_bound) +
                            " 张时深表");
        }
        if (parts.empty()) {
            outcome.message = "工程中无地震体/井位资产";
        } else {
            for (std::size_t i = 0; i < parts.size(); ++i) {
                if (i > 0) outcome.message += "，";
                outcome.message += parts[i];
            }
        }
    }
    return outcome;
}

}  // namespace pwb::app::closure_joint3d

#endif  // PWB_WITH_UI_WELLSEIS
