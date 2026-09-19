#pragma once

// VIZ-D 井位散点（well-head XY scatter）Qt-free 核心 —— geo-viz-engine
// geoviz/previews/dat.py `_well_head_payload` / `XYScatterBackend.prepare`
// 的逐行移植（冻结 oracle）：
//   * `_WELL_HEAD_MARKER "WellHead File From SMI"` 标记检查；
//   * `_column_mapping`（别名 name/well/wellname + x + y，extras 放行）与
//     声明宽度唯一性（"ambiguous well-head column width"）、UWI 投票；
//   * `_source_crs_declaration` / `_unit_declarations` /
//     `_merge_declared_metadata` / `_metadata_provenance` /
//     `_same_explicit_crs`（含 epsg 规范化）元数据语义；
//   * `_split_data_line`（含引号走 shlex 语义，否则按空白切分）的行循环、
//     "列数与声明不一致"、20 条 issue 上限、
//     `井位数据超过 50,000 个有效记录的显示上限` 资源上限、
//     UTF-8-BOM 跳过、`_MAX_HEADER_LINES=256` / `_MAX_HEADER_CHARS=65536`。
//
// ScatterViewSpec 是交给 E 线图表的数据规格（D 只出数据与语义；通用
// 坐标轴/图例绘制归 E）。错误按字符串 fail-closed 返回（对应 Python 的
// GeoVizError INVALID_DATA / RESOURCE_LIMIT 文案），不抛异常。

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace pwb::ui_pages_preview::xy_scatter {

// Python: PreviewRowIssue(source_row, reason) —— source_row 是文件里的
// 物理 1 基行号（含空行/注释行计数）。
struct WellHeadScatterIssue {
    std::int64_t source_row{0};
    std::string reason;
};

// Python: XYPreviewPayload + SourceCoordinateStatus + XYPreviewDiagnostics
// 的并集（本预览用到的字段）。record_ids 是数据行 0 基序号（含失败行），
// source_rows 是物理 1 基行号；uwis 仅在文件声明唯一 UWI 列时非空，
// 否则为空向量（Python 的空 tuple）。
struct WellHeadScatter {
    std::vector<std::string> names;
    std::vector<double> x;
    std::vector<double> y;
    std::vector<std::string> uwis;
    std::vector<std::int64_t> record_ids;
    std::vector<std::int64_t> source_rows;
    std::string source_crs;
    std::string coordinate_units;
    std::string source_crs_provenance;        // "asset+file" / "asset" / "file" / "undeclared"
    std::string coordinate_units_provenance;  // "asset+file" / "asset" / "file" / "unknown"
    std::string comparison_crs;
    std::optional<bool> comparison_matches_source;  // 双方都非空才比较
    std::int64_t total_records{0};
    std::int64_t valid_records{0};
    std::vector<WellHeadScatterIssue> issues;  // 最多 20 条
    std::int64_t omitted_issue_count{0};

    [[nodiscard]] std::int64_t skipped_count() const {
        return total_records - valid_records;
    }
};

struct WellHeadScatterOptions {
    // Python `_well_head_payload` 忽略 PreviewOptions、固定用 _MAX_POINTS
    // （50,000）；这里默认同值。取值 < 1 按 1 处理（自守卫）。
    std::int64_t max_points{50'000};
    // 资产侧显式元数据（PreviewRequest.source_crs / coordinate_units /
    // comparison_crs）。全部为空即纯文件声明路径。
    std::string source_crs;
    std::string coordinate_units;
    std::string comparison_crs;
};

// fail-closed 结果：ok 为假时 error/detail 给出 Python 的 GeoVizError
// 文案 —— 模式错误 error="DAT 数据结构与资源类型不匹配"、detail 为
// _DatSchemaError 的 str；资源超限 error 为
// "井位数据超过 {limit} 个有效记录的显示上限"（千分位逗号）且
// resource_limit=true。
struct WellHeadScatterResult {
    bool ok{false};
    bool resource_limit{false};
    std::string error;
    std::string detail;
    WellHeadScatter payload;
};

// 输入是已解码的 DAT 全文（UTF-8；文件级 BOM 由本函数跳过，等价
// encoding="utf-8-sig"）。函数不读文件、不起子进程。
WellHeadScatterResult build_well_head_scatter(
    std::string_view text, const WellHeadScatterOptions& options = {});

// ---------------------------------------------------------------------------
// E 线图表的数据规格（XYScatterBackend.prepare / render 语义）
// ---------------------------------------------------------------------------

// Python render(): 坐标单位已知时轴标签为 "X (unit)" / "Y (unit)"，
// 否则裸 "X" / "Y"。warnings 按 prepare 的顺序拼装（" · " 连接成
// warning 文本）；summary_rows 为 (("有效井数", n), ("源记录", total))。
struct ScatterViewSpec {
    std::string title;
    std::string x_axis_label;
    std::string y_axis_label;
    std::vector<std::string> warnings;
    std::string warning;  // warnings 以 " · " 连接（PreparedPreview.warning）
    std::vector<std::pair<std::string, std::string>> summary_rows;
};

ScatterViewSpec make_scatter_view_spec(const WellHeadScatter& scatter,
                                       std::string title);

}  // namespace pwb::ui_pages_preview::xy_scatter
