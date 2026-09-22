// workflow/fault_lifecycle.py port — see fault_lifecycle.hpp for the seam
// map. The artifact container + fingerprint bytes are byte-compatible with
// the Python chain (canonical JSON + SHA-256 via factor_host).
#include "pwb/workflow_interpretation/fault_lifecycle.hpp"

#include <pwb/domain/ids.hpp>
#include <pwb/domain/sha256.hpp>
#include <pwb/factor_host/canonical_json.hpp>
#include <pwb/factor_host/fingerprint.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#if !defined(_WIN32)
#include <unistd.h>
#endif
#include <set>
#include <fstream>
#include <map>
#include <sstream>

namespace pwb::workflow_interpretation {
namespace {

constexpr const char* kFaultArtifactSuffix = ".fault_interp.json";
constexpr const char* kFaultGenerator = "fault-interp-v1";

const Json* field(const Json& object, const char* key) {
    if (!object.is_object()) return nullptr;
    const auto it = object.find(key);
    return it != object.end() ? &*it : nullptr;
}

std::string str_of(const Json& object, const char* key) {
    const Json* v = field(object, key);
    return v != nullptr && v->is_string() ? v->get<std::string>() : "";
}

// _as_xy_ring parity: [x, y] numeric pairs (extras dropped).
std::vector<std::pair<double, double>> xy_ring(const Json& coordinates) {
    std::vector<std::pair<double, double>> out;
    if (!coordinates.is_array()) return out;
    for (const Json& point : coordinates) {
        if (!point.is_array() || point.size() < 2) continue;
        if (!point[0].is_number() || !point[1].is_number()) continue;
        out.emplace_back(point[0].get<double>(), point[1].get<double>());
    }
    return out;
}

void atomic_write_json(const std::filesystem::path& path,
                       const std::string& text) {
    std::filesystem::create_directories(path.parent_path());
    const std::filesystem::path tmp =
        path.parent_path() / (path.filename().string() + ".tmp");
    {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        out.write(text.data(), static_cast<std::streamsize>(text.size()));
        out.flush();
        if (!out.good()) {
            std::error_code cleanup_ec;
            std::filesystem::remove(tmp, cleanup_ec);
            throw std::runtime_error("fault artifact write failed: "
                                     + tmp.string());
        }
    }
#if !defined(_WIN32)
    // WI10: fsync before rename — "atomic" naming without the sync can
    // publish an empty artifact after a crash. Windows rename-replace
    // semantics are documented as unsupported for this helper (POSIX
    // paths only, same as the catalog persistence layer).
    if (FILE* handle = std::fopen(tmp.string().c_str(), "r")) {
        const int fd = fileno(handle);
        if (fd >= 0) (void)::fsync(fd);
        std::fclose(handle);
    }
#endif
    std::error_code rename_ec;
    std::filesystem::rename(tmp, path, rename_ec);
    if (rename_ec) {
        std::error_code cleanup_ec;
        std::filesystem::remove(tmp, cleanup_ec);
        throw std::runtime_error("fault artifact rename failed: "
                                 + rename_ec.message());
    }
}

std::optional<std::string> sha256_file_or_none(
    const std::filesystem::path& file) {
    return domain::Sha256::of_file(file);
}

}  // namespace

Json FaultTrace::to_dict() const {
    Json coordinates = Json::array();
    for (const auto& [x, y] : polyline) {
        coordinates.push_back(Json::array({x, y}));
    }
    Json out = Json::object();
    out["id"] = id;
    out["name"] = name;
    out["polyline"] = std::move(coordinates);
    out["role"] = role;
    out["vertical_domain"] = vertical_domain;
    out["notes"] = notes;
    out["section_picks"] = section_picks.is_array() ? section_picks
                                                    : Json::array();
    out["map_fault_id"] = map_fault_id.has_value()
                              ? Json(*map_fault_id)
                              : Json(nullptr);
    return out;
}

FaultTrace FaultTrace::from_dict(const Json& data) {
    FaultTrace trace;
    trace.id = str_of(data, "id");
    trace.name = str_of(data, "name");
    trace.polyline = xy_ring(*field(data, "polyline") != nullptr
                                 ? *field(data, "polyline")
                                 : Json::array());
    trace.role = str_of(data, "role");
    if (trace.role.empty()) trace.role = "fault";
    trace.vertical_domain = str_of(data, "vertical_domain");
    trace.notes = str_of(data, "notes");
    if (const Json* picks = field(data, "section_picks");
        picks != nullptr && picks->is_array()) {
        trace.section_picks = *picks;
    }
    if (const Json* linked = field(data, "map_fault_id");
        linked != nullptr && linked->is_string()) {
        trace.map_fault_id = linked->get<std::string>();
    }
    return trace;
}

Json FaultInterpretationPayload::scientific_dict() const {
    std::vector<const FaultTrace*> sorted;
    sorted.reserve(this->traces.size());
    for (const FaultTrace& trace : this->traces) sorted.push_back(&trace);
    std::sort(sorted.begin(), sorted.end(),
              [](const FaultTrace* a, const FaultTrace* b) {
                  if (a->name != b->name) return a->name < b->name;
                  return a->id < b->id;
              });
    Json traces = Json::array();
    for (const FaultTrace* trace : sorted) {
        traces.push_back(trace->to_dict());
    }
    Json sources = Json::array();
    for (const std::string& id : source_version_ids) {
        sources.push_back(id);
    }
    Json out = Json::object();
    out["schema_version"] = schema_version;
    out["interpretation_id"] = interpretation_id;
    out["name"] = name;
    out["traces"] = std::move(traces);
    out["source_version_ids"] = std::move(sources);
    out["crs"] = crs;
    out["notes"] = notes;
    return out;
}

Json FaultInterpretationRef::to_dict() const {
    Json sources = Json::array();
    for (const std::string& id : source_version_ids) {
        sources.push_back(id);
    }
    Json out = Json::object();
    out["id"] = id;
    out["name"] = name;
    out["current_version_id"] = current_version_id;
    out["artifact_path"] = artifact_path;
    out["parent_version_id"] = parent_version_id.has_value()
                                   ? Json(*parent_version_id)
                                   : Json(nullptr);
    out["status"] = status;
    out["source_version_ids"] = std::move(sources);
    out["scientific_fingerprint"] = scientific_fingerprint;
    out["crs"] = crs;
    out["display"] = display.is_object() ? display : Json::object();
    return out;
}

FaultInterpretationRef FaultInterpretationRef::from_dict(const Json& data) {
    FaultInterpretationRef ref;
    ref.id = str_of(data, "id");
    ref.name = str_of(data, "name");
    ref.current_version_id = str_of(data, "current_version_id");
    ref.artifact_path = str_of(data, "artifact_path");
    if (const Json* parent = field(data, "parent_version_id");
        parent != nullptr && parent->is_string()) {
        ref.parent_version_id = parent->get<std::string>();
    }
    ref.status = str_of(data, "status");
    if (ref.status.empty()) ref.status = "clean";
    if (const Json* sources = field(data, "source_version_ids");
        sources != nullptr && sources->is_array()) {
        for (const Json& id : *sources) {
            if (id.is_string()) ref.source_version_ids.push_back(
                id.get<std::string>());
        }
    }
    ref.scientific_fingerprint = str_of(data, "scientific_fingerprint");
    ref.crs = str_of(data, "crs");
    if (const Json* shown = field(data, "display");
        shown != nullptr && shown->is_object()) {
        ref.display = *shown;
    }
    return ref;
}

std::string fault_id(const std::string& prefix) {
    return domain::make_id(prefix + "_");
}

FaultInterpretationDraft new_fault_draft(
    const std::string& name, const std::vector<FaultTrace>& traces,
    const std::vector<std::string>& source_version_ids, const std::string& crs,
    const std::optional<std::string>& interpretation_id,
    const std::optional<std::string>& parent_version_id) {
    // WI1: non-finite coordinates cannot round-trip — the fingerprint
    // encodes NaN but the artifact serializes it as null and the restore
    // silently drops the vertex, so a save/reload minted a new "version"
    // with altered geometry. Fail closed at the public entry instead of
    // destroying data downstream.
    for (const FaultTrace& trace : traces) {
        for (const auto& [x, y] : trace.polyline) {
            if (!std::isfinite(x) || !std::isfinite(y)) {
                throw std::invalid_argument(
                    "fault trace '" + trace.id +
                    "' has non-finite coordinates (x=" +
                    std::to_string(x) + ", y=" + std::to_string(y) + ")");
            }
        }
    }
    FaultInterpretationDraft draft;
    draft.interpretation_id = interpretation_id.has_value()
                                  ? *interpretation_id
                                  : fault_id("fault");
    draft.name = name;
    draft.payload.interpretation_id = draft.interpretation_id;
    draft.payload.name = name;
    draft.payload.traces = traces;
    draft.payload.source_version_ids = source_version_ids;
    draft.payload.parent_version_id = parent_version_id;
    draft.payload.crs = crs;
    return draft;
}

FaultInterpretationDraft draft_from_constraint_layers(
    const Json& layers, const std::string& name, const std::string& crs) {
    std::vector<FaultTrace> traces;
    const Json* lines = field(layers, "lines");
    if (lines != nullptr && lines->is_array()) {
        for (const Json& line : *lines) {
            const std::string role = str_of(line, "role");
            if (role != "break" && role != "fault") continue;
            const Json* coordinates = field(line, "coordinates");
            if (coordinates == nullptr) {
                coordinates = field(line, "points");
            }
            std::vector<std::pair<double, double>> poly =
                coordinates != nullptr ? xy_ring(*coordinates)
                                       : std::vector<std::pair<double, double>>{};
            if (poly.size() < 2) continue;
            FaultTrace trace;
            trace.id = fault_id("ftrace");
            trace.name = str_of(line, "name");
            trace.polyline = std::move(poly);
            trace.role = role == "break" ? "break" : "fault";
            traces.push_back(std::move(trace));
        }
    }
    return new_fault_draft(name, traces, {}, crs);
}

std::string draft_fingerprint(const FaultInterpretationDraft& draft) {
    return factor_host::stable_sha256(draft.payload.scientific_dict());
}

std::filesystem::path write_fault_artifact(
    const FaultInterpretationPayload& payload,
    const std::filesystem::path& directory, const std::string& basename,
    const Json& extra_descriptor) {
    const Json scientific = payload.scientific_dict();
    Json body = Json::object();
    body["kind"] = "fault_interpretation";
    body["scientific"] = scientific;
    body["fingerprint"] = factor_host::stable_sha256(scientific);
    body["descriptor"] = extra_descriptor.is_object() ? extra_descriptor
                                                      : Json::object();
    // json.dumps(indent=2, sort_keys=True) — a permissive re-serialization
    // is fine here: the fingerprint (canonical bytes) is the identity.
    const std::filesystem::path path =
        directory / (basename + kFaultArtifactSuffix);
    atomic_write_json(path, body.dump(2) + "\n");
    return path;
}

std::optional<FaultInterpretationPayload> read_fault_artifact(
    const std::filesystem::path& artifact_path, Json* descriptor_out) {
    std::ifstream in(artifact_path, std::ios::binary);
    if (!in.good()) return std::nullopt;
    std::ostringstream buffer;
    buffer << in.rdbuf();
    Json data = Json::parse(buffer.str(), nullptr, false);
    if (data.is_discarded()) return std::nullopt;
    const Json* scientific = field(data, "scientific");
    if (scientific == nullptr || !scientific->is_object()) {
        scientific = &data;
    }
    if (descriptor_out != nullptr) {
        const Json* descriptor = field(data, "descriptor");
        *descriptor_out =
            descriptor != nullptr && descriptor->is_object()
                ? *descriptor
                : Json::object();
    }
    FaultInterpretationPayload payload;
    if (const Json* version = field(*scientific, "schema_version");
        version != nullptr && version->is_number_integer()) {
        payload.schema_version =
            static_cast<int>(version->get<long long>());
    }
    payload.interpretation_id = str_of(*scientific, "interpretation_id");
    payload.name = str_of(*scientific, "name");
    if (const Json* traces = field(*scientific, "traces");
        traces != nullptr && traces->is_array()) {
        for (const Json& trace : *traces) {
            if (trace.is_object()) {
                payload.traces.push_back(FaultTrace::from_dict(trace));
            }
        }
    }
    if (const Json* sources = field(*scientific, "source_version_ids");
        sources != nullptr && sources->is_array()) {
        for (const Json& id : *sources) {
            if (id.is_string()) {
                payload.source_version_ids.push_back(
                    id.get<std::string>());
            }
        }
    }
    if (const Json* parent = field(*scientific, "parent_version_id");
        parent != nullptr && parent->is_string()) {
        payload.parent_version_id = parent->get<std::string>();
    }
    payload.crs = str_of(*scientific, "crs");
    payload.notes = str_of(*scientific, "notes");
    return payload;
}

std::optional<FaultInterpretationDraft> open_fault_draft_from_version(
    const std::filesystem::path& artifact_path,
    const std::optional<std::string>& interpretation_id) {
    auto payload = read_fault_artifact(artifact_path);
    if (!payload.has_value()) return std::nullopt;
    FaultInterpretationDraft draft;
    draft.interpretation_id = interpretation_id.has_value()
                                  ? *interpretation_id
                                  : (!payload->interpretation_id.empty()
                                         ? payload->interpretation_id
                                         : fault_id("fault"));
    payload->interpretation_id = draft.interpretation_id;
    draft.name = payload->name.empty() ? "断层解释" : payload->name;
    draft.payload = std::move(*payload);
    draft.dirty = false;
    draft.last_saved_fingerprint = draft_fingerprint(draft);
    return draft;
}

namespace {

Json& fault_refs_array(Json& project_root) {
    if (!project_root.contains("fault_interpretations")
        || !project_root["fault_interpretations"].is_array()) {
        project_root["fault_interpretations"] = Json::array();
    }
    return project_root["fault_interpretations"];
}

}  // namespace

std::optional<FaultInterpretationRef> find_fault_ref(
    const Json& project_root, const std::string& interpretation_id) {
    const Json* refs = field(project_root, "fault_interpretations");
    if (refs == nullptr || !refs->is_array()) return std::nullopt;
    for (const Json& ref : *refs) {
        if (ref.is_object() && str_of(ref, "id") == interpretation_id) {
            return FaultInterpretationRef::from_dict(ref);
        }
    }
    return std::nullopt;
}

std::pair<std::optional<FaultInterpretationRef>, std::string>
save_fault_draft(FaultInterpretationDraft& draft, Json& project_root,
                 const std::filesystem::path& fault_dir,
                 const std::filesystem::path& project_dir,
                 workflow_runtime::CatalogRepository* catalog,
                 bool force_new_version) {
    const std::string fingerprint = draft_fingerprint(draft);
    const auto existing = find_fault_ref(project_root,
                                         draft.interpretation_id);
    if (!force_new_version && existing.has_value()
        && existing->scientific_fingerprint == fingerprint) {
        draft.dirty = false;
        draft.last_saved_fingerprint = fingerprint;
        return {existing, "noop_unchanged"};
    }
    if (!force_new_version
        && draft.last_saved_fingerprint == fingerprint
        && existing.has_value()) {
        draft.dirty = false;
        return {existing, "noop_unchanged"};
    }

    std::optional<std::string> parent = draft.payload.parent_version_id;
    if (existing.has_value() && !existing->current_version_id.empty()
        && !parent.has_value()) {
        parent = existing->current_version_id;
        draft.payload.parent_version_id = parent;
    }

    const std::string version_token = fault_id("ver");
    const std::filesystem::path artifact = write_fault_artifact(
        draft.payload, fault_dir,
        draft.interpretation_id + "_" + version_token);
    const auto checksum = sha256_file_or_none(artifact);

    // register_fault_interpretation_run parity over the runtime seam.
    std::string version_id = version_token;
    std::string managed_path = artifact.generic_string();
    bool managed_resolved = false;
    if (catalog != nullptr) {
        std::vector<std::string> inputs = draft.payload.source_version_ids;
        if (parent.has_value()
            && std::find(inputs.begin(), inputs.end(), *parent)
                   == inputs.end()) {
            inputs.push_back(*parent);
        }
        Json parameters = Json::object();
        parameters["trace_count"] = draft.payload.traces.size();
        int pick_count = 0;
        int seismic_trace_count = 0;
        int map_linked_trace_count = 0;
        std::set<std::string> vertical_domains;
        for (const FaultTrace& trace : draft.payload.traces) {
            pick_count += static_cast<int>(trace.section_picks.is_array()
                                               ? trace.section_picks.size()
                                               : 0);
            if (trace.section_picks.is_array()
                && !trace.section_picks.empty()) {
                ++seismic_trace_count;
            }
            if (trace.map_fault_id.has_value()) ++map_linked_trace_count;
            if (!trace.vertical_domain.empty()) {
                vertical_domains.insert(trace.vertical_domain);
            }
        }
        parameters["pick_count"] = pick_count;
        parameters["seismic_trace_count"] = seismic_trace_count;
        parameters["map_linked_trace_count"] = map_linked_trace_count;
        Json domains = Json::array();
        for (const std::string& domain : vertical_domains) {
            domains.push_back(domain);
        }
        parameters["vertical_domains"] = std::move(domains);
        parameters["crs"] = draft.payload.crs;
        parameters["scientific_fingerprint"] = fingerprint;
        parameters["parent_version_id"] =
            parent.has_value() ? Json(*parent) : Json(nullptr);
        std::string run_id;
        try {
            run_id = catalog->register_run(
                "fault_interpretation", inputs, parameters, kFaultGenerator,
                "running", draft.interpretation_id, fingerprint);
            Json asset_metadata = Json::object();
            asset_metadata["kind"] = "fault_interpretation";
            Json version_metadata = Json::object();
            version_metadata["scientific_fingerprint"] = fingerprint;
            version_metadata["parent_version_id"] =
                parent.has_value() ? Json(*parent) : Json(nullptr);
            version_metadata["checksum"] = checksum.has_value()
                                               ? Json(*checksum)
                                               : Json(nullptr);
            const auto registered = catalog->register_result_asset(
                draft.name + " fault", "fault_interpretation", "json",
                asset_metadata,
                /*payload_json=*/[&] {
                    std::ifstream in(artifact, std::ios::binary);
                    std::ostringstream buffer;
                    buffer << in.rdbuf();
                    // WI6: a failed re-read would register an EMPTY payload
                    // against the real checksum — a permanent integrity
                    // mismatch. The stream must be healthy and non-empty
                    // (the artifact was just written with bytes).
                    if (in.bad() || buffer.str().empty()) {
                        throw std::runtime_error(
                            "fault artifact re-read failed before "
                            "registration");
                    }
                    return buffer.str();
                }(),
                "derived", run_id, version_metadata);
            version_id = registered.version_id;
            // WI4: resolve INSIDE the guarded block — a throw after the
            // run/asset registration left a "completed" run plus a
            // registered asset while save re-threw, and a retry
            // double-registered both.
            if (const auto version = catalog->resolve_version(version_id);
                version.has_value() && !version->path.empty()) {
                managed_path = version->path;
                managed_resolved = true;
            }
            catalog->update_run_status(run_id, "completed");
        } catch (const std::exception&) {
            // No orphan RUNNING run + no ghost artifact (H7 compensation).
            // WI5: only runs that were actually created can be failed —
            // update_run_status("") itself throws on unknown ids.
            if (!run_id.empty()) {
                try {
                    catalog->update_run_status(run_id, "failed");
                } catch (const std::exception&) {
                }
            }
            std::error_code ignored;
            std::filesystem::remove(artifact, ignored);
            throw;
        }
        if (managed_resolved) {
            // Success-path hygiene: the managed copy is the record — drop
            // the local working duplicate so saves don't accumulate ghosts.
            // Only when resolution confirmed the managed path: the local
            // file is the only copy otherwise.
            std::error_code ignored;
            std::filesystem::remove(artifact, ignored);
        }
    }

    std::string store_path = managed_path;
    {
        const std::filesystem::path resolved =
            std::filesystem::weakly_canonical(managed_path);
        const std::filesystem::path base =
            std::filesystem::weakly_canonical(project_dir);
        std::error_code ignored;
        if (const auto rel =
                std::filesystem::relative(resolved, base, ignored);
            !ignored && !rel.empty() && rel.native().rfind("..", 0) != 0) {
            store_path = rel.generic_string();
        }
    }

    FaultInterpretationRef ref;
    ref.id = draft.interpretation_id;
    ref.name = draft.name;
    ref.current_version_id = version_id;
    ref.artifact_path = store_path;
    ref.parent_version_id = parent;
    ref.status = "clean";
    ref.source_version_ids = draft.payload.source_version_ids;
    ref.scientific_fingerprint = fingerprint;
    ref.crs = draft.payload.crs;
    ref.display = draft.display.is_object() ? draft.display : Json::object();

    Json& refs = fault_refs_array(project_root);
    bool replaced = false;
    for (Json& entry : refs) {
        if (entry.is_object() && str_of(entry, "id") == ref.id) {
            entry = ref.to_dict();
            replaced = true;
            break;
        }
    }
    if (!replaced) refs.push_back(ref.to_dict());

    draft.dirty = false;
    draft.last_saved_fingerprint = fingerprint;
    draft.payload.parent_version_id = version_id;
    return {ref, "ok"};
}

std::optional<FaultInterpretationDraft> restore_fault_draft_from_project(
    const Json& project_root, const std::filesystem::path& project_dir,
    const std::optional<std::string>& interpretation_id) {
    const Json* refs = field(project_root, "fault_interpretations");
    if (refs == nullptr || !refs->is_array() || refs->empty()) {
        return std::nullopt;
    }
    const Json* chosen = nullptr;
    if (interpretation_id.has_value()) {
        for (const Json& ref : *refs) {
            if (ref.is_object()
                && str_of(ref, "id") == *interpretation_id) {
                chosen = &ref;
                break;
            }
        }
    }
    if (chosen == nullptr) chosen = &refs->front();
    const std::string artifact_path = str_of(*chosen, "artifact_path");
    if (artifact_path.empty()) return std::nullopt;
    std::filesystem::path path(artifact_path);
    if (!std::filesystem::is_regular_file(path)) {
        path = project_dir / artifact_path;
    }
    auto draft = open_fault_draft_from_version(
        path, str_of(*chosen, "id").empty()
                  ? std::optional<std::string>()
                  : std::optional<std::string>(str_of(*chosen, "id")));
    if (!draft.has_value()) return std::nullopt;
    const std::string current = str_of(*chosen, "current_version_id");
    if (!current.empty()) {
        draft->payload.parent_version_id = current;
    }
    draft->last_saved_fingerprint =
        str_of(*chosen, "scientific_fingerprint").empty()
            ? draft_fingerprint(*draft)
            : str_of(*chosen, "scientific_fingerprint");
    draft->dirty = false;
    return draft;
}

}  // namespace pwb::workflow_interpretation
