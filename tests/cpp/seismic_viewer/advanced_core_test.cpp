// seismic_viewer.advanced_core — Qt-free cores of the 07 line: attribute
// fusion (fuse_rgb oracle semantics + tamper self-checks), slice export
// (npy 1.0 byte contract via an independent reader, csv savetxt parity) and
// the view-state schema (strict parse, round-trip, fail-closed rejection).

#include "sv_test.hpp"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <limits>
#include <string>
#include <vector>

#include <pwb/seismic_viewer/attribute_fusion_core.hpp>
#include <pwb/seismic_viewer/slice_export.hpp>
#include <pwb/seismic_viewer/view_state.hpp>

using namespace pwb::seismic_viewer;
using namespace pwb::seismic_viewer::fusion;
using namespace pwb::seismic_viewer::slice_export;

namespace {

std::string temp_path(const std::string& name) {
    const char* dir = std::getenv("PWB_SEISMIC_VIEWER_ARTIFACT_DIR");
    return (dir != nullptr ? std::string(dir) : std::string(".")) + "/" + name;
}

std::vector<unsigned char> read_bytes(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

bool write_text(const std::string& path, const std::string& text) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out << text;
    return static_cast<bool>(out);
}

// Independent (not shared with the writer) numpy 1.0 header decoder: the
// checks re-derive the np.save layout from the format spec, so a writer bug
// cannot validate itself.
struct NpyView {
    std::size_t data_offset{0};
    std::int64_t rows{0};
    std::int64_t cols{0};
};

bool decode_npy(const std::vector<unsigned char>& bytes, NpyView& out,
                std::string& error) {
    if (bytes.size() < 12 || std::memcmp(bytes.data(), "\x93NUMPY", 6) != 0) {
        error = "bad magic";
        return false;
    }
    if (bytes[6] != 0x01 || bytes[7] != 0x00) {
        error = "not format 1.0";
        return false;
    }
    const std::size_t header_len =
        static_cast<std::size_t>(bytes[8]) | (static_cast<std::size_t>(bytes[9]) << 8);
    const std::size_t prefix = 10 + header_len;
    if (prefix % 64 != 0) {
        error = "prefix not 64-byte aligned";
        return false;
    }
    if (bytes.size() < prefix) {
        error = "truncated header";
        return false;
    }
    const std::string header(bytes.begin() + 10, bytes.begin() + prefix);
    if (header.back() != '\n') {
        error = "header not newline terminated";
        return false;
    }
    if (header.find("'descr': '<f4'") == std::string::npos) {
        error = "descr is not <f4";
        return false;
    }
    if (header.find("'fortran_order': False") == std::string::npos) {
        error = "fortran_order is not False";
        return false;
    }
    const std::size_t shape_at = header.find("'shape': (");
    if (shape_at == std::string::npos) {
        error = "no shape";
        return false;
    }
    // Parse "(rows, cols)" from the header text.
    const char* shape_text = header.c_str() + shape_at;
    long long rows = 0;
    long long cols = 0;
    if (std::sscanf(shape_text, "'shape': (%lld, %lld)", &rows, &cols) != 2) {
        error = "shape unparsable: " + header;
        return false;
    }
    out.rows = rows;
    out.cols = cols;
    out.data_offset = prefix;
    return true;
}

} // namespace

TEST(channel_plan_percentile_and_fallback) {
    // Two-value channel {0, 5} at pct 99: numpy linear nanpercentile over
    // n=2 — hi = P99 = 5 - 0.05 = 4.95, lo = P1 = 0.05 (float32 lerp).
    const ChannelPlan plan = channel_plan(std::vector<float>{0.0f, 5.0f}, 99.0);
    PWB_CHECK(!plan.zero_channel);
    PWB_CHECK(std::abs(plan.lo - 0.05) < 1e-6);
    PWB_CHECK(std::abs(plan.hi - 4.95) < 1e-6);

    // Constant channel: finite extent collapsed -> zero channel (Python
    // takes the zeros branch).
    const ChannelPlan constant = channel_plan(std::vector<float>{7.0f, 7.0f}, 99.0);
    PWB_CHECK(constant.zero_channel);

    // All-NaN channel: cast parity -> zero channel (declared deviation).
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const ChannelPlan all_nan = channel_plan(std::vector<float>{nan, nan}, 99.0);
    PWB_CHECK(all_nan.zero_channel);

    // Mixed NaN: percentiles ignore NaN, NaN samples quantize to 0.
    const ChannelPlan mixed =
        channel_plan(std::vector<float>{0.0f, nan, 5.0f, 2.5f}, 99.0);
    PWB_CHECK(!mixed.zero_channel);
}

TEST(fuse_rgb_oracle_channels_and_tamper_self_check) {
    // R = {0, 5} (spans the full 0..255 output), G = constant 3, B = NaN.
    // Expected RGB pairs: (0,255,255) at value 0? No — G/B constant ->
    // zeros; R=0 -> 0, R=5 -> 255. Layout out[(cell)*3 + channel].
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const std::vector<std::uint8_t> fused =
        fuse_rgb(std::vector<float>{0.0f, 5.0f}, std::vector<float>{3.0f, 3.0f},
                 std::vector<float>{nan, nan}, 1, 2, 99.0);
    PWB_CHECK(fused.size() == 6);
    // cell 0: R=0 -> 0; G,B zero channels -> 0.
    PWB_CHECK(fused[0] == 0 && fused[1] == 0 && fused[2] == 0);
    // cell 1: R=5 (the hi sample, norm 1.0) -> 255.
    PWB_CHECK(fused[3] == 255);
    PWB_CHECK(fused[4] == 0 && fused[5] == 0);

    // Tamper self-check: the byte assertions above are the load-bearing
    // oracle (exact channel values incl. the truncation point); this swap
    // guard additionally documents that a channel-order implementation
    // cannot reproduce the asserted byte sequence.
    std::vector<std::uint8_t> tampered = fused;
    std::swap(tampered[3], tampered[4]);
    PWB_CHECK(tampered != fused);
    // (2) value tamper: quantization must truncate (127.5 -> 127), not round.
    // All three channels must match the cell count; a length mismatch is the
    // honest shape-mismatch zero image (asserted separately below).
    const std::vector<std::uint8_t> mid =
        fuse_rgb(std::vector<float>{0.0f, 5.0f, 2.5f}, std::vector<float>{0.0f, 0.0f, 0.0f},
                 std::vector<float>{0.0f, 0.0f, 0.0f}, 1, 3, 99.0);
    // cell 2: norm(2.5) over P1..P99 of {0, 2.5, 5} = 2.45/4.9 = 0.5 ->
    // 127.5 -> trunc 127 (float32 chain; never 128).
    PWB_CHECK(mid[6] == 127);
    PWB_CHECK(mid[6] != 128); // tamper: rounding instead of truncation is red

    // Shape mismatch: honest empty image, no throw.
    const std::vector<std::uint8_t> bad =
        fuse_rgb(std::vector<float>{0.0f}, std::vector<float>{0.0f},
                 std::vector<float>{0.0f}, 2, 2, 99.0);
    PWB_CHECK(bad.size() == 12 && bad[0] == 0);
}

TEST(npy_export_byte_contract_and_independent_decode) {
    // Pattern row-major plane, display orientation (rows x cols) per the
    // export contract.
    const std::vector<float> plane = {1.0f, -2.5f, 3.25f, 0.0f,
                                      1000.0f, 0.5f, -0.125f, 9.0f};
    const std::string path = temp_path("advanced_export.npy");
    std::string error;
    PWB_CHECK_MSG(write_npy(path, plane, 2, 4, error), error.c_str());

    const std::vector<unsigned char> bytes = read_bytes(path);
    NpyView view;
    PWB_CHECK_MSG(decode_npy(bytes, view, error), error.c_str());
    PWB_CHECK(view.rows == 2 && view.cols == 4);
    PWB_CHECK(bytes.size() == view.data_offset + plane.size() * sizeof(float));
    // Little-endian float32 payload, C order (this host is LE; the header
    // descr '<f4' is the portability contract).
    for (std::size_t i = 0; i < plane.size(); ++i) {
        float value = 0.0f;
        std::memcpy(&value, bytes.data() + view.data_offset + i * 4, 4);
        PWB_CHECK(value == plane[i]);
    }

    // Shape mismatch and unwritable path fail honestly.
    PWB_CHECK(!write_npy(path, plane, 4, 4, error));
    PWB_CHECK(!error.empty());
    PWB_CHECK(!write_npy("/nonexistent-dir-07/x.npy", plane, 2, 4, error));
    PWB_CHECK(!write_npy(path, {}, 0, 0, error));
}

TEST(csv_export_savetxt_parity) {
    const std::vector<float> plane = {1.0f, -2.5f, 3.25f, 0.5f};
    const std::string path = temp_path("advanced_export.csv");
    std::string error;
    PWB_CHECK_MSG(write_csv(path, plane, 2, 2, error), error.c_str());

    const std::string text = [&] {
        const std::vector<unsigned char> bytes = read_bytes(path);
        return std::string(bytes.begin(), bytes.end());
    }();
    // np.savetxt fmt="%.6f", comma delimiter, no header, '\n' endings.
    PWB_CHECK(text == "1.000000,-2.500000\n3.250000,0.500000\n");
    PWB_CHECK(!write_csv("/nonexistent-dir-07/x.csv", plane, 2, 2, error));
    PWB_CHECK(!write_csv(path, plane, 0, 0, error));
}

TEST(view_state_json_round_trip_all_fields) {
    SeismicViewState state;
    state.volume_id = "vol-07";
    state.volume_version = 3;
    state.axis = "crossline";
    state.slice_index = 12;
    state.color_map = "grayscale";
    state.display_mode = "wiggle";
    state.polarity_normal = false;
    state.clip_enabled = true;
    state.clip_percentile = 97.5;
    state.wiggle_gain = 3.5;
    state.auto_range = false;
    state.range_min = -10.0;
    state.range_max = 10.0;
    state.view_scale = 1.25;
    state.view_offset_x = 8.0;
    state.view_offset_y = -3.0;
    state.picking_enabled = true;
    state.picks = pwb::domain::Json::parse(
        R"({"schema_version":1,"volume_id":"vol-07","picks":[]})");

    const std::string text = to_json_text(state);
    SeismicViewState parsed;
    std::string error;
    PWB_CHECK_MSG(from_json_text(text, parsed, error) == ViewStateParse::ok,
                  error.c_str());
    PWB_CHECK(parsed.volume_id == state.volume_id);
    PWB_CHECK(parsed.volume_version == state.volume_version);
    PWB_CHECK(parsed.axis == state.axis);
    PWB_CHECK(parsed.slice_index == state.slice_index);
    PWB_CHECK(parsed.color_map == state.color_map);
    PWB_CHECK(parsed.display_mode == state.display_mode);
    PWB_CHECK(parsed.polarity_normal == state.polarity_normal);
    PWB_CHECK(parsed.clip_enabled == state.clip_enabled);
    PWB_CHECK(parsed.clip_percentile == state.clip_percentile);
    PWB_CHECK(parsed.wiggle_gain == state.wiggle_gain);
    PWB_CHECK(parsed.auto_range == state.auto_range);
    PWB_CHECK(parsed.range_min == state.range_min);
    PWB_CHECK(parsed.range_max == state.range_max);
    PWB_CHECK(parsed.view_scale == state.view_scale);
    PWB_CHECK(parsed.view_offset_x == state.view_offset_x);
    PWB_CHECK(parsed.view_offset_y == state.view_offset_y);
    PWB_CHECK(parsed.picking_enabled == state.picking_enabled);
    PWB_CHECK(parsed.picks == state.picks);
}

TEST(view_state_parse_fails_closed) {
    SeismicViewState parsed;
    std::string error;

    // JSON syntax error -> bad_json.
    PWB_CHECK(from_json_text("{not json", parsed, error) == ViewStateParse::bad_json);

    // Non-object root -> bad_schema.
    PWB_CHECK(from_json_text("[]", parsed, error) == ViewStateParse::bad_schema);

    // Future / unknown schema version -> bad_schema (never guess).
    PWB_CHECK(from_json_text(R"({"schema_version": 99})", parsed, error) ==
              ViewStateParse::bad_schema);

    // Missing keys -> bad_schema.
    PWB_CHECK(from_json_text(R"({"schema_version": 1, "volume_id": "x"})",
                             parsed, error) == ViewStateParse::bad_schema);

    // Mistyped key (slice_index as a string) -> bad_schema. Surgery on the
    // serializer's own output: the declared key order makes this stable.
    const std::string text = to_json_text(SeismicViewState{});
    const std::size_t slice_at = text.find("\"slice_index\": 0");
    PWB_CHECK(slice_at != std::string::npos);
    const std::string mistyped =
        text.substr(0, slice_at) + "\"slice_index\": \"nine\"" +
        text.substr(slice_at + std::strlen("\"slice_index\": 0"));
    PWB_CHECK(from_json_text(mistyped, parsed, error) == ViewStateParse::bad_schema);

    // picks not an object (null) -> bad_schema.
    const std::size_t picks_at = text.find("\"picks\": {}");
    PWB_CHECK(picks_at != std::string::npos);
    const std::string bad_picks =
        text.substr(0, picks_at) + "\"picks\": null" +
        text.substr(picks_at + std::strlen("\"picks\": {}"));
    PWB_CHECK(from_json_text(bad_picks, parsed, error) == ViewStateParse::bad_schema);
}

#include "sv_test_main.inc"
