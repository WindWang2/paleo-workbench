#include <pwb/viz/well_log_document_plan.hpp>
#include <pwb/well_science/depth_unit.hpp>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cctype>
#include <charconv>
#include <cmath>
#include <cstring>
#include <stdexcept>

namespace pwb::viz {

namespace {

// --- SHA-1 (RFC 3174), only for UUIDv5 entity ids ---------------------------
// No SHA-1 lives in the repo's shared libs (pwb_domain ships SHA-256 only);
// the engine's io layer hashes for manifests, not for UUIDv5. Kept local:
// correctness is pinned end-to-end by the Python-oracle parity fixture
// (uuid5 ids across 12 cases) plus the negative self-check, not by local
// RFC test vectors.

class Sha1 {
public:
    Sha1() = default;
    void update(const std::uint8_t* data, std::size_t length) {
        message_length_ += length;
        while (length > 0) {
            const std::size_t take =
                std::min(length, std::size_t{64} - buffer_length_);
            std::memcpy(buffer_.data() + buffer_length_, data, take);
            buffer_length_ += take;
            data += take;
            length -= take;
            if (buffer_length_ == 64) {
                process_block(buffer_.data());
                buffer_length_ = 0;
            }
        }
    }
    [[nodiscard]] std::array<std::uint8_t, 20> digest() {
        const std::uint64_t bit_length = message_length_ * 8;
        const std::uint8_t one = 0x80;
        update(&one, 1);
        const std::uint8_t zero = 0x00;
        while (buffer_length_ != 56) {
            update(&zero, 1);
        }
        std::array<std::uint8_t, 8> length_bytes{};
        for (std::size_t i = 0; i < 8; ++i) {
            length_bytes[i] = static_cast<std::uint8_t>(
                bit_length >> (56 - 8 * i));
        }
        // update() would count the padding, but digest() is terminal — write
        // the block directly instead.
        std::memcpy(buffer_.data() + 56, length_bytes.data(), 8);
        process_block(buffer_.data());
        buffer_length_ = 0;
        std::array<std::uint8_t, 20> out{};
        for (std::size_t i = 0; i < 5; ++i) {
            out[4 * i + 0] = static_cast<std::uint8_t>(state_[i] >> 24);
            out[4 * i + 1] = static_cast<std::uint8_t>(state_[i] >> 16);
            out[4 * i + 2] = static_cast<std::uint8_t>(state_[i] >> 8);
            out[4 * i + 3] = static_cast<std::uint8_t>(state_[i]);
        }
        return out;
    }

private:
    static std::uint32_t rotate_left(std::uint32_t value, unsigned count) {
        return (value << count) | (value >> (32 - count));
    }
    void process_block(const std::uint8_t* block) {
        std::array<std::uint32_t, 80> words{};
        for (std::size_t i = 0; i < 16; ++i) {
            words[i] = (static_cast<std::uint32_t>(block[4 * i]) << 24) |
                       (static_cast<std::uint32_t>(block[4 * i + 1]) << 16) |
                       (static_cast<std::uint32_t>(block[4 * i + 2]) << 8) |
                       static_cast<std::uint32_t>(block[4 * i + 3]);
        }
        for (std::size_t i = 16; i < 80; ++i) {
            words[i] = rotate_left(words[i - 3] ^ words[i - 8] ^
                                       words[i - 14] ^ words[i - 16],
                                   1);
        }
        std::uint32_t a = state_[0], b = state_[1], c = state_[2];
        std::uint32_t d = state_[3], e = state_[4];
        for (std::size_t i = 0; i < 80; ++i) {
            std::uint32_t f = 0;
            std::uint32_t k = 0;
            if (i < 20) {
                f = (b & c) | ((~b) & d);
                k = 0x5A827999;
            } else if (i < 40) {
                f = b ^ c ^ d;
                k = 0x6ED9EBA1;
            } else if (i < 60) {
                f = (b & c) | (b & d) | (c & d);
                k = 0x8F1BBCDC;
            } else {
                f = b ^ c ^ d;
                k = 0xCA62C1D6;
            }
            const std::uint32_t temp =
                rotate_left(a, 5) + f + e + k + words[i];
            e = d;
            d = c;
            c = rotate_left(b, 30);
            b = a;
            a = temp;
        }
        state_[0] += a;
        state_[1] += b;
        state_[2] += c;
        state_[3] += d;
        state_[4] += e;
    }

    std::array<std::uint32_t, 5> state_{0x67452301, 0xEFCDAB89, 0x98BADCFE,
                                        0x10325476, 0xC3D2E1F0};
    std::array<std::uint8_t, 64> buffer_{};
    std::size_t buffer_length_{0};
    std::uint64_t message_length_{0};
};

// Python uuid.uuid5(NAMESPACE, name) over the fixed Workbench namespace.
constexpr std::array<std::uint8_t, 16> kEntityNamespace = {
    0xa1, 0x69, 0x00, 0x00, 0x00, 0x00, 0x40, 0x00,
    0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01};

std::string uuid5_hex(const std::string& name) {
    Sha1 sha;
    sha.update(kEntityNamespace.data(), kEntityNamespace.size());
    sha.update(reinterpret_cast<const std::uint8_t*>(name.data()), name.size());
    auto bytes = sha.digest();
    bytes[6] = static_cast<std::uint8_t>((bytes[6] & 0x0F) | 0x50);
    bytes[8] = static_cast<std::uint8_t>((bytes[8] & 0x3F) | 0x80);
    static constexpr char kHex[] = "0123456789abcdef";
    std::string out;
    out.reserve(36);
    for (std::size_t i = 0; i < 16; ++i) {
        if (i == 4 || i == 6 || i == 8 || i == 10) {
            out.push_back('-');
        }
        out.push_back(kHex[bytes[i] >> 4]);
        out.push_back(kHex[bytes[i] & 0x0F]);
    }
    return out;
}

// Python repr(float): shortest round-trip digits, fixed notation for
// decimal exponents in [-4, 16), scientific ("1e+16" style, 2-digit
// exponent) outside, ".0" on integral values.
std::string python_repr_double(double value) {
    if (std::isnan(value)) return "nan";
    if (std::isinf(value)) return value > 0 ? "inf" : "-inf";
    if (value == 0.0) return std::signbit(value) ? "-0.0" : "0.0";
    char buffer[64];
    const auto result = std::to_chars(buffer, buffer + sizeof(buffer), value,
                                      std::chars_format::scientific);
    const std::string text(buffer, result.ptr);
    const auto epos = text.find('e');
    std::string mantissa = text.substr(0, epos);
    const int exp10 = std::atoi(text.c_str() + epos + 1);
    bool negative = false;
    if (!mantissa.empty() && mantissa.front() == '-') {
        negative = true;
        mantissa.erase(0, 1);
    }
    std::string digits;
    for (const char c : mantissa) {
        if (c != '.') digits += c;
    }
    std::string out = negative ? "-" : "";
    if (exp10 < -4 || exp10 >= 16) {
        out += digits.substr(0, 1);
        if (digits.size() > 1) {
            out += '.';
            out += digits.substr(1);
        }
        char exponent[8];
        std::snprintf(exponent, sizeof(exponent), "%c%02d",
                      exp10 < 0 ? '-' : '+', std::abs(exp10));
        out += 'e';
        out += exponent;
    } else if (exp10 >= static_cast<int>(digits.size()) - 1) {
        out += digits;
        out.append(static_cast<std::size_t>(exp10) - (digits.size() - 1), '0');
        out += ".0";
    } else if (exp10 >= 0) {
        out += digits.substr(0, static_cast<std::size_t>(exp10) + 1);
        out += '.';
        out += digits.substr(static_cast<std::size_t>(exp10) + 1);
    } else {
        out += "0.";
        out.append(static_cast<std::size_t>(-exp10) - 1, '0');
        out += digits;
    }
    return out;
}

// --- vendored color tables (mirror the Python adapter verbatim) -------------

}  // namespace

// BEGIN VIZ-A — the frozen FACIES_COLORS table now lives in the core
// visualization lib (facies_colors.cpp; same declaration via
// well_log_document_plan.hpp) so non-WLE consumers share it; the fuzzy
// lookup semantics stay per consumer (plan: interval_color; viz-a:
// facies_color_for with the Python longest-substring rule).

namespace {

std::string interval_color(const std::string& label, std::size_t index,
                           std::string_view semantic) {
    const auto& table = facies_colors();
    const auto exact = std::find_if(
        table.begin(), table.end(),
        [&label](const auto& entry) { return entry.first == label; });
    if (exact != table.end()) {
        return exact->second;
    }
    // Longest containing key wins; ties resolve in table order (the oracle
    // sorts by descending length with a stable sort over the table).
    std::vector<const std::pair<std::string, std::string>*> candidates;
    candidates.reserve(table.size());
    for (const auto& entry : table) {
        candidates.push_back(&entry);
    }
    std::stable_sort(candidates.begin(), candidates.end(),
                     [](const auto* a, const auto* b) {
                         return a->first.size() > b->first.size();
                     });
    for (const auto* entry : candidates) {
        if (!entry->first.empty() && label.find(entry->first) != std::string::npos) {
            return entry->second;
        }
    }
    if (semantic == "lithology") {
        return "#e0e0e0";
    }
    static const std::array<const char*, 8> kPalette = {
        "#d4e6f1", "#d5f5e3", "#fdebd0", "#e8daef",
        "#fcf3cf", "#fadbd8", "#d1f2eb", "#ebdef0"};
    return kPalette[index % kPalette.size()];
}

std::string curve_color_for(const std::string& mnemonic,
                            const std::string& override_color) {
    if (!override_color.empty()) {
        return override_color;
    }
    static const std::vector<std::pair<std::string, std::string>> kCurveColors =
        {{"AC", "#1d4ed8"}, {"GR", "#15803d"}, {"RT", "#b91c1c"},
         {"RXO", "#ea580c"}};
    std::string folded;
    folded.reserve(mnemonic.size());
    for (const char c : mnemonic) {
        folded.push_back(static_cast<char>(
            std::toupper(static_cast<unsigned char>(c))));
    }
    for (const auto& [name, color] : kCurveColors) {
        if (name == folded) {
            return color;
        }
    }
    return "#63b3ed";
}

constexpr double kLogScaleFloor = 1e-10;

struct FinitePairs {
    std::shared_ptr<const std::vector<double>> depth;
    std::shared_ptr<const std::vector<double>> values;
    std::vector<std::uint64_t> null_indices;
};

// Gap-honest alignment (oracle: _finite_pairs). Non-finite depths drop the
// sample; non-finite values stay with a null diagnostic.
FinitePairs finite_pairs(const std::shared_ptr<const std::vector<double>>& depth,
                         const std::shared_ptr<const std::vector<double>>& values) {
    static const auto kEmpty =
        std::make_shared<const std::vector<double>>();
    const auto& d = depth != nullptr ? *depth : *kEmpty;
    const auto& v = values != nullptr ? *values : *kEmpty;
    const std::size_t n = std::min(d.size(), v.size());

    FinitePairs out;
    bool any_valid_depth = false;
    for (std::size_t i = 0; i < n; ++i) {
        const bool valid = std::isfinite(d[i]) && std::isfinite(v[i]);
        if (!valid) {
            out.null_indices.push_back(i);
        }
        if (std::isfinite(d[i])) {
            any_valid_depth = true;
        }
    }
    if (!any_valid_depth) {
        out.depth = kEmpty;
        out.values = kEmpty;
        return out;
    }
    if (out.null_indices.empty() && d.size() == v.size()) {
        out.depth = depth != nullptr ? depth : kEmpty;
        out.values = values != nullptr ? values : kEmpty;
        return out;
    }
    auto kept_depth = std::make_shared<std::vector<double>>();
    auto kept_values = std::make_shared<std::vector<double>>();
    kept_depth->reserve(n);
    kept_values->reserve(n);
    for (std::size_t i = 0; i < n; ++i) {
        if (std::isfinite(d[i])) {
            kept_depth->push_back(d[i]);
            kept_values->push_back(v[i]);
        }
    }
    out.depth = std::move(kept_depth);
    out.values = std::move(kept_values);
    return out;
}

struct DepthUnitEnvelope {
    std::string unit{"m"};
    bool declared{true};
};

DepthUnitEnvelope depth_unit_envelope(const std::optional<std::string>& token) {
    const auto info = pwb::well_science::classify_depth_unit(token);
    if (info.known()) {
        return {*info.unit, true};
    }
    return {"m", false};
}

// Primary curve: GR/GAM/GAMMA/预测概率 or any name containing "GR" (oracle:
// _pick_primary).
std::size_t pick_primary_index(const std::vector<WellLogCurveInput>& curves) {
    for (std::size_t i = 0; i < curves.size(); ++i) {
        std::string upper;
        for (const char c : curves[i].mnemonic) {
            upper.push_back(static_cast<char>(
                std::toupper(static_cast<unsigned char>(c))));
        }
        if (upper == "GR" || upper == "GAM" || upper == "GAMMA" ||
            curves[i].mnemonic == "预测概率" ||
            upper.find("GR") != std::string::npos) {
            return i;
        }
    }
    return 0;
}

std::pair<double, double> display_range_of(const WellLogCurveInput& curve) {
    if (!curve.display_range.has_value()) {
        return {0.0, 100.0};
    }
    const double lower = curve.display_range->first;
    const double upper = curve.display_range->second;
    if (std::isfinite(lower) && std::isfinite(upper)) {
        return {lower, upper};
    }
    return {0.0, 100.0};
}

void append_intervals(EngineLoadPlan& plan,
                      const std::vector<WellLogIntervalInput>& source,
                      std::string_view semantic) {
    for (std::size_t index = 0; index < source.size(); ++index) {
        const auto& item = source[index];
        const double top = item.top;
        const double bottom = item.bottom;
        if (!(std::isfinite(top) && std::isfinite(bottom) && bottom > top)) {
            plan.diagnostics.push_back(
                "interval_invalid:" + std::string(semantic) + ":" +
                std::to_string(index));
            continue;
        }
        EngineIntervalSubmission interval;
        interval.interval_id = stable_entity_id(
            {"interval", plan.well_name, std::string(semantic),
             std::to_string(index), python_repr_double(top),
             python_repr_double(bottom), item.label});
        interval.top = top;
        interval.bottom = bottom;
        interval.semantic = std::string(semantic);
        interval.label = item.label;
        interval.fill_color =
            interval_color(item.label, index, semantic);
        plan.intervals.push_back(std::move(interval));
        if (semantic == "lithology") {
            plan.lithology_bounds.emplace_back(top, bottom, item.label);
        } else {
            plan.facies_bounds.emplace_back(top, bottom, item.label);
        }
    }
}

void append_markers(EngineLoadPlan& plan,
                    const std::vector<WellLogMarkerInput>& source) {
    for (std::size_t index = 0; index < source.size(); ++index) {
        const auto& item = source[index];
        if (!std::isfinite(item.depth)) {
            plan.diagnostics.push_back("marker_invalid:" +
                                       std::to_string(index));
            continue;
        }
        EngineMarkerSubmission marker;
        marker.marker_id =
            item.id.empty()
                ? stable_entity_id({"marker", plan.well_name,
                                    std::to_string(index),
                                    python_repr_double(item.depth), item.label})
                : item.id;
        marker.depth = item.depth;
        marker.label = item.label;
        marker.semantic = item.semantic.empty() ? "formation_top" : item.semantic;
        plan.markers.push_back(std::move(marker));
    }
}

// Log-range sanitization (oracle: _log_track_range): (is_log, scale_min).
std::pair<bool, double> log_track_range(const EngineCurveSubmission& curve,
                                        double lower) {
    bool has_positive = false;
    if (curve.values != nullptr) {
        for (const double value : *curve.values) {
            if (value > 0.0 && std::isfinite(value)) {
                has_positive = true;
                break;
            }
        }
    }
    if (!has_positive) {
        return {false, lower};
    }
    return {true, std::max(lower, kLogScaleFloor)};
}

nlohmann::ordered_json snapshot_curve(const EngineCurveSubmission& curve) {
    nlohmann::ordered_json entry;
    entry["mnemonic"] = curve.mnemonic;
    entry["unit"] = curve.value_unit;
    entry["depth_unit"] = curve.depth_unit;
    entry["depth_unit_declared"] = curve.depth_unit_declared;
    const auto& depth = curve.depth != nullptr ? *curve.depth : std::vector<double>{};
    const auto& values =
        curve.values != nullptr ? *curve.values : std::vector<double>{};
    entry["length"] = depth.size();
    entry["depth_first"] = depth.empty() ? nlohmann::ordered_json()
                                         : nlohmann::ordered_json(depth.front());
    entry["depth_last"] = depth.empty() ? nlohmann::ordered_json()
                                        : nlohmann::ordered_json(depth.back());
    entry["value_first"] = values.empty() ? nlohmann::ordered_json()
                                          : nlohmann::ordered_json(values.front());
    entry["value_last"] = values.empty() ? nlohmann::ordered_json()
                                         : nlohmann::ordered_json(values.back());
    auto nulls = nlohmann::ordered_json::array();
    for (const auto index : curve.null_indices) {
        nulls.push_back(index);
    }
    entry["null_indices"] = std::move(nulls);
    entry["curve_id"] = curve.curve_id;
    entry["axis_id"] = curve.axis_id;
    return entry;
}

} // namespace

std::string stable_entity_id(std::vector<std::string_view> parts) {
    std::string joined;
    for (std::size_t i = 0; i < parts.size(); ++i) {
        if (i > 0) {
            joined.push_back('|');
        }
        std::string_view part = parts[i];
        // ASCII whitespace only: Python str.strip() also strips Unicode
        // spaces (U+00A0/U+3000/...). Parts in this product are mnemonics
        // and labels without those; a part carrying one would derive a
        // different (still stable) id — declared limitation, not parity.
        constexpr std::string_view kStrip = " \t\n\r\f\v";
        while (!part.empty() && kStrip.find(part.front()) != std::string_view::npos) {
            part.remove_prefix(1);
        }
        while (!part.empty() && kStrip.find(part.back()) != std::string_view::npos) {
            part.remove_suffix(1);
        }
        joined.append(part);
    }
    return uuid5_hex(joined);
}

const EngineCurveSubmission* EngineLoadPlan::primary() const {
    if (primary_curve_id.has_value()) {
        for (const auto& curve : curves) {
            if (curve.curve_id == *primary_curve_id) {
                return &curve;
            }
        }
    }
    if (!curves.empty()) {
        return &curves.front();
    }
    return nullptr;
}

std::optional<std::string> EngineLoadPlan::document_id() const {
    const auto* main_curve = primary();
    if (main_curve != nullptr) {
        return main_curve->document_id;
    }
    return std::nullopt;
}

EngineLoadPlan adapt_well_log_data(const WellLogDocumentInput& input) {
    EngineLoadPlan plan;
    plan.well_name = input.well_name.empty() ? "well" : input.well_name;
    plan.top_depth = input.top_depth;
    plan.bottom_depth = input.bottom_depth;
    if (input.curves.empty()) {
        plan.diagnostics.push_back("no_curves");
        return plan;
    }

    const std::size_t primary_index = pick_primary_index(input.curves);
    const std::string document_id =
        stable_entity_id({"document", plan.well_name});
    const auto unit = depth_unit_envelope(input.depth_unit);
    if (!unit.declared) {
        plan.diagnostics.push_back(
            "depth-unit:unknown — engine label defaults to m for rendering only");
    }
    for (std::size_t index = 0; index < input.curves.size(); ++index) {
        const auto& curve = input.curves[index];
        std::string mnemonic = curve.mnemonic;
        if (mnemonic.empty()) {
            mnemonic = "CURVE_" + std::to_string(index);
        }
        std::string unit_text = curve.unit.empty() ? "unit" : curve.unit;
        auto pairs = finite_pairs(curve.depth, curve.values);
        const bool any_finite_value =
            pairs.values != nullptr &&
            std::any_of(pairs.values->begin(), pairs.values->end(),
                        [](double v) { return std::isfinite(v); });
        if (pairs.depth->empty() || !any_finite_value) {
            plan.diagnostics.push_back("curve_empty:" + mnemonic);
            continue;
        }
        EngineCurveSubmission submission;
        submission.input_index = index;
        submission.document_id = document_id;
        submission.axis_id =
            stable_entity_id({"axis", plan.well_name, mnemonic,
                              std::to_string(index)});
        submission.curve_id = stable_entity_id(
            {"curve", plan.well_name, mnemonic, std::to_string(index)});
        submission.mnemonic = mnemonic;
        submission.depth_unit = unit.unit;
        submission.value_unit = unit_text;
        submission.depth = std::move(pairs.depth);
        submission.values = std::move(pairs.values);
        submission.null_indices = std::move(pairs.null_indices);
        submission.display_range = display_range_of(curve);
        submission.color = curve_color_for(mnemonic, curve.color);
        submission.depth_unit_declared = unit.declared;
        if (index == primary_index) {
            plan.primary_curve_id = submission.curve_id;
        }
        plan.curves.push_back(std::move(submission));
    }

    std::vector<WellLogIntervalInput> lithology = input.lithology;
    std::vector<WellLogIntervalInput> facies = input.facies;
    if (lithology.empty() && input.facies_groups.has_value()) {
        // Python: `if not lithology and grouped is not None: lithology =
        // grouped.lithology`.
        lithology = input.facies_groups->lithology;
    }
    if (facies.empty() && input.facies_groups.has_value()) {
        const auto& grouped = *input.facies_groups;
        facies.reserve(grouped.phase.size() + grouped.sub_phase.size() +
                       grouped.micro_phase.size());
        facies.insert(facies.end(), grouped.phase.begin(), grouped.phase.end());
        facies.insert(facies.end(), grouped.sub_phase.begin(),
                      grouped.sub_phase.end());
        facies.insert(facies.end(), grouped.micro_phase.begin(),
                      grouped.micro_phase.end());
    }
    append_intervals(plan, lithology, "lithology");
    append_intervals(plan, facies, "facies");
    append_markers(plan, input.markers);
    if (plan.curves.empty()) {
        plan.diagnostics.push_back("all_curves_empty");
    }
    return plan;
}

std::optional<EngineLoadPlan>
adapt_well_log_data_from_source(WellLogCurveSource& source,
                                const std::atomic_bool& cancel,
                                std::vector<std::string>* diagnostics) {
    WellLogDocumentInput input;
    input.well_name = source.well_name();
    input.depth_unit = source.depth_unit();
    const auto envelope = source.depth_envelope();
    input.top_depth = envelope.first;
    input.bottom_depth = envelope.second;
    input.curves.reserve(source.curve_count());
    for (std::size_t i = 0; i < source.curve_count(); ++i) {
        if (cancel.load()) {
            if (diagnostics != nullptr) {
                diagnostics->push_back("cancelled");
            }
            return std::nullopt;
        }
        input.curves.push_back(source.load_curve(i, cancel));
    }
    auto plan = adapt_well_log_data(input);
    if (diagnostics != nullptr) {
        *diagnostics = plan.diagnostics;
    }
    return plan;
}

std::vector<EngineTrackPlan>
build_track_payload(const EngineLoadPlan& plan,
                    std::vector<std::string>* diagnostics) {
    std::vector<EngineTrackPlan> tracks;
    bool has_lithology = false;
    bool has_facies = false;
    for (const auto& interval : plan.intervals) {
        if (interval.semantic == "lithology") has_lithology = true;
        if (interval.semantic == "facies") has_facies = true;
    }
    if (has_lithology) {
        EngineTrackPlan track;
        track.width_mm = 24.0;
        track.interval_semantic = "lithology";
        tracks.push_back(track);
    }
    if (has_facies) {
        EngineTrackPlan track;
        track.width_mm = 24.0;
        track.interval_semantic = "facies";
        tracks.push_back(track);
    }
    for (const auto& curve : plan.curves) {
        double lower = curve.display_range.first;
        double upper = curve.display_range.second;
        if (!(upper > lower)) {
            upper = lower + 1.0;
        }
        std::string folded;
        folded.reserve(curve.mnemonic.size());
        for (const char c : curve.mnemonic) {
            folded.push_back(
                static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
        }
        bool is_log = folded == "RT" || folded == "RXO";
        if (is_log) {
            auto sanitized = log_track_range(curve, lower);
            is_log = sanitized.first;
            lower = sanitized.second;
            if (!is_log && diagnostics != nullptr) {
                diagnostics->push_back("log_scale_fallback:" + curve.mnemonic);
            }
        }
        EngineTrackPlan track;
        track.width_mm = 40.0;
        track.scale_mode = is_log ? "log" : "linear";
        track.scale_min = lower;
        track.scale_max = upper;
        track.curve_id = curve.curve_id;
        track.color = curve.color;
        tracks.push_back(std::move(track));
    }
    return tracks;
}

std::optional<std::pair<double, double>>
submit_depth_envelope(const EngineLoadPlan& plan) {
    const auto* main_curve = plan.primary();
    if (main_curve == nullptr) {
        return std::nullopt;
    }
    double top = std::min(plan.top_depth, plan.bottom_depth);
    double bottom = std::max(plan.top_depth, plan.bottom_depth);
    const auto& depth = *main_curve->depth;
    if (!(bottom > top) && depth.size() >= 2) {
        top = std::min(depth.front(), depth.back());
        bottom = std::max(depth.front(), depth.back());
    }
    return std::make_pair(top, bottom);
}

std::string parity_snapshot_json(const EngineLoadPlan& plan) {
    nlohmann::ordered_json snapshot;
    snapshot["well_name"] = plan.well_name;
    snapshot["top_depth"] = plan.top_depth;
    snapshot["bottom_depth"] = plan.bottom_depth;
    const auto document_id = plan.document_id();
    snapshot["document_id"] = document_id.has_value()
                                  ? nlohmann::ordered_json(*document_id)
                                  : nlohmann::ordered_json();
    auto curves = nlohmann::ordered_json::array();
    for (const auto& curve : plan.curves) {
        curves.push_back(snapshot_curve(curve));
    }
    snapshot["curves"] = std::move(curves);
    auto bounds_array =
        [](const std::vector<std::tuple<double, double, std::string>>& bounds) {
            auto array = nlohmann::ordered_json::array();
            for (const auto& [top, bottom, label] : bounds) {
                array.push_back(nlohmann::ordered_json::array(
                    {top, bottom, label}));
            }
            return array;
        };
    snapshot["lithology_bounds"] = bounds_array(plan.lithology_bounds);
    snapshot["facies_bounds"] = bounds_array(plan.facies_bounds);
    auto markers = nlohmann::ordered_json::array();
    for (const auto& marker : plan.markers) {
        nlohmann::ordered_json entry;
        entry["depth"] = marker.depth;
        entry["label"] = marker.label;
        entry["semantic"] = marker.semantic;
        markers.push_back(std::move(entry));
    }
    snapshot["markers"] = std::move(markers);
    auto diagnostics = nlohmann::ordered_json::array();
    for (const auto& diagnostic : plan.diagnostics) {
        diagnostics.push_back(diagnostic);
    }
    snapshot["diagnostics"] = std::move(diagnostics);
    return snapshot.dump();
}

} // namespace pwb::viz
