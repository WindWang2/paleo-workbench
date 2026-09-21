#include "posix_shim.hpp"
#include "pwb/catalog/audit.hpp"

#include "pwb/catalog/checksum.hpp"
#include "pwb/catalog/gc.hpp"
#include "pwb/catalog/policies.hpp"
#include "pwb/catalog/trash.hpp"
#include "pwb/project/paths.hpp"

#include <algorithm>
#include <set>

namespace pwb::catalog {

namespace {

std::string py_repr(std::string_view text) {
    std::string out = "'";
    for (char c : text) {
        if (c == '\\' || c == '\'') out.push_back('\\');
        out.push_back(c);
    }
    out.push_back('\'');
    return out;
}

void issue(AuditReport* report, std::string_view kind, std::string_view severity,
           std::string ref_id, std::string detail) {
    report->issues.push_back(
        {std::string(kind), std::string(severity), std::move(ref_id), std::move(detail)});
}

// _parse_iso: ISO-8601 "YYYY-MM-DDTHH:MM:SS..." prefix (fractions and
// offsets beyond the seconds are ignored; naive stamps read as UTC via
// timegm). Returns epoch seconds.
std::optional<std::int64_t> parse_iso_epoch(const std::string& raw) {
    if (raw.empty()) return std::nullopt;
    std::tm tm{};
    if (!posix_shim::strptime_iso_prefix(raw.c_str(), &tm)) {
        return std::nullopt;
    }
    return static_cast<std::int64_t>(posix_shim::timegm_compat(&tm));
}

std::int64_t utc_now_epoch() {
    return static_cast<std::int64_t>(::time(nullptr));
}

void check_current_versions(AuditReport* report, const CatalogDocument& document,
                            const DocumentIndex& index) {
    for (const auto& asset : document.assets) {
        if (!asset.current_version_id.has_value()) continue;
        const std::string current = asset.current_version_id->str();
        const DataVersion* version = index.version(current);
        if (version == nullptr) {
            issue(report, "invalid_current_version", kSeverityHigh, asset.id.str(),
                  "current_version_id " + current + " does not exist");
        } else if (!(version->asset_id == asset.id)) {
            issue(report, "invalid_current_version", kSeverityHigh, asset.id.str(),
                  "current_version_id " + current + " belongs to asset " +
                      version->asset_id.str());
        } else if (version->trashed) {
            issue(report, "invalid_current_version", kSeverityMedium, asset.id.str(),
                  "current_version_id " + current + " is trashed");
        }
    }
}

void check_lineage(AuditReport* report, const CatalogDocument& document,
                   const DocumentIndex& index) {
    for (const auto& version : document.versions) {
        for (const auto& parent : version.parent_version_ids) {
            if (index.version(parent.str()) == nullptr) {
                issue(report, "broken_lineage", kSeverityMedium, version.id.str(),
                      "parent_version_id " + parent.str() + " does not exist");
            }
        }
    }
    // Iterative three-color DFS over ALL parent edges: a back-edge to a
    // gray node closes a cycle regardless of the parent slot it came from.
    enum Color { White, Gray, Black };
    std::map<std::string, Color> color;
    for (const auto& version : document.versions) {
        color[version.id.str()] = White;
    }
    for (const auto& start : document.versions) {
        if (color[start.id.str()] != White) continue;
        std::vector<std::pair<std::string, std::size_t>> stack;
        stack.push_back({start.id.str(), 0});
        color[start.id.str()] = Gray;
        while (!stack.empty()) {
            auto& [node_id, slot] = stack.back();
            const DataVersion* node = index.version(node_id);
            if (node == nullptr || slot >= node->parent_version_ids.size()) {
                color[node_id] = Black;
                stack.pop_back();
                continue;
            }
            const std::string next_id =
                node->parent_version_ids[slot++].str();
            if (index.version(next_id) == nullptr) continue;  // dangling: above
            if (color[next_id] == Gray) {
                issue(report, "lineage_cycle", kSeverityLow, start.id.str(),
                      "parent chain revisits " + next_id);
                for (const auto& [on_stack, _] : stack) color[on_stack] = Black;
                break;
            }
            if (color[next_id] == White) {
                color[next_id] = Gray;
                stack.push_back({next_id, 0});
            }
        }
    }
}

void check_run_links(AuditReport* report, const CatalogDocument& document,
                     const DocumentIndex& index) {
    for (const auto& run : document.runs) {
        for (const auto& input : run.input_version_ids) {
            if (index.version(input.str()) == nullptr) {
                issue(report, "broken_run_link", kSeverityLow, run.id.str(),
                      "input_version_id " + input.str() +
                          " does not exist (possibly purge-retained provenance)");
            }
        }
        for (const auto& output : run.output_version_ids) {
            if (index.version(output.str()) == nullptr) {
                issue(report, "broken_run_link", kSeverityLow, run.id.str(),
                      "output_version_id " + output.str() +
                          " does not exist (possibly purge-retained provenance)");
            }
        }
    }
}

void check_run_outputs(AuditReport* report, const CatalogDocument& document) {
    static const std::set<std::string> kAlwaysProducing = {
        "materialize", "working_copy_commit", "manual_edit",
        "map_product_assembly", "interchange.import"};
    for (const auto& run : document.runs) {
        if (kAlwaysProducing.count(run.operation) && run.status == "completed" &&
            run.output_version_ids.empty()) {
            issue(report, "orphan_completed_run", kSeverityLow, run.id.str(),
                  "'" + run.operation + "' run completed with no output version");
        }
    }
}

void check_science_run_inputs(AuditReport* report, const CatalogDocument& document) {
    static const std::set<std::string> kScienceOps = {"factor_map", "prediction",
                                                      "map_compile", "qc"};
    for (const auto& run : document.runs) {
        if (!kScienceOps.count(run.operation)) continue;
        if (run.status != "completed" && run.status != "complete") continue;
        if (!run.input_version_ids.empty()) continue;
        issue(report, "science_run_without_inputs", kSeverityMedium, run.id.str(),
              "completed '" + run.operation +
                  "' run records no input versions — its outputs cannot be "
                  "traced to RAW");
    }
}

void check_provenance(AuditReport* report, const CatalogDocument& document) {
    for (const auto& version : document.versions) {
        if (version.stage == domain::DataStage::Raw || version.trashed) continue;
        if (!version.run_id.has_value() && version.parent_version_ids.empty()) {
            issue(report, "unprovenanced_version", kSeverityMedium, version.id.str(),
                  std::string(domain::to_string(version.stage)) +
                      " version has no producing run and no parent versions");
        }
    }
}

void check_stale_runs(AuditReport* report, const CatalogDocument& document,
                      int after_seconds) {
    const std::int64_t now = utc_now_epoch();
    for (const auto& run : document.runs) {
        if (run.status != "running") continue;
        auto started = parse_iso_epoch(run.created_at);
        if (!started.has_value()) continue;
        const std::int64_t age = now - *started;
        if (age > after_seconds) {
            issue(report, "stale_running_run", kSeverityLow, run.id.str(),
                  "'" + run.operation + "' run still running after " +
                      std::to_string(age / 3600) + "h");
        }
    }
}

void check_output_claims(AuditReport* report, const CatalogDocument& document,
                         const DocumentIndex& index) {
    std::map<std::string, std::vector<const DataRun*>> claims;
    for (const auto& run : document.runs) {
        for (const auto& output : run.output_version_ids) {
            if (index.version(output.str()) != nullptr) {
                claims[output.str()].push_back(&run);
            }
        }
    }
    for (const auto& [output_id, claiming_runs] : claims) {
        const DataVersion* version = index.version(output_id);
        if (claiming_runs.size() > 1) {
            std::string names;
            for (std::size_t i = 0; i < claiming_runs.size(); ++i) {
                if (i) names += ", ";
                names += claiming_runs[i]->operation + ":" + claiming_runs[i]->id.str();
            }
            issue(report, "multi_claimed_output", kSeverityLow, output_id,
                  "version claimed as output by " +
                      std::to_string(claiming_runs.size()) + " runs (" + names + ")");
        } else if (version->run_id.has_value() &&
                   !(version->run_id->str() == claiming_runs[0]->id.str())) {
            issue(report, "multi_claimed_output", kSeverityLow, output_id,
                  "version.run_id " + version->run_id->str() + " != claiming run " +
                      claiming_runs[0]->id.str() + " (" +
                      claiming_runs[0]->operation + ")");
        }
    }
}

void check_run_lineage_divergence(AuditReport* report,
                                  const CatalogDocument& document,
                                  const DocumentIndex& index) {
    for (const auto& run : document.runs) {
        if (run.input_version_ids.empty() || run.output_version_ids.empty()) continue;
        for (const auto& output : run.output_version_ids) {
            const DataVersion* version = index.version(output.str());
            if (version == nullptr) continue;
            std::set<std::string> live_inputs;
            for (const auto& input : run.input_version_ids) {
                if (index.version(input.str()) != nullptr) {
                    live_inputs.insert(input.str());
                }
            }
            if (live_inputs.empty()) continue;
            bool any_edge = false;
            for (const auto& parent : version->parent_version_ids) {
                if (live_inputs.count(parent.str())) any_edge = true;
            }
            if (!any_edge) {
                issue(report, "run_lineage_divergence", kSeverityLow, output.str(),
                      "run " + run.id.str() + " (" + run.operation + ") consumed " +
                          std::to_string(live_inputs.size()) +
                          " input(s) but the output version has no matching parent "
                          "edge");
            }
        }
    }
}

void check_governance_metadata(AuditReport* report, const CatalogDocument& document) {
    for (const auto& asset : document.assets) {
        if (!asset.metadata.is_object()) continue;
        for (const auto& spec : governance_fields()) {
            if (!asset.metadata.contains(spec.key)) continue;
            const auto& raw = asset.metadata[spec.key];
            if (raw.is_null() || (raw.is_string() && raw.get<std::string>().empty())) {
                continue;
            }
            if (spec.vocabulary.empty()) continue;
            auto normalized = normalize_governance_value(spec.key, raw);
            if (!normalized.is_ok()) {
                std::string vocab;
                for (std::size_t i = 0; i < spec.vocabulary.size(); ++i) {
                    if (i) vocab += "、";
                    vocab += spec.vocabulary[i];
                }
                std::string raw_text =
                    raw.is_string() ? raw.get<std::string>() : raw.dump();
                issue(report, "invalid_metadata_value", kSeverityLow, asset.id.str(),
                      spec.label + "(" + spec.key + ")=" + py_repr(raw_text) +
                          " 不在受控词表 " + vocab);
            }
        }
    }
}

void check_tags(AuditReport* report, const CatalogDocument& document,
                const DocumentIndex& index) {
    std::set<std::string> tag_ids;
    for (const auto& tag : document.tags) tag_ids.insert(tag.id);
    // Python iterates the association MAPS: one unknown-owner issue per
    // owner key, one unknown-tag issue per (owner, tag) association.
    std::set<std::string> seen_asset_owners;
    for (const auto& [asset_id, tag_id] : document.asset_tags) {
        if (seen_asset_owners.insert(asset_id).second &&
            index.asset(asset_id) == nullptr) {
            issue(report, "dangling_tag_ref", kSeverityMedium, asset_id,
                  "asset_tags entry for unknown asset");
        }
        if (!tag_ids.count(tag_id)) {
            issue(report, "dangling_tag_ref", kSeverityMedium, asset_id,
                  "asset_tags references unknown tag " + tag_id);
        }
    }
    std::set<std::string> seen_version_owners;
    for (const auto& [version_id, tag_id] : document.version_tags) {
        if (seen_version_owners.insert(version_id).second &&
            index.version(version_id) == nullptr) {
            issue(report, "dangling_tag_ref", kSeverityMedium, version_id,
                  "version_tags entry for unknown version");
        }
        if (!tag_ids.count(tag_id)) {
            issue(report, "dangling_tag_ref", kSeverityMedium, version_id,
                  "version_tags references unknown tag " + tag_id);
        }
    }
    std::set<std::string> used;
    for (const auto& [owner, tag_id] : document.asset_tags) used.insert(tag_id);
    for (const auto& [owner, tag_id] : document.version_tags) used.insert(tag_id);
    for (const auto& tag : document.tags) {
        if (!used.count(tag.id)) {
            issue(report, "unused_tag", kSeverityLow, tag.id,
                  "tag '" + tag.name + "' has no associations");
        }
    }
}

void check_paths(AuditReport* report, const AuditContext& context,
                 const CatalogDocument& document) {
    const std::string artifacts_name =
        pwb::project::artifact_dir_for(context.project_path).filename().string();
    for (const auto& version : document.versions) {
        if (!version.managed) {
            // Platform-correct absoluteness (a Windows drive path is
            // absolute too — the POSIX-only startswith("/") check
            // false-positived there).
            if (!version.path.empty() &&
                fs::path(version.path).is_relative()) {
                issue(report, "path_mismatch", kSeverityLow, version.id.str(),
                      "external version path is not absolute: " + version.path);
            }
            continue;
        }
        if (is_cas_path(context.project_path, version.path)) continue;
        const std::string posix = version.path;
        if (version.trashed) {
            const std::string expected = artifacts_name + "/trash/" + version.id.str() + "/";
            const std::string* original = nullptr;
            std::string original_storage;
            if (version.metadata.is_object() && version.metadata.contains("trash") &&
                version.metadata["trash"].is_object() &&
                version.metadata["trash"].contains("original_path") &&
                version.metadata["trash"]["original_path"].is_string()) {
                original_storage = version.metadata["trash"]["original_path"];
                original = &original_storage;
            }
            if (posix.rfind(expected, 0) == 0) continue;
            if (original != nullptr && posix == *original) continue;  // crash window
            issue(report, "path_mismatch", kSeverityMedium, version.id.str(),
                  "trashed managed payload not under " + expected + ": " + posix);
            continue;
        }
        const std::string expected = artifacts_name + "/" +
                                     stage_dir_name(version.stage) + "/" +
                                     version.asset_id.str() + "/" +
                                     version.id.str() + "/";
        if (posix.rfind(expected, 0) != 0) {
            issue(report, "path_mismatch", kSeverityMedium, version.id.str(),
                  "managed payload not under " + expected + ": " + posix);
        }
    }
}

void check_payloads(AuditReport* report, const AuditContext& context,
                    const CatalogDocument& document, bool deep,
                    const std::function<bool()>& cancel) {
    auto resolver = context.resolve_path;
    for (const auto& version : document.versions) {
        if (cancel && cancel()) {
            report->cancelled = true;
            return;
        }
        if (!version.managed) {
            std::error_code ec;
            if (!version.path.empty() && !fs::exists(fs::path(version.path), ec)) {
                issue(report, "external_path_missing", kSeverityMedium,
                      version.id.str(), "external payload not found: " + version.path);
            }
            continue;
        }
        fs::path payload = resolver ? resolver(version)
                                    : fs::path(version.path);
        std::error_code ec;
        if (!fs::exists(payload, ec)) {
            // A trashed version's payload may legitimately be missing
            // (metadata-only tombstone): recoverable metadata, not data loss.
            issue(report, "payload_missing",
                  version.trashed ? kSeverityLow : kSeverityHigh, version.id.str(),
                  "payload not found: " + payload.string());
        }
    }
    // Orphan files on disk (payload without a catalog record).
    GcContext gc_context;
    gc_context.project_path = context.project_path;
    gc_context.document = context.document;
    GcReport gc_report = plan_gc(gc_context, /*explicit_plan=*/true);
    for (const auto& item : gc_report.items) {
        issue(report, "orphan_" + item.kind, kSeverityLow,
              fs::path(item.rel_path).filename().string(), item.rel_path);
    }
    if (deep) {
        for (const auto& version : document.versions) {
            if (cancel && cancel()) {
                report->cancelled = true;
                break;
            }
            if (version.trashed) continue;
            fs::path payload = resolver ? resolver(version)
                                        : fs::path(version.path);
            std::error_code ec;
            if (!fs::is_regular_file(payload, ec)) continue;
            if (!version.sha256.has_value() || version.sha256->empty()) continue;
            auto digest = sha256_file(payload, kChecksumChunkSize, cancel);
            if (!digest.is_ok()) {
                report->cancelled = true;
                break;
            }
            if (digest.value() != *version.sha256) {
                issue(report, "integrity_mismatch", kSeverityHigh, version.id.str(),
                      "recorded sha256 does not match payload content");
            }
        }
    }
}

}  // namespace

std::vector<AuditIssue> AuditReport::by_kind(std::string_view kind) const {
    std::vector<AuditIssue> out;
    for (const auto& i : issues) {
        if (i.kind == kind) out.push_back(i);
    }
    return out;
}

std::vector<AuditIssue> AuditReport::by_severity(std::string_view severity) const {
    std::vector<AuditIssue> out;
    for (const auto& i : issues) {
        if (i.severity == severity) out.push_back(i);
    }
    return out;
}

std::map<std::string, int> AuditReport::counts_by_kind() const {
    std::map<std::string, int> counts;
    for (const auto& i : issues) counts[i.kind] += 1;
    return counts;
}

AuditStats AuditReport::statistics() const {
    AuditStats stats;
    stats.checked = checked;
    stats.issues_high = static_cast<int>(by_severity(kSeverityHigh).size());
    stats.issues_medium = static_cast<int>(by_severity(kSeverityMedium).size());
    stats.issues_low = static_cast<int>(by_severity(kSeverityLow).size());
    stats.by_kind = counts_by_kind();
    return stats;
}

bool AuditReport::ok() const {
    return by_severity(kSeverityHigh).empty() && by_severity(kSeverityMedium).empty();
}

AuditReport audit_catalog(const AuditContext& context, bool deep,
                          std::optional<int> stale_run_after_seconds,
                          const std::function<bool()>& cancel) {
    AuditReport report;
    const CatalogDocument& document = *context.document;
    const DocumentIndex& index = *context.index;
    report.checked = {{"assets", static_cast<int>(document.assets.size())},
                      {"versions", static_cast<int>(document.versions.size())},
                      {"runs", static_cast<int>(document.runs.size())},
                      {"tags", static_cast<int>(document.tags.size())}};

    check_current_versions(&report, document, index);
    check_lineage(&report, document, index);
    check_run_links(&report, document, index);
    check_run_outputs(&report, document);
    check_science_run_inputs(&report, document);
    check_provenance(&report, document);
    check_stale_runs(&report, document,
                     stale_run_after_seconds.value_or(kStaleRunAfterSeconds));
    check_output_claims(&report, document, index);
    check_run_lineage_divergence(&report, document, index);
    check_governance_metadata(&report, document);
    check_tags(&report, document, index);
    check_paths(&report, context, document);
    check_payloads(&report, context, document, deep, cancel);
    return report;
}

}  // namespace pwb::catalog
