#include "pwb/ingest/preview/document_parsers.hpp"

#include <cctype>

#include "pwb/ingest/py_compat.hpp"

namespace pwb::ingest::preview {

std::string markdown_to_html(std::string_view markdown) {
    std::vector<std::string> rendered;
    std::vector<std::string> paragraph;
    std::vector<std::string> list_items;
    std::string list_tag;
    std::vector<std::string> code_lines;
    bool in_code_block = false;

    auto flush_paragraph = [&]() {
        if (!paragraph.empty()) {
            std::string joined;
            for (size_t i = 0; i < paragraph.size(); ++i) {
                if (i) joined.push_back(' ');
                joined += paragraph[i];
            }
            rendered.push_back("<p>" + joined + "</p>");
            paragraph.clear();
        }
    };
    auto flush_list = [&]() {
        if (!list_items.empty()) {
            std::string joined;
            for (const auto& item : list_items) joined += item;
            rendered.push_back("<" + list_tag + ">" + joined + "</" + list_tag + ">");
            list_items.clear();
        }
        list_tag.clear();
    };
    auto is_space = [](char c) {
        return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
               c == '\v';
    };

    size_t pos = 0;
    while (pos < markdown.size()) {
        size_t eol = markdown.find('\n', pos);
        size_t end = eol == std::string_view::npos ? markdown.size() : eol + 1;
        std::string_view line = markdown.substr(pos, end - pos);
        pos = end;
        while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
            line.remove_suffix(1);
        }
        if (line.rfind("```", 0) == 0) {
            flush_paragraph();
            flush_list();
            if (in_code_block) {
                std::string code;
                for (size_t i = 0; i < code_lines.size(); ++i) {
                    if (i) code.push_back('\n');
                    code += code_lines[i];
                }
                rendered.push_back("<pre><code>" + code + "</code></pre>");
                code_lines.clear();
            }
            in_code_block = !in_code_block;
            continue;
        }
        std::string escaped = html_escape(line);
        if (in_code_block) {
            code_lines.push_back(escaped);
            continue;
        }
        bool blank = true;
        for (char c : line) {
            if (!is_space(c)) {
                blank = false;
                break;
            }
        }
        if (blank) {
            flush_paragraph();
            flush_list();
            continue;
        }
        // ^("#{1,6})\s+(.*)$
        std::string_view ls = line;
        size_t hashes = 0;
        while (hashes < ls.size() && ls[hashes] == '#' && hashes < 6) ++hashes;
        if (hashes >= 1 && hashes < ls.size() && is_space(ls[hashes])) {
            size_t ws = hashes;
            while (ws < ls.size() && is_space(ls[ws])) ++ws;
            flush_paragraph();
            flush_list();
            rendered.push_back("<h" + std::to_string(hashes) + ">" +
                               html_escape(ls.substr(ws)) + "</h" +
                               std::to_string(hashes) + ">");
            continue;
        }
        // ^[-*]\s+(.*)$ or ^\d+\.\s+(.*)$
        std::string_view item;
        std::string next_list_tag;
        if (!ls.empty() && (ls[0] == '-' || ls[0] == '*') && ls.size() > 1 &&
            is_space(ls[1])) {
            size_t ws = 1;
            while (ws < ls.size() && is_space(ls[ws])) ++ws;
            next_list_tag = "ul";
            item = ls.substr(ws);
        } else {
            size_t d = 0;
            while (d < ls.size() && std::isdigit(static_cast<unsigned char>(ls[d]))) ++d;
            if (d > 0 && d + 1 < ls.size() && ls[d] == '.' && is_space(ls[d + 1])) {
                size_t ws = d + 1;
                while (ws < ls.size() && is_space(ls[ws])) ++ws;
                next_list_tag = "ol";
                item = ls.substr(ws);
            }
        }
        if (!next_list_tag.empty()) {
            if (!list_tag.empty() && list_tag != next_list_tag) flush_list();
            flush_paragraph();
            list_tag = next_list_tag;
            list_items.push_back("<li>" + html_escape(item) + "</li>");
            continue;
        }

        flush_list();
        paragraph.push_back(escaped);
    }

    if (in_code_block) {
        std::string code;
        for (size_t i = 0; i < code_lines.size(); ++i) {
            if (i) code.push_back('\n');
            code += code_lines[i];
        }
        rendered.push_back("<pre><code>" + code + "</code></pre>");
    }
    flush_paragraph();
    flush_list();
    std::string out;
    for (size_t i = 0; i < rendered.size(); ++i) {
        if (i) out.push_back('\n');
        out += rendered[i];
    }
    return out;
}

namespace {

struct JsonCursor {
    std::string_view s;
    size_t i = 0;

    bool eof() const { return i >= s.size(); }
    char peek() const { return s[i]; }
    void skip_ws() {
        while (!eof()) {
            char c = s[i];
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                ++i;
            } else {
                break;
            }
        }
    }
    bool literal(std::string_view lit) {
        if (s.compare(i, lit.size(), lit) == 0) {
            i += lit.size();
            return true;
        }
        return false;
    }
};

bool parse_value(JsonCursor& c, int depth);

bool parse_string(JsonCursor& c) {
    while (!c.eof()) {
        char ch = c.peek();
        if (static_cast<unsigned char>(ch) < 0x20) return false;  // strict mode
        if (ch == '"') {
            ++c.i;
            return true;
        }
        if (ch == '\\') {
            ++c.i;
            if (c.eof()) return false;
            char esc = c.peek();
            if (esc == 'u') {
                ++c.i;
                for (int k = 0; k < 4; ++k) {
                    if (c.eof() ||
                        !std::isxdigit(static_cast<unsigned char>(c.peek()))) {
                        return false;
                    }
                    ++c.i;
                }
            } else if (esc == '"' || esc == '\\' || esc == '/' || esc == 'b' ||
                       esc == 'f' || esc == 'n' || esc == 'r' || esc == 't') {
                ++c.i;
            } else {
                return false;
            }
        } else {
            ++c.i;
        }
    }
    return false;  // unterminated
}

bool parse_number(JsonCursor& c) {
    size_t start = c.i;
    if (!c.eof() && c.peek() == '-') ++c.i;
    if (c.eof()) return false;
    if (c.peek() == '0') {
        ++c.i;
        if (!c.eof() && std::isdigit(static_cast<unsigned char>(c.peek()))) return false;
    } else if (!c.eof() && std::isdigit(static_cast<unsigned char>(c.peek()))) {
        while (!c.eof() && std::isdigit(static_cast<unsigned char>(c.peek()))) ++c.i;
    } else {
        return false;
    }
    if (!c.eof() && c.peek() == '.') {
        ++c.i;
        if (c.eof() || !std::isdigit(static_cast<unsigned char>(c.peek()))) return false;
        while (!c.eof() && std::isdigit(static_cast<unsigned char>(c.peek()))) ++c.i;
    }
    if (!c.eof() && (c.peek() == 'e' || c.peek() == 'E')) {
        ++c.i;
        if (!c.eof() && (c.peek() == '+' || c.peek() == '-')) ++c.i;
        if (c.eof() || !std::isdigit(static_cast<unsigned char>(c.peek()))) return false;
        while (!c.eof() && std::isdigit(static_cast<unsigned char>(c.peek()))) ++c.i;
    }
    return c.i > start;
}

bool parse_value(JsonCursor& c, int depth) {
    if (depth > 200) return false;  // recursion guard analog
    c.skip_ws();
    if (c.eof()) return false;
    char ch = c.peek();
    if (ch == '{') {
        ++c.i;
        c.skip_ws();
        if (!c.eof() && c.peek() == '}') {
            ++c.i;
            return true;
        }
        while (true) {
            c.skip_ws();
            if (c.eof() || c.peek() != '"') return false;
            ++c.i;
            if (!parse_string(c)) return false;
            c.skip_ws();
            if (c.eof() || c.peek() != ':') return false;
            ++c.i;
            if (!parse_value(c, depth + 1)) return false;
            c.skip_ws();
            if (c.eof()) return false;
            if (c.peek() == ',') {
                ++c.i;
                continue;
            }
            if (c.peek() == '}') {
                ++c.i;
                return true;
            }
            return false;
        }
    }
    if (ch == '[') {
        ++c.i;
        c.skip_ws();
        if (!c.eof() && c.peek() == ']') {
            ++c.i;
            return true;
        }
        while (true) {
            if (!parse_value(c, depth + 1)) return false;
            c.skip_ws();
            if (c.eof()) return false;
            if (c.peek() == ',') {
                ++c.i;
                continue;
            }
            if (c.peek() == ']') {
                ++c.i;
                return true;
            }
            return false;
        }
    }
    if (ch == '"') {
        ++c.i;
        return parse_string(c);
    }
    if (c.literal("NaN") || c.literal("Infinity") || c.literal("-Infinity")) {
        return true;
    }
    if (c.literal("true") || c.literal("false") || c.literal("null")) return true;
    return parse_number(c);
}

std::string limit_message_body(int mib, bool instructive) {
    // "JSON 文件超过预览设置上限 N MiB" + ("，请在预览设置中提高上限" | "，仅解析前 N MiB")
    std::string head =
        "JSON \xE6\x96\x87\xE4\xBB\xB6\xE8\xB6\x85\xE8\xBF\x87\xE9\xA2\x84\xE8\xA7\x88"
        "\xE8\xAE\xBE\xE7\xBD\xAE\xE4\xB8\x8A\xE9\x99\x90 " +
        std::to_string(mib) + " MiB";
    if (instructive) {
        return head +
               "\xEF\xBC\x8C\xE8\xAF\xB7\xE5\x9C\xA8\xE9\xA2\x84\xE8\xA7\x88\xE8\xAE\xBE"
               "\xE7\xBD\xAE\xE4\xB8\xAD\xE6\x8F\x90\xE9\xAB\x98\xE4\xB8\x8A\xE9\x99\x90";
    }
    return head +
           "\xEF\xBC\x8C\xE4\xBB\x85\xE8\xA7\xA3\xE6\x9E\x90\xE5\x89\x8D " +
           std::to_string(mib) + " MiB";
}

}  // namespace

std::optional<std::string> json_validate(std::string_view text) {
    JsonCursor c{text};
    if (!parse_value(c, 0)) return std::nullopt;
    c.skip_ws();
    if (!c.eof()) return std::nullopt;
    return std::string(text);  // valid; payload tree not materialized (D7)
}

PreviewResult json_preview(const ResourceRef& resource, std::string_view bytes,
                           const PreviewSettings& settings) {
    long long limit = static_cast<long long>(settings.json_limit_mib) * 1024 * 1024;
    bool truncated = static_cast<long long>(bytes.size()) > limit;
    std::string_view raw_bytes =
        truncated ? bytes.substr(0, static_cast<size_t>(limit)) : bytes;

    PreviewResult r;
    r.mode = "json_tree";
    r.title = resource.name;
    r.path = resource.path;
    r.revision = resource.revision;
    r.format = resource.format;
    r.status = resource.status;
    r.type_label = resource.type;

    auto decoded = decode_utf8_sig(raw_bytes, /*strict=*/false);
    auto payload = json_validate(*decoded);
    if (!payload) {
        // parse_error_preview: revision drops to the bare safe_stat tuple
        r.revision.present = true;
        r.revision.has_stat = true;
        r.revision.stat_size = static_cast<long long>(bytes.size());
        r.mode = "message";
        if (truncated) {
            r.message = limit_message_body(settings.json_limit_mib, true);
        } else {
            r.message =
                "JSON \xE8\xA7\xA3\xE6\x9E\x90\xE5\xA4\xB1\xE8\xB4\xA5: "
                "JSONDecodeError";  // JSON 解析失败:
        }
        r.warning = r.message;
        return r;
    }
    r.json_ok = true;
    r.json_truncated = truncated;
    r.warning =
        truncated ? limit_message_body(settings.json_limit_mib, false) : "";
    return r;
}

PreviewResult markdown_rich_preview(const ResourceRef& resource,
                                    std::string_view bytes,
                                    const PreviewSettings& settings) {
    size_t limit = static_cast<size_t>(settings.text_limit_kib) * 1024;
    std::string_view chunk = bytes.substr(0, limit);
    bool truncated = bytes.size() > limit;
    // utf-8-sig decode so a leading BOM does not hide the first heading
    auto decoded = decode_utf8_sig(chunk, /*strict=*/false);
    PreviewResult r;
    r.mode = "rich_text";
    r.title = resource.name;
    r.path = resource.path;
    r.revision = resource.revision;
    r.format = resource.format;
    r.status = resource.status;
    r.type_label = resource.type;
    r.rich_html = markdown_to_html(*decoded);
    r.warning = truncated
                    ? "\xE4\xBB\x85\xE6\x98\xBE\xE7\xA4\xBA\xE5\x89\x8D " +
                          std::to_string(settings.text_limit_kib) + " KiB"
                    : "";
    r.truncated = truncated;
    return r;
}

}  // namespace pwb::ingest::preview
