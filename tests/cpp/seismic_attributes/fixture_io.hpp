#pragma once

// Fixture IO for the seismic-attribute oracle tests: raw float32 payloads
// written by oracle/generate_attribute_fixtures.py. The frozen case table
// (shape/params/tolerances) lives in attribute_kernels_test.cpp and mirrors
// the per-case manifest.json files, which remain the audit artifacts.

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace fixture_io {

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

inline std::filesystem::path fixture_root() {
    const char* env = std::getenv("PWB_SEISMIC_ATTRIBUTES_FIXTURE_ROOT");
    if (env != nullptr && env[0] != '\0') {
        return std::filesystem::path(env);
    }
    return std::filesystem::path("tests/cpp/seismic_attributes/fixtures");
}

} // namespace fixture_io
