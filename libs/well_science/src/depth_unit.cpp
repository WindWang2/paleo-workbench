// Depth-unit vocabulary + typed refusal, frozen against well_science.py.
#include <algorithm>
#include <array>
#include <cctype>
#include <string>

#include <pwb/well_science/errors.hpp>

namespace pwb::well_science {

namespace {
constexpr std::array<std::string_view, 4> kFtTokens{"FT", "F", "FEET", "FOOT"};
constexpr std::array<std::string_view, 7> kMTokens{"M",    "METER",  "METERS", "MTR",
                                                   "MTRS", "METRE", "METRES"};

std::string ascii_upper(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return c >= 'a' && c <= 'z' ? static_cast<char>(c - 'a' + 'A') : c;
    });
    return s;
}
}  // namespace

DepthUnitInfo classify_depth_unit(std::optional<std::string> token) {
    DepthUnitInfo info;
    if (!token) return info;  // unit=nullopt, declared=false, raw=""
    std::string raw = *token;
    std::size_t b = 0, e = raw.size();
    while (b < e && std::isspace(static_cast<unsigned char>(raw[b]))) ++b;
    while (e > b && std::isspace(static_cast<unsigned char>(raw[e - 1]))) --e;
    raw = raw.substr(b, e - b);
    if (raw.empty()) return info;
    const std::string upper = ascii_upper(raw);
    for (std::string_view t : kFtTokens)
        if (upper == t) return DepthUnitInfo{std::string("ft"), true, raw};
    for (std::string_view t : kMTokens)
        if (upper == t) return DepthUnitInfo{std::string("m"), true, raw};
    return DepthUnitInfo{std::nullopt, true, raw};
}

UnknownDepthUnitError::UnknownDepthUnitError(DepthUnitInfo info, std::string operation)
    : CurveOpError("operation '" + operation +
                   "' depends on the depth unit, which is " +
                   (info.declared ? "declared as '" + info.raw + "' but unrecognized"
                                  : "not declared by the file") +
                   "; refusing instead of assuming meters"),
      info_(std::move(info)),
      operation_(std::move(operation)) {}

std::string require_depth_unit(const DepthUnitInfo& info, const std::string& operation) {
    if (!info.known()) throw UnknownDepthUnitError(info, operation);
    return *info.unit;
}

std::string require_depth_unit(std::optional<std::string> token,
                               const std::string& operation) {
    return require_depth_unit(classify_depth_unit(std::move(token)), operation);
}

DepthUnitInfo depth_unit_of(std::optional<std::string> envelope_unit) {
    if (!envelope_unit) return DepthUnitInfo{};  // absence is never evidence of meters
    return classify_depth_unit(std::move(envelope_unit));
}

}  // namespace pwb::well_science
