// UI-06 — project_overview_panel.refresh_from_project.
#include <pwb/ui_pages_data/overview.hpp>
#include <pwb/ui_pages_data/vocab.hpp>

#include <algorithm>
#include <cstdio>

namespace pwb::ui_pages_data {
namespace {

std::string f1(double v) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.1f", v);
    return buf;
}

int stage_count(const CatalogCounts* counts, const char* stage) {
    if (!counts) return 0;
    const auto it = counts->stages.find(stage);
    return it != counts->stages.end() ? it->second : 0;
}

}  // namespace

OverviewView compute_project_overview(const OverviewProject* project,
                                      const CatalogCounts* counts) {
    // Spec order from the Python `specs` table.
    static const char* kKeys[] = {"wells",   "surveys", "raw",
                                  "derived", "output",  "issues",
                                  "unresolved", "recent"};

    OverviewView view;
    view.title = "工区概览";
    if (!project) {
        view.meta = "未打开工程";
        for (const char* key : kKeys) view.values.emplace_back(key, "—");
        return view;
    }

    const std::string& crs = !project->workarea_crs.empty()
                                 ? project->workarea_crs
                                 : project->coordinate_crs;
    const std::string& name = !project->workarea_name.empty()
                                  ? project->workarea_name
                                  : project->meta_name;
    view.title = "工区 · " + name;
    view.meta = "CRS: " + (crs.empty() ? std::string("未设置") : crs);
    if (!project->region.empty()) view.meta += "　区域: " + project->region;

    // bad_coords: coordinate_status_is_flagged(status) = status != "ok".
    int bad_coords = 0;
    for (const auto& well : project->wells)
        if (well.coordinate_status != "ok") ++bad_coords;
    const int unresolved = project->unresolved_links;

    const bool counts_known = counts != nullptr;
    const bool integrity_known = counts_known && counts->integrity_known;
    int missing = 0;
    if (counts) {
        const auto get = [&](const char* key) {
            const auto it = counts->integrity.find(key);
            return it != counts->integrity.end() ? it->second : 0;
        };
        missing = get("missing") + get("modified");
    }

    auto num = [](int v) { return std::to_string(v); };
    auto or_dash = [](bool known, const std::string& v) {
        return known ? v : std::string("—");
    };
    view.values = {
        {"wells", num(static_cast<int>(project->wells.size()))},
        {"surveys", num(project->survey_count)},
        {"raw", or_dash(counts_known, num(stage_count(counts, "raw")))},
        {"derived",
         or_dash(counts_known,
                 num(stage_count(counts, "derived") +
                     stage_count(counts, "intermediate")))},
        {"output", or_dash(counts_known, num(stage_count(counts, "output")))},
        {"issues", or_dash(integrity_known, num(missing))},
        {"unresolved", num(unresolved + bad_coords)},
    };

    // max(runs, key=updated_at) — Python max keeps the FIRST maximum.
    const OverviewProject::Run* latest = nullptr;
    for (const auto& run : project->compilation_runs) {
        if (!latest || run.updated_at > latest->updated_at) latest = &run;
    }
    std::string recent = "—";
    if (latest && !latest->name.empty()) recent = latest->name;
    view.values.emplace_back("recent", recent);

    if (unresolved) {
        view.hints.push_back(std::to_string(unresolved) +
                             " 条数据关联存在歧义，请在井列表中治理。");
    }
    if (bad_coords) {
        view.hints.push_back(
            std::to_string(bad_coords) +
            " 口井坐标缺少 CRS 或转换失败，地图按源坐标显示。");
    }
    if (!project->boundary.empty()) {
        std::vector<double> xs, ys;
        for (const auto& point : project->boundary) {
            if (point.size() >= 2) {
                xs.push_back(point[0]);
                ys.push_back(point[1]);
            }
        }
        if (!xs.empty() && !ys.empty()) {
            const auto [xmin, xmax] =
                std::minmax_element(xs.begin(), xs.end());
            const auto [ymin, ymax] =
                std::minmax_element(ys.begin(), ys.end());
            view.hints.push_back("工区范围: X [" + f1(*xmin) + ", " +
                                 f1(*xmax) + "] · Y [" + f1(*ymin) + ", " +
                                 f1(*ymax) + "]");
        }
    } else if (!project->wells.empty()) {
        std::vector<double> xs, ys;
        for (const auto& well : project->wells) {
            if (well.project_x) xs.push_back(*well.project_x);
            if (well.project_y) ys.push_back(*well.project_y);
        }
        if (!xs.empty() && !ys.empty()) {
            const auto [xmin, xmax] =
                std::minmax_element(xs.begin(), xs.end());
            const auto [ymin, ymax] =
                std::minmax_element(ys.begin(), ys.end());
            view.hints.push_back("井位范围: X [" + f1(*xmin) + ", " +
                                 f1(*xmax) + "] · Y [" + f1(*ymin) + ", " +
                                 f1(*ymax) + "]");
        }
    }
    return view;
}

}  // namespace pwb::ui_pages_data
