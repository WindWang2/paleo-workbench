#pragma once

// pwb::science core contract types (interface handshake v1, frozen in
// docs/development/cpp-science/02-contracts.md). Qt-free, Python-free,
// QGIS-free: no include below may pull QWidget/Python/QGIS headers.

#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace pwb::science {

// ---------------------------------------------------------------------------
// Descriptor vocabulary
// ---------------------------------------------------------------------------

enum class PortKind : std::uint8_t {
    volume_f32, // 3-D float32 seismic-style volume (inline, crossline, sample)
    grid_f32,   // 2-D float32 grid
    well_log,   // well log document handle
    table,      // tabular data handle
    path,       // filesystem path (workspace-relative)
    artifact,   // opaque persisted artifact handle
};

struct PortSpec {
    std::string name;
    PortKind kind{PortKind::volume_f32};
    std::string unit; // SI unit or "" when unitless
    bool required{true};
};

struct ParamSpec {
    enum class Type : std::uint8_t { integer, number, boolean, string };
    std::string name;
    Type type{Type::integer};
    std::string unit;
    double minimum{0}; // inclusive; only meaningful for integer/number
    double maximum{0}; // inclusive; 0 = unbounded when minimum <= 0
    std::string default_json; // JSON literal ("" = no default)
};

struct AlgorithmDescriptor {
    std::string algorithm_id; // "<domain>.<name>", e.g. "seismic.coherence_c3"
    std::string version;      // semantic version; numeric-result changes must bump
    std::string display_name;
    std::string family;       // aligns with Python ProviderFamily vocabulary
    std::vector<PortSpec> inputs;
    std::vector<PortSpec> outputs;
    std::vector<ParamSpec> parameters;
    bool supports_cancel{false};
    bool deterministic{true};
    bool approximate{false};  // power-iteration and similar methods must set this
    std::string build_identity; // git sha / build tag, copied into provenance
};

// ---------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------

// Immutable identity of one catalog data version (mirrors the semantics of
// B's DataVersionRef; C never opens the catalog itself).
struct VersionRef {
    std::string asset_id;
    std::string version_id;
    std::string path; // optional data location resolved by the host
};

// Non-owning view over one float32 volume plus a lifetime guard. Callers must
// keep `lifetime` alive for the whole asynchronous execution; algorithms must
// not retain the view beyond run().
struct VolumeView {
    const float* data{nullptr};
    std::array<std::int64_t, 3> shape{0, 0, 0};   // (n_inline, n_crossline, n_sample)
    std::array<std::int64_t, 3> strides{0, 0, 0}; // element strides; {0,0,0} => packed C-order
    std::shared_ptr<const void> lifetime;         // keeps backing storage alive

    [[nodiscard]] std::int64_t size() const noexcept {
        return shape[0] * shape[1] * shape[2];
    }
    [[nodiscard]] bool is_packed() const noexcept {
        return strides[2] == 1 && strides[1] == shape[2] && strides[0] == shape[1] * shape[2];
    }
    [[nodiscard]] std::array<std::int64_t, 3> effective_strides() const noexcept {
        if (strides[0] != 0 || strides[1] != 0 || strides[2] != 0) {
            return strides;
        }
        return {shape[1] * shape[2], shape[2], 1};
    }
};

struct AlgorithmRequestV1 {
    std::string request_id;     // idempotency key; empty => runtime generates
    std::string algorithm_id;
    std::string algorithm_version;
    std::map<std::string, std::string> params_json; // JSON-encoded values
    std::vector<VersionRef> input_refs;
    std::vector<VolumeView> input_volumes;          // descriptor input order
};

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

struct Diagnostic {
    std::string code;     // stable machine code, e.g. "param.win_il.not_positive"
    std::string message;  // human-readable detail
    std::string severity; // "error" | "warning" | "info"
};

struct ProducedVolume {
    std::string name;
    VolumeView volume;
    std::string unit;
};

struct ProvenanceRecord {
    std::string algorithm_id;
    std::string algorithm_version;
    std::string build_identity;
    std::map<std::string, std::string> params_json;
    std::vector<VersionRef> input_refs;
    std::string started_utc;  // ISO-8601
    std::string finished_utc; // ISO-8601
    bool approximate{false};
    std::uint64_t wall_time_ms{0};
};

struct AlgorithmResultV1 {
    std::string request_id;
    std::vector<ProducedVolume> outputs;
    ProvenanceRecord provenance;
    std::vector<Diagnostic> diagnostics;
};

// ---------------------------------------------------------------------------
// Progress
// ---------------------------------------------------------------------------

struct ProgressReport {
    double fraction{0.0}; // [0, 1], weakly monotonic
    std::string stage;    // free-form stage label
};

} // namespace pwb::science
