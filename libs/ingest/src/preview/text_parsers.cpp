#include "pwb/ingest/preview/text_parsers.hpp"

#include <algorithm>

#include "pwb/ingest/py_compat.hpp"

namespace pwb::ingest::preview {

std::string decode_text_with_fallback(std::string_view bytes) {
    auto strict = decode_utf8_sig(bytes, /*strict=*/true);
    if (strict) return *strict;
    return *decode_utf8_sig(bytes, /*strict=*/false);
}

std::optional<std::vector<std::string>> shlex_split(std::string_view text) {
    // CPython shlex.shlex(posix=True, whitespace_split=True) with
    // whitespace=" \t\r\n", comments disabled, escape='\\', quotes='\'"'
    // and escapedquotes='"' (see lib/shlex.py read_token).
    static const std::string whitespace = " \t\r\n";
    static const char escape = '\\';

    std::vector<std::string> tokens;
    std::string token;
    char state = ' ';
    char escapedstate = ' ';
    bool quoted = false;
    size_t i = 0;
    auto nextchar = [&]() -> std::optional<char> {
        if (i >= text.size()) return std::nullopt;
        return text[i++];
    };

    while (true) {
        auto nc = nextchar();
        if (!nc) {
            // EOF: read_token terminates per state — quote states raise
            // "No closing quotation", the escape state raises "No escaped
            // character", 'a' emits its pending token, ' ' emits nothing.
            if (state == '"' || state == '\'') return std::nullopt;
            if (state == escape) return std::nullopt;
            if (state == 'a' && (!token.empty() || quoted)) {
                tokens.push_back(token);
            }
            break;
        }
        char c = *nc;
        switch (state) {
            case ' ':
                if (whitespace.find(c) != std::string::npos) {
                    if (!token.empty() || quoted) {
                        tokens.push_back(token);
                        token.clear();
                        quoted = false;
                        state = ' ';
                        continue;
                    }
                } else if (c == '"' || c == '\'') {
                    state = c;
                } else if (c == escape) {
                    escapedstate = 'a';
                    state = escape;
                } else {
                    token.push_back(c);
                    state = 'a';
                }
                break;
            case '"':
            case '\'':
                quoted = true;
                if (c == state) {
                    state = 'a';
                } else if (c == escape && state == '"') {
                    escapedstate = state;
                    state = escape;
                } else {
                    token.push_back(c);
                }
                break;
            default:
                if (state == escape) {
                    if (!nc) return std::nullopt;  // No escaped character
                    // In POSIX shells, only the quote itself or the escape
                    // character may be escaped within quotes.
                    if ((escapedstate == '"' || escapedstate == '\'') &&
                        c != escape && c != escapedstate) {
                        token.push_back(state);
                    }
                    token.push_back(c);
                    state = escapedstate;
                    break;
                }
                if (state == 'a') {
                    if (whitespace.find(c) != std::string::npos) {
                        state = ' ';
                        if (!token.empty() || quoted) {
                            tokens.push_back(token);
                            token.clear();
                            quoted = false;
                            continue;
                        }
                    } else if (c == '"' || c == '\'') {
                        state = c;
                    } else if (c == escape) {
                        escapedstate = 'a';
                        state = escape;
                    } else {
                        token.push_back(c);
                    }
                    break;
                }
                break;
        }
    }
    return tokens;
}

std::vector<std::vector<std::string>> csv_reader(std::string_view text, char delimiter) {
    // CPython _csv.c state machine, excel dialect, strict=False,
    // doublequote=True, skipinitialspace=False, escapechar=None. Blank lines
    // emit empty records; only the terminator after a quoted field enters
    // EatCrnl (matching the CPython reader's record emission exactly).
    enum class St { StartRecord, StartField, InField, InQuotedField,
                    QuoteInQuotedField, EatCrnl };
    std::vector<std::vector<std::string>> records;
    std::vector<std::string> record;
    std::string field;
    St state = St::StartRecord;

    auto save_field = [&]() {
        record.push_back(field);
        field.clear();
    };
    auto emit_record = [&]() {
        records.push_back(record);
        record.clear();
    };

    for (char c : text) {
        switch (state) {
            case St::StartRecord:
                if (c == '\n') {
                    emit_record();  // blank line -> one empty record
                    state = St::StartRecord;
                } else if (c == '\r') {
                    state = St::EatCrnl;  // CPython: \r alone emits nothing
                } else if (c == delimiter) {
                    save_field();  // leading empty field
                    state = St::StartField;
                } else if (c == '"') {
                    state = St::InQuotedField;
                } else {
                    field.push_back(c);
                    state = St::InField;
                }
                break;
            case St::StartField:
                if (c == '\n' || c == '\r') {
                    save_field();
                    emit_record();
                    state = St::StartRecord;
                } else if (c == delimiter) {
                    save_field();
                    state = St::StartField;
                } else if (c == '"') {
                    state = St::InQuotedField;
                } else {
                    field.push_back(c);
                    state = St::InField;
                }
                break;
            case St::InField:
                if (c == '\n' || c == '\r') {
                    save_field();
                    emit_record();
                    state = St::StartRecord;
                } else if (c == delimiter) {
                    save_field();
                    state = St::StartField;
                } else {
                    field.push_back(c);
                }
                break;
            case St::InQuotedField:
                if (c == '"') {
                    state = St::QuoteInQuotedField;
                } else {
                    field.push_back(c);  // newlines included
                }
                break;
            case St::QuoteInQuotedField:
                if (c == '"') {  // doubled quote
                    field.push_back('"');
                    state = St::InQuotedField;
                } else if (c == delimiter) {
                    save_field();
                    state = St::StartField;
                } else if (c == '\n' || c == '\r') {
                    save_field();
                    emit_record();
                    state = St::EatCrnl;
                } else {
                    // closing quote followed by junk: characters are appended
                    field.push_back(c);
                    state = St::InField;
                }
                break;
            case St::EatCrnl:
                if (c == '\n' || c == '\r') break;  // consume the terminator
                state = St::StartRecord;
                // reprocess this character as a new record
                if (c == delimiter) {
                    record.push_back("");
                    state = St::StartField;
                } else if (c == '"') {
                    state = St::InQuotedField;
                } else {
                    field.push_back(c);
                    state = St::InField;
                }
                break;
        }
    }
    // EOF: CPython saves any pending field (including an open quoted field)
    // and emits the pending record.
    if (state == St::InField || state == St::InQuotedField ||
        state == St::QuoteInQuotedField || state == St::StartField) {
        save_field();
    }
    if (!record.empty()) records.push_back(record);
    return records;
}

namespace {

PreviewResult base_result(std::string mode, const ResourceRef& resource) {
    PreviewResult r;
    r.mode = std::move(mode);
    r.title = resource.name;
    r.path = resource.path;
    r.revision = resource.revision;
    r.format = resource.format;
    r.status = resource.status;
    r.type_label = resource.type;
    return r;
}

std::string truncation_warning(int kib) {
    return "\xE4\xBB\x85\xE6\x98\xBE\xE7\xA4\xBA\xE5\x89\x8D " + std::to_string(kib) +
           " KiB";  // 仅显示前 N KiB
}

}  // namespace

PreviewResult text_preview(const ResourceRef& resource, std::string_view bytes,
                           const PreviewSettings& settings) {
    size_t limit = static_cast<size_t>(settings.text_limit_kib) * 1024;
    std::string_view chunk = bytes.substr(0, limit);
    bool truncated = bytes.size() > limit;
    PreviewResult r = base_result("text", resource);
    r.text = decode_text_with_fallback(chunk);
    r.warning = truncated ? truncation_warning(settings.text_limit_kib) : "";
    r.truncated = truncated;
    return r;
}

PreviewResult table_preview(const ResourceRef& resource, std::string_view bytes,
                            char delimiter, const PreviewSettings& settings) {
    size_t limit = static_cast<size_t>(settings.text_limit_kib) * 1024;
    std::string_view chunk = bytes.substr(0, limit);
    bool truncated = bytes.size() > limit;
    std::string text = *decode_utf8_sig(chunk, /*strict=*/false);
    auto rows = csv_reader(text, delimiter);
    std::vector<std::vector<std::string>> parsed;
    for (size_t i = 0; i < rows.size(); ++i) {
        if (static_cast<int>(i) > settings.table_max_rows) {
            truncated = true;
            break;
        }
        if (static_cast<int>(rows[i].size()) > settings.table_max_columns) {
            truncated = true;
        }
        auto row = rows[i];
        if (row.size() > static_cast<size_t>(settings.table_max_columns)) {
            row.resize(static_cast<size_t>(settings.table_max_columns));
        }
        parsed.push_back(std::move(row));
    }
    PreviewResult r = base_result("table", resource);
    if (!parsed.empty()) {
        r.table_headers = parsed[0];
        r.table_rows.assign(parsed.begin() + 1, parsed.end());
    }
    r.warning = truncated ? "\xE8\xA1\xA8\xE6\xA0\xBC\xE9\xA2\x84\xE8\xA7\x88\xE5\xB7\xB2\xE6\x8C\x89\xE8\xA1\x8C\xE5\x88\x97\xE4\xB8\x8A\xE9\x99\x90\xE6\x88\xAA\xE6\x96\xAD"  // 表格预览已按行列上限截断
                          : "";
    r.truncated = truncated;
    return r;
}

PreviewResult dat_preview(const ResourceRef& resource, std::string_view bytes,
                          const PreviewSettings& settings) {
    auto text_fallback = [&]() {
        return text_preview(resource, bytes, settings);
    };
    size_t limit = static_cast<size_t>(settings.text_limit_kib) * 1024;
    std::string_view chunk = bytes.substr(0, limit);
    bool byte_truncated = bytes.size() > limit;
    if (byte_truncated && !chunk.empty() && chunk.back() != '\n' &&
        chunk.back() != '\r') {
        // Python max(rfind('\n'), rfind('\r')) treats -1 as absent; npos is
        // SIZE_MAX, so resolve the two candidates explicitly.
        size_t lf = chunk.rfind('\n');
        size_t cr = chunk.rfind('\r');
        size_t last_break = std::max(lf, cr);
        if (lf == std::string_view::npos) last_break = cr;
        else if (cr == std::string_view::npos) last_break = lf;
        chunk = chunk.substr(0, last_break == std::string_view::npos
                                   ? 0
                                   : last_break + 1);
    }
    std::string preview_text = *decode_utf8_sig(chunk, /*strict=*/false);
    std::vector<std::vector<std::string>> header_candidates;
    std::vector<std::vector<std::string>> data_rows;
    size_t pos = 0;
    while (pos <= preview_text.size()) {
        // str.splitlines() for these inputs: \n, \r\n and lone \r
        size_t eol = preview_text.find('\n', pos);
        size_t alt = preview_text.find('\r', pos);
        if (alt != std::string::npos && (eol == std::string::npos || alt < eol) &&
            (alt + 1 >= preview_text.size() || preview_text[alt + 1] != '\n')) {
            eol = alt;  // lone \r terminates the line
        }
        size_t line_end = eol == std::string::npos ? preview_text.size() : eol + 1;
        std::string_view line(preview_text.data() + pos, line_end - pos);
        pos = line_end;
        if (eol == std::string::npos && line.empty()) break;
        while (!line.empty() && (line.back() == '\n' || line.back() == '\r')) {
            line.remove_suffix(1);
        }
        std::string stripped = py_strip(line);
        if (stripped.empty()) continue;
        bool is_comment = stripped[0] == '#';
        std::string token_source;
        if (is_comment) {
            // lstrip('#'): a line of only '#' yields "" and is skipped
            size_t first = stripped.find_first_not_of('#');
            token_source =
                first == std::string::npos ? "" : py_strip(stripped.substr(first));
        } else {
            token_source = stripped;
        }
        auto tokens = shlex_split(token_source);
        if (!tokens) return text_fallback();
        if (tokens->empty()) continue;
        if (is_comment) {
            std::string first = (*tokens)[0];
            for (auto& ch : first) {
                if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + 32);
            }
            while (!first.empty() && first.back() == ':') first.pop_back();
            std::string marker;
            for (size_t t = 0; t < tokens->size(); ++t) {
                if (t) marker.push_back(' ');
                marker += (*tokens)[t];
            }
            for (auto& ch : marker) {
                if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + 32);
            }
            if (first != "field" && first != "type" &&
                marker.find("file from smi") == std::string::npos) {
                header_candidates.push_back(std::move(*tokens));
            }
            continue;
        }
        data_rows.push_back(std::move(*tokens));
    }

    if (data_rows.size() < 2) return text_fallback();
    size_t row_width = data_rows[0].size();
    if (row_width < 2) return text_fallback();
    for (const auto& row : data_rows) {
        if (row.size() != row_width) return text_fallback();
    }

    std::vector<std::string> header;
    bool found = false;
    for (auto it = header_candidates.rbegin(); it != header_candidates.rend(); ++it) {
        if (it->size() == row_width) {
            header = *it;
            found = true;
            break;
        }
    }
    if (!found) {
        for (size_t i = 0; i < row_width; ++i) {
            header.push_back("\xE5\x88\x97 " + std::to_string(i + 1));  // 列 N
        }
    }
    bool truncated =
        byte_truncated || static_cast<int>(data_rows.size()) > settings.table_max_rows ||
        static_cast<int>(row_width) > settings.table_max_columns;
    PreviewResult r = base_result("table", resource);
    size_t column_limit =
        std::min<size_t>(header.size(), static_cast<size_t>(settings.table_max_columns));
    r.table_headers.assign(header.begin(), header.begin() + column_limit);
    for (size_t i = 0;
         i < data_rows.size() && i < static_cast<size_t>(settings.table_max_rows);
         ++i) {
        auto& row = data_rows[i];
        size_t n =
            std::min<size_t>(row.size(), static_cast<size_t>(settings.table_max_columns));
        r.table_rows.emplace_back(row.begin(), row.begin() + n);
    }
    r.warning = truncated ? "\xE6\x95\xB0\xE6\x8D\xAE\xE5\x88\x97\xE8\xA1\xA8\xE5\xB7\xB2\xE6\x8C\x89\xE9\xA2\x84\xE8\xA7\x88\xE4\xB8\x8A\xE9\x99\x90\xE6\x88\xAA\xE6\x96\xAD"  // 数据列表已按预览上限截断
                          : "";
    r.truncated = truncated;
    return r;
}

}  // namespace pwb::ingest::preview
