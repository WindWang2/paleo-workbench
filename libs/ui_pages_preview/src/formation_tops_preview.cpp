// VIZ-D 井分层预览核心实现 —— 见头文件的诚实呈现决策（真实解析表，
// 生产消费者是 libs/prediction postprocess；岩性条带归 mapping/连井）。

#include <pwb/ui_pages_preview/formation_tops_preview.hpp>

#include <algorithm>
#include <cstdio>
#include <map>
#include <string>
#include <string_view>
#include <utility>

namespace pwb::ui_pages_preview::formation_tops {

namespace {

std::size_t code_point_count(std::string_view s) {
    // 列对齐按码点数计（CJK 显示宽度不参与；纯文本预览的既定近似）。
    std::size_t count = 0;
    for (const char c : s) {
        if (static_cast<unsigned char>(c) < 0x80 ||
            (static_cast<unsigned char>(c) & 0xC0) != 0x80) {
            ++count;  // ASCII 或多字节序列首字节
        }
    }
    return count;
}

std::string pad_to(std::string_view value, std::size_t width) {
    std::string out(value);
    const std::size_t current = code_point_count(out);
    if (current < width) {
        out.append(width - current, ' ');
    }
    return out;
}

}  // namespace

std::string format_depth(double value) {
    char buffer[64];
    const int written = std::snprintf(buffer, sizeof(buffer), "%.2f", value);
    if (written <= 0) {
        return {};
    }
    return std::string(buffer, static_cast<std::size_t>(written));
}

FormationTopsSummary build_formation_tops_summary(
    const std::vector<pwb::ingest::WellTop>& tops) {
    FormationTopsSummary summary;
    std::map<std::string, std::size_t> well_index;  // 井名 → wells 下标
    for (const pwb::ingest::WellTop& top : tops) {
        FormationTopsRow row;
        row.well = top.well_name;
        row.top = top.top_name;
        row.md = format_depth(top.md);
        row.tvd = top.tvd.has_value() ? format_depth(*top.tvd) : std::string();
        const auto inserted = well_index.emplace(
            top.well_name, summary.wells.size());
        if (inserted.second) {
            summary.wells.push_back(FormationTopsWellGroup{top.well_name, {}});
        }
        summary.wells[inserted.first->second].rows.push_back(std::move(row));
    }
    summary.total_wells = summary.wells.size();
    summary.total_tops = tops.size();
    return summary;
}

std::string make_formation_tops_preview_text(const FormationTopsSummary& summary) {
    // 统计行口径与 dat.py WellStratificationBackend.prepare 的
    // summary_rows（("层位点", n), ("井数", m)）一致。
    std::string text = "井数: " + std::to_string(summary.total_wells) +
                       " · 层位点: " + std::to_string(summary.total_tops);
    if (summary.wells.empty()) {
        return text;
    }

    std::size_t well_width = code_point_count("井名");
    std::size_t top_width = code_point_count("层位");
    for (const FormationTopsWellGroup& group : summary.wells) {
        for (const FormationTopsRow& row : group.rows) {
            well_width = std::max(well_width, code_point_count(row.well));
            top_width = std::max(top_width, code_point_count(row.top));
        }
    }
    // 两空格列距；MD 右对齐（数字列），TVD 缺失为空。
    text += "\n";
    text += pad_to("井名", well_width) + "  " + pad_to("层位", top_width) +
            "         MD  TVD";
    for (const FormationTopsWellGroup& group : summary.wells) {
        for (const FormationTopsRow& row : group.rows) {
            std::string md = row.md;
            if (md.size() < 9) {
                md.insert(0, 9 - md.size(), ' ');
            }
            text += "\n";
            text += pad_to(row.well, well_width) + "  " +
                    pad_to(row.top, top_width) + "  " + md + "  " + row.tvd;
        }
    }
    return text;
}

}  // namespace pwb::ui_pages_preview::formation_tops
