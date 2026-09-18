// entity identity resolution (conv-26) — see entity_identity.hpp. Every
// branch mirrors paleo_workbench/project/domain.py; deviations are declared
// in 26-decisions.md (bounded name fold, link id vocabulary).
#include "pwb/data/entity_identity.hpp"

#include "pwb/domain/ids.hpp"

#include <cctype>
#include <deque>

namespace pwb::data {

namespace {

bool is_ascii_space(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\v' ||
           c == '\f';
}

// Separator class of normalize_well_name: ASCII whitespace/_-,.()[] plus the
// explicit Unicode separators Python's regex lists (– — · （ ） 【 】).
bool is_separator_byte_run(const std::string& text, std::size_t i,
                           std::size_t* length) {
    const unsigned char c = static_cast<unsigned char>(text[i]);
    if (is_ascii_space(text[i]) ||
        (text[i] >= 0 && std::isspace(static_cast<unsigned char>(text[i]))) ||
        text[i] == '_' || text[i] == '-' || text[i] == ',' || text[i] == '.' ||
        text[i] == '(' || text[i] == ')' || text[i] == '[' || text[i] == ']') {
        *length = 1;
        return true;
    }
    // Multi-byte separators (UTF-8): U+2013, U+2014, U+00B7, U+FF08,
    // U+FF09, U+3010, U+3011.
    struct MultiSep {
        const char* bytes;
        std::size_t length;
    };
    static const MultiSep kMultiSeps[] = {
        {"\xE2\x80\x93", 3}, {"\xE2\x80\x94", 3}, {"\xC2\xB7", 2},
        {"\xEF\xBC\x88", 3}, {"\xEF\xBC\x89", 3}, {"\xE3\x80\x90", 3},
        {"\xE3\x80\x91", 3},
    };
    for (const MultiSep& sep : kMultiSeps) {
        if (text.compare(i, sep.length, sep.bytes, sep.length) == 0) {
            *length = sep.length;
            return true;
        }
    }
    return false;
}

std::string_view trimmed(std::string_view text) {
    std::size_t begin = 0;
    while (begin < text.size() &&
           is_ascii_space(static_cast<char>(text[begin]))) {
        ++begin;
    }
    std::size_t end = text.size();
    while (end > begin &&
           is_ascii_space(static_cast<char>(text[end - 1]))) {
        --end;
    }
    return text.substr(begin, end - begin);
}

}  // namespace

std::unordered_set<std::string> WellRecord::match_keys() const {
    std::unordered_set<std::string> keys;
    const std::string name_key = normalize_well_name(name);
    if (!name_key.empty()) keys.insert(name_key);
    if (!uwi.empty()) {
        const std::string uwi_key = normalize_well_name(uwi);
        if (!uwi_key.empty()) {
            keys.insert(uwi_key);
            keys.insert("uwi:" + uwi_key);
        }
    }
    for (const std::string& alias : aliases) {
        const std::string key = normalize_well_name(alias);
        if (!key.empty()) keys.insert(key);
    }
    return keys;
}

WellRegistry::WellRegistry(const domain::Json& wells) {
    if (!wells.is_array()) return;
    for (const auto& node : wells) {
        if (!node.is_object()) continue;
        WellRecord well;
        if (node.contains("id") && node["id"].is_string()) {
            well.id = node["id"].get<std::string>();
        }
        if (well.id.empty()) continue;
        if (node.contains("name") && node["name"].is_string()) {
            well.name = node["name"].get<std::string>();
        }
        if (node.contains("uwi") && node["uwi"].is_string()) {
            well.uwi = node["uwi"].get<std::string>();
        }
        if (node.contains("aliases") && node["aliases"].is_array()) {
            for (const auto& alias : node["aliases"]) {
                if (alias.is_string()) {
                    well.aliases.push_back(alias.get<std::string>());
                }
            }
        }
        add(std::move(well));
    }
}

void WellRegistry::add(WellRecord well) {
    if (by_id_.count(well.id)) return;  // already indexed
    wells_.push_back(std::move(well));
    WellRecord* stored = &wells_.back();
    order_.push_back(stored);
    by_id_[stored->id] = stored;
    for (const std::string& key : stored->match_keys()) {
        index_[key].push_back(stored);
        auto existing = by_key_.find(key);
        if (existing == by_key_.end()) {
            by_key_[key] = stored;
        } else if (existing->second->id != stored->id) {
            ambiguous_keys_.insert(key);
        }
    }
}

const WellRecord* WellRegistry::by_id(const std::string& well_id) const {
    auto it = by_id_.find(well_id);
    return it == by_id_.end() ? nullptr : it->second;
}

const WellRecord* WellRegistry::by_key(const std::string& key) const {
    const std::string normalized = normalize_well_name(key);
    if (ambiguous_keys_.count(normalized)) return nullptr;
    auto it = by_key_.find(normalized);
    return it == by_key_.end() ? nullptr : it->second;
}

std::vector<const WellRecord*> WellRegistry::find_all_by_name(
    const std::string& name) const {
    std::vector<const WellRecord*> found;
    const std::string normalized = normalize_well_name(name);
    if (normalized.empty()) return found;
    auto it = index_.find(normalized);
    if (it != index_.end()) {
        for (const WellRecord* well : it->second) found.push_back(well);
    }
    return found;
}

SurveyRegistry::SurveyRegistry(const domain::Json& surveys) {
    if (!surveys.is_array()) return;
    for (const auto& node : surveys) {
        if (!node.is_object()) continue;
        SurveyRecord survey;
        if (node.contains("id") && node["id"].is_string()) {
            survey.id = node["id"].get<std::string>();
        }
        if (survey.id.empty()) continue;
        if (node.contains("name") && node["name"].is_string()) {
            survey.name = node["name"].get<std::string>();
        }
        surveys_.push_back(std::move(survey));
        SurveyRecord* stored = &surveys_.back();
        by_id_[stored->id] = stored;
        const std::string key = normalize_well_name(stored->name);
        if (!key.empty() && !by_key_.count(key)) by_key_[key] = stored;
    }
}

const SurveyRecord* SurveyRegistry::by_id(const std::string& survey_id) const {
    auto it = by_id_.find(survey_id);
    return it == by_id_.end() ? nullptr : it->second;
}

const SurveyRecord* SurveyRegistry::by_key(const std::string& key) const {
    auto it = by_key_.find(normalize_well_name(key));
    return it == by_key_.end() ? nullptr : it->second;
}

ResolutionOutcome resolve_well(const domain::Json& project_root,
                               const WellRegistry* registry,
                               std::string_view name, std::string_view uwi,
                               std::string_view well_id,
                               const std::optional<domain::Json>& overrides) {
    WellRegistry owned;
    if (registry == nullptr) {
        auto wells = project_root.find("wells");
        owned = WellRegistry(wells != project_root.end() && wells->is_array()
                                 ? *wells
                                 : domain::Json::array());
        registry = &owned;
    }
    ResolutionOutcome outcome;
    if (!well_id.empty()) {
        if (const WellRecord* well = registry->by_id(std::string(well_id))) {
            outcome.matched = true;
            outcome.well_id = well->id;
            outcome.strategy = "persisted_id";
            return outcome;
        }
    }
    if (!uwi.empty()) {
        const std::string normalized_uwi =
            "uwi:" + normalize_well_name(uwi);
        if (const WellRecord* well = registry->by_key(normalized_uwi)) {
            outcome.matched = true;
            outcome.well_id = well->id;
            outcome.strategy = "uwi";
            return outcome;
        }
    }
    const std::string normalized = normalize_well_name(name);
    if (!normalized.empty()) {
        const std::vector<const WellRecord*> candidates =
            registry->find_all_by_name(normalized);
        if (candidates.size() == 1) {
            const WellRecord* well = candidates.front();
            outcome.strategy = "canonical_name";
            if (!uwi.empty()) {
                const std::string uwi_key = normalize_well_name(uwi);
                for (const std::string& alias : well->aliases) {
                    if (normalize_well_name(alias) == uwi_key && !uwi_key.empty()) {
                        outcome.strategy = "alias";
                        break;
                    }
                }
            }
            outcome.matched = true;
            outcome.well_id = well->id;
            return outcome;
        }
        if (candidates.size() > 1) {
            outcome.ambiguous = true;
            outcome.strategy = "ambiguous_name";
            for (const WellRecord* candidate : candidates) {
                outcome.candidates.push_back(candidate->id);
            }
            return outcome;
        }
    }
    domain::Json effective_overrides = domain::Json::object();
    if (overrides.has_value()) {
        effective_overrides = *overrides;
    } else {
        // workarea.metadata.well_identity_overrides (governance mappings).
        auto workarea = project_root.find("workarea");
        if (workarea != project_root.end() && workarea->is_object()) {
            auto metadata = workarea->find("metadata");
            if (metadata != workarea->end() && metadata->is_object()) {
                auto mapping =
                    metadata->find("well_identity_overrides");
                if (mapping != metadata->end() && mapping->is_object()) {
                    effective_overrides = *mapping;
                }
            }
        }
    }
    if (effective_overrides.is_object() && !effective_overrides.empty()) {
        std::vector<std::string> keys{normalize_well_name(name)};
        if (!uwi.empty()) {
            keys.push_back("uwi:" + normalize_well_name(uwi));
        }
        for (const std::string& key : keys) {
            if (key.empty()) continue;
            auto hit = effective_overrides.find(key);
            if (hit != effective_overrides.end() && hit->is_string()) {
                const std::string target = hit->get<std::string>();
                if (const WellRecord* well = registry->by_id(target)) {
                    outcome.matched = true;
                    outcome.well_id = well->id;
                    outcome.strategy = "explicit_mapping";
                    return outcome;
                }
            }
        }
    }
    outcome.strategy = "none";
    return outcome;
}

namespace {

domain::Json& links_array(domain::Json& project_root) {
    auto links = project_root.find("entity_asset_links");
    if (links == project_root.end() || !links->is_array()) {
        project_root["entity_asset_links"] = domain::Json::array();
        return project_root["entity_asset_links"];
    }
    return *links;
}

bool demote_sibling_primaries(domain::Json& links,
                              const std::string& entity_type,
                              const std::string& entity_id,
                              const std::string& role,
                              const std::string& keep_link_id) {
    bool changed = false;
    for (auto& link : links) {
        if (!link.is_object()) continue;
        const std::string id =
            link.value("id", std::string());
        const std::string other_type =
            link.value("entity_type", std::string());
        const std::string other_id =
            link.value("entity_id", std::string());
        const std::string other_role =
            link.value("role", std::string());
        if (id != keep_link_id && other_type == entity_type &&
            other_id == entity_id && other_role == role &&
            link.value("is_primary", false)) {
            link["is_primary"] = false;
            changed = true;
        }
    }
    return changed;
}

}  // namespace

LinkUpsert upsert_entity_asset_link(domain::Json& project_root,
                                    std::string_view entity_type,
                                    std::string_view entity_id,
                                    std::string_view asset_id,
                                    std::string_view role, bool is_primary,
                                    bool unresolved, std::string_view note) {
    domain::Json& links = links_array(project_root);
    const std::string role_value =
        role.empty() ? std::string("other") : std::string(role);
    for (std::size_t i = 0; i < links.size(); ++i) {
        domain::Json& link = links[i];
        if (!link.is_object()) continue;
        if (link.value("entity_type", std::string()) == entity_type &&
            link.value("entity_id", std::string()) == entity_id &&
            link.value("asset_id", std::string()) == asset_id &&
            link.value("role", std::string()) == role_value) {
            LinkUpsert result;
            result.index = i;
            if (is_primary && !link.value("is_primary", false)) {
                link["is_primary"] = true;
                result.changed = true;
            }
            if (unresolved != link.value("unresolved", false)) {
                link["unresolved"] = unresolved;
                result.changed = true;
            }
            const std::string existing_note =
                link.value("note", std::string());
            if (!note.empty() && existing_note != note) {
                link["note"] = note;
                result.changed = true;
            }
            if (is_primary) {
                result.changed |= demote_sibling_primaries(
                    links, std::string(entity_type), std::string(entity_id),
                    role_value, link.value("id", std::string()));
            }
            return result;
        }
    }
    LinkUpsert result;
    result.created = true;
    result.changed = true;
    if (is_primary) {
        demote_sibling_primaries(links, std::string(entity_type),
                                 std::string(entity_id), role_value, "");
    }
    domain::Json link = domain::Json::object();
    link["id"] = domain::make_id("link_");
    link["entity_type"] = entity_type;
    link["entity_id"] = entity_id;
    link["asset_id"] = asset_id;
    link["role"] = role_value;
    link["is_primary"] = is_primary;
    link["unresolved"] = unresolved;
    link["note"] = note;
    link["metadata"] = domain::Json::object();
    link["created_at"] = "";
    links.push_back(std::move(link));
    result.index = links.size() - 1;
    return result;
}

std::vector<std::string> asset_ids_for_entity(
    const domain::Json& project_root, std::string_view entity_type,
    std::string_view entity_id, std::string_view role) {
    std::vector<std::string> ids;
    auto links = project_root.find("entity_asset_links");
    if (links == project_root.end() || !links->is_array()) return ids;
    for (const auto& link : *links) {
        if (!link.is_object()) continue;
        if (link.value("entity_type", std::string()) == entity_type &&
            link.value("entity_id", std::string()) == entity_id) {
            if (!role.empty() &&
                link.value("role", std::string()) != role) {
                continue;
            }
            ids.push_back(link.value("asset_id", std::string()));
        }
    }
    return ids;
}

std::string normalize_well_name(std::string_view name) {
    // Bounded fold: ASCII casefold + separator collapse (see header note).
    std::string folded;
    folded.reserve(name.size());
    const std::string text(trimmed(name));
    for (std::size_t i = 0; i < text.size();) {
        std::size_t run = 0;
        if (is_separator_byte_run(text, i, &run)) {
            folded.push_back(' ');
            i += run;
            continue;
        }
        const char c = text[i];
        if (c >= 'A' && c <= 'Z') {
            folded.push_back(static_cast<char>(c - 'A' + 'a'));
        } else {
            folded.push_back(c);
        }
        ++i;
    }
    // Collapse runs of spaces (folded separators + original ASCII spaces).
    std::string collapsed;
    collapsed.reserve(folded.size());
    bool pending_space = false;
    bool seen_any = false;
    for (const char c : folded) {
        if (is_ascii_space(c)) {
            pending_space = seen_any;
        } else {
            if (pending_space) collapsed.push_back(' ');
            pending_space = false;
            collapsed.push_back(c);
            seen_any = true;
        }
    }
    return collapsed;
}

std::string infer_role_for_type(std::string_view resource_type,
                                std::string_view file_suffix,
                                std::string_view file_name) {
    auto lower = [](std::string text) {
        for (char& c : text) {
            if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
        }
        return text;
    };
    const std::string rtype = lower(
        trimmed(resource_type).empty() ? std::string()
                                       : std::string(trimmed(resource_type)));
    std::string suffix = lower(std::string(file_suffix));
    while (!suffix.empty() && suffix.front() == ' ') suffix.erase(suffix.begin());
    while (!suffix.empty() && suffix.back() == ' ') suffix.pop_back();
    if (!suffix.empty() && suffix.front() != '.') suffix.insert(suffix.begin(), '.');
    std::string stem = lower(std::string(file_name));
    const auto dot = stem.rfind('.');
    if (dot != std::string::npos) stem.resize(dot);

    if (rtype == "well_head") return "well_head";
    if (rtype == "well_log" || rtype == "las" || rtype == "dlis" ||
        rtype == "lis") {
        return "well_log";
    }
    if (rtype == "well_stratification" || rtype == "tops") return "tops";
    if (rtype == "seismic" || rtype == "segy") return "seismic_volume";
    if (rtype == "horizon") return "horizon";
    if (rtype == "fault" || rtype == "faults") return "fault";
    if (rtype == "trajectory" || rtype == "deviation") return "trajectory";
    if (rtype == "time_depth" || rtype == "checkshot" || rtype == "td_table") {
        return "time_depth";
    }
    if (rtype == "core") return "core";
    // Well-known filename tokens for generically-typed files — presentation
    // conventions, not identity claims.
    const bool generic = rtype == "table" || rtype == "tabular" ||
                         rtype == "spreadsheet" || rtype == "csv" ||
                         rtype == "unknown" || rtype == "document";
    if (generic) {
        auto has_token = [&stem](std::initializer_list<const char*> tokens) {
            for (const char* token : tokens) {
                if (stem.find(token) != std::string::npos) return true;
            }
            return false;
        };
        if (has_token({"deviation", "trajectory", "survey_", "wellpath"})) {
            return "trajectory";
        }
        if (has_token({"tops", "marker", "formation"})) return "tops";
        if (has_token({"checkshot", "check_shot", "td_table", "timedepth",
                       "time_depth"})) {
            return "time_depth";
        }
        if (has_token({"core"})) return "core";
    }
    // Format-only hints, iterating ROLE_DEFINITIONS declaration order with
    // its first-win index (roles.py); trajectory is skipped for bare
    // spreadsheet/csv files (a bare .xlsx/.csv is far more often tops).
    const bool format_scoped = rtype == "table" || rtype == "tabular" ||
                               rtype == "spreadsheet" || rtype == "csv" ||
                               rtype == "unknown";
    if (format_scoped && !suffix.empty()) {
        struct RoleHints {
            const char* role;
            std::initializer_list<const char*> extensions;
        };
        static const RoleHints kHints[] = {
            {"well_head", {".dat", ".xml"}},
            {"well_log", {".las", ".lis", ".dlis", ".xml"}},
            // trajectory deliberately skipped (roles.py guard).
            {"tops", {".csv", ".txt"}},
            {"time_depth", {".dat", ".csv", ".txt"}},
            {"seismic_volume", {".sgy", ".segy"}},
        };
        for (const RoleHints& hint : kHints) {
            for (const char* ext : hint.extensions) {
                if (suffix == ext) return hint.role;
            }
        }
    }
    return "";
}

}  // namespace pwb::data
