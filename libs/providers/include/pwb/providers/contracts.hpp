// Capability provider contracts — C++ port of paleo_workbench/providers/contracts.py.
//
// A *capability provider* is the sanctioned extension unit of the workbench
// (ADR 0055 track P.REG): descriptors are data, inputs are typed refs,
// outputs are ProviderResult envelopes. Qt-free, Python-free; Json is
// pwb::domain::Json (nlohmann ordered_json) so key order matches the Python
// dicts exactly.
#pragma once

#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <vector>

namespace pwb::providers {

using Json = pwb::domain::Json;

enum class ProviderFamily {
    Interpolation,
    SeismicAttribute,
    Inference,
    Visualization,
    Exporter,
    Importer,
    DataFormat,
    Preview,
    MapComponent,
};

std::string to_string(ProviderFamily family);
// nullopt for unknown vocabulary (the C++ enum makes an "invalid family"
// descriptor unrepresentable at compile time; this parse is for JSON I/O).
std::optional<ProviderFamily> family_from_string(std::string_view value);

// Typed reference vocabulary: the names usable in input_types/output_types.
// Sorted, matching the Python `sorted(TYPED_REFS)` used in validation
// messages.
const std::vector<std::string>& typed_refs();

struct ResourceProfile {
    double estimated_cpu_cores = 1.0;
    long long estimated_ram_bytes = 0;
    long long estimated_vram_bytes = 0;
    double io_weight = 1.0;
    std::string category = "background.compute";  // TaskCategory value

    Json to_json() const;
};

struct ProviderDescriptor {
    std::string provider_id;
    ProviderFamily family = ProviderFamily::Interpolation;
    std::string version;
    std::string display_name;
    std::string description;
    std::vector<std::string> capabilities;
    std::vector<std::string> input_types;
    std::vector<std::string> output_types;
    Json parameters_schema = Json::object();
    ResourceProfile resource_profile;
    bool supports_cancel = false;
    bool supports_resume = false;
    bool deterministic = true;
    std::string threading_model = "worker_thread";  // worker_thread|gui_thread|any
    // Harness 2.0: optional build identity (git sha, native lib build tag…)
    // recorded in receipts alongside `version`.
    std::optional<std::string> build_identity;

    Json to_json() const;  // Python to_dict() parity (key order included)
};

// Structural validation; returns problems (empty = valid). Message strings
// and problem order are byte-identical to the Python oracle. The two Python
// checks unrepresentable in C++ (family not a ProviderFamily, non-string
// build_identity) are compile-time guarantees here and never emitted.
std::vector<std::string> validate_descriptor(const ProviderDescriptor& descriptor);

// Throws InvalidProviderError when validate_descriptor reports problems.
void assert_valid_descriptor(const ProviderDescriptor& descriptor);

}  // namespace pwb::providers
