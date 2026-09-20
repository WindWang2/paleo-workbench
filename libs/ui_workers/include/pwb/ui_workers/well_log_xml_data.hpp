#pragma once

// 05 线 — XML 井曲线真加载的纯数据核（Qt-free、无 WLE 依赖）。
//
// 语义逐条对齐冻结参考（不改其行为）：
//   * 识别：paleo_workbench/resources/well_log_xml.py is_well_log_xml
//     （WITSML 三件套 / witsml 根或标签 + 两件套 / 具名工作表；200k 元素
//     有界扫描；defusedxml 优先 → 实体禁止语义）。
//   * 加载：geo-viz-engine@08851951
//     packages/geoviz_well_log/geoviz_well_log/xml_preview.py load_xml_preview
//     （SpreadsheetML 工作表含 ss:Index 列填充、测井曲线表优先、深度列
//     推断、uniform stride 抽稀、-9000 哨兵与 NaN 保留、max_curves 截断、
//     岩性/地层/相/文本/标准层 区间表提取；XML 不声明深度单位——诚实
//     保持未声明状态，绝不推断为 m）。
//
// 展示侧关注点（display_range/颜色）不在此核：与 LAS 路径一致，由宿主
// 的 presentation 构建期计算，解析载荷只承载数据事实。
//
// 失败语义：语法错误（XML 不是良构）由调用方以识别失败/None 处理；
// 数据语义错误（无数据行、采样点 < 2）抛 std::invalid_argument——
// 经 worker_common 的 py_error_class_name 映射为 Python 的 "ValueError"。

#include <cstddef>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::ui_workers {

// 与 resources/well_log_xml.py 同语义的有界识别：仅当内容显式呈现
// WITSML 或测井 SpreadsheetML 语义时为真；文件名提示不参与判断。
// 解析失败（含实体禁止）一律 false。
[[nodiscard]] bool is_well_log_xml_bytes(std::string_view bytes);

// 一条 XML 井曲线：采样共享缓冲（供 WLE BufferView::from_vector 零拷贝
// 消费），values 允许 NaN（缺测样本，与 Python 参考一致）；depth 无 NaN
//（坏深度行在解析期整行剔除）。unit 来自表头名启发（_unit_for_header）。
struct WellLogXmlCurve {
    std::string name;
    std::string unit;
    std::shared_ptr<const std::vector<double>> depth;
    std::shared_ptr<const std::vector<double>> values;
};

// 区间/标准层记录（kinds：岩性/相/地层/文本描述；horizon 单列）。
struct WellLogXmlInterval {
    double top = 0.0;
    double bottom = 0.0;
    std::string label;
};

struct WellLogXmlData {
    std::string well_name;
    double top_depth = 0.0;
    double bottom_depth = 0.0;
    std::vector<WellLogXmlCurve> curves;
    std::vector<WellLogXmlInterval> lithology;
    std::vector<WellLogXmlInterval> facies;
    std::vector<WellLogXmlInterval> formation;
    std::vector<WellLogXmlInterval> text_desc;
    // 标准层道：top 为标记深度，bottom=top+1（Python IntervalItem 形状）。
    std::vector<WellLogXmlInterval> horizons;
    // 抽稀事实（#1193 诚实采样记录的输入）：文件声明的数据行数与实际
    // 采样的 stride（1 = 每行保留）。
    std::size_t total_rows = 0;
    std::size_t sample_stride = 1;
};

// 有界加载（load_xml_preview 逐条移植）。max_curves=30、
// max_samples=100_000 与 Python 生产调用点
//（viz/well_log_load.py _load_well_log → load_xml_preview）同值。
// path_name 仅用于错误消息（Python 用 Path(path).name）。
// 抛 std::invalid_argument：无法解析 XML 测井数据 / 采样点小于 2。
[[nodiscard]] WellLogXmlData parse_well_log_xml(std::string_view bytes,
                                                const std::string& path_name,
                                                int max_curves = 30,
                                                std::size_t max_samples = 100000);

}  // namespace pwb::ui_workers
