#pragma once

// pwb::science_service — result envelope (CONV-28): the interchange unit the
// science service layer hands to publishers / the workflow line.
//
// Every service result — factor grid, layer products, curve operation, log
// match, fusion, geomodel build/section/export — is wrapped in one envelope
// carrying the interchange fields the Workflow branch needs to register node
// adapters without talking to science internals:
//   schema_version / result_type / units / crs / extent / quality /
//   provenance / fingerprint / payload / diagnostics.
//
// Contract rules (frozen with the service oracle):
//   * units/crs are ""-able and NEVER guessed: an undeclared unit stays "",
//     an undeclared CRS stays "" (JSON null). Kernels already follow this
//     (crs_policy three-state, unit whitelists); the envelope preserves it.
//   * `fingerprint` is the SHA-256 of the canonical JSON encoding of
//     `payload` ONLY (pwb::factor_host::stable_sha256 / canonical_encode —
//     byte-identical to Python json.dumps(sort_keys=True)). Timestamps and
//     other run-varying provenance fields are outside the fingerprint, so
//     identical scientific inputs -> identical fingerprints, run-to-run and
//     host-to-host.
//   * `payload` carries only deterministic content; `provenance` carries
//     algorithm identity, params, input refs, generator version and the
//     started/finished timestamps.
// Qt-free, Python-free.

#include <pwb/domain/json.hpp>

#include <array>
#include <optional>
#include <string>

namespace pwb::science_service {

using pwb::domain::Json;

inline constexpr int kEnvelopeSchemaVersion = 1;

struct ScienceEnvelope {
    int schema_version = kEnvelopeSchemaVersion;
    // "factor_grid" | "factor_layer_products" | "facies_surface" |
    // "curve_operation" | "log_match" | "factor_fusion" |
    // "geomodel_build" | "geomodel_section" | "geomodel_export"
    std::string result_type;
    std::string units;  // "" = undeclared/unitless
    std::string crs;    // "" = undeclared (never silently EPSG:4326)
    // [minx, miny, maxx, maxy] when the product is spatial; nullopt else.
    std::optional<std::array<double, 4>> extent;
    Json quality = Json::object();     // metrics dict (GridStatistics etc.)
    Json provenance = Json::object();  // identity/params/inputs/timestamps
    std::string fingerprint;           // sha256 over canonical payload
    Json payload = Json::object();     // the deterministic product content
    Json diagnostics = Json::array();  // non-fatal warnings (info/warning)

    // Fixed key order, strict-JSON-safe encoding of non-finite numbers
    // (payload itself is expected to be finite-or-null already; any stray
    // non-finite double serializes as null to stay allow_nan=False safe).
    [[nodiscard]] Json to_json() const;
    // Round-trip; throws std::invalid_argument on a foreign shape.
    [[nodiscard]] static ScienceEnvelope from_json(const Json& data);

    // Compute and set `fingerprint` from the current payload (factor_host
    // canonical encoding). Returns the fingerprint.
    [[nodiscard]] std::string compute_fingerprint() const;
};

// Serialize with Python-compatible formatting
// (pwb::domain::dump_json_python_compatible).
[[nodiscard]] std::string dump_envelope(const ScienceEnvelope& envelope);

}  // namespace pwb::science_service
