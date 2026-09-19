// UI-10 — sequence framework state: workflow ports + panel view models.

#include "pwb/ui_seqviz/sequence_state.hpp"

#include <algorithm>
#include <set>

namespace pwb::ui_seqviz {

namespace {

std::string strip(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\n\r\f\v");
    if (first == std::string::npos) {
        return "";
    }
    const auto last = text.find_last_not_of(" \t\n\r\f\v");
    return text.substr(first, last - first + 1);
}

bool starts_with(const std::string& text, const std::string& prefix) {
    return text.size() >= prefix.size() &&
           text.compare(0, prefix.size(), prefix) == 0;
}

}  // namespace

StratigraphySlice& apply_stratigraphy_scheme(
    StratigraphyProjectSlice& project,
    std::optional<std::string> target_horizon,
    std::optional<std::string> systems_tract_scheme,
    std::optional<std::string> interpretation_version,
    std::optional<std::vector<std::string>> sequence_boundaries,
    bool bind_downstream) {
    StratigraphySlice& strat = project.stratigraphy;
    const std::string previous_horizon = strip(strat.target_horizon);

    if (target_horizon.has_value()) {
        strat.target_horizon = strip(*target_horizon);
    }
    if (systems_tract_scheme.has_value()) {
        const std::string value = strip(*systems_tract_scheme);
        strat.systems_tract_scheme =
            value.empty() ? strat.systems_tract_scheme : value;
    }
    if (interpretation_version.has_value()) {
        const std::string value = strip(*interpretation_version);
        strat.interpretation_version =
            value.empty() ? strat.interpretation_version : value;
    }
    if (sequence_boundaries.has_value()) {
        std::vector<std::string> cleaned;
        for (const auto& boundary : *sequence_boundaries) {
            const std::string text = strip(boundary);
            if (!text.empty()) {
                cleaned.push_back(text);
            }
        }
        strat.sequence_boundaries = std::move(cleaned);
    }

    const std::string new_horizon = strip(strat.target_horizon);
    const std::string scheme = strip(strat.systems_tract_scheme);

    if (!project.compilation_runs.empty()) {
        CompilationRunSlice& run = project.compilation_runs.back();
        if (!new_horizon.empty()) {
            run.target_horizon = new_horizon;
        }
        if (!scheme.empty()) {
            run.sequence_scheme_ref = scheme;
        }
    }

    if (bind_downstream && !new_horizon.empty()) {
        // _bind_target_horizon — propagate into maps/factors sharing the
        // previous (or an empty) horizon; never clobber unrelated values.
        for (auto& doc : project.paleomap_documents) {
            const std::string linked = strip(doc.linked_target_horizon);
            if (linked.empty() || linked == previous_horizon) {
                doc.linked_target_horizon = new_horizon;
            }
        }
        for (auto& task : project.factor_map_tasks) {
            const std::string current = strip(task.target_horizon);
            if (!(current.empty() || current == previous_horizon)) {
                continue;
            }
            task.target_horizon = new_horizon;
            // Keep display name aligned when it was horizon-prefixed.
            if (!previous_horizon.empty() &&
                starts_with(task.name, previous_horizon + " ")) {
                const std::string rest =
                    task.name.substr(previous_horizon.size() + 1);
                task.name = new_horizon + " " +
                            (task.factor_type.empty() ? rest
                                                      : task.factor_type);
            } else if (previous_horizon.empty() &&
                       !task.factor_type.empty() &&
                       task.name == task.factor_type) {
                task.name = new_horizon + " " + task.factor_type;
            }
        }
    }
    return strat;
}

StratigraphySlice& set_target_from_boundary(
    StratigraphyProjectSlice& project, const std::string& boundary,
    bool bind_downstream) {
    const std::string name = strip(boundary);
    if (name.empty()) {
        return project.stratigraphy;
    }
    auto& boundaries = project.stratigraphy.sequence_boundaries;
    if (std::find(boundaries.begin(), boundaries.end(), name) ==
        boundaries.end()) {
        boundaries.push_back(name);
    }
    return apply_stratigraphy_scheme(project, name, std::nullopt,
                                     std::nullopt, std::nullopt,
                                     bind_downstream);
}

std::string active_target_horizon(const StratigraphyProjectSlice& project) {
    if (!project.compilation_runs.empty()) {
        const std::string th =
            strip(project.compilation_runs.back().target_horizon);
        if (!th.empty()) {
            return th;
        }
    }
    return strip(project.stratigraphy.target_horizon);
}

SequenceTargetView sequence_target_view(const StratigraphySlice& stratigraphy) {
    const std::string target = stratigraphy.target_horizon;
    SequenceTargetView view;
    view.version_text = stratigraphy.interpretation_version.empty()
                            ? "v1"
                            : stratigraphy.interpretation_version;
    view.scheme_text = stratigraphy.systems_tract_scheme.empty()
                           ? "LST/TST/HST"
                           : stratigraphy.systems_tract_scheme;

    std::vector<std::string> options;
    std::set<std::string> seen;
    for (const auto& name : stratigraphy.sequence_boundaries) {
        const std::string text = strip(name);
        if (!text.empty() && seen.insert(text).second) {
            options.push_back(text);
        }
    }
    if (!target.empty() && seen.find(target) == seen.end()) {
        options.insert(options.begin(), target);
    }
    if (options.empty()) {
        options.push_back("");
    }
    view.options = std::move(options);

    if (!target.empty()) {
        const auto it =
            std::find(view.options.begin(), view.options.end(), target);
        if (it != view.options.end()) {
            view.selected_index =
                static_cast<int>(std::distance(view.options.begin(), it));
            view.edit_text.clear();
        } else {
            // Unreachable with the front-insert above; kept for parity.
            view.selected_index = -1;
            view.edit_text = target;
        }
    } else {
        view.selected_index = 0;
        view.edit_text.clear();
    }

    view.scope_text = std::to_string(stratigraphy.applicable_wells.size()) +
                      " 口井 / " +
                      std::to_string(
                          stratigraphy.applicable_seismic_ranges.size()) +
                      " 条测线";
    view.last_committed_target =
        target.empty() ? std::nullopt
                       : std::optional<std::string>(target);
    return view;
}

std::vector<BoundaryRow> sequence_boundary_rows(
    const StratigraphySlice& stratigraphy) {
    const std::string target = stratigraphy.target_horizon.empty()
                                   ? "未设置"
                                   : stratigraphy.target_horizon;
    std::vector<BoundaryRow> rows;
    rows.reserve(stratigraphy.sequence_boundaries.size());
    int index = 0;
    for (const auto& boundary : stratigraphy.sequence_boundaries) {
        BoundaryRow row;
        row.name = boundary;
        row.target = target;
        row.note = boundary == target
                       ? "当前目标"
                       : "第 " + std::to_string(index + 1) + " 层序界面";
        rows.push_back(std::move(row));
        ++index;
    }
    return rows;
}

SequenceSchemeSummaryView sequence_scheme_summary_view(
    const StratigraphySlice& stratigraphy) {
    SequenceSchemeSummaryView view;
    view.scheme_text = stratigraphy.systems_tract_scheme.empty()
                           ? "LST/TST/HST"
                           : stratigraphy.systems_tract_scheme;
    view.boundary_count_text =
        std::to_string(stratigraphy.sequence_boundaries.size()) + " 个";
    view.systems_tract_text = "LST / TST / HST";
    view.status_text = stratigraphy.target_horizon.empty()
                           ? "未设置目标层位"
                           : "目标 " + stratigraphy.target_horizon;
    return view;
}

}  // namespace pwb::ui_seqviz
