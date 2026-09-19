// revision.cpp — C++ port of
// paleo_workbench/workflow/interpretation/revision.py (CONV-32, ADR-8).
// Implements the frozen include/pwb/workflow_interpretation/revision.hpp
// contract: human-edit provenance chains per layer + layer content
// fingerprints (sha256 over Python json.dumps with DEFAULT separators
// ", " / ": " — NOT the compact form — over 9dp-stabilized geometry).
//
// Seam mapping (Python duck-typed layers -> Json views):
//   document.interpretation_revisions   -> array of revision dicts (mutated)
//   document.integrated_interpretations -> array of interpretation records
//   layer                               -> {"features": [feature, …]}
//   feature                             -> {"feature_id"?, "id",
//                                           "geometry", "attributes"?}
// (UserVectorFeature carries no "attributes" key — Python's
// getattr(feature, "attributes", None) or {} then yields {}.)

#include <pwb/workflow_interpretation/revision.hpp>

#include <pwb/domain/sha256.hpp>
#include <pwb/factor_host/canonical_json.hpp>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace pwb::workflow_interpretation {
namespace {

// ---- local Python-parity helpers -------------------------------------------

bool truthy(const Json& value) {
    switch (value.type()) {
    case Json::value_t::null: return false;
    case Json::value_t::boolean: return value.get<bool>();
    case Json::value_t::number_integer:
        return value.get<std::int64_t>() != 0;
    case Json::value_t::number_unsigned:
        return value.get<std::uint64_t>() != 0;
    case Json::value_t::number_float:
        return value.get<double>() != 0.0;
    case Json::value_t::string:
        return !value.get_ref<const std::string&>().empty();
    case Json::value_t::array: return !value.empty();
    case Json::value_t::object: return !value.empty();
    default: return false;
    }
}

// str(x) for scalars (null -> "None" — array elements are str()'d directly,
// unlike the `x or ""` fields where null never survives the or).
std::string str_scalar(const Json& value) {
    if (value.is_string()) return value.get<std::string>();
    if (value.is_null()) return "None";
    return pwb::factor_host::python_str_scalar(value);
}

// str(x or "") — truthy scalar -> str(), falsy/missing -> "".
std::string str_or(const Json& obj, const char* key) {
    if (!obj.is_object() || !obj.contains(key)) return "";
    const Json& value = obj.at(key);
    if (!truthy(value)) return "";
    return pwb::factor_host::python_str_scalar(value);
}

// Python round(x, 9): correctly-rounded decimal rounding of the binary
// double (glibc printf is correctly rounded, matching CPython's dtoa).
double round9(double value) {
    if (!std::isfinite(value)) return value;
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.9f", value);
    return std::strtod(buf, nullptr);
}

// ---- Python json.dumps(payload, sort_keys=True, ensure_ascii=False) with
// DEFAULT separators (", " items, ": " keys) — nlohmann dump() is compact
// and NOT equivalent. Floats use Python repr (shortest round-trip); ints
// stay ints.

void append_escaped_string(std::string& out, const std::string& text) {
    out += '"';
    for (unsigned char c : text) {
        switch (c) {
        case '"': out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\b': out += "\\b"; break;
        case '\f': out += "\\f"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (c < 0x20) {
                char buf[8];
                std::snprintf(buf, sizeof buf, "\\u%04x", c);
                out += buf;
            } else {
                out += static_cast<char>(c);
            }
        }
    }
    out += '"';
}

void dump_python_default_separators(std::string& out, const Json& value) {
    if (value.is_null()) {
        out += "null";
    } else if (value.is_boolean()) {
        out += value.get<bool>() ? "true" : "false";
    } else if (value.is_number_integer()) {
        out += std::to_string(value.get<std::int64_t>());
    } else if (value.is_number_float()) {
        out += pwb::factor_host::python_repr_double(value.get<double>());
    } else if (value.is_string()) {
        append_escaped_string(out, value.get<std::string>());
    } else if (value.is_array()) {
        out += '[';
        bool first = true;
        for (const Json& item : value) {
            if (!first) out += ", ";
            first = false;
            dump_python_default_separators(out, item);
        }
        out += ']';
    } else if (value.is_object()) {
        std::vector<std::string> keys;
        keys.reserve(value.size());
        for (auto it = value.begin(); it != value.end(); ++it) {
            keys.push_back(it.key());
        }
        std::sort(keys.begin(), keys.end());  // UTF-8 byte order == code point
        out += '{';
        bool first = true;
        for (const std::string& key : keys) {
            if (!first) out += ", ";
            first = false;
            append_escaped_string(out, key);
            out += ": ";
            dump_python_default_separators(out, value.at(key));
        }
        out += '}';
    }
}

// ---- fingerprint stabilization ----------------------------------------------

// _stab: numbers (bool included — Python bool is an int) -> round 9dp float;
// lists -> mapped; everything else verbatim.
Json stabilized(const Json& node) {
    if (node.is_number()) return Json(round9(node.get<double>()));
    if (node.is_boolean()) {
        return Json(round9(node.get<bool>() ? 1.0 : 0.0));
    }
    if (node.is_array()) {
        Json out = Json::array();
        for (const Json& item : node) out.push_back(stabilized(item));
        return out;
    }
    return node;
}

// Python isinstance(v, (int, float)) — True for bools.
bool python_numeric(const Json& value) {
    return value.is_number() || value.is_boolean();
}

// _count_vertices over the RAW geometry tree (NOT the stabilized copy):
// dict values recursed; 2-element all-numeric arrays counted (and not
// descended into); longer/other arrays recursed.
void count_vertices(const Json& node, long& count) {
    if (node.is_object()) {
        for (auto it = node.begin(); it != node.end(); ++it) {
            count_vertices(it.value(), count);
        }
    } else if (node.is_array()) {
        if (node.size() == 2 && python_numeric(node.at(0)) &&
            python_numeric(node.at(1))) {
            ++count;
        } else {
            for (const Json& item : node) count_vertices(item, count);
        }
    }
}

// str(getattr(feature, "feature_id", "") or getattr(feature, "id", "") or "")
std::string feature_id_or_id(const Json& feature) {
    std::string id = str_or(feature, "feature_id");
    if (!id.empty()) return id;
    return str_or(feature, "id");
}

// int(prev_counts.get(k, 0)) — deltas are written by this module (ints);
// non-numeric values coerce to 0 (tolerant; Python would raise).
long long int_or_zero(const Json& delta, const char* key) {
    if (!delta.is_object() || !delta.contains(key)) return 0;
    const Json& value = delta.at(key);
    if (value.is_number_integer()) return value.get<std::int64_t>();
    if (value.is_number_unsigned()) {
        return static_cast<long long>(value.get<std::uint64_t>());
    }
    if (value.is_number_float()) {
        return static_cast<long long>(value.get<double>());  // trunc toward 0
    }
    if (value.is_boolean()) return value.get<bool>() ? 1 : 0;
    return 0;
}

}  // namespace

Json InterpretationRevision::to_dict() const {
    Json out = Json::object();
    out["revision_id"] = revision_id;
    out["target_kind"] = target_kind;
    out["target_layer_id"] = target_layer_id;
    out["interpretation_id"] = interpretation_id;
    out["parent_revision_id"] = parent_revision_id;
    out["base_kind"] = base_kind;
    out["base_version_id"] = base_version_id;
    Json refs = Json::array();
    for (const std::string& ref : evidence_refs) refs.push_back(ref);
    out["evidence_refs"] = std::move(refs);
    out["actor"] = actor;
    out["created_at"] = created_at;
    out["content_fingerprint"] = content_fingerprint;
    out["delta"] = delta;
    out["note"] = note;
    return out;
}

InterpretationRevision InterpretationRevision::from_dict(const Json& data) {
    InterpretationRevision out;
    out.revision_id = str_or(data, "revision_id");
    out.target_kind = str_or(data, "target_kind");
    out.target_layer_id = str_or(data, "target_layer_id");
    out.interpretation_id = str_or(data, "interpretation_id");
    out.parent_revision_id = str_or(data, "parent_revision_id");
    out.base_kind = str_or(data, "base_kind");
    if (out.base_kind.empty()) out.base_kind = BASE_MANUAL;
    out.base_version_id = str_or(data, "base_version_id");
    if (data.is_object() && data.contains("evidence_refs") &&
        data.at("evidence_refs").is_array()) {
        for (const Json& ref : data.at("evidence_refs")) {
            out.evidence_refs.push_back(str_scalar(ref));
        }
    }
    out.actor = str_or(data, "actor");
    out.created_at = str_or(data, "created_at");
    out.content_fingerprint = str_or(data, "content_fingerprint");
    out.delta = (data.is_object() && data.contains("delta") &&
                 data.at("delta").is_object())
                    ? data.at("delta")
                    : Json::object();
    out.note = str_or(data, "note");
    return out;
}

LayerFingerprint layer_content_fingerprint(const Json& layer) {
    LayerFingerprint out;  // {"features": 0, "vertices": 0}

    Json payload = Json::array();
    if (layer.is_object() && layer.contains("features") &&
        layer.at("features").is_array()) {
        for (const Json& feature : layer.at("features")) {
            ++out.features;
            Json geometry = Json::object();
            if (feature.is_object() && feature.contains("geometry") &&
                !feature.at("geometry").is_null()) {
                geometry = feature.at("geometry");
            }
            count_vertices(geometry, out.vertices);

            Json attributes = Json::object();
            if (feature.is_object() && feature.contains("attributes") &&
                feature.at("attributes").is_object()) {
                attributes = feature.at("attributes");
            }
            Json stabilized_attributes = Json::object();
            for (auto it = attributes.begin(); it != attributes.end(); ++it) {
                stabilized_attributes[it.key()] = stabilized(it.value());
            }

            Json entry = Json::object();
            entry["id"] = feature_id_or_id(feature);
            entry["geometry"] = stabilized(geometry);
            entry["attributes"] = std::move(stabilized_attributes);
            payload.push_back(std::move(entry));
        }
    }

    std::string encoded;
    dump_python_default_separators(encoded, payload);
    out.digest = pwb::domain::Sha256::of_bytes(encoded);
    return out;
}

RevisionIdGen default_revision_id_gen() {
    // "irev_" + 12 lowercase hex — uuid4 slice parity is opaque (injectable
    // for deterministic tests).
    auto rng = std::make_shared<std::mt19937_64>(std::random_device{}());
    return [rng = std::move(rng)]() {
        static constexpr char kHex[] = "0123456789abcdef";
        std::uniform_int_distribution<int> nibble(0, 15);
        std::string id = "irev_";
        for (int i = 0; i < 12; ++i) id += kHex[nibble(*rng)];
        return id;
    };
}

std::optional<InterpretationRevision> record_interpretation_revision(
    Json& document, const std::string& target_kind,
    const std::string& target_layer_id, const Json& layer,
    const std::string& actor, const std::string& now,
    const std::string& interpretation_id, const std::string& base_kind,
    const std::string& base_version_id,
    const std::vector<std::string>& evidence_refs, const std::string& note,
    const RevisionIdGen& id_gen) {
    const std::optional<InterpretationRevision> previous =
        latest_revision_for_layer(document, target_layer_id);
    const LayerFingerprint fingerprint = layer_content_fingerprint(layer);
    if (previous.has_value() &&
        previous->content_fingerprint == fingerprint.digest) {
        return std::nullopt;  // explicit save, unchanged content — no revision
    }

    Json delta = Json::object();
    if (previous.has_value()) {
        const Json& prev_delta = previous->delta;
        delta["features"] =
            fingerprint.features - int_or_zero(prev_delta, "features");
        delta["vertices"] =
            fingerprint.vertices - int_or_zero(prev_delta, "vertices");
    } else {
        delta["features"] = fingerprint.features;
        delta["vertices"] = fingerprint.vertices;
    }

    InterpretationRevision revision;
    revision.revision_id = id_gen ? id_gen() : default_revision_id_gen()();
    revision.target_kind = target_kind;
    revision.target_layer_id = target_layer_id;
    revision.interpretation_id = interpretation_id;
    revision.parent_revision_id =
        previous.has_value() ? previous->revision_id : "";
    revision.base_kind = base_kind;
    revision.base_version_id = base_version_id;
    revision.evidence_refs = evidence_refs;
    revision.actor = actor;
    revision.created_at = now;
    revision.content_fingerprint = fingerprint.digest;
    revision.delta = std::move(delta);
    revision.note = note;

    if (!document.is_object()) {
        document = Json::object();
    }
    if (!document.contains("interpretation_revisions") ||
        !document.at("interpretation_revisions").is_array()) {
        document["interpretation_revisions"] = Json::array();
    }
    document.at("interpretation_revisions").push_back(revision.to_dict());

    // Domain link: revisions of integrated targets (or with an explicit
    // interpretation id) attach to the matching interpretation record —
    // failures swallowed (the revision itself is not blocked).
    if (!interpretation_id.empty() ||
        target_kind == TARGET_INTEGRATED_FACIES ||
        target_kind == TARGET_INTEGRATED_BOUNDARY) {
        try {
            if (document.contains("integrated_interpretations") &&
                document.at("integrated_interpretations").is_array()) {
                for (Json& record :
                     document.at("integrated_interpretations")) {
                    if (!record.is_object()) continue;
                    if (!truthy(record.contains("interpretation_id")
                                    ? record.at("interpretation_id")
                                    : Json(nullptr))) {
                        continue;
                    }
                    if (str_or(record, "layer_id") != target_layer_id) {
                        continue;
                    }
                    if (!record.contains("revision_ids") ||
                        !record.at("revision_ids").is_array()) {
                        record["revision_ids"] = Json::array();
                    }
                    Json& ids = record.at("revision_ids");
                    const std::string& revision_id = revision.revision_id;
                    const auto found = std::find_if(
                        ids.begin(), ids.end(),
                        [&revision_id](const Json& existing) {
                            return existing == Json(revision_id);
                        });
                    if (found == ids.end()) {
                        ids.push_back(revision_id);
                    }
                }
            }
        } catch (...) {  // noqa — link failure never blocks the revision
        }
    }
    return revision;
}

std::vector<InterpretationRevision> revisions_for_layer(
    const Json& document, const std::string& layer_id) {
    std::vector<InterpretationRevision> out;
    if (!document.is_object() || !document.contains("interpretation_revisions") ||
        !document.at("interpretation_revisions").is_array()) {
        return out;
    }
    for (const Json& entry : document.at("interpretation_revisions")) {
        if (!entry.is_object()) continue;
        if (str_or(entry, "target_layer_id") == layer_id) {
            out.push_back(InterpretationRevision::from_dict(entry));
        }
    }
    return out;
}

std::optional<InterpretationRevision> latest_revision_for_layer(
    const Json& document, const std::string& layer_id) {
    const std::vector<InterpretationRevision> chain =
        revisions_for_layer(document, layer_id);
    if (chain.empty()) return std::nullopt;
    return chain.back();
}

Json revision_summary(const Json& document, const std::string& layer_id) {
    const std::vector<InterpretationRevision> chain =
        revisions_for_layer(document, layer_id);
    Json out = Json::object();
    out["layer_id"] = layer_id;
    if (chain.empty()) {
        out["revisions"] = 0;
        out["detail"] = "无修订记录（未保存或旧工程）";
        return out;
    }
    const InterpretationRevision& last = chain.back();
    out["revisions"] = static_cast<std::int64_t>(chain.size());
    out["first_revision_id"] = chain.front().revision_id;
    out["latest_revision_id"] = last.revision_id;
    out["latest_actor"] = last.actor;
    out["latest_created_at"] = last.created_at;
    out["base_kind"] = last.base_kind;
    out["base_version_id"] = last.base_version_id;
    Json refs = Json::array();
    for (const std::string& ref : last.evidence_refs) refs.push_back(ref);
    out["evidence_refs"] = std::move(refs);
    out["delta"] = last.delta;
    return out;
}

}  // namespace pwb::workflow_interpretation
