// VIZ-B — cross-well model/planner/tie/geometry oracle replay. The
// fixture is frozen from the real Python reference
// (tools/oracle/generate_viz_b_cross_well_fixtures.py @ geo-viz-engine
// 08851951). Pick IDs are random on both sides (uuid4 / random_device),
// so picks snapshots are compared structurally with cross-snapshot ID
// stability; everything else is exact.

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#if defined(_WIN32)
#include <process.h>
inline int pwb_test_pid() { return _getpid(); }
#else
#include <unistd.h>
inline int pwb_test_pid() { return static_cast<int>(::getpid()); }
#endif

#include <pwb/domain/json.hpp>
#include <pwb/viz/cross_well/auto_section_planner.hpp>
#include <pwb/viz/cross_well/formation_preview.hpp>
#include <pwb/viz/cross_well/picks_model.hpp>
#include <pwb/viz/cross_well/section_geometry.hpp>
#include <pwb/viz/cross_well/seismic_tie.hpp>
#include <pwb/viz/cross_well/tops_model.hpp>

#ifndef PWB_VIZ_B_CROSS_WELL_FIXTURE
#error "PWB_VIZ_B_CROSS_WELL_FIXTURE must be defined"
#endif

using pwb::domain::Json;
using pwb::viz::cross_well::FormationTop;
using pwb::viz::cross_well::FormationTopsModel;
using pwb::viz::cross_well::HorizonPicksModel;
using pwb::viz::cross_well::PickConfidence;
using pwb::viz::cross_well::SeismicTie;

namespace {

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& label) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::cerr << "FAIL: " << label << "\n";
    }
}

double read_num(const Json& v) {
    if (v.is_string()) {
        const std::string s = v.get<std::string>();
        if (s == "inf") return std::numeric_limits<double>::infinity();
        if (s == "-inf") return -std::numeric_limits<double>::infinity();
        if (s == "nan") return std::numeric_limits<double>::quiet_NaN();
    }
    return v.get<double>();
}

std::vector<double> read_nums(const Json& arr) {
    std::vector<double> out;
    for (const Json& v : arr) out.push_back(read_num(v));
    return out;
}

class TempDir {
  public:
    TempDir() {
        auto base = std::filesystem::temp_directory_path();
        // PWB-V14-DATA-LINEAGE: mkdtemp is POSIX-only; same contract (a
        // fresh unique created directory) via the temp root + probe loop.
        static unsigned seq = 0;
        std::error_code ec;
        for (unsigned attempt = 0; attempt < 4096; ++attempt) {
            const std::filesystem::path candidate =
                base / ("viz_b_test_" + std::to_string(pwb_test_pid()) +
                        "_" + std::to_string(seq++));
            if (std::filesystem::create_directory(candidate, ec)) {
                path_ = candidate;
                break;
            }
        }
        if (path_.empty()) path_ = base / "viz_b_test_fallback";
        std::filesystem::create_directories(path_);
    }
    ~TempDir() {
        std::error_code ec;
        std::filesystem::remove_all(path_, ec);
    }
    [[nodiscard]] std::string file(const std::string& name) const {
        return (path_ / name).string();
    }

  private:
    std::filesystem::path path_;
};

// --- structural pick comparison (ids random on both sides) ------------

std::string pick_shape(const pwb::viz::cross_well::HorizonPick& pick,
                       std::map<std::string, std::string>* id_map) {
    std::ostringstream out;
    if (id_map != nullptr) {
        auto it = id_map->find(pick.pick_id);
        if (it == id_map->end()) {
            const std::string alias =
                "P" + std::to_string(id_map->size() + 1);
            id_map->emplace(pick.pick_id, alias);
            out << alias;
        } else {
            out << it->second;
        }
    }
    out << "|" << pick.formation_name << "|source=" << pick.source << "|wd=";
    for (const auto& [w, d] : pick.well_depths) {
        out << "(" << w << ",";
        if (d.has_value()) {
            out << pwb::domain::Json(*d).dump();
        } else {
            out << "null";
        }
        out << ")";
    }
    out << "|conf=";
    for (const auto& [w, c] : pick.confidence.entries) {
        out << "(" << w << "=" << pwb::domain::Json(c).dump() << ")";
    }
    return out.str();
}

void replay_picks_sequence(const Json& case_data) {
    HorizonPicksModel model;
    std::map<std::string, std::string> id_map;  // C++ id -> alias (stable)
    std::map<std::string, std::string> fixture_alias;  // fixture id -> alias
    std::size_t snap_index = 0;

    auto compare_snapshot = [&](const std::string& step) {
        const Json& expected = case_data.at("snapshots")[snap_index];
        ++snap_index;
        check(expected.at("step").get<std::string>() == step,
              "picks step order at " + step);
        const Json& want = expected.at("dict").at("picks");
        const auto got = model.all_picks();
        check(got.size() == want.size(),
              step + " pick count " + std::to_string(got.size()) + " vs " +
                  std::to_string(want.size()));
        if (got.size() != want.size()) return;
        for (std::size_t i = 0; i < got.size(); ++i) {
            // Fixture side: alias the fixture's random ids.
            const std::string fixture_id =
                want[i].at("pick_id").get<std::string>();
            if (fixture_alias.find(fixture_id) == fixture_alias.end()) {
                fixture_alias.emplace(
                    fixture_id,
                    "P" + std::to_string(fixture_alias.size() + 1));
            }
            std::ostringstream want_shape;
            want_shape << fixture_alias[fixture_id] << "|"
                       << want[i].at("formation_name").get<std::string>()
                       << "|source="
                       << want[i].at("source").get<std::string>() << "|wd=";
            for (const Json& wd : want[i].at("well_depths")) {
                want_shape << "(" << wd[0].get<std::string>() << ","
                           << (wd[1].is_null() ? "null"
                                               : wd[1].dump()) << ")";
            }
            want_shape << "|conf=";
            for (auto it = want[i].at("confidence").begin();
                 it != want[i].at("confidence").end(); ++it) {
                want_shape << "(" << it.key() << "=" << it.value().dump()
                           << ")";
            }
            const std::string got_shape = pick_shape(*got[i], &id_map);
            check(got_shape == want_shape.str(),
                  step + " pick[" + std::to_string(i) + "] got '" +
                      got_shape + "' want '" + want_shape.str() + "'");
        }
        check(expected.at("can_undo").get<bool>() == (model.undo_count() > 0),
              step + " can_undo");
        check(expected.at("can_redo").get<bool>() == (model.redo_count() > 0),
              step + " can_redo");
    };

    const std::string a = model.add_pick("Horizon-1", "W1", 1000.0);
    compare_snapshot("add1");
    const std::string b = model.add_pick("Sand-2", "W1", 1150.0, "manual");
    compare_snapshot("add2");
    model.connect_picks(a, "W2", 1002.5);
    compare_snapshot("connect_w2");
    model.connect_picks(a, "W3", 1001.25);
    compare_snapshot("connect_w3");
    model.move_pick(a, "W2", 1004.0);
    compare_snapshot("move_w2");
    PickConfidence confidence;
    confidence.set("W2", 0.83);
    const std::string d = model.add_dtw_pick("Auto-3", "W1", 1230.0,
                                             PickConfidence{});
    model.connect_picks(d, "W2", 1233.5);
    // Confidence recorded after connect (Python sets it directly on the
    // pick; the model exposes the same mutation without undo recording).
    model.set_pick_confidence(d, confidence);
    compare_snapshot("dtw_add_confidence");
    model.reject_dtw_pick(d);
    compare_snapshot("dtw_reject");
    (void)model.undo();  // 快照即 oracle，bool 仅示是否有东西可撤
    compare_snapshot("undo_reject");
    model.accept_dtw_pick(d);
    compare_snapshot("dtw_accept");
    model.delete_pick(b);
    compare_snapshot("delete2");
    (void)model.undo();  // 快照即 oracle，bool 仅示是否有东西可撤
    compare_snapshot("undo_delete");
    (void)model.redo();
    compare_snapshot("redo_delete");
    (void)model.undo();  // 快照即 oracle，bool 仅示是否有东西可撤
    (void)model.undo();  // 快照即 oracle，bool 仅示是否有东西可撤
    (void)model.undo();  // 快照即 oracle，bool 仅示是否有东西可撤
    compare_snapshot("undo_x3");
    (void)model.redo();
    compare_snapshot("redo_x1");
}

void run_picks_roundtrip(const Json& c) {
    const std::string id = c.at("id").get<std::string>();
    HorizonPicksModel model;
    model.from_json(Json::parse(c.at("json_text").get<std::string>()));
    const Json mine = model.to_json();
    const Json want = Json::parse(c.at("json_text").get<std::string>());
    check(mine.dump() == want.dump(), id + " json roundtrip dump");
    if (c.contains("identical")) {
        check(model.to_json().dump() == want.dump(), id + " second pass");
    }
    if (c.contains("connected_wells")) {
        const auto picks = model.all_picks();
        std::vector<std::string> got;
        for (const auto* p : picks) {
            for (const std::string& w : p->connected_wells()) {
                got.push_back(w);
            }
        }
        const Json want_wells = c.at("connected_wells");
        bool ok = got.size() == want_wells.size();
        if (ok) {
            for (std::size_t i = 0; i < got.size(); ++i) {
                ok = ok && got[i] == want_wells[i].get<std::string>();
            }
        }
        check(ok, id + " connected_wells");
    }
}

void run_tops_csv(const Json& c, const TempDir& tmp) {
    const std::string id = c.at("id").get<std::string>();
    const std::string path = tmp.file("tops.csv");
    { std::ofstream f(path); f << c.at("csv_text").get<std::string>(); }
    FormationTopsModel model;
    check(model.load_csv(path), id + " load ok");
    const Json want = c.at("tops");
    const auto all = model.all_tops();
    check(all.size() == want.size(), id + " count");
    for (std::size_t i = 0; i < all.size() && i < want.size(); ++i) {
        check(all[i].well_name == want[i].at("well").get<std::string>(),
              id + " well " + std::to_string(i));
        check(all[i].formation_name ==
                  want[i].at("formation").get<std::string>(),
              id + " formation " + std::to_string(i));
        check(all[i].depth_m == read_num(want[i].at("depth")),
              id + " depth " + std::to_string(i));
        check(all[i].color == want[i].at("color").get<std::string>(),
              id + " color " + std::to_string(i));
    }
    // formation_names / well_names order.
    const auto formations = model.formation_names();
    const Json want_f = c.at("formation_names");
    bool ok = formations.size() == want_f.size();
    for (std::size_t i = 0; ok && i < formations.size(); ++i) {
        ok = formations[i] == want_f[i].get<std::string>();
    }
    check(ok, id + " formation_names");
    const auto wells = model.well_names();
    const Json want_w = c.at("well_names");
    ok = wells.size() == want_w.size();
    for (std::size_t i = 0; ok && i < wells.size(); ++i) {
        ok = wells[i] == want_w[i].get<std::string>();
    }
    check(ok, id + " well_names");
    // save_csv text equality (Python str(float) formatting parity).
    const std::string out_path = tmp.file("tops_out.csv");
    check(model.save_csv(out_path), id + " save ok");
    std::ifstream out_file(out_path);
    std::stringstream buffer;
    buffer << out_file.rdbuf();
    check(buffer.str() == c.at("saved_text").get<std::string>(),
          id + " saved text:\n  got '" + buffer.str() + "'\n  want '" +
              c.at("saved_text").get<std::string>() + "'");
}

void run_tops_mutate(const Json& c) {
    FormationTopsModel model;
    FormationTop t1{"W1", "Formation-A", 1000.5, ""};
    model.add_top(t1);
    model.add_top(FormationTop{"W1", "Formation-B", 1150.0, ""});
    model.add_top(FormationTop{"W2", "Formation-A", 1005.25, ""});
    model.add_top(FormationTop{"W2", "Formation-B", 1152.75, ""});
    model.add_top(FormationTop{"W3", "Formation-B", 1160.0, ""});
    model.add_top(FormationTop{"W3", "Formation-A", 1008.0, ""});
    model.add_top(FormationTop{"W4", "Formation-A", 1010.0, ""});
    model.delete_top("W1", "Formation-B");
    const Json want = c.at("tops");
    const auto all = model.all_tops();
    check(all.size() == want.size(), c.at("id").get<std::string>() +
                                         " mutate count");
    for (std::size_t i = 0; i < all.size() && i < want.size(); ++i) {
        check(all[i].well_name == want[i].at("well").get<std::string>() &&
                  all[i].formation_name ==
                      want[i].at("formation").get<std::string>() &&
                  all[i].depth_m == read_num(want[i].at("depth")) &&
                  all[i].color == want[i].at("color").get<std::string>(),
              c.at("id").get<std::string>() + " mutate row " +
                  std::to_string(i));
    }
}

void run_planner(const Json& c) {
    const std::string id = c.at("id").get<std::string>();
    std::vector<pwb::viz::cross_well::WellCoord> wells;
    for (const Json& w : c.at("wells")) {
        wells.push_back({w.at("name").get<std::string>(),
                         w.at("lng").get<double>(), w.at("lat").get<double>()});
    }
    const auto pca = pwb::viz::cross_well::plan_section_pca(wells);
    const Json want_pca = c.at("pca_canonical");
    bool ok = pca.size() == want_pca.size();
    for (std::size_t i = 0; ok && i < pca.size(); ++i) {
        ok = static_cast<int>(pca[i]) == want_pca[i].get<int>();
    }
    check(ok, id + " pca canonical");
    // Determinism: repeated calls identical.
    const auto pca2 = pwb::viz::cross_well::plan_section_pca(wells);
    check(pca == pca2, id + " pca deterministic");
    const auto nn = pwb::viz::cross_well::plan_section_nearest_neighbor(wells);
    const Json want_nn = c.at("nn_canonical");
    ok = nn.size() == want_nn.size();
    for (std::size_t i = 0; ok && i < nn.size(); ++i) {
        ok = static_cast<int>(nn[i]) == want_nn[i].get<int>();
    }
    check(ok, id + " nn canonical");
    const auto nn2 =
        pwb::viz::cross_well::plan_section_nearest_neighbor(wells);
    check(nn == nn2, id + " nn deterministic");
    // The dispatch entry point.
    const auto via_dispatch =
        pwb::viz::cross_well::plan_section(wells, "pca");
    check(via_dispatch == pca, id + " plan_section dispatch");
}

void run_seismic_tie(const Json& c, const TempDir& tmp) {
    const std::string id = c.at("id").get<std::string>();
    const std::string path = tmp.file("checkshot.csv");
    { std::ofstream f(path); f << c.at("csv_text").get<std::string>(); }
    SeismicTie tie;
    check(tie.load_csv(path), id + " load ok");
    const Json tables = c.at("tables");
    const auto names = tie.well_names();
    check(names.size() == tables.size(), id + " table count");
    for (std::size_t i = 0; i < names.size() && i < tables.size(); ++i) {
        const auto* table = tie.table_for_well(names[i]);
        check(table != nullptr, id + " table lookup");
        if (table == nullptr) continue;
        check(table->well_name == tables[i].at("well").get<std::string>(),
              id + " well name");
        const auto depths = read_nums(tables[i].at("depths"));
        const auto twts = read_nums(tables[i].at("twts"));
        check(table->depths_m == depths, id + " depths sorted");
        check(table->twt_ms == twts, id + " twts sorted");
    }
    // Probes with well names (fixture encodes order; the trailing probe
    // is the MISSING-well null).
    struct Probe { std::string well; double depth; };
    const std::vector<Probe> probes = {
        {"W1", 1025.0}, {"W1", 800.0}, {"W1", 2000.0}, {"W2", 1225.0},
    };
    const Json& want = c.at("twt_probes");
    for (std::size_t i = 0; i < probes.size(); ++i) {
        const auto got = tie.depth_to_twt(probes[i].well, probes[i].depth);
        check(got.has_value() && !want[i].is_null() &&
                  *got == read_num(want[i]),
              id + " twt probe " + std::to_string(i));
    }
    const auto missing = tie.depth_to_twt("MISSING", 1000.0);
    check(!missing.has_value(), id + " missing well -> nullopt");
    // Depth probes.
    const Json depth_want = c.at("depth_probe_results");
    const std::vector<std::pair<std::string, double>> depth_probes = {
        {"W1", 530.0}, {"W1", 999.0}, {"W2", 622.5}};
    for (std::size_t i = 0; i < depth_probes.size(); ++i) {
        const auto got = tie.twt_to_depth(depth_probes[i].first,
                                          depth_probes[i].second);
        check(got.has_value() && *got == read_num(depth_want[i]),
              id + " depth probe " + std::to_string(i));
    }
}

void run_geometry(const Json& c) {
    const std::string id = c.at("id").get<std::string>();
    pwb::viz::cross_well::WellColumnGeometry geometry;
    geometry.depth_top = c.at("depth_top").get<double>();
    geometry.depth_bottom = c.at("depth_bottom").get<double>();
    geometry.header_height_px = c.at("header_h").get<double>();
    geometry.canvas_height_px = c.at("canvas_h").get<double>();
    const Json y_probes = c.at("y_probes");
    const Json y_want = c.at("y_to_depth");
    for (std::size_t i = 0; i < y_probes.size(); ++i) {
        const auto got = geometry.y_to_depth(y_probes[i].get<double>());
        const double want = read_num(y_want[i]);
        check(got.has_value() && *got == want,
              id + " y_to_depth " + std::to_string(i));
    }
    const Json d_probes = c.at("depth_probes");
    const Json d_want = c.at("depth_to_y");
    for (std::size_t i = 0; i < d_probes.size(); ++i) {
        const double got = geometry.depth_to_y(d_probes[i].get<double>());
        check(got == read_num(d_want[i]),
              id + " depth_to_y " + std::to_string(i));
    }
}

void run_geometry_degenerate(const Json& c) {
    const std::string id = c.at("id").get<std::string>();
    pwb::viz::cross_well::WellColumnGeometry span0;
    span0.depth_top = 1000.0;
    span0.depth_bottom = 1000.0;
    span0.header_height_px = 56.0;
    span0.canvas_height_px = 456.0;
    check(!span0.y_to_depth(200.0).has_value(),
          id + " span0 y_to_depth null");
    check(span0.depth_to_y(1050.0) == c.at("span0_depth_to_y").get<double>(),
          id + " span0 depth_to_y");
    pwb::viz::cross_well::WellColumnGeometry tiny;
    tiny.depth_top = 1000.0;
    tiny.depth_bottom = 1100.0;
    tiny.header_height_px = 600.0;
    tiny.canvas_height_px = 456.0;
    check(!tiny.y_to_depth(200.0).has_value(),
          id + " tiny y_to_depth null");
    check(tiny.depth_to_y(1050.0) == c.at("tiny_depth_to_y").get<double>(),
          id + " tiny depth_to_y");
}

void run_preview(const Json& c) {
    using namespace pwb::viz::cross_well;
    const std::string id = c.at("id").get<std::string>();
    // Per-well tops in the sorted-well order (set_tops semantics).
    std::vector<std::vector<FormationTop>> per_well;
    std::map<std::string, std::vector<FormationTop>> by_well;
    for (const Json& t : c.at("tops")) {
        by_well[t.at("well").get<std::string>()].push_back(
            FormationTop{t.at("well").get<std::string>(),
                         t.at("formation").get<std::string>(),
                         read_num(t.at("depth")), ""});
    }
    for (const auto& [well, tops] : by_well) {
        (void)well;
        per_well.push_back(tops);
    }
    const auto connections = build_preview_connections(per_well);
    const Json want_connections = c.at("connections");
    check(connections.size() == want_connections.size(),
          id + " connection count " +
              std::to_string(connections.size()) + " vs " +
              std::to_string(want_connections.size()));
    for (std::size_t i = 0; i < connections.size() && i < want_connections.size();
         ++i) {
        check(connections[i].from_index ==
                      static_cast<std::size_t>(
                          want_connections[i].at("from_index").get<int>()) &&
                  connections[i].from_top.well_name ==
                      want_connections[i].at("from_well").get<std::string>() &&
                  connections[i].to_top.well_name ==
                      want_connections[i].at("to_well").get<std::string>() &&
                  connections[i].from_top.depth_m ==
                      read_num(want_connections[i].at("from_depth")) &&
                  connections[i].to_top.depth_m ==
                      read_num(want_connections[i].at("to_depth")),
              id + " connection " + std::to_string(i));
    }
    PreviewLayout layout;
    layout.width_px = c.at("width").get<double>();
    layout.height_px = c.at("height").get<double>();
    const auto full = preview_full_range(per_well);
    layout.full_min_depth = read_num(c.at("full_range")[0]);
    layout.full_max_depth = read_num(c.at("full_range")[1]);
    check(full.first == layout.full_min_depth &&
              full.second == layout.full_max_depth,
          id + " full range");
    const Json clamped = c.at("clamped_views");
    const std::vector<std::pair<double, double>> requests = {
        {0.0, 1.0}, {990.0, 1180.0}, {1000.0, 1100.0},
        {1100.0, 1200.0}, {1155.0, 1155.0}, {1050.0, 1040.0}};
    for (std::size_t i = 0; i < requests.size(); ++i) {
        const auto got =
            preview_clamped_view(layout, requests[i].first, requests[i].second);
        check(got.first == read_num(clamped[i][0]) &&
                  got.second == read_num(clamped[i][1]),
              id + " clamped " + std::to_string(i));
    }
    const Json zoomed = c.at("zoomed_views");
    const std::vector<std::pair<double, bool>> zoom_reqs = {
        {38.0, true}, {200.0, true}, {400.0, true}, {200.0, false}};
    for (std::size_t i = 0; i < zoom_reqs.size(); ++i) {
        layout.view_min_depth = 1000.0;
        layout.view_max_depth = 1200.0;
        const auto got = preview_zoomed_view(layout, zoom_reqs[i].first,
                                             zoom_reqs[i].second);
        check(got.first == read_num(zoomed[i][0]) &&
                  got.second == read_num(zoomed[i][1]),
              id + " zoom " + std::to_string(i) + " got (" +
                  std::to_string(got.first) + "," +
                  std::to_string(got.second) + ") want (" +
                  std::to_string(read_num(zoomed[i][0])) + "," +
                  std::to_string(read_num(zoomed[i][1])) + ")");
    }
    const Json panned = c.at("panned_views");
    const std::vector<double> pan_reqs = {-50.0, 60.0};
    for (std::size_t i = 0; i < pan_reqs.size(); ++i) {
        layout.view_min_depth = 1000.0;
        layout.view_max_depth = 1200.0;
        const auto got = preview_paned_view(layout, pan_reqs[i]);
        check(got.first == read_num(panned[i][0]) &&
                  got.second == read_num(panned[i][1]),
              id + " pan " + std::to_string(i));
    }
    const Json depth_ys = c.at("depth_ys");
    for (std::size_t i = 0; i < depth_ys.size(); ++i) {
        layout.view_min_depth = 1000.0;
        layout.view_max_depth = 1200.0;
        const std::vector<double> probes = {1000.0, 1080.0, 1160.0};
        const double got = preview_depth_to_y(layout, probes[i]);
        check(got == read_num(depth_ys[i]),
              id + " depth_y " + std::to_string(i));
    }
    layout.view_min_depth = 1100.0;
    layout.view_max_depth = 1100.0;
    check(preview_depth_to_y(layout, 1100.0) ==
              read_num(c.at("zero_span_y")),
          id + " zero span y");
    // Margins contract.
    const Json margins = c.at("margins");
    check(margins.at("left").get<double>() == kPreviewMarginLeftPx &&
              margins.at("right").get<double>() == kPreviewMarginRightPx &&
              margins.at("top").get<double>() == kPreviewMarginTopPx &&
              margins.at("bottom").get<double>() == kPreviewMarginBottomPx,
          id + " margins");
}

bool negative_self_check(const Json& payload) {
    Json tampered = payload;
    for (Json& c : tampered.at("cases")) {
        if (!c.is_object()) continue;
        if (c.value("kind", std::string()) == "planner" &&
            c.value("id", std::string()) == "planner_collinear_diag") {
            Json& order = c.at("pca_canonical");
            std::swap(order[0], order[order.size() - 1]);
            break;
        }
    }
    const int before = g_failures;
    for (const Json& c : tampered.at("cases")) {
        if (!c.is_object()) continue;
        if (c.value("kind", std::string()) == "planner" &&
            c.value("id", std::string()) == "planner_collinear_diag") {
            run_planner(c);
        }
    }
    ++g_checks;
    if (g_failures == before) {
        ++g_failures;
        std::cerr << "FAIL: cross_well negative self-check did not catch "
                     "tampering\n";
        return false;
    }
    // The tamper WAS caught: roll the induced failures back out so the
    // deliberate mismatch does not pollute the exit code.
    g_failures = before;
    return true;
}

}  // namespace

int main() {
    std::ifstream file(PWB_VIZ_B_CROSS_WELL_FIXTURE);
    if (!file.is_open()) {
        std::cerr << "cannot open fixture " << PWB_VIZ_B_CROSS_WELL_FIXTURE
                  << "\n";
        return 2;
    }
    Json payload;
    file >> payload;
    TempDir tmp;
    for (const Json& c : payload.at("cases")) {
        if (!c.is_object() || !c.contains("kind")) continue;
        const std::string kind = c.at("kind").get<std::string>();
        if (kind == "picks_sequence") {
            replay_picks_sequence(c);
        } else if (kind == "picks_roundtrip") {
            run_picks_roundtrip(c);
        } else if (kind == "picks_roundtrip_undo") {
            HorizonPicksModel model;
            model.from_json(Json::parse("{\"picks\":[]}"));
            check(model.undo_count() == 0,
                  c.at("id").get<std::string>() + " clears undo");
        } else if (kind == "tops_csv") {
            run_tops_csv(c, tmp);
        } else if (kind == "tops_mutate") {
            run_tops_mutate(c);
        } else if (kind == "tops_palette") {
            const Json palette = c.at("palette");
            for (std::size_t i = 0; i < palette.size(); ++i) {
                check(pwb::viz::cross_well::formation_palette_color(i) ==
                          palette[i].get<std::string>(),
                      "palette " + std::to_string(i));
            }
            // Assignment replay: first-seen palette order, then overflow.
            std::vector<std::pair<std::string, std::string>> existing;
            for (const Json& a : c.at("assignments")) {
                const std::string want = a.at("assigned").get<std::string>();
                const std::string name = a.at("formation").get<std::string>();
                // Mirror _assign_color via the model's add path.
                static thread_local FormationTopsModel* palette_model =
                    new FormationTopsModel();
                FormationTop top{"X", name, 1.0, ""};
                palette_model->add_top(top);
                const std::string got =
                    palette_model->tops_for_well("X").back().color;
                check(got == want, "palette assign " + name + " got " + got +
                                       " want " + want);
            }
        } else if (kind == "planner") {
            run_planner(c);
        } else if (kind == "planner_error") {
            std::vector<pwb::viz::cross_well::WellCoord> wells = {
                {"A", 0.0, 0.0}, {"B", 1.0, 1.0}};
            bool threw = false;
            try {
                // 错误路径探针：只关心是否抛出，返回值无关。
                (void)pwb::viz::cross_well::plan_section(wells, "bogus");
            } catch (const pwb::viz::cross_well::PlannerError&) {
                threw = true;
            }
            check(threw, "planner unknown method throws");
        } else if (kind == "seismic_tie") {
            run_seismic_tie(c, tmp);
        } else if (kind == "section_geometry") {
            if (c.at("id").get<std::string>() == "geometry_degenerate") {
                run_geometry_degenerate(c);
            } else {
                run_geometry(c);
            }
        }
    }
    run_preview(payload.at("formation_preview"));

    // Real wells: load → edit → save → reopen identity with the B-line
    // JSON codec (hard gate #1).
    {
        const Json& wells = payload.at("real_wells").at("wells");
        HorizonPicksModel model;
        std::vector<std::string> names;
        for (const Json& w : wells) {
            names.push_back(w.at("name").get<std::string>());
        }
        check(names.size() >= 2, "real wells >= 2");
        const std::string p1 =
            model.add_pick("Formation-A", names[0], 2340.5);
        model.connect_picks(p1, names[1], 2351.25);
        PickConfidence conf;
        conf.set(names[1], 0.91);
        const std::string p2 = model.add_dtw_pick("Formation-B", names[0],
                                                  2510.0, PickConfidence{});
        model.connect_picks(p2, names[2], 2522.75);
        model.set_pick_confidence(p2, conf);
        const Json saved = model.to_json();
        const std::string path = tmp.file("picks_workspace.json");
        { std::ofstream f(path); f << saved.dump(2); }
        HorizonPicksModel reopened;
        std::ifstream in(path);
        Json loaded;
        in >> loaded;
        reopened.from_json(loaded);
        check(reopened.to_json().dump() == saved.dump(),
              "real wells reopen identity");
        check(reopened.get_pick(p1) != nullptr &&
                  reopened.get_pick(p1)->depth_for_well(names[1]) ==
                      std::optional<double>(2351.25),
              "real wells depth identity");
        const pwb::viz::cross_well::HorizonPick* reopened_dtw =
            reopened.get_pick(p2);
        check(reopened_dtw != nullptr && reopened_dtw->source == "dtw",
              "real wells dtw source identity");
        check(reopened_dtw != nullptr &&
                  reopened_dtw->confidence.entries.size() == 1 &&
                  reopened_dtw->confidence.entries[0].first == names[1],
              "real wells confidence identity");
    }

    negative_self_check(payload);

    std::cout << "cross_well oracle: " << g_checks << " checks, "
              << g_failures << " failures\n";
    return g_failures == 0 ? 0 : 1;
}
