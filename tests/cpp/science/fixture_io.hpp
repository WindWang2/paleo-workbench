#pragma once

// Frozen-fixture IO for the oracle tests: reads the flat JSON manifests and
// raw float32 payloads written by tests/cpp/science/oracle/*.py. The manifest
// vocabulary is fixture-internal (controlled by the oracle scripts), so this
// parser only supports what those scripts emit: flat objects of numbers,
// strings and one number array ("shape").

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace fixture_io {

struct Manifest {
    std::map<std::string, double> numbers;
    std::map<std::string, std::string> strings;
    std::map<std::string, std::vector<double>> arrays;

    [[nodiscard]] double number(const std::string& key, double fallback) const {
        const auto it = numbers.find(key);
        return it == numbers.end() ? fallback : it->second;
    }
};

inline void skip_space(const std::string& text, std::size_t& pos) {
    while (pos < text.size() &&
           (text[pos] == ' ' || text[pos] == '\n' || text[pos] == '\r' ||
            text[pos] == '\t')) {
        ++pos;
    }
}

inline bool parse_manifest(const std::string& text, Manifest& out) {
    std::size_t pos = 0;
    skip_space(text, pos);
    if (pos >= text.size() || text[pos] != '{') {
        return false;
    }
    ++pos;
    skip_space(text, pos);
    if (pos < text.size() && text[pos] == '}') {
        return true;
    }
    while (pos < text.size()) {
        skip_space(text, pos);
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
        skip_space(text, pos);
        if (pos >= text.size() || text[pos] != ':') {
            return false;
        }
        ++pos;
        skip_space(text, pos);
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
                skip_space(text, pos);
                if (pos < text.size() && text[pos] == ']') {
                    ++pos;
                    break;
                }
                const std::size_t value_start = pos;
                while (pos < text.size() && text[pos] != ',' && text[pos] != ']') {
                    ++pos;
                }
                values.push_back(std::strtod(text.substr(value_start, pos - value_start).c_str(),
                                             nullptr));
                skip_space(text, pos);
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
        skip_space(text, pos);
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

inline std::filesystem::path fixture_root() {
    const char* env = std::getenv("PWB_SCIENCE_FIXTURE_ROOT");
    if (env != nullptr && env[0] != '\0') {
        return std::filesystem::path(env);
    }
    return std::filesystem::path("tests/cpp/science/fixtures");
}

} // namespace fixture_io
