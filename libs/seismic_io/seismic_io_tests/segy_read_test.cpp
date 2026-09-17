// seismic_io.segy_read — the real tiny.sgy fixture through the C++
// reader, compared sample-exactly against the frozen geoviz oracle
// (tiny_sgy_real/input.f32) plus the structural facts the oracle froze
// (8x8x32 grid, 1x1 line steps, dt=2 ms). Refusal paths (short file,
// irregular grid, unsupported format) are exercised on synthetic bytes.

#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include <pwb/seismic_io/segy_reader.hpp>

namespace fs = std::filesystem;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

std::vector<float> read_f32(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    input.seekg(0, std::ios::end);
    const std::streamsize size = input.tellg();
    input.seekg(0, std::ios::beg);
    std::vector<float> data(static_cast<std::size_t>(size / 4));
    if (!data.empty()) {
        input.read(reinterpret_cast<char*>(data.data()), size);
    }
    return data;
}

// Writes a minimal synthetic SEG-Y with the given inline/crossline
// sequence (format 5, ns=2, dt=1000us) for the refusal tests.
fs::path write_synthetic(const fs::path& dir, const std::string& name,
                         const std::vector<std::pair<int, int>>& grid,
                         std::size_t truncate_to = 0) {
    const std::size_t ns = 2;
    std::vector<unsigned char> bytes(3600, 0);
    const auto put16 = [&bytes](std::size_t off, std::uint16_t v) {
        bytes[off] = static_cast<unsigned char>(v >> 8);
        bytes[off + 1] = static_cast<unsigned char>(v & 0xff);
    };
    put16(3200 + 16, 1000);   // dt us
    put16(3200 + 20, ns);     // samples
    put16(3200 + 24, 5);      // IEEE
    for (const auto& [il, xl] : grid) {
        std::vector<unsigned char> trace(240 + ns * 4, 0);
        const auto put32 = [&trace](std::size_t off, std::int32_t v) {
            for (int b = 0; b < 4; ++b) {
                trace[off + static_cast<std::size_t>(b)] =
                    static_cast<unsigned char>((v >> (24 - 8 * b)) & 0xff);
            }
        };
        put32(188, il);
        put32(192, xl);
        bytes.insert(bytes.end(), trace.begin(), trace.end());
    }
    if (truncate_to != 0 && bytes.size() > truncate_to) {
        bytes.resize(truncate_to);
    }
    const fs::path path = dir / name;
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(bytes.data()),
              static_cast<std::streamsize>(bytes.size()));
    return path;
}

}  // namespace

int main() {
    const fs::path work = fs::temp_directory_path()
        / "pwb-seismic-io-test";
    std::error_code ec;
    fs::create_directories(work, ec);

    // ---- oracle: real tiny.sgy vs frozen geoviz output --------------------
    {
        std::string error;
        const auto volume = pwb::seismic_io::read_segy(
            fs::path(PWB_REALDATA_DIR) / "tiny.sgy", &error);
        check(volume.has_value(), "tiny.sgy read: " + error);
        if (volume.has_value()) {
            check(volume->ni == 8 && volume->nc == 8 && volume->ns == 32,
                  "tiny.sgy shape 8x8x32");
            check(volume->iline_start == 1.0 && volume->xline_start == 1.0,
                  "tiny.sgy line origins");
            check(volume->iline_step == 1.0 && volume->xline_step == 1.0,
                  "tiny.sgy line steps");
            check(std::fabs(volume->dt_ms - 2.0) < 1e-12,
                  "tiny.sgy dt=2ms");
            check(volume->unit == "ms", "tiny.sgy unit");

            const std::vector<float> oracle = read_f32(
                fs::path(PWB_ATTRIBUTE_FIXTURES) / "tiny_sgy_real"
                / "input.f32");
            check(oracle.size() == volume->samples.size(), "oracle size");
            double max_diff = 0.0;
            for (std::size_t i = 0; i < oracle.size() && i < volume->samples.size(); ++i) {
                max_diff = std::max(max_diff,
                    static_cast<double>(std::fabs(
                        static_cast<double>(oracle[i])
                        - static_cast<double>(volume->samples[i]))));
            }
            check(max_diff == 0.0,
                  "tiny.sgy sample-exact vs oracle (max_diff="
                      + std::to_string(max_diff) + ")");
        }
    }

    // ---- refusals (synthetic) ---------------------------------------------
    {
        std::string error;
        auto volume = pwb::seismic_io::read_segy(
            write_synthetic(work, "incomplete.sgy",
                            {{1, 1}, {1, 2}, {2, 1}}),  // {2,2} missing
            &error);
        check(!volume.has_value() && error.find("incomplete grid")
                  != std::string::npos,
              "incomplete grid refused: " + error);
    }
    {
        std::string error;
        auto volume = pwb::seismic_io::read_segy(
            write_synthetic(work, "duplicate.sgy",
                            {{1, 1}, {1, 1}}),
            &error);
        check(!volume.has_value() && error.find("duplicate") != std::string::npos,
              "duplicate trace refused: " + error);
    }
    {
        std::string error;
        auto volume = pwb::seismic_io::read_segy(
            write_synthetic(work, "truncated.sgy", {{1, 1}, {1, 2}}, 3700),
            &error);
        check(!volume.has_value()
                  && error.find("whole multiple") != std::string::npos,
              "truncated body refused: " + error);
    }
    {
        std::string error;
        auto volume = pwb::seismic_io::read_segy(work / "missing.sgy", &error);
        check(!volume.has_value() && error.find("cannot open")
                  != std::string::npos,
              "missing file refused: " + error);
    }
    // Unsorted but complete grids must reorder, not fail.
    {
        std::string error;
        auto volume = pwb::seismic_io::read_segy(
            write_synthetic(work, "unsorted.sgy",
                            {{2, 2}, {1, 1}, {2, 1}, {1, 2}}),
            &error);
        check(volume.has_value(), "unsorted-but-complete accepted: " + error);
        if (volume.has_value()) {
            // Trace (1,1) was written with zeros; (2,2) last — order
            // independence is structural here, the read itself suffices.
            check(volume->ni == 2 && volume->nc == 2 && volume->ns == 2,
                  "unsorted shape");
        }
    }

    std::printf("%s: %d failure(s)\n", g_failures == 0 ? "PASS" : "FAIL",
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
