#pragma once

// Fixture IO for the seismic_viewer tests. Reads the FROZEN science oracle
// fixture (tiny_sgy) read-only from the science fixtures tree and the D-line
// fixtures under tests/cpp/seismic_viewer/fixtures. C++-only: flat JSON
// manifest (same vocabulary the science oracle scripts emit) + raw f32.

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#include <pwb/viz/seismic_volume.hpp>

namespace sv_fixture_io {

struct Manifest {
    std::map<std::string, double> numbers;
    std::map<std::string, std::string> strings;
    std::map<std::string, std::vector<double>> arrays;

    [[nodiscard]] double number(const std::string& key, double fallback) const {
        const auto it = numbers.find(key);
        return it == numbers.end() ? fallback : it->second;
    }
};

inline bool parse_manifest(const std::string& text, Manifest& out) {
    std::size_t pos = 0;
    const auto skip_space = [&](void) {
        while (pos < text.size() && (text[pos] == ' ' || text[pos] == '\n' ||
                                     text[pos] == '\r' || text[pos] == '\t')) {
            ++pos;
        }
    };
    skip_space();
    if (pos >= text.size() || text[pos] != '{') {
        return false;
    }
    ++pos;
    skip_space();
    if (pos < text.size() && text[pos] == '}') {
        return true;
    }
    while (pos < text.size()) {
        skip_space();
        if (pos >= text.size() || text[pos] != '"') {
            return false;
        }
        const std::size_t key_start = ++pos;
        while (pos < text.size() && text[pos] != '"') {
            ++pos;
        }
        if (pos >= text.size()) {
            return false;
        }
        const std::string key = text.substr(key_start, pos - key_start);
        ++pos;
        skip_space();
        if (pos >= text.size() || text[pos] != ':') {
            return false;
        }
        ++pos;
        skip_space();
        if (pos < text.size() && text[pos] == '"') {
            const std::size_t value_start = ++pos;
            while (pos < text.size() && text[pos] != '"') {
                ++pos;
            }
            if (pos >= text.size()) {
                return false;
            }
            out.strings[key] = text.substr(value_start, pos - value_start);
            ++pos;
        } else if (pos < text.size() && text[pos] == '[') {
            ++pos;
            std::vector<double> values;
            for (;;) {
                skip_space();
                if (pos < text.size() && text[pos] == ']') {
                    ++pos;
                    break;
                }
                const std::size_t value_start = pos;
                while (pos < text.size() && text[pos] != ',' && text[pos] != ']') {
                    ++pos;
                }
                values.push_back(
                    std::strtod(text.substr(value_start, pos - value_start).c_str(), nullptr));
                skip_space();
                if (pos < text.size() && text[pos] == ',') {
                    ++pos;
                }
            }
            out.arrays[key] = std::move(values);
        } else {
            const std::size_t value_start = pos;
            while (pos < text.size() && text[pos] != ',' && text[pos] != '}') {
                ++pos;
            }
            out.numbers[key] =
                std::strtod(text.substr(value_start, pos - value_start).c_str(), nullptr);
        }
        skip_space();
        if (pos < text.size() && text[pos] == ',') {
            ++pos;
            continue;
        }
        if (pos < text.size() && text[pos] == '}') {
            return true;
        }
        return false;
    }
    return false;
}

inline std::string read_text(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return {};
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

inline std::vector<float> read_f32(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        return {};
    }
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    std::vector<float> data(static_cast<std::size_t>(size / sizeof(float)));
    if (!data.empty()) {
        input.read(reinterpret_cast<char*>(data.data()), size);
    }
    return data;
}

// The frozen science fixture root (tiny_sgy), read-only input.
inline std::filesystem::path science_fixture_root() {
    const char* env = std::getenv("PWB_SEISMIC_VIEWER_SCIENCE_FIXTURES");
    if (env != nullptr && env[0] != '\0') {
        return std::filesystem::path(env);
    }
    return std::filesystem::path("tests/cpp/science/fixtures");
}

// D-line owned fixture root.
inline std::filesystem::path own_fixture_root() {
    const char* env = std::getenv("PWB_SEISMIC_VIEWER_FIXTURES");
    if (env != nullptr && env[0] != '\0') {
        return std::filesystem::path(env);
    }
    return std::filesystem::path("tests/cpp/seismic_viewer/fixtures");
}

// Builds the frozen tiny_sgy volume exactly the way the science slice test
// does (crossline-major permuted strides, real expected planes available).
inline std::shared_ptr<pwb::viz::ISeismicVolume> load_tiny_sgy(
    pwb::viz::VolumeGeometryV1& geometry_out) {
    const std::filesystem::path dir = science_fixture_root() / "seismic" / "tiny_sgy";
    Manifest manifest;
    if (!parse_manifest(read_text(dir / "manifest.json"), manifest)) {
        return nullptr;
    }
    const std::vector<double>& shape = manifest.arrays.at("shape");
    const std::int64_t n_il = static_cast<std::int64_t>(shape[0]);
    const std::int64_t n_xl = static_cast<std::int64_t>(shape[1]);
    const std::int64_t n_t = static_cast<std::int64_t>(shape[2]);
    std::vector<float> payload = read_f32(dir / "volume_xl_major.f32");
    if (payload.size() != static_cast<std::size_t>(n_il * n_xl * n_t)) {
        return nullptr;
    }
    pwb::viz::VolumeGeometryV1 geometry;
    geometry.shape = {n_il, n_xl, n_t};
    geometry.strides = {n_t, n_il * n_t, 1}; // crossline-major (permuted)
    geometry.origin = {manifest.number("iline_start", 1.0),
                       manifest.number("xline_start", 1.0), 0.0};
    geometry.step = {manifest.number("iline_step", 1.0),
                     manifest.number("xline_step", 1.0), manifest.number("dt_ms", 2.0)};
    geometry.unit = "ms";
    auto buffer = std::make_shared<const std::vector<float>>(std::move(payload));
    geometry_out = geometry;
    return pwb::viz::make_in_memory_volume(geometry, buffer->data(), buffer);
}

} // namespace sv_fixture_io
