#include "pwb/ingest/preview/las_preview.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace pwb::ingest::preview {

namespace {

LasPreviewProvider& provider_slot() {
    static LasPreviewProvider provider;
    return provider;
}

// Path.stem parity: basename without the final extension; a leading dot in
// the basename is part of the name (Python Path semantics).
std::string path_stem(const std::string& path) {
    auto slash = path.find_last_of("/\\");
    std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
    auto dot = name.find_last_of('.');
    if (dot == std::string::npos || dot == 0) return name;
    return name.substr(0, dot);
}

}  // namespace

void set_las_preview_provider(LasPreviewProvider provider) {
    provider_slot() = std::move(provider);
}

bool las_preview_provider_installed() {
    return static_cast<bool>(provider_slot());
}

std::string las_format_value(double value) {
    if (std::isnan(value)) return "NaN";
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.4f", value);
    std::string text(buf);
    // f"{v:.4f}".rstrip('0').rstrip('.') — trim trailing zeros, then a
    // trailing dot (leaves integers bare; "-0.0000" trims to "-0").
    while (!text.empty() && text.back() == '0') text.pop_back();
    if (!text.empty() && text.back() == '.') text.pop_back();
    return text;
}

PreviewResult las_preview_result(const ResourceRef& asset,
                                 const std::string& bytes,
                                 const PreviewSettings& settings) {
    const LasPreviewProvider provider = provider_slot();
    if (!provider) {
        // Honest capability statement: no fabricated Python dependency.
        PreviewResult unavailable;
        unavailable.mode = "message";
        unavailable.title = asset.name;
        unavailable.path = asset.path;
        unavailable.format = asset.format;
        unavailable.status = asset.status;
        unavailable.type_label = asset.type;
        unavailable.message =
            "LAS \xE9\xA2\x84\xE8\xA7\x88\xE4\xB8\x8D\xE5\x8F\xAF\xE7\x94\xA8"
            "\xEF\xBC\x9A""WLE LAS \xE8\xA7\xA3\xE6\x9E\x90\xE5\x86\x85\xE6\xA0"
            "\xB8\xE6\x9C\xAA\xE6\x8E\xA5\xE5\x85\xA5";  // LAS 预览不可用：WLE LAS 解析内核未接入
        unavailable.warning = unavailable.message;
        unavailable.cacheable = false;
        unavailable.retryable = true;
        return unavailable;
    }

    std::optional<LasPreviewData> data = provider(bytes, asset.path);
    if (!data) {
        // Provider present but declined (e.g. cancelled): treat as parse
        // failure with the bridge-supplied class, defaulting to ValueError.
        PreviewResult r;
        r.mode = "message";
        r.title = asset.name;
        r.path = asset.path;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        r.message = "LAS \xE9\xA2\x84\xE8\xA7\x88\xE5\xA4\xB1\xE8\xB4\xA5: "
                    "ValueError";  // LAS 预览失败: ValueError
        r.warning = r.message;
        return r;
    }

    const std::string stem = path_stem(asset.path);

    if (data->status == LasPreviewData::Status::no_curve_headers) {
        // Python: ValueError("LAS contains no curve headers") branch.
        PreviewResult r;
        r.mode = "well_log";
        r.title = asset.name;
        r.path = asset.path;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        r.summary_rows = {
            {"\xE4\xBA\x95\xE5\x90\x8D", stem},   // 井名
            {"\xE6\x9B\xB2\xE7\xBA\xBF\xE6\x95\xB0", "0"},  // 曲线数
            {"\xE9\x87\x87\xE6\xA0\xB7\xE7\x82\xB9", "0"},  // 采样点
        };
        r.table_headers = {"\xE6\x9B\xB2\xE7\xBA\xBF",     // 曲线
                           "\xE5\x8D\x95\xE4\xBD\x8D",     // 单位
                           "\xE6\x8F\x8F\xE8\xBF\xB0"};    // 描述
        r.warning =
            "LAS \xE6\x96\x87\xE4\xBB\xB6\xE7\xBC\xBA\xE5\xB0\x91\xE6\x9B\xB2"
            "\xE7\xBA\xBF\xE5\xAE\x9A\xE4\xB9\x89";  // LAS 文件缺少曲线定义
        return r;
    }

    if (data->status == LasPreviewData::Status::parse_error) {
        const std::string label =
            data->parse_error_class.empty() ? "ValueError" : data->parse_error_class;
        PreviewResult r;
        r.mode = "message";
        r.title = asset.name;
        r.path = asset.path;
        r.format = asset.format;
        r.status = asset.status;
        r.type_label = asset.type;
        r.message = "LAS \xE9\xA2\x84\xE8\xA7\x88\xE5\xA4\xB1\xE8\xB4\xA5: " +
                    label;  // LAS 预览失败: <class>
        r.warning = r.message;
        return r;
    }

    // Header ok: curve table (truncated at table_max_rows).
    const std::size_t columns = data->curves.size();
    const std::size_t table_rows =
        std::min<std::size_t>(columns, static_cast<std::size_t>(
                                           std::max(0, settings.table_max_rows)));
    const bool truncated = columns > table_rows;

    const std::string well_name =
        data->well_name.empty() ? stem : data->well_name;

    PreviewResult r;
    r.mode = "well_log";
    r.title = asset.name;
    r.path = asset.path;
    r.format = asset.format;
    r.status = asset.status;
    r.type_label = asset.type;
    r.summary_rows = {
        {"\xE4\xBA\x95\xE5\x90\x8D", well_name},  // 井名
        {"\xE6\x9B\xB2\xE7\xBA\xBF\xE6\x95\xB0", std::to_string(columns)},  // 曲线数
        {"\xE9\x87\x87\xE6\xA0\xB7\xE7\x82\xB9", std::to_string(data->row_count)},  // 采样点
    };
    r.table_headers = {"\xE6\x9B\xB2\xE7\xBA\xBF",     // 曲线
                       "\xE5\x8D\x95\xE4\xBD\x8D",     // 单位
                       "\xE6\x8F\x8F\xE8\xBF\xB0"};    // 描述
    r.table_rows.reserve(table_rows);
    for (std::size_t i = 0; i < table_rows; ++i) {
        r.table_rows.push_back({data->curves[i].mnemonic, data->curves[i].unit,
                                data->curves[i].description});
    }

    // Data table: bridge already capped rows at kLasPreviewDataRows; columns
    // always match the curve list (WLE drops mismatched rows instead of
    // NaN-padding, so the Python column-mismatch warning cannot fire —
    // adjudicated in docs/development/cpp-viz-a/reconciliation.md).
    if (columns > 0) {
        const std::size_t rows = data->values.size() / columns;
        r.data_headers.reserve(columns);
        for (const auto& curve : data->curves) r.data_headers.push_back(curve.mnemonic);
        r.data_rows.reserve(rows);
        for (std::size_t row = 0; row < rows; ++row) {
            std::vector<std::string> cells;
            cells.reserve(columns);
            for (std::size_t col = 0; col < columns; ++col) {
                cells.push_back(las_format_value(data->values[row * columns + col]));
            }
            r.data_rows.push_back(std::move(cells));
        }
    }

    if (truncated) {
        r.warning =
            "\xE6\x9B\xB2\xE7\xBA\xBF\xE5\x88\x97\xE8\xA1\xA8\xE5\xB7\xB2\xE6"
            "\x8C\x89\xE8\xA1\x8C\xE4\xB8\x8A\xE9\x99\x90\xE6\x88\xAA\xE6\x96"
            "\xAD";  // 曲线列表已按行上限截断
    }
    r.truncated = truncated;
    return r;
}

}  // namespace pwb::ingest::preview
