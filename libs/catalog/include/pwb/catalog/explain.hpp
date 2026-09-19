// Explain service — "why does this file exist?" (conv-31;
// catalog/explain.py parity, V11 §15).
//
// One version-level answer object assembled from catalog + lineage +
// lifecycle policy so UIs never stitch provenance themselves: producing
// run (typed ports included), upstream closure, downstream usage, delete
// eligibility, regenerability, staleness (pinned-aware). The Python
// service injected project entity links; here they arrive as an optional
// (entity_type, entity_id, asset_id) list — absent links degrade to an
// empty entity context.
#pragma once

#include "pwb/catalog/document_index.hpp"
#include "pwb/catalog/impact.hpp"
#include "pwb/catalog/models.hpp"
#include "pwb/catalog/v11_policy.hpp"
#include "pwb/domain/errors.hpp"
#include "pwb/domain/json.hpp"

#include <optional>
#include <string>
#include <vector>

namespace pwb::catalog {

struct VersionExplanation {
    std::string version_id;
    std::string asset_id;
    std::string asset_name;
    std::string asset_type;
    std::string stage;
    bool bundle = false;
    int member_count = 0;

    // provenance
    std::optional<std::string> producing_run_id;
    std::optional<std::string> operation;
    std::string generator;
    domain::Json model_ref;                  // null or object
    domain::Json parameters = domain::Json::object();
    std::string created_at;
    domain::Json input_ports = domain::Json::array();
    domain::Json output_ports = domain::Json::array();
    std::vector<std::string> parent_version_ids;
    bool typed_lineage = false;

    // entity context
    std::vector<std::pair<std::string, std::string>> entities;

    // usage
    std::vector<std::string> downstream_version_ids;
    std::vector<std::string> downstream_run_ids;

    // lifecycle answers
    bool deletable = true;
    std::vector<std::string> delete_blockers;
    bool regenerable = false;
    bool stale = false;
    std::string stale_reason;
    bool pinned = false;
    std::string integrity_status = "unknown";

    domain::Json to_dict() const;
};

class ExplainService {
public:
    ExplainService(const CatalogDocument& document, const DocumentIndex& index)
        : document_(document), index_(index), impact_(document, index) {}

    // explain_version parity. *entity_links supplies the project-side
    // (entity_type, entity_id, asset_id) bindings when available.
    domain::Result<VersionExplanation> explain_version(
        const std::string& version_id,
        const std::vector<ImpactService::EntityLink>* entity_links = nullptr,
        bool live_working_copy = false);

    // explain_asset parity (asset-level rollup as JSON).
    domain::Json explain_asset(
        const std::string& asset_id,
        const std::vector<ImpactService::EntityLink>* entity_links = nullptr,
        bool live_working_copy = false);

private:
    const CatalogDocument& document_;
    const DocumentIndex& index_;
    ImpactService impact_;
};

}  // namespace pwb::catalog
