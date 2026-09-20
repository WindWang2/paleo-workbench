// intent.cpp — IntentParser port. The Python regex
//   ([T|J|K|P|C|D|S|O|Є]\w+|\w+组|\w+段)
// is reimplemented as a code-point scanner: alternation order and greedy
// backtracking (last occurrence of 组/段 inside the maximal word run wins;
// the ASCII-letter alternative anchors only when the NEXT char is a word
// char) reproduce Python's leftmost-match semantics on geological text.
// Unicode word chars are approximated as ASCII [0-9A-Za-z_] plus CJK/kana/
// fullwidth-alnum blocks — fullwidth punctuation (，。 etc.) is NOT a word
// char, matching Python. Documented approximation; oracle-frozen verdicts
// live in closure_agent_tests/agent_oracle.json.
#include <pwb/closure_agent/intent.hpp>

#include <algorithm>
#include <cstdint>
#include <vector>

namespace pwb::closure_agent {

std::string to_string(TaskDomain domain) {
    switch (domain) {
        case TaskDomain::DataManagement: return "data";
        case TaskDomain::WellLogging: return "well";
        case TaskDomain::SeismicInterpretation: return "seismic";
        case TaskDomain::SpatialGis: return "gis";
        case TaskDomain::SingleFactorMapping: return "cartography";
        case TaskDomain::PaleomapCompilation: return "compilation";
        case TaskDomain::Visualization: return "visualization";
        case TaskDomain::QualityControl: return "qa";
        case TaskDomain::General: return "general";
    }
    return "general";
}

std::optional<TaskDomain> task_domain_from_string(const std::string& value) {
    if (value == "data") return TaskDomain::DataManagement;
    if (value == "well") return TaskDomain::WellLogging;
    if (value == "seismic") return TaskDomain::SeismicInterpretation;
    if (value == "gis") return TaskDomain::SpatialGis;
    if (value == "cartography") return TaskDomain::SingleFactorMapping;
    if (value == "compilation") return TaskDomain::PaleomapCompilation;
    if (value == "visualization") return TaskDomain::Visualization;
    if (value == "qa") return TaskDomain::QualityControl;
    if (value == "general") return TaskDomain::General;
    return std::nullopt;
}

Json ParsedIntent::to_dict() const {
    Json dict = Json::object();
    dict["raw_query"] = raw_query;
    dict["primary_domain"] = to_string(primary_domain);
    Json secondary = Json::array();
    for (const auto domain : secondary_domains) secondary.push_back(to_string(domain));
    dict["secondary_domains"] = secondary;
    dict["action_goal"] = action_goal;
    dict["parameters"] = parameters;
    dict["target_horizon"] = target_horizon;
    dict["factor_type"] = factor_type;
    dict["suggested_skills"] = suggested_skills;
    dict["requires_data"] = requires_data;
    dict["confidence"] = confidence;
    return dict;
}

namespace {

std::string ascii_lower(const std::string& text) {
    std::string lowered = text;
    for (char& ch : lowered) {
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch - 'A' + 'a');
    }
    return lowered;
}

// Decode one UTF-8 code point starting at `pos`; advances `pos`.
std::uint32_t decode_code_point(const std::string& text, std::size_t& pos) {
    const auto lead = static_cast<unsigned char>(text[pos]);
    if (lead < 0x80) {
        ++pos;
        return lead;
    }
    std::size_t extra = 0;
    std::uint32_t value = 0;
    if ((lead & 0xE0) == 0xC0) {
        extra = 1;
        value = lead & 0x1F;
    } else if ((lead & 0xF0) == 0xE0) {
        extra = 2;
        value = lead & 0x0F;
    } else {
        extra = 3;
        value = lead & 0x07;
    }
    for (std::size_t i = 0; i < extra && pos + 1 < text.size(); ++i) {
        ++pos;
        value = (value << 6) | (static_cast<unsigned char>(text[pos]) & 0x3F);
    }
    ++pos;
    return value;
}

// Python \w for the geological text domain: ASCII word chars + CJK/kana/
// fullwidth alphanumerics. Punctuation (CJK or fullwidth) is excluded.
bool is_word_code_point(std::uint32_t cp) {
    if ((cp >= '0' && cp <= '9') || (cp >= 'A' && cp <= 'Z') ||
        (cp >= 'a' && cp <= 'z') || cp == '_') {
        return true;
    }
    // Hiragana / Katakana
    if (cp >= 0x3041 && cp <= 0x30FF) return true;
    // CJK Extension A + CJK Unified Ideographs
    if (cp >= 0x3400 && cp <= 0x9FFF) return true;
    // CJK Compatibility Ideographs
    if (cp >= 0xF900 && cp <= 0xFA6D) return true;
    // Fullwidth ASCII digits/letters
    if (cp >= 0xFF10 && cp <= 0xFF19) return true;
    if (cp >= 0xFF21 && cp <= 0xFF3A) return true;
    if (cp >= 0xFF41 && cp <= 0xFF5A) return true;
    return false;
}

bool is_word_at(const std::string& text, std::size_t byte_pos) {
    if (byte_pos >= text.size()) return false;
    // Word chars never appear as a UTF-8 continuation byte at a start
    // position; decode and classify.
    std::size_t next = byte_pos;
    return is_word_code_point(decode_code_point(text, next));
}

std::size_t next_code_point(const std::string& text, std::size_t byte_pos) {
    std::size_t next = byte_pos;
    decode_code_point(text, next);
    return next;
}

bool contains(const std::string& haystack_lower, const std::string& needle) {
    return haystack_lower.find(needle) != std::string::npos;
}

// The frozen keyword table (dict insertion order matters for stable-sorted
// ties). Chinese needles are matched on the raw query; ASCII needles on the
// lowercased pair (Python lowers both sides).
const std::vector<std::pair<TaskDomain, std::vector<std::string>>>& keyword_table() {
    static const std::vector<std::pair<TaskDomain, std::vector<std::string>>> table = {
        {TaskDomain::WellLogging,
         {"井", "测井", "曲线", "连井", "对比", "分层", "标志层", "GR", "DTW", "拉平"}},
        {TaskDomain::SeismicInterpretation,
         {"地震", "剖面", "切片", "相干", "Inline", "Crossline", "Time", "层位", "断层",
          "等值面"}},
        {TaskDomain::SpatialGis,
         {"空间", "缓冲区", "拓扑", "自相交", "投影", "坐标", "叠加", "相交", "多边形",
          "图层"}},
        {TaskDomain::SingleFactorMapping,
         {"单因素", "插值", "IDW", "砂地比", "孔隙度", "厚度", "各向异性", "廊道",
          "等值线", "网格"}},
        {TaskDomain::PaleomapCompilation,
         {"古地理", "编图", "岩相", "相带", "沉积", "图例", "指北针", "比例尺", "排版",
          "出版"}},
        {TaskDomain::DataManagement,
         {"导入", "资产", "版本", "血缘", "CAS", "RAW", "catalog", "存储", "清洗"}},
        {TaskDomain::QualityControl,
         {"质检", "QC", "合规", "残差", "检查", "修复", "自愈", "孤立点", "极值"}},
        {TaskDomain::Visualization,
         {"三维", "渲染", "视口", "导出", "SVG", "PDF", "PNG", "GeoTIFF", "截图",
          "高精"}},
    };
    return table;
}

bool domain_keyword_hit(const std::string& keyword, const std::string& raw,
                        const std::string& raw_lower) {
    const std::string lowered = ascii_lower(keyword);
    if (lowered != keyword) {
        // ASCII-bearing keyword: case-insensitive containment.
        return raw_lower.find(lowered) != std::string::npos;
    }
    return raw.find(keyword) != std::string::npos;
}

}  // namespace

std::optional<std::string> match_target_horizon(const std::string& query) {
    const std::uint32_t pipe = U'|';
    const std::uint32_t epsilon = 0x0404;   // Є
    const std::uint32_t zu = 0x7EC4;        // 组
    const std::uint32_t duan = 0x6BB5;      // 段
    auto is_alt1_head = [&](std::uint32_t cp) {
        switch (cp) {
            case U'T': case U'J': case U'K': case U'P': case U'C': case U'D':
            case U'S': case U'O': case pipe: case epsilon:
                return true;
            default:
                return false;
        }
    };
    std::size_t pos = 0;
    while (pos < query.size()) {
        const std::size_t char_start = pos;
        const std::uint32_t cp = decode_code_point(query, pos);
        // Alternative 1: [T|JKPCDSOЄ]\w+ — needs one word char after.
        if (is_alt1_head(cp) && is_word_at(query, pos)) {
            std::size_t run_end = pos;
            while (run_end < query.size() && is_word_at(query, run_end)) {
                run_end = next_code_point(query, run_end);
            }
            return query.substr(char_start, run_end - char_start);
        }
        // Alternatives 2/3 start at a word char: scan the maximal run.
        if (is_word_code_point(cp)) {
            std::vector<std::size_t> offsets;
            std::size_t run_end = char_start;
            while (run_end < query.size() && is_word_at(query, run_end)) {
                offsets.push_back(run_end);
                run_end = next_code_point(query, run_end);
            }
            // \w+组 / \w+段 with Python greedy backtracking: the LAST run
            // position k (k >= 1, so \w+ keeps at least one char) holding the
            // literal wins; the match ends right after it. Alternative 2 (组)
            // exhausts fully before 3 (段) is tried.
            auto match_literal = [&](std::uint32_t literal)
                -> std::optional<std::string> {
                for (std::size_t k = offsets.size(); k-- > 1;) {
                    std::size_t at = offsets[k];
                    if (decode_code_point(query, at) == literal) {
                        const std::size_t end =
                            k + 1 < offsets.size() ? offsets[k + 1] : run_end;
                        return query.substr(char_start, end - char_start);
                    }
                }
                return std::nullopt;
            };
            if (auto match = match_literal(zu)) return *match;
            if (auto match = match_literal(duan)) return *match;
        }
        pos = next_code_point(query, char_start);
    }
    return std::nullopt;
}

ParsedIntent IntentParser::parse(const std::string& user_query,
                                 const Json& context) const {
    const std::string query = user_query;
    const std::string raw_lower = ascii_lower(query);

    // Domain scoring: stable sort by score desc, tie keeps table order.
    std::vector<std::pair<int, TaskDomain>> matched;
    for (const auto& [domain, keywords] : keyword_table()) {
        int score = 0;
        for (const auto& keyword : keywords) {
            if (domain_keyword_hit(keyword, query, raw_lower)) ++score;
        }
        if (score > 0) matched.emplace_back(score, domain);
    }
    std::stable_sort(matched.begin(), matched.end(),
                     [](const auto& a, const auto& b) { return a.first > b.first; });

    ParsedIntent intent;
    intent.raw_query = query;
    if (!matched.empty()) {
        intent.primary_domain = matched.front().second;
        for (std::size_t i = 1; i < matched.size(); ++i) {
            intent.secondary_domains.push_back(matched[i].second);
        }
        intent.confidence = 0.95;
    } else {
        intent.primary_domain = TaskDomain::General;
        intent.confidence = 0.5;
    }

    const auto horizon = match_target_horizon(query);
    if (horizon) intent.target_horizon = *horizon;

    // factor_type mapping (first hit wins, fixed order).
    if (contains(query, "砂地比") || contains(query, "砂岩")) {
        intent.factor_type = "sand_ratio";
    } else if (contains(query, "厚度")) {
        intent.factor_type = "thickness";
    } else if (contains(query, "孔隙度")) {
        intent.factor_type = "porosity";
    } else if (contains(query, "渗透率")) {
        intent.factor_type = "permeability";
    }

    // Suggested skills (fixed order, conditions as in Python).
    if (intent.primary_domain == TaskDomain::SingleFactorMapping ||
        contains(query, "单因素")) {
        intent.suggested_skills.push_back("skill.single_factor_mapping_pipeline");
    }
    if (intent.primary_domain == TaskDomain::WellLogging ||
        contains(query, "对比") || contains(query, "对齐")) {
        intent.suggested_skills.push_back("skill.well_correlation_pipeline");
    }
    if (intent.primary_domain == TaskDomain::PaleomapCompilation ||
        contains(query, "编图")) {
        intent.suggested_skills.push_back("skill.comprehensive_paleomap_pipeline");
    }

    // parameters = dict(context or {}) + horizon/factor overrides.
    if (context.is_object()) {
        intent.parameters = context;
    } else {
        intent.parameters = Json::object();
    }
    if (!intent.target_horizon.empty()) {
        intent.parameters["target_horizon"] = intent.target_horizon;
    }
    if (!intent.factor_type.empty()) {
        intent.parameters["factor_type"] = intent.factor_type;
    }

    intent.action_goal = query;
    intent.requires_data = true;
    return intent;
}

}  // namespace pwb::closure_agent
