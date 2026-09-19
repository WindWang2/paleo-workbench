#pragma once

// VIZ-D 井分层（formation tops）预览 —— Qt-free 核心 + 纯文本呈现。
//
// 诚实呈现决策：formation tops 的生产消费者是预测/成图后处理管线
// （libs/prediction postprocess —— pwb::ingest::parse_well_tops_text 的
// 行级结果在那里进入 boundaries 归一化）；预览页呈现的是同一 parser 解析
// 出的真实分层表/统计（不是占位符、不重复解析逻辑）。图形化的岩性条带
// 留在 mapping/连井消费者一侧（geo-viz-engine geoviz_cross_well 的
// FormationTopsPreviewWidget），本模块不重复实现。
//
// 与 Python 预览侧（geoviz/previews/dat.py `_well_stratification_payload`）
// 的关系：Python 在渲染前用 representative_indices/max_points 采样并按
// 井重排后交给连井条带控件；这里按任务约定给出全量分层表 + 统计（采样
// 是渲染侧策略，属 E/连井消费者的职责）。行内容（井名/层位/MD/TVD）与
// parser 语义完全一致。

#include <cstddef>
#include <string>
#include <vector>

#include <pwb/ingest/well_parsers.hpp>

namespace pwb::ui_pages_preview::formation_tops {

// 一行分层（TVD 缺失时 tvd 为空串；md/tvd 均按 "%.2f" 语义格式化）。
struct FormationTopsRow {
    std::string well;
    std::string top;
    std::string md;   // "%.2f"
    std::string tvd;  // "%.2f"，缺失为 ""
};

// 按井分组（文件出现顺序 = 插入序），组内保持解析顺序。
struct FormationTopsWellGroup {
    std::string well;
    std::vector<FormationTopsRow> rows;
};

struct FormationTopsSummary {
    std::vector<FormationTopsWellGroup> wells;
    std::size_t total_wells{0};
    std::size_t total_tops{0};
};

// 由 libs/ingest parse_well_tops_text 的输出构建汇总（Qt-free、无 I/O）。
FormationTopsSummary build_formation_tops_summary(
    const std::vector<pwb::ingest::WellTop>& tops);

// 纯文本分层表（E 挂到 message/text 型渲染；Qt-free 字符串拼装）。
// 首行统计 "井数: N · 层位点: M"（对齐 dat.py 的 summary_rows 口径），
// 随后是 "井名/层位/MD/TDV" 表头与数据行；列宽按码点数对齐。
std::string make_formation_tops_preview_text(const FormationTopsSummary& summary);

// "%.2f"（Python f"{v:.2f}" 的四舍五入口径由 snprintf 提供）。
std::string format_depth(double value);

}  // namespace pwb::ui_pages_preview::formation_tops
