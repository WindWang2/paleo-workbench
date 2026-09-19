// viz_a.las_preview_core — provider-less branches of the LAS preview core:
// formatting parity, classification (no-curve-headers / parse-error), and
// the honest capability-unavailable result when no parse provider is
// installed. WLE-backed replay lives in las_preview_wle_test.cpp.

#include <cstdio>
#include <cstdlib>
#include <string>

#include <pwb/ingest/preview/las_preview.hpp>
#include <pwb/ingest/preview/models.hpp>

using namespace pwb::ingest::preview;

namespace {

int g_failures = 0;

void check(bool ok, const std::string& what) {
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

void check_eq(const std::string& expected, const std::string& actual,
              const std::string& what) {
    check(expected == actual, what + ": expected '" + expected + "' got '" +
                                  actual + "'");
}

}  // namespace

int main() {
    // Formatting parity: f"{v:.4f}".rstrip('0').rstrip('.'); NaN literal.
    check_eq("NaN", las_format_value(0.0 / 0.0 * 0.0), "NaN display");
    check_eq("1000", las_format_value(1000.0), "integer trim");
    check_eq("45.2", las_format_value(45.20), "one decimal");
    check_eq("0", las_format_value(0.0), "zero");
    check_eq("-0", las_format_value(-0.0), "negative zero trim");
    check_eq("2.45", las_format_value(2.45), "two decimals");
    check_eq("100000000", las_format_value(1e8), "large value");

    // Provider-less: honest capability statement, no fabricated Python
    // dependency error, not cached, retryable.
    set_las_preview_provider(nullptr);
    ResourceRef asset;
    asset.name = "w.las";
    asset.path = "/tmp/w.las";
    asset.format = "las";
    asset.type = "well_log";
    asset.status = "active";
    PreviewResult r = las_preview_result(asset, "", PreviewSettings{});
    check(r.mode == "message", "unavailable mode");
    check(r.message.find("WLE") != std::string::npos &&
              r.message.find("ModuleNotFoundError") == std::string::npos,
          "unavailable message names WLE, not a fake Python error");
    check(!r.cacheable && r.retryable, "unavailable is transient");
    check(!las_preview_provider_installed(), "provider cleared");

    // Scripted provider: classification branches.
    set_las_preview_provider([](const std::string&,
                                const std::string&) -> std::optional<LasPreviewData> {
        LasPreviewData data;
        data.status = LasPreviewData::Status::no_curve_headers;
        return data;
    });
    r = las_preview_result(asset, "", PreviewSettings{});
    check(r.mode == "well_log", "no-curve mode");
    check_eq("0", r.summary_rows[1].second, "no-curve count");
    check(r.warning.find("\xE7\xBC\xBA\xE5\xB0\x91") != std::string::npos,
          "no-curve warning");  // 缺少

    set_las_preview_provider([](const std::string&,
                                const std::string&) -> std::optional<LasPreviewData> {
        LasPreviewData data;
        data.status = LasPreviewData::Status::parse_error;
        data.parse_error_class = "ValueError";
        return data;
    });
    r = las_preview_result(asset, "", PreviewSettings{});
    check(r.mode == "message", "parse-error mode");
    check(r.message.find("ValueError") != std::string::npos, "parse-error class");

    // Declined provider (nullopt) also lands on the ValueError message.
    set_las_preview_provider([](const std::string&,
                                const std::string&) -> std::optional<LasPreviewData> {
        return std::nullopt;
    });
    r = las_preview_result(asset, "", PreviewSettings{});
    check(r.mode == "message" && r.message.find("ValueError") != std::string::npos,
          "declined provider message");

    // Truncation + stem fallback + data formatting through the core.
    set_las_preview_provider([](const std::string&,
                                const std::string&) -> std::optional<LasPreviewData> {
        LasPreviewData data;
        data.well_name = "";
        data.row_count = 3;
        for (int i = 0; i < 205; ++i) {
            data.curves.push_back({"C" + std::to_string(i), "U", "d" + std::to_string(i)});
        }
        // two rows, three columns, one NaN
        data.values = {1.0, 2.5, 0.0 / 0.0 * 0.0, 3.25, -0.0, 100.0};
        return data;
    });
    PreviewSettings settings;
    settings.table_max_rows = 200;
    r = las_preview_result(asset, "", settings);
    check(r.truncated, "truncation flag");
    check(r.table_rows.size() == 200, "truncated table rows");
    check_eq("w", r.summary_rows[0].second, "stem fallback (w.las -> w)");
    check_eq("205", r.summary_rows[1].second, "curve count");
    check_eq("3", r.summary_rows[2].second, "sample count");
    check(r.data_headers.size() == 205 && r.data_rows.size() == 2,
          "data table shape");
    check_eq("NaN", r.data_rows[0][2], "data NaN cell");
    check_eq("3.25", r.data_rows[1][0], "data value cell");
    check(!r.warning.empty(), "truncation warning set");

    // Unicode path stem (path_stem parity with Python Path.stem on
    // non-ASCII names).
    asset.path = "/data/\xE4\xBB\x95/\xE5\x9C\xB0\xE8\xb4\xA8\xE4\xBA\x95.las";  // 地质井.las
    r = las_preview_result(asset, "", settings);
    check_eq("\xE5\x9C\xB0\xE8\xb4\xA8\xE4\xBA\x95", r.summary_rows[0].second,
             "unicode stem");

    set_las_preview_provider(nullptr);
    if (g_failures == 0) {
        std::printf("viz_a.las_preview_core: OK\n");
        return 0;
    }
    std::printf("viz_a.las_preview_core: %d failure(s)\n", g_failures);
    return 1;
}
