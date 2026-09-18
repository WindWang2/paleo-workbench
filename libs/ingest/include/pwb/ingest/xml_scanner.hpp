// Minimal streaming XML scanner with ElementTree-compatible semantics:
// tags/attributes expand to "{uri}local", text/tail are tracked, comments
// and PIs are skipped, and malformed input raises XmlError whose class_name
// matches the CPython exception the Python code would surface ("ParseError",
// or "EntitiesForbidden" when entity forbidding is on, mirroring defusedxml).
#pragma once

#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace pwb::ingest {

struct XmlError : std::runtime_error {
    std::string class_name;  // Python exception class name for user messages
    XmlError(std::string cls, const std::string& message)
        : std::runtime_error(message), class_name(std::move(cls)) {}
};

// A parsed element. `text` is character data before the first child; child
// tails are stored on the children, mirroring ElementTree.
struct XmlNode {
    std::string tag;  // "{uri}local" or "local"
    std::vector<std::pair<std::string, std::string>> attrib;  // ordered
    std::string text;
    std::vector<std::unique_ptr<XmlNode>> children;

    const std::string* attr(std::string_view name) const;
    // document-order descendant iteration (self first), as element.iter()
    void iter(std::vector<const XmlNode*>& out) const;
    // "".join(itertext()) — text + descendants' text + tails
    std::string itertext() const;
};

// Incremental parser. Feed the byte stream in any number of chunks; events
// are delivered as soon as they are unambiguous (Start when the tag is
// complete, End once the element is closed) so a truncated stream still
// yields the events that precede the error — the observable contract of
// ElementTree.iterparse over a bounded reader.
class XmlScanner {
public:
    struct Attributes {
        std::string tag;
        std::vector<std::pair<std::string, std::string>> attrib;
    };

    enum class Event { Start, End };

    explicit XmlScanner(bool forbid_entities = false);
    ~XmlScanner();  // out-of-line: Impl is incomplete in this header
    XmlScanner(XmlScanner&&) = delete;
    XmlScanner& operator=(XmlScanner&&) = delete;

    void feed(std::string_view bytes);
    // Declare the byte stream finished; EOF well-formedness checks run when
    // the scanner runs dry afterwards.
    void mark_end();
    // Returns false when no more events are available or a parse error
    // occurred (failed()/error() then describe which). On End, end_node
    // points at the completed element (owned by the scanner until the next
    // event / scanner destruction — copy out anything retained).
    bool next(Event& event, Attributes& start_attrs, const XmlNode*& end_node);
    bool failed() const { return failed_; }
    const XmlError& error() const { return *error_; }
    // xml_parse support: move out the parsed root after the stream ends.
    std::unique_ptr<XmlNode> take_root();
    // Bytes consumed so far (whether the parse ran to the end of the fed
    // buffer or stopped early at an error).
    size_t consumed_bytes() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    bool failed_ = false;
    std::unique_ptr<XmlError> error_;
};

// Parse a complete document into its root element. Throws XmlError on any
// malformed input (ET.parse semantics).
std::unique_ptr<XmlNode> xml_parse(std::string_view bytes, bool forbid_entities = false);

}  // namespace pwb::ingest
