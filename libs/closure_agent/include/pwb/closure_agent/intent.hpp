#pragma once

// User intent understanding — C++ port of paleo_workbench/agent/intent.py.
// Keyword-domain scoring over the frozen Chinese vocabulary, horizon/factor
// extraction, and suggested-skill derivation. The horizon scanner mirrors
// Python's re.search(r"([T|J|K|P|C|D|S|O|Є]\w+|\w+组|\w+段)") semantics
// (including the literal pipes inside that character class) over a Unicode
// word-char approximation documented in intent.cpp.

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <tuple>
#include <vector>

namespace pwb::closure_agent {

using Json = pwb::domain::Json;

enum class TaskDomain {
    DataManagement,        // "data"
    WellLogging,           // "well"
    SeismicInterpretation, // "seismic"
    SpatialGis,            // "gis"
    SingleFactorMapping,   // "cartography"
    PaleomapCompilation,   // "compilation"
    Visualization,         // "visualization"
    QualityControl,        // "qa"
    General,               // "general"
};

std::string to_string(TaskDomain domain);
std::optional<TaskDomain> task_domain_from_string(const std::string& value);

struct ParsedIntent {
    std::string raw_query;
    TaskDomain primary_domain = TaskDomain::General;
    std::vector<TaskDomain> secondary_domains;
    std::string action_goal;  // the query itself (Python parity)
    Json parameters = Json::object();
    std::string target_horizon;
    std::string factor_type;
    std::vector<std::string> suggested_skills;
    bool requires_data = true;
    double confidence = 1.0;

    Json to_dict() const;
};

class IntentParser {
public:
    ParsedIntent parse(const std::string& user_query,
                       const Json& context = Json(nullptr)) const;
};

// Leftmost-anchored horizon match with Python \w semantics for geological
// text; exposed for tests.
std::optional<std::string> match_target_horizon(const std::string& query);

}  // namespace pwb::closure_agent
