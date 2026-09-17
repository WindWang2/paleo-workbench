#include "pwb/ingest/xml_scanner.hpp"

#include <map>

namespace pwb::ingest {

namespace {

[[noreturn]] void parse_error(const std::string& msg) {
    throw XmlError("ParseError", msg);
}

std::string trim_ascii(const std::string& s) {
    size_t b = 0, e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\n' || s[b] == '\r')) ++b;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\n' ||
                     s[e - 1] == '\r')) {
        --e;
    }
    return s.substr(b, e - b);
}

bool is_space_char(char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r';
}

// Decode an entity reference (the payload between '&' and ';').
std::string decode_entity(const std::string& name) {
    if (name == "amp") return "&";
    if (name == "lt") return "<";
    if (name == "gt") return ">";
    if (name == "quot") return "\"";
    if (name == "apos") return "'";
    if (!name.empty() && name[0] == '#') {
        unsigned long cp = 0;
        try {
            cp = (name.size() > 1 && (name[1] == 'x' || name[1] == 'X'))
                     ? std::stoul(name.substr(2), nullptr, 16)
                     : std::stoul(name.substr(1), nullptr, 10);
        } catch (...) {
            parse_error("undefined entity &" + name + ";");
        }
        if (cp == 0 || cp > 0x10FFFF) parse_error("invalid character reference");
        std::string out;
        if (cp < 0x80) {
            out.push_back(static_cast<char>(cp));
        } else if (cp < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (cp >> 6)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else if (cp < 0x10000) {
            out.push_back(static_cast<char>(0xE0 | (cp >> 12)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xF0 | (cp >> 18)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (cp & 0x3F)));
        }
        return out;
    }
    parse_error("undefined entity &" + name + ";");
}

// Expand "{uri}local"/"prefix:local" text using the in-scope namespace map.
// ET semantics: an undeclared prefix is a parse error ("unbound prefix");
// unprefixed attributes are never namespaced.
std::string expand_name(const std::string& raw,
                        const std::map<std::string, std::string>& ns,
                        bool is_attribute) {
    auto colon = raw.find(':');
    if (colon == std::string::npos) {
        if (is_attribute) return raw;
        auto it = ns.find("");
        return it == ns.end() ? raw : "{" + it->second + "}" + raw;
    }
    std::string prefix = raw.substr(0, colon);
    std::string local = raw.substr(colon + 1);
    if (prefix == "xml") return "{http://www.w3.org/XML/1998/namespace}" + local;
    auto it = ns.find(prefix);
    if (it == ns.end()) parse_error("unbound prefix");
    return "{" + it->second + "}" + local;
}

}  // namespace

const std::string* XmlNode::attr(std::string_view name) const {
    for (const auto& [k, v] : attrib) {
        if (k == name) return &v;
    }
    return nullptr;
}

void XmlNode::iter(std::vector<const XmlNode*>& out) const {
    out.push_back(this);
    for (const auto& child : children) child->iter(out);
}

std::string XmlNode::itertext() const {
    std::string out = text;
    for (const auto& child : children) out += child->itertext();
    return out;
}

namespace {

// Node under construction; finalized into an XmlNode when its end tag is
// seen (tails are never read by the ported consumers and are dropped).
struct BuildNode {
    std::string tag;
    std::vector<std::pair<std::string, std::string>> attrib;
    std::string text;
    std::vector<std::unique_ptr<XmlNode>> children;
};

}  // namespace

struct XmlScanner::Impl {
    explicit Impl(bool forbid) : forbid_entities(forbid) {}

    std::string buffer;
    size_t pos = 0;
    bool root_seen = false;
    bool root_closed = false;
    bool fed_all = false;

    struct OpenElement {
        BuildNode node;
        std::map<std::string, std::string> ns;
        std::string raw_name;
    };
    std::vector<OpenElement> stack;

    std::vector<Event> events;
    std::vector<Attributes> start_payloads;
    std::vector<const XmlNode*> end_payloads;
    std::unique_ptr<XmlNode> root_owner;  // owns the tree for xml_parse

    bool forbid_entities;

    void push_start(std::string tag,
                    std::vector<std::pair<std::string, std::string>> attribs) {
        events.push_back(Event::Start);
        start_payloads.push_back({std::move(tag), std::move(attribs)});
        end_payloads.push_back(nullptr);
    }
    void push_end(const XmlNode* node) {
        events.push_back(Event::End);
        start_payloads.emplace_back();
        end_payloads.push_back(node);
    }

    void append_text(const std::string& s) {
        if (s.empty()) return;
        if (stack.empty()) {
            bool only_space = true;
            for (char c : s) {
                if (!is_space_char(c)) {
                    only_space = false;
                    break;
                }
            }
            if (!only_space) parse_error("junk before document element");
            return;
        }
        BuildNode& top = stack.back().node;
        if (top.children.empty()) top.text += s;
        // text after children is tail material; no ported consumer reads it
    }

    int step_text_node() {
        size_t start = pos;
        while (pos < buffer.size()) {
            char c = buffer[pos];
            if (c == '<') break;
            if (c == '&') {
                auto semi = buffer.find(';', pos);
                size_t lt = buffer.find('<', pos);
                if (semi == std::string::npos ||
                    (lt != std::string::npos && lt < semi)) {
                    if (fed_all) parse_error("not well-formed (invalid token)");
                    return 0;  // may complete in the next chunk
                }
                std::string ent = buffer.substr(pos + 1, semi - pos - 1);
                append_text(buffer.substr(start, pos - start));
                append_text(decode_entity(ent));
                pos = semi + 1;
                start = pos;
                continue;
            }
            ++pos;
        }
        if (pos > start) append_text(buffer.substr(start, pos - start));
        return 1;
    }

    int step_markup() {
        if (pos + 1 >= buffer.size()) {
            if (fed_all) parse_error("no element found");
            return 0;
        }
        char c = buffer[pos + 1];
        if (c == '/') {
            auto gt = buffer.find('>', pos);
            if (gt == std::string::npos) {
                if (fed_all) parse_error("mismatched tag");
                return 0;
            }
            std::string raw = trim_ascii(buffer.substr(pos + 2, gt - pos - 2));
            pos = gt + 1;
            if (stack.empty() || raw != stack.back().raw_name) {
                parse_error("mismatched tag");
            }
            OpenElement top = std::move(stack.back());
            stack.pop_back();
            auto node = std::make_unique<XmlNode>();
            node->tag = std::move(top.node.tag);
            node->attrib = std::move(top.node.attrib);
            node->text = std::move(top.node.text);
            node->children = std::move(top.node.children);
            if (stack.empty()) {
                root_closed = true;
                root_owner = std::move(node);
                push_end(root_owner.get());
            } else {
                push_end(node.get());
                stack.back().node.children.push_back(std::move(node));
            }
            return 1;
        }
        if (c == '?') {
            auto end = buffer.find("?>", pos);
            if (end == std::string::npos) {
                if (fed_all) parse_error("unclosed token");
                return 0;
            }
            pos = end + 2;
            return 1;
        }
        if (c == '!') {
            if (buffer.compare(pos, 4, "<!--") == 0) {
                auto end = buffer.find("-->", pos + 4);
                if (end == std::string::npos) {
                    if (fed_all) parse_error("unclosed token");
                    return 0;
                }
                pos = end + 3;
                return 1;
            }
            if (buffer.compare(pos, 9, "<![CDATA[") == 0) {
                auto end = buffer.find("]]>", pos + 9);
                if (end == std::string::npos) {
                    if (fed_all) parse_error("unclosed token");
                    return 0;
                }
                append_text(buffer.substr(pos + 9, end - pos - 9));
                pos = end + 3;
                return 1;
            }
            if (buffer.compare(pos, 2, "<!") == 0) {
                auto end = buffer.find('>', pos);
                if (end == std::string::npos) {
                    if (fed_all) parse_error("unclosed token");
                    return 0;
                }
                std::string decl = buffer.substr(pos, end - pos);
                if (decl.find("<!ENTITY") != std::string::npos && forbid_entities) {
                    throw XmlError("EntitiesForbidden",
                                   "Entity declaration is forbidden");
                }
                pos = end + 1;
                return 1;
            }
            parse_error("invalid token");
        }

        // --- start tag: find '>' outside quotes ---
        bool in_quote = false;
        char quote = 0;
        size_t gt = pos + 1;
        for (; gt < buffer.size(); ++gt) {
            char g = buffer[gt];
            if (in_quote) {
                if (g == quote) in_quote = false;
            } else if (g == '"' || g == '\'') {
                in_quote = true;
                quote = g;
            } else if (g == '>') {
                break;
            }
        }
        if (gt >= buffer.size()) {
            if (fed_all) parse_error("unclosed token");
            return 0;
        }
        std::string inner = buffer.substr(pos + 1, gt - pos - 1);
        bool self_closing = !inner.empty() && inner.back() == '/';
        if (self_closing) inner.pop_back();
        pos = gt + 1;

        size_t i = 0;
        while (i < inner.size() && is_space_char(inner[i])) ++i;
        size_t name_start = i;
        while (i < inner.size() && !is_space_char(inner[i])) ++i;
        if (i == name_start) parse_error("invalid token");
        std::string raw_name = inner.substr(name_start, i - name_start);

        std::map<std::string, std::string> ns;
        if (!stack.empty()) ns = stack.back().ns;
        std::vector<std::pair<std::string, std::string>> attribs;
        while (i < inner.size()) {
            while (i < inner.size() && is_space_char(inner[i])) ++i;
            if (i >= inner.size()) break;
            size_t key_start = i;
            while (i < inner.size() && inner[i] != '=') ++i;
            std::string key = trim_ascii(inner.substr(key_start, i - key_start));
            if (key.empty() || i >= inner.size() || inner[i] != '=') {
                parse_error("invalid token");
            }
            ++i;
            while (i < inner.size() && (inner[i] == ' ' || inner[i] == '\t')) ++i;
            if (i >= inner.size() || (inner[i] != '"' && inner[i] != '\'')) {
                parse_error("invalid token");
            }
            char q = inner[i++];
            std::string value;
            size_t vstart = i;
            while (i < inner.size() && inner[i] != q) ++i;
            if (i >= inner.size()) parse_error("invalid token");
            value = inner.substr(vstart, i - vstart);
            ++i;
            std::string decoded;
            for (size_t k = 0; k < value.size();) {
                if (value[k] == '&') {
                    auto semi = value.find(';', k);
                    if (semi == std::string::npos) parse_error("invalid token");
                    decoded += decode_entity(value.substr(k + 1, semi - k - 1));
                    k = semi + 1;
                } else {
                    decoded.push_back(value[k++]);
                }
            }
            if (key == "xmlns") {
                ns[""] = decoded;
            } else if (key.rfind("xmlns:", 0) == 0) {
                ns[key.substr(6)] = decoded;
            } else {
                attribs.emplace_back(expand_name(key, ns, true), decoded);
            }
        }

        if (stack.empty()) {
            if (root_seen) parse_error("junk after document element");
            root_seen = true;
        }

        std::string tag = expand_name(raw_name, ns, false);
        push_start(tag, attribs);
        BuildNode bn;
        bn.tag = tag;
        bn.attrib = attribs;
        stack.push_back(OpenElement{std::move(bn), std::move(ns), raw_name});
        if (self_closing) {
            OpenElement top = std::move(stack.back());
            stack.pop_back();
            auto node = std::make_unique<XmlNode>();
            node->tag = std::move(top.node.tag);
            node->attrib = std::move(top.node.attrib);
            node->text = std::move(top.node.text);
            node->children = std::move(top.node.children);
            if (stack.empty()) {
                root_closed = true;
                root_owner = std::move(node);
                push_end(root_owner.get());
            } else {
                push_end(node.get());
                stack.back().node.children.push_back(std::move(node));
            }
        }
        return 1;
    }
};

XmlScanner::XmlScanner(bool forbid_entities)
    : impl_(std::make_unique<Impl>(forbid_entities)) {}

XmlScanner::~XmlScanner() = default;

void XmlScanner::feed(std::string_view bytes) {
    // a UTF-8 BOM at the very start of the stream is skipped (ET.parse does)
    if (impl_->buffer.empty() && impl_->pos == 0 && bytes.size() >= 3 &&
        static_cast<unsigned char>(bytes[0]) == 0xEF &&
        static_cast<unsigned char>(bytes[1]) == 0xBB &&
        static_cast<unsigned char>(bytes[2]) == 0xBF) {
        bytes = bytes.substr(3);
    }
    impl_->buffer.append(bytes.data(), bytes.size());
}

void XmlScanner::mark_end() { impl_->fed_all = true; }

std::unique_ptr<XmlNode> XmlScanner::take_root() {
    return std::move(impl_->root_owner);
}

size_t XmlScanner::consumed_bytes() const { return impl_->pos; }

bool XmlScanner::next(Event& event, Attributes& start_attrs,
                      const XmlNode*& end_node) {
    if (failed_) return false;
    try {
        while (impl_->events.empty()) {
            if (impl_->pos >= impl_->buffer.size()) {
                if (!impl_->fed_all) return false;  // wait for more input
                if (!impl_->stack.empty() || (impl_->root_seen &&
                                              !impl_->root_closed)) {
                    parse_error("no element found");
                }
                return false;
            }
            if (impl_->buffer[impl_->pos] == '<') {
                impl_->step_markup();
            } else {
                impl_->step_text_node();
            }
        }
    } catch (const XmlError& e) {
        failed_ = true;
        error_ = std::make_unique<XmlError>(e.class_name, e.what());
        return false;
    }
    event = impl_->events.front();
    impl_->events.erase(impl_->events.begin());
    if (event == Event::Start) {
        start_attrs = std::move(impl_->start_payloads.front());
        end_node = nullptr;
    } else {
        end_node = impl_->end_payloads.front();
    }
    impl_->start_payloads.erase(impl_->start_payloads.begin());
    impl_->end_payloads.erase(impl_->end_payloads.begin());
    return true;
}

std::unique_ptr<XmlNode> xml_parse(std::string_view bytes, bool forbid_entities) {
    XmlScanner scanner(forbid_entities);
    scanner.feed(bytes);
    scanner.mark_end();
    XmlScanner::Event event;
    XmlScanner::Attributes attrs;
    const XmlNode* node = nullptr;
    while (scanner.next(event, attrs, node)) {
    }
    if (scanner.failed()) throw XmlError(scanner.error());
    auto root = scanner.take_root();
    if (!root) parse_error("no element found");
    return root;
}

}  // namespace pwb::ingest
