#include <pwb/ui_wellseis/correlation.hpp>

#include <algorithm>
#include <cstdio>
#include <unordered_map>

namespace pwb::ui_wellseis {

const std::vector<std::string> kCorrelationStatuses = {
    "active", "tentative", "rejected"};

namespace {

const CorrelationTopSlice* find_top(
    const std::unordered_map<std::string, const CorrelationTopSlice*>& tops,
    const std::string& id) {
    const auto it = tops.find(id);
    return it == tops.end() ? nullptr : it->second;
}

std::string format_depth_2f(double depth, const std::string& domain) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.2f", depth);
    std::string text(buf);
    if (!domain.empty()) {
        text += " ";
        text += domain;
    }
    return text;
}

CorrelationLinkSlice* find_link_mut(CorrelationDraftSlice& draft,
                                    const std::string& link_id) {
    for (auto& link : draft.links) {
        if (link.id == link_id) {
            return &link;
        }
    }
    return nullptr;
}

CorrelationTopSlice* find_top_mut(CorrelationDraftSlice& draft,
                                  const std::string& top_id) {
    for (auto& top : draft.tops) {
        if (top.id == top_id) {
            return &top;
        }
    }
    return nullptr;
}

}  // namespace

std::string correlation_method_label(const std::string& method) {
    static const std::unordered_map<std::string, std::string> labels = {
        {"MANUAL", "手工"},
        {"DTW_ASSISTED", "DTW 辅助"},
        {"CURVE_SHAPE_ASSISTED", "曲线形态辅助"},
        {"IMPORTED", "导入"},
    };
    const auto it = labels.find(method);
    return it == labels.end() ? method : it->second;
}

std::vector<CorrelationLinkRow> correlation_link_rows(
    const CorrelationDraftSlice& draft) {
    std::unordered_map<std::string, const CorrelationTopSlice*> tops;
    tops.reserve(draft.tops.size());
    for (const auto& top : draft.tops) {
        tops.emplace(top.id, &top);
    }
    std::vector<const CorrelationLinkSlice*> sorted;
    sorted.reserve(draft.links.size());
    for (const auto& link : draft.links) {
        sorted.push_back(&link);
    }
    std::sort(sorted.begin(), sorted.end(), [](const auto* a, const auto* b) {
        if (a->top_a_id != b->top_a_id) {
            return a->top_a_id < b->top_a_id;
        }
        if (a->top_b_id != b->top_b_id) {
            return a->top_b_id < b->top_b_id;
        }
        return a->id < b->id;
    });
    std::vector<CorrelationLinkRow> rows;
    rows.reserve(sorted.size());
    for (const auto* link : sorted) {
        const CorrelationTopSlice* a = find_top(tops, link->top_a_id);
        const CorrelationTopSlice* b = find_top(tops, link->top_b_id);
        CorrelationLinkRow row;
        row.id = link->id;
        row.marker = a != nullptr ? a->marker : "?";
        row.pair_text = (a != nullptr ? a->well_name : "?") +
                        std::string(" → ") +
                        (b != nullptr ? b->well_name : "?");
        row.method_label = correlation_method_label(link->method);
        row.adjacent_text = link->adjacent_only ? "是" : "否";
        row.notes = link->notes;
        rows.push_back(std::move(row));
    }
    return rows;
}

std::vector<CorrelationTopRow> correlation_top_rows(
    const CorrelationDraftSlice& draft) {
    std::vector<const CorrelationTopSlice*> sorted;
    sorted.reserve(draft.tops.size());
    for (const auto& top : draft.tops) {
        sorted.push_back(&top);
    }
    std::sort(sorted.begin(), sorted.end(), [](const auto* a, const auto* b) {
        if (a->well_name != b->well_name) {
            return a->well_name < b->well_name;
        }
        if (a->marker != b->marker) {
            return a->marker < b->marker;
        }
        return a->depth < b->depth;
    });
    std::vector<CorrelationTopRow> rows;
    rows.reserve(sorted.size());
    for (const auto* top : sorted) {
        rows.push_back(
            {top->id, top->well_name, top->marker,
             format_depth_2f(top->depth, top->depth_domain),
             correlation_method_label(top->method),
             top->confidence.empty() ? "—" : top->confidence});
    }
    return rows;
}

std::vector<CorrelationTopChoice> correlation_top_choices(
    const CorrelationDraftSlice& draft) {
    std::vector<const CorrelationTopSlice*> sorted;
    sorted.reserve(draft.tops.size());
    for (const auto& top : draft.tops) {
        sorted.push_back(&top);
    }
    std::sort(sorted.begin(), sorted.end(), [](const auto* a, const auto* b) {
        if (a->well_name != b->well_name) {
            return a->well_name < b->well_name;
        }
        return a->marker < b->marker;
    });
    std::vector<CorrelationTopChoice> choices;
    choices.reserve(sorted.size());
    for (std::size_t i = 0; i < sorted.size(); ++i) {
        const auto* top = sorted[i];
        char depth[32];
        std::snprintf(depth, sizeof(depth), "%.1f", top->depth);
        choices.push_back(
            {top->well_name + " · " + top->marker + " (" + depth + ") #" +
                 std::to_string(i),
             top->id});
    }
    return choices;
}

bool correlation_add_manual_link(CorrelationDraftSlice& draft,
                                 const std::string& new_link_id,
                                 const std::string& top_a_id,
                                 const std::string& top_b_id,
                                 bool adjacent_only,
                                 const std::string& notes) {
    if (new_link_id.empty() || top_a_id.empty() || top_b_id.empty() ||
        top_a_id == top_b_id) {
        return false;
    }
    // Both tops must exist (the Python picker only offers real tops).
    const std::unordered_map<std::string, const CorrelationTopSlice*> tops = [&] {
        std::unordered_map<std::string, const CorrelationTopSlice*> map;
        for (const auto& top : draft.tops) {
            map.emplace(top.id, &top);
        }
        return map;
    }();
    if (find_top(tops, top_a_id) == nullptr ||
        find_top(tops, top_b_id) == nullptr) {
        return false;
    }
    CorrelationLinkSlice link;
    link.id = new_link_id;
    link.top_a_id = top_a_id;
    link.top_b_id = top_b_id;
    link.method = "MANUAL";
    link.adjacent_only = adjacent_only;
    link.notes = notes;
    draft.links.push_back(std::move(link));
    return true;
}

bool correlation_remove_link(CorrelationDraftSlice& draft,
                             const std::string& link_id) {
    const auto it =
        std::find_if(draft.links.begin(), draft.links.end(),
                     [&](const auto& link) { return link.id == link_id; });
    if (it == draft.links.end()) {
        return false;
    }
    draft.links.erase(it);
    return true;
}

bool correlation_edit_link(CorrelationDraftSlice& draft,
                           const std::string& link_id,
                           const std::string& method,
                           const std::string& notes) {
    CorrelationLinkSlice* link = find_link_mut(draft, link_id);
    if (link == nullptr) {
        return false;
    }
    link->method = method;
    link->notes = notes;
    return true;
}

bool correlation_edit_top(CorrelationDraftSlice& draft,
                          const std::string& top_id,
                          const std::string& method,
                          const std::string& confidence,
                          const std::string& status,
                          const std::string& notes) {
    CorrelationTopSlice* top = find_top_mut(draft, top_id);
    if (top == nullptr) {
        return false;
    }
    top->method = method;
    top->confidence = confidence;
    top->status = status;
    top->notes = notes;
    return true;
}

}  // namespace pwb::ui_wellseis
