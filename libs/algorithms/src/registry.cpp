#include <pwb/science/registry.hpp>

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <set>

namespace pwb::science {

namespace {

bool valid_algorithm_id(const std::string& id) {
    if (id.size() < 3 || id.size() > 64) {
        return false;
    }
    bool dot_seen = false;
    for (const char c : id) {
        if (c == '.') {
            if (dot_seen) {
                return false;
            }
            dot_seen = true;
            continue;
        }
        if (std::isdigit(static_cast<unsigned char>(c)) != 0 ||
            std::islower(static_cast<unsigned char>(c)) != 0 || c == '_') {
            continue;
        }
        return false;
    }
    return dot_seen;
}

bool valid_version(const std::string& version) {
    if (version.empty()) {
        return false;
    }
    std::size_t segments = 1;
    for (const char c : version) {
        if (c == '.') {
            ++segments;
            continue;
        }
        if (std::isdigit(static_cast<unsigned char>(c)) == 0) {
            return false;
        }
    }
    return segments <= 4;
}

// Minimal JSON scalar parsing: integers, numbers, booleans, null and quoted
// strings. Enough for parameter values; composite JSON is rejected.
struct Scalar {
    enum class Kind { integer, number, boolean, string, null } kind;
    long long integer{0};
    double number{0.0};
    bool boolean{false};
    std::string str;
};

bool parse_scalar(const std::string& text, Scalar& out) {
    if (text.empty()) {
        return false;
    }
    if (text == "true" || text == "false") {
        out.kind = Scalar::Kind::boolean;
        out.boolean = text == "true";
        return true;
    }
    if (text == "null") {
        out.kind = Scalar::Kind::null;
        return true;
    }
    if (text.front() == '"') {
        if (text.size() < 2 || text.back() != '"') {
            return false;
        }
        out.kind = Scalar::Kind::string;
        out.str = text.substr(1, text.size() - 2);
        return true;
    }
    errno = 0;
    char* end = nullptr;
    const long long as_int = std::strtoll(text.c_str(), &end, 10);
    if (errno == 0 && end != nullptr && *end == '\0') {
        out.kind = Scalar::Kind::integer;
        out.integer = as_int;
        return true;
    }
    errno = 0;
    end = nullptr;
    const double as_double = std::strtod(text.c_str(), &end);
    if (errno == 0 && end != nullptr && *end == '\0') {
        out.kind = Scalar::Kind::number;
        out.number = as_double;
        return true;
    }
    return false;
}

Diagnostic param_error(const std::string& name, const std::string& suffix,
                       const std::string& message) {
    return Diagnostic{"param." + name + "." + suffix, message, "error"};
}

} // namespace

std::vector<std::string> validate_descriptor(const AlgorithmDescriptor& descriptor) {
    std::vector<std::string> problems;
    if (!valid_algorithm_id(descriptor.algorithm_id)) {
        problems.push_back("algorithm_id must be '<domain>.<name>' ([a-z0-9_]+ both sides)");
    }
    if (!valid_version(descriptor.version)) {
        problems.push_back("version must be dotted numeric (max 4 segments)");
    }
    if (descriptor.display_name.empty()) {
        problems.push_back("display_name must not be empty");
    }
    std::set<std::string> port_names;
    for (const PortSpec& port : descriptor.inputs) {
        if (port.name.empty() || !port_names.insert(port.name).second) {
            problems.push_back("input port name empty or duplicated: '" + port.name + "'");
        }
    }
    for (const PortSpec& port : descriptor.outputs) {
        if (port.name.empty() || !port_names.insert(port.name).second) {
            problems.push_back("output port name empty or duplicated: '" + port.name + "'");
        }
    }
    std::set<std::string> param_names;
    for (const ParamSpec& param : descriptor.parameters) {
        if (param.name.empty() || !param_names.insert(param.name).second) {
            problems.push_back("parameter name empty or duplicated: '" + param.name + "'");
        }
    }
    return problems;
}

std::string AlgorithmRegistry::register_algorithm(std::unique_ptr<IAlgorithm> algorithm) {
    if (algorithm == nullptr) {
        return "algorithm is null";
    }
    const std::vector<std::string> problems = validate_descriptor(algorithm->descriptor());
    if (!problems.empty()) {
        return problems.front();
    }
    const std::string id = algorithm->descriptor().algorithm_id;
    std::lock_guard<std::mutex> lock(mutex_);
    if (algorithms_.count(id) != 0) {
        return "duplicate algorithm_id: " + id;
    }
    algorithms_.emplace(id, std::move(algorithm));
    return {};
}

IAlgorithm* AlgorithmRegistry::find(const std::string& algorithm_id) const {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto it = algorithms_.find(algorithm_id);
    return it == algorithms_.end() ? nullptr : it->second.get();
}

std::vector<std::string> AlgorithmRegistry::algorithm_ids() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> ids;
    ids.reserve(algorithms_.size());
    for (const auto& [id, algorithm] : algorithms_) {
        ids.push_back(id);
    }
    return ids;
}

std::vector<Diagnostic> validate_request(const AlgorithmDescriptor& descriptor,
                                         const AlgorithmRequestV1& request) {
    std::vector<Diagnostic> diagnostics;
    const auto reject = [&diagnostics](const std::string& code, const std::string& message) {
        diagnostics.push_back(Diagnostic{code, message, "error"});
    };

    if (request.algorithm_id != descriptor.algorithm_id) {
        reject("request.algorithm_id.mismatch",
               "expected '" + descriptor.algorithm_id + "' got '" + request.algorithm_id + "'");
        return diagnostics;
    }
    if (request.algorithm_version != descriptor.version) {
        reject("request.algorithm_version.mismatch",
               "expected '" + descriptor.version + "' got '" + request.algorithm_version + "'");
        return diagnostics;
    }

    std::size_t required_volumes = 0;
    std::size_t total_volume_ports = 0;
    for (const PortSpec& port : descriptor.inputs) {
        if (port.kind == PortKind::volume_f32) {
            ++total_volume_ports;
            if (port.required) {
                ++required_volumes;
            }
        }
    }
    if (request.input_volumes.size() < required_volumes ||
        request.input_volumes.size() > total_volume_ports) {
        reject("request.input_volumes.count",
               "expected between " + std::to_string(required_volumes) + " and " +
                   std::to_string(total_volume_ports) + " volumes, got " +
                   std::to_string(request.input_volumes.size()));
        return diagnostics;
    }
    for (std::size_t i = 0; i < request.input_volumes.size(); ++i) {
        const VolumeView& volume = request.input_volumes[i];
        if (volume.data == nullptr || volume.shape[0] <= 0 || volume.shape[1] <= 0 ||
            volume.shape[2] <= 0) {
            reject("request.input_volumes.invalid",
                   "input volume " + std::to_string(i) + " is null or has a zero dimension");
        }
    }

    for (const ParamSpec& spec : descriptor.parameters) {
        const auto it = request.params_json.find(spec.name);
        const std::string& text = it == request.params_json.end() ? spec.default_json : it->second;
        if (text.empty()) {
            if (it != request.params_json.end() || spec.default_json.empty()) {
                // Present-but-empty or no default at all.
                if (spec.default_json.empty()) {
                    reject(param_error(spec.name, "missing", "no value and no default").code,
                           "parameter '" + spec.name + "' has no value and no default");
                }
            }
            continue;
        }
        Scalar scalar;
        if (!parse_scalar(text, scalar)) {
            reject(param_error(spec.name, "invalid_json", "not a JSON scalar").code,
                   "parameter '" + spec.name + "' value '" + text + "' is not a JSON scalar");
            continue;
        }
        const bool kind_ok = [kind = scalar.kind, type = spec.type,
                              number = scalar.number]() {
            switch (type) {
            case ParamSpec::Type::integer:
                // Pydantic-lax parity: an integral double ("5.0") is a
                // valid integer; a fractional one is not.
                return kind == Scalar::Kind::integer ||
                       (kind == Scalar::Kind::number &&
                        std::trunc(number) == number);
            case ParamSpec::Type::number:
                return kind == Scalar::Kind::integer || kind == Scalar::Kind::number;
            case ParamSpec::Type::boolean:
                return kind == Scalar::Kind::boolean;
            case ParamSpec::Type::string:
                return kind == Scalar::Kind::string;
            }
            return false;
        }();
        if (!kind_ok) {
            reject(param_error(spec.name, "wrong_type", "unexpected JSON type").code,
                   "parameter '" + spec.name + "' has the wrong JSON type");
            continue;
        }
        if (spec.type == ParamSpec::Type::integer || spec.type == ParamSpec::Type::number) {
            const double value = scalar.kind == Scalar::Kind::integer
                                     ? static_cast<double>(scalar.integer)
                                     : scalar.number;
            if (value < spec.minimum) {
                reject(param_error(spec.name, "out_of_range", "below minimum").code,
                       "parameter '" + spec.name + "' value below minimum " +
                           std::to_string(spec.minimum));
            } else if (spec.maximum > spec.minimum && value > spec.maximum) {
                reject(param_error(spec.name, "out_of_range", "above maximum").code,
                       "parameter '" + spec.name + "' value above maximum " +
                           std::to_string(spec.maximum));
            }
        }
    }
    return diagnostics;
}

Result<long long> request_param_integer(const AlgorithmRequestV1& request, const ParamSpec& spec) {
    const auto it = request.params_json.find(spec.name);
    const std::string& text = it == request.params_json.end() ? spec.default_json : it->second;
    Scalar scalar;
    if (!parse_scalar(text, scalar)) {
        return AlgorithmError{{param_error(spec.name, "not_integer", "expected JSON integer")}};
    }
    if (scalar.kind == Scalar::Kind::integer) return scalar.integer;
    if (scalar.kind == Scalar::Kind::number &&
        std::trunc(scalar.number) == scalar.number) {
        return static_cast<long long>(scalar.number);
    }
    return AlgorithmError{{param_error(spec.name, "not_integer", "expected JSON integer")}};
}

Result<double> request_param_number(const AlgorithmRequestV1& request, const ParamSpec& spec) {
    const auto it = request.params_json.find(spec.name);
    const std::string& text = it == request.params_json.end() ? spec.default_json : it->second;
    Scalar scalar;
    if (!parse_scalar(text, scalar) ||
        (scalar.kind != Scalar::Kind::integer && scalar.kind != Scalar::Kind::number)) {
        return AlgorithmError{{param_error(spec.name, "not_number", "expected JSON number")}};
    }
    return scalar.kind == Scalar::Kind::integer ? static_cast<double>(scalar.integer)
                                                : scalar.number;
}

} // namespace pwb::science
