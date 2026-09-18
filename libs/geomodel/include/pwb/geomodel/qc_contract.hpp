#pragma once

// pwb::geomodel — QC contract layer (CONV-22): faithful C++ port of
// paleo_workbench/viz/geomodel/qc.py — the severity ladder, per-object
// audits, assembly roll-up and the assert_exportable export gate.
// The numeric mesh cores (tri_degenerate_fraction / edge_manifold_stats /
// connected_components / triangulate_heightfield) were ported in CONV-12;
// this layer is the issue orchestration on top of them.
//
// Frozen against geomodel_contract_oracle.json.

#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/geomodel/domain_contract.hpp>

namespace pwb::geomodel {

using pwb::domain::Json;

// qc.QCBlockerError — export gate refusal. Message identical to Python
// ("export refused: blocker-level QC issues in ..." + per-issue lines).
struct QCBlockerError : std::runtime_error {
    explicit QCBlockerError(const std::string& msg)
        : std::runtime_error(msg) {}
};

struct QCIssue {
    std::string code;
    std::string severity;  // info|warning|error|blocker
    std::string message;
    std::string object_id;
    std::optional<double> metric;

    Json to_meta() const;
};

struct QCReport {
    std::vector<QCIssue> issues;

    void add(QCIssue i);
    void extend(const QCReport& other);
    std::vector<QCIssue> of(const std::string& object_id) const;
    Json severities(
        const std::optional<std::string>& object_id = std::nullopt) const;
    std::string worst(
        const std::optional<std::string>& object_id = std::nullopt) const;
    std::vector<const QCIssue*> blockers() const;
    Json to_meta() const;
    static QCReport from_meta(const Json& meta);
};

// qc_object — dispatches on object_id prefix, catches audit crashes into
// QC_AUDIT_FAILED (blocker) like the Python try/except.
QCReport qc_object(const DomainObject& obj);

// qc_assembly — known_source_ids nullopt -> no staleness check; else
// objects whose source_version_ids are all absent get STALE_SOURCE.
QCReport qc_assembly(
    const ModelAssembly& assembly,
    const std::optional<std::unordered_set<std::string>>& known_source_ids =
        std::nullopt);

// assert_exportable — report=nullopt -> fresh qc_object roll-up; blockers
// throw QCBlockerError (message identical, sorted object ids).
QCReport assert_exportable(const std::vector<DomainObject>& objects,
                           std::optional<QCReport> report = std::nullopt);

}  // namespace pwb::geomodel
