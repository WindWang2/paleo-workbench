#include <pwb/ui_wellseis/redact.hpp>

#include <algorithm>
#include <cctype>
#include <regex>

namespace pwb::ui_wellseis {

namespace {

// (?i)(authorization\s*:\s*bearer\s+)[^\s,;]+
const std::regex& authorization_re() {
    static const std::regex re(
        R"((authorization\s*:\s*bearer\s+)[^\s,;]+)",
        std::regex_constants::icase | std::regex_constants::optimize);
    return re;
}

// (?i)\b(api[_-]?key|token|secret|password)\s*([=:])\s*[^\s,;&]+
const std::regex& secret_value_re() {
    static const std::regex re(
        R"(\b(api[_-]?key|token|secret|password)\s*([=:])\s*[^\s,;&]+)",
        std::regex_constants::icase | std::regex_constants::optimize);
    return re;
}

std::string trim_copy(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r\n");
    if (first == std::string::npos) {
        return "";
    }
    const auto last = text.find_last_not_of(" \t\r\n");
    return text.substr(first, last - first + 1);
}

bool all_digits(const std::string& text) {
    return !text.empty() &&
           std::all_of(text.begin(), text.end(),
                       [](unsigned char c) { return std::isdigit(c) != 0; });
}

// Minimal urlsplit for "scheme://authority/path?query#fragment". Userinfo
// is stripped from the authority; a non-numeric port counts as an invalid
// endpoint (Python raises ValueError on parsed.port — see ledger).
struct ParsedUrl {
    std::string scheme;
    std::string host;
    std::string port;
    std::string path;
    bool has_authority_marker = false;
    bool ok = false;
};

ParsedUrl parse_url(const std::string& endpoint) {
    ParsedUrl out;
    const std::size_t scheme_end = endpoint.find("://");
    out.has_authority_marker = scheme_end != std::string::npos;
    if (!out.has_authority_marker || scheme_end == 0) {
        return out;
    }
    out.scheme = endpoint.substr(0, scheme_end);
    const std::string rest = endpoint.substr(scheme_end + 3);

    const std::size_t auth_end = rest.find_first_of("/?#");
    std::string authority =
        auth_end == std::string::npos ? rest : rest.substr(0, auth_end);
    if (auth_end != std::string::npos && rest[auth_end] == '/') {
        const std::size_t path_end = rest.find_first_of("?#", auth_end);
        out.path = rest.substr(
            auth_end, path_end == std::string::npos
                          ? std::string::npos
                          : path_end - auth_end);
    }

    const std::size_t at = authority.rfind('@');
    if (at != std::string::npos) {
        authority = authority.substr(at + 1);
    }

    if (!authority.empty() && authority.front() == '[') {
        // Bracketed host (IPv6 literal): host spans to ']'.
        const std::size_t close = authority.find(']');
        if (close == std::string::npos) {
            return out;
        }
        out.host = authority.substr(0, close + 1);
        if (close + 1 < authority.size()) {
            if (authority[close + 1] != ':') {
                return out;
            }
            out.port = authority.substr(close + 2);
        }
    } else {
        const std::size_t colon = authority.rfind(':');
        if (colon == std::string::npos) {
            out.host = authority;
        } else {
            out.host = authority.substr(0, colon);
            out.port = authority.substr(colon + 1);
        }
    }
    if (out.host.empty()) {
        return out;
    }
    if (!out.port.empty() && !all_digits(out.port)) {
        return out;
    }
    out.ok = true;
    return out;
}

}  // namespace

std::string redact_authorization(const std::string& value) {
    return std::regex_replace(value, authorization_re(), "$1<REDACTED>");
}

std::string redact_secret_values(const std::string& value) {
    return std::regex_replace(value, secret_value_re(), "$1$2<REDACTED>");
}

std::string redact_diagnostic_text(const std::string& value) {
    std::string text = redact_authorization(value);
    text = redact_secret_values(text);
    if (text.size() > kDiagnosticCharCap) {
        text.resize(kDiagnosticCharCap);
    }
    return text;
}

std::string redact_endpoint(const std::string& value) {
    const std::string endpoint = trim_copy(value);
    if (endpoint.empty()) {
        return "";
    }
    const ParsedUrl parsed = parse_url(endpoint);
    if (!parsed.has_authority_marker) {
        // urlsplit succeeded but found no scheme/host: Python scrubs the
        // raw string with _SECRET_VALUE_RE.
        return redact_secret_values(endpoint);
    }
    if (!parsed.ok) {
        // urlsplit raised / produced no usable endpoint.
        return "<无效地址>";
    }
    std::string host = parsed.host;
    if (!parsed.port.empty()) {
        host += ":" + parsed.port;
    }
    return parsed.scheme + "://" + host + parsed.path;
}

}  // namespace pwb::ui_wellseis
