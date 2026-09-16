#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/json.hpp"

#include <cmath>
#include <iomanip>
#include <sstream>

namespace pwb::domain {

namespace {
std::string format_two(int value) {
    std::string out = std::to_string(value);
    if (out.size() < 2) out.insert(out.begin(), '0');
    return out;
}
}  // namespace

std::string now_iso8601() {
    const auto now = std::chrono::system_clock::now();
    const std::time_t tt = std::chrono::system_clock::to_time_t(now);
    const auto us = std::chrono::duration_cast<std::chrono::microseconds>(
                        now.time_since_epoch())
                        .count() %
                    1'000'000;
    std::tm tm{};
    gmtime_s(&tm, &tt);
    std::ostringstream os;
    os << (tm.tm_year + 1900) << '-' << format_two(tm.tm_mon + 1) << '-'
       << format_two(tm.tm_mday) << 'T' << format_two(tm.tm_hour) << ':'
       << format_two(tm.tm_min) << ':' << format_two(tm.tm_sec) << '.'
       << std::setw(6) << std::setfill('0') << us << "+00:00";
    return os.str();
}

std::string fixed_iso8601_for_tests() {
    return "2026-09-16T08:00:00.000000+00:00";
}

nlohmann::ordered_json Diagnostic::to_json() const {
    nlohmann::ordered_json out;
    switch (severity) {
        case Severity::Info: out["severity"] = "info"; break;
        case Severity::Warning: out["severity"] = "warning"; break;
        case Severity::Error: out["severity"] = "error"; break;
    }
    out["code"] = code;
    out["message"] = message;
    if (!detail.is_null()) out["detail"] = detail;
    return out;
}

namespace {

JsonDiff diff_number(const Json& left, const Json& right,
                     const std::string& path) {
    const bool left_int =
        left.is_number_integer() && !left.is_number_float();
    const bool right_int =
        right.is_number_integer() && !right.is_number_float();
    if (left_int != right_int) {
        return JsonDiff::fail(
            path, "number kind differs (int vs float): " + left.dump() +
                      " vs " + right.dump());
    }
    if (left == right) return JsonDiff::ok();
    return JsonDiff::fail(path,
                          "number value differs: " + left.dump() + " vs " +
                              right.dump());
}

}  // namespace

JsonDiff json_semantic_diff(const Json& left, const Json& right,
                            const std::string& path) {
    if (left.type() != right.type()) {
        return JsonDiff::fail(path, "type differs: " +
                                        std::to_string(static_cast<int>(
                                            left.type())) +
                                        " vs " +
                                        std::to_string(static_cast<int>(
                                            right.type())));
    }
    if (left.is_object()) {
        for (auto it = left.begin(); it != left.end(); ++it) {
            if (!right.contains(it.key())) {
                return JsonDiff::fail(path + "." + it.key(),
                                      "key missing on right");
            }
            auto child = json_semantic_diff(
                it.value(), right.at(it.key()), path + "." + it.key());
            if (!child.equal) return child;
        }
        for (auto it = right.begin(); it != right.end(); ++it) {
            if (!left.contains(it.key())) {
                return JsonDiff::fail(path + "." + it.key(),
                                      "key missing on left");
            }
        }
        return JsonDiff::ok();
    }
    if (left.is_array()) {
        if (left.size() != right.size()) {
            return JsonDiff::fail(path, "array length differs: " +
                                            std::to_string(left.size()) +
                                            " vs " +
                                            std::to_string(right.size()));
        }
        for (std::size_t i = 0; i < left.size(); ++i) {
            auto child = json_semantic_diff(
                left[i], right[i], path + "[" + std::to_string(i) + "]");
            if (!child.equal) return child;
        }
        return JsonDiff::ok();
    }
    if (left.is_number()) return diff_number(left, right, path);
    if (left == right) return JsonDiff::ok();
    return JsonDiff::fail(path,
                          "value differs: " + left.dump() + " vs " +
                              right.dump());
}

bool json_semantically_equal(const Json& left, const Json& right) {
    return json_semantic_diff(left, right).equal;
}

std::string dump_json_python_compatible(const Json& value) {
    return value.dump(2, ' ', false, nlohmann::json::error_handler_t::strict) +
           "\n";
}

std::string dump_json_compact_header(const Json& value) {
    return value.dump(2, ' ', false);
}

}  // namespace pwb::domain
