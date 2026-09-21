#include "pwb/data/role_registry.hpp"

#include <unordered_map>

namespace pwb::data {
namespace {

// roles.py _WELL_ROLE_DEFS / _SURVEY_ROLE_DEFS / _GEOLOGICAL_ROLE_DEFS,
// field-for-field. Table order IS the vocabulary order ("other" last).
std::vector<RoleDefinition> build_table() {
    std::vector<RoleDefinition> table;
    const auto add = [&table](RoleDefinition definition) {
        table.push_back(std::move(definition));
    };

    add({"well_head", {"well"}, "0..N", "required_single", false, "井身/井位",
         "raw", {".dat", ".xml"}});
    add({"well_log", {"well"}, "0..N", "optional", true, "测井曲线", "raw",
         {".las", ".lis", ".dlis", ".xml"}});
    add({"trajectory", {"well"}, "0..N", "optional", false, "井斜轨迹", "raw",
         {".xlsx", ".xls", ".csv", ".dev"}});
    add({"tops", {"well"}, "0..N", "optional", false, "分层顶", "raw",
         {".csv", ".txt"}});
    add({"time_depth", {"well"}, "0..N", "required_single", false, "时深关系",
         "raw", {".dat", ".csv", ".txt"}});
    add({"core", {"well"}, "0..N", "optional", false, "岩心", "raw", {}});
    add({"interpretation", {"well"}, "0..N", "none", false, "井周解释",
         "raw", {}});
    add({"qc", {"well"}, "0..N", "none", false, "质量控制", "raw", {}});
    add({"other", {"well"}, "0..N", "none", false, "其他", "raw", {}});

    add({"seismic_volume", {"seismic_survey"}, "0..N", "required_single",
         false, "地震数据体", "raw", {".sgy", ".segy"}});
    add({"geometry", {"seismic_survey"}, "0..N", "optional", false, "观测系统",
         "raw", {}});
    add({"velocity", {"seismic_survey"}, "0..N", "optional", false, "速度场",
         "raw", {}});
    add({"horizon", {"seismic_survey"}, "0..N", "optional", false, "层位",
         "raw", {}});
    add({"fault", {"seismic_survey"}, "0..N", "optional", false, "断层",
         "raw", {}});
    add({"interpretation", {"seismic_survey"}, "0..N", "none", false,
         "调查解释", "raw", {}});
    add({"other", {"seismic_survey"}, "0..N", "none", false, "其他", "raw",
         {}});

    add({"horizon", {"geological_entity"}, "0..N", "optional", false, "层位",
         "raw", {}});
    add({"tops", {"geological_entity"}, "0..N", "optional", false, "分层",
         "raw", {}});
    add({"fault", {"geological_entity"}, "0..N", "optional", false, "断层",
         "raw", {}});
    add({"other", {"geological_entity"}, "0..N", "none", false, "其他",
         "raw", {}});
    return table;
}

// Process-lifetime table + indexes (function-local statics avoid the
// static-init-order hazard; the table is never mutated after build).
struct Registry {
    std::vector<RoleDefinition> table;
    // (entity_type, role) → definition; the authoritative scoped index.
    std::unordered_map<std::string, const RoleDefinition*> by_type;
    // role → FIRST definition seen (well vocabulary first in build order).
    std::unordered_map<std::string, const RoleDefinition*> by_role;

    Registry() : table(build_table()) {
        for (const auto& definition : table) {
            for (auto entity_type : definition.entity_types) {
                by_type.emplace(std::string(entity_type) + "\x1f" +
                                    std::string(definition.role),
                                &definition);
            }
            by_role.emplace(std::string(definition.role), &definition);
        }
    }
};

const Registry& registry() {
    static const Registry instance;
    return instance;
}

const RoleDefinition kFallback{"other", {}, "0..N", "none", false, "其他",
                               "raw", {}};

std::vector<std::string_view> vocabulary_for(std::string_view entity_type) {
    const auto& reg = registry();
    std::vector<std::string_view> roles;
    for (const auto& definition : reg.table) {
        if (definition.applies_to(entity_type)) {
            roles.push_back(definition.role);
        }
    }
    return roles;
}

}  // namespace

const RoleDefinition* role_definition(std::string_view role,
                                      std::string_view entity_type) {
    const auto& reg = registry();
    if (!entity_type.empty()) {
        const std::string key = std::string(entity_type) + "\x1f" +
                                std::string(role);
        if (auto it = reg.by_type.find(key); it != reg.by_type.end()) {
            return it->second;
        }
    }
    if (auto it = reg.by_role.find(std::string(role));
        it != reg.by_role.end()) {
        return it->second;
    }
    return &kFallback;
}

bool known_role(std::string_view role) {
    return registry().by_role.count(std::string(role)) != 0;
}

std::vector<std::string_view> roles_for_entity_type(
    std::string_view entity_type) {
    if (entity_type == "well") return well_roles();
    if (entity_type == "seismic_survey") return survey_roles();
    if (entity_type == "geological_entity") return geological_roles();
    return {"other"};
}

bool cardinality_allows_multiple(std::string_view role) {
    return role_definition(role)->cardinality != "0..1";
}

bool primary_required(std::string_view role) {
    return role_definition(role)->primary_policy == "required_single";
}

const std::vector<std::string_view>& well_roles() {
    static const std::vector<std::string_view> value =
        vocabulary_for("well");
    return value;
}

const std::vector<std::string_view>& survey_roles() {
    static const std::vector<std::string_view> value =
        vocabulary_for("seismic_survey");
    return value;
}

const std::vector<std::string_view>& geological_roles() {
    static const std::vector<std::string_view> value =
        vocabulary_for("geological_entity");
    return value;
}

std::string role_display(std::string_view role,
                         std::string_view entity_type) {
    const RoleDefinition* definition =
        role_definition(role, entity_type);
    if (definition == nullptr) return std::string(role);
    if (!definition->display.empty()) {
        return std::string(definition->display);
    }
    return std::string(role);
}

}  // namespace pwb::data
