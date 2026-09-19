#include <pwb/ui_wellseis/well_map.hpp>

#include <cctype>
#include <cmath>
#include <unordered_map>

namespace pwb::ui_wellseis {

namespace {

std::string trim_copy(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }
    const auto last = text.find_last_not_of(" \t\r\n");
    return text.substr(first, last - first + 1);
}

std::string casefold_copy(std::string text) {
    for (char& c : text) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return text;
}

}  // namespace

std::string coordinate_status_flag(const std::string& status) {
    static const std::unordered_map<std::string, std::string> flags = {
        {"untransformed", " ⚠坐标未转换"},
        {"invalid", " ⚠坐标无效"},
        {"missing", " ⚠无坐标"},
    };
    const auto it = flags.find(status);
    return it == flags.end() ? "" : it->second;
}

bool crs_equivalent(const std::string& left, const std::string& right) {
    if (left.empty() || right.empty()) {
        return false;
    }
    if (left == right) {
        return true;
    }
    return casefold_copy(trim_copy(left)) == casefold_copy(trim_copy(right));
}

std::vector<std::pair<double, double>> complete_survey_corners(
    const std::vector<std::pair<double, double>>& corners) {
    if (corners.size() != 3) {
        return corners;
    }
    const auto& p1 = corners[0];
    const auto& p2 = corners[1];
    const auto& p3 = corners[2];
    return {p1, p2, p3,
            {p1.first + p3.first - p2.first,
             p1.second + p3.second - p2.second}};
}

WellMapModel build_well_map_model(const std::vector<WellSlice>& wells) {
    WellMapModel model;
    // Pass 1: list rows over non-reference wells only.
    struct Drawable {
        int list_row;
        std::pair<double, double> coord;
        bool is_ok;
    };
    std::vector<Drawable> drawable;
    for (const WellSlice& well : wells) {
        const std::string scope =
            well.spatial_scope.empty() ? "workarea" : well.spatial_scope;
        if (scope == "reference") {
            continue;
        }
        WellMapListRow row;
        row.well_id = well.id;
        row.display_name =
            well.name.empty() ? "(未命名井)" : well.name;
        row.flag = coordinate_status_flag(well.coordinate_status);
        model.rows.push_back(std::move(row));
        const int list_row = static_cast<int>(model.rows.size()) - 1;

        // Coordinate pick: project coords first, else source surface.
        const bool have_project =
            well.project_x.has_value() && well.project_y.has_value();
        const std::optional<double> x =
            have_project ? well.project_x : well.surface_x;
        const std::optional<double> y =
            have_project ? well.project_y : well.surface_y;
        if (!x.has_value() || !y.has_value() || std::isnan(*x) ||
            std::isnan(*y)) {
            continue;
        }
        const bool is_ok =
            well.coordinate_status == "ok" && have_project;
        drawable.push_back({list_row, {*x, *y}, is_ok});
    }
    // Pass 2: stable OK-then-flagged ordering.
    for (const Drawable& d : drawable) {
        if (d.is_ok) {
            model.scatter.push_back(d.coord);
            model.ordered_labels.push_back(model.rows[d.list_row].display_name);
            model.ordered_list_rows.push_back(d.list_row);
        }
    }
    model.ok_count = model.scatter.size();
    for (const Drawable& d : drawable) {
        if (!d.is_ok) {
            model.scatter.push_back(d.coord);
            model.ordered_labels.push_back(model.rows[d.list_row].display_name);
            model.ordered_list_rows.push_back(d.list_row);
        }
    }
    for (int array = 0; array < static_cast<int>(model.ordered_list_rows.size());
         ++array) {
        model.row_to_array.emplace(model.ordered_list_rows[array], array);
    }
    return model;
}

std::vector<std::string> crs_warnings(const ProjectSlice& project) {
    std::vector<std::string> warnings;
    const std::string& project_crs = project.project_crs;
    if (!project.workarea_boundary_crs.empty() &&
        !project.workarea_boundary.empty() &&
        !crs_equivalent(project.workarea_boundary_crs, project_crs)) {
        warnings.push_back("工区边界坐标系 " + project.workarea_boundary_crs +
                           " 与工程不一致，未叠加");
    }
    for (const SurveySlice& survey : project.seismic_surveys) {
        if (!survey.crs.empty() && !survey.extent.empty() &&
            !crs_equivalent(survey.crs, project_crs)) {
            warnings.push_back("地震工区「" + survey.name + "」坐标系 " +
                               survey.crs + " 与工程不一致，未叠加");
        }
    }
    return warnings;
}

std::string crs_warning_banner(const ProjectSlice& project) {
    const std::vector<std::string> warnings = crs_warnings(project);
    if (warnings.empty()) {
        return "";
    }
    std::string banner = "⚠ ";
    for (std::size_t i = 0; i < warnings.size(); ++i) {
        if (i != 0) {
            banner += "；";
        }
        banner += warnings[i];
    }
    return banner;
}

std::string project_crs_label(const ProjectSlice& project) {
    return "工程 CRS: " +
           (project.project_crs.empty() ? std::string("未设置")
                                        : project.project_crs);
}

std::vector<std::pair<double, double>> boundary_ring(
    const ProjectSlice& project) {
    std::vector<std::pair<double, double>> points;
    const bool frame_ok =
        project.workarea_boundary_crs.empty() ||
        crs_equivalent(project.workarea_boundary_crs, project.project_crs);
    if (!frame_ok) {
        return points;
    }
    for (const auto& point : project.workarea_boundary) {
        if (std::isnan(point.first) || std::isnan(point.second)) {
            continue;
        }
        points.push_back(point);
    }
    if (points.size() > 1 && points.front() != points.back()) {
        points.push_back(points.front());
    }
    return points;
}

std::vector<std::vector<std::pair<double, double>>> survey_extent_rings(
    const ProjectSlice& project) {
    std::vector<std::vector<std::pair<double, double>>> rings;
    for (const SurveySlice& survey : project.seismic_surveys) {
        if (!survey.crs.empty() &&
            !crs_equivalent(survey.crs, project.project_crs)) {
            continue;
        }
        std::vector<std::pair<double, double>> corners;
        corners.reserve(survey.extent.size());
        for (const auto& corner : survey.extent) {
            if (std::isnan(corner.first) || std::isnan(corner.second)) {
                continue;
            }
            corners.push_back(corner);
        }
        if (corners.size() < 3) {
            continue;
        }
        corners = complete_survey_corners(corners);
        if (corners.front() != corners.back()) {
            corners.push_back(corners.front());
        }
        rings.push_back(std::move(corners));
    }
    return rings;
}

}  // namespace pwb::ui_wellseis
