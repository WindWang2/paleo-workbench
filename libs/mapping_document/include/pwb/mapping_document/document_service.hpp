// Document service facades (CONV-27): the single C++ entry point for the
// UI / Composer / Workflow hosts over the mapping_document data kernel.
//
// One facade per document kind, each owning the document, its edit session
// and the IO path:
//   * load_json / load_file replace the document and RESET the history
//     (Python host contract: composition_panel.set_document builds a new
//     session per loaded document — undo history never crosses documents);
//   * save_file serializes through the CONV-02 kernel, writes atomically
//     with recovery, and latches the saved revisions (dirty → clean);
//   * snapshot() pins the immutable capture with the current session
//     revision as the staleness key.
#pragma once

#include <pwb/mapping_document/composition.hpp>
#include <pwb/mapping_document/composition_session.hpp>
#include <pwb/mapping_document/document_io.hpp>
#include <pwb/mapping_document/map_document.hpp>
#include <pwb/mapping_document/map_document_session.hpp>
#include <pwb/mapping_document/map_document_snapshot.hpp>

#include <memory>
#include <string>

namespace pwb::mapping_document {

class MapDocumentService {
public:
    MapDocumentService();

    MapDocument& document() { return document_; }
    const MapDocument& document() const { return document_; }
    MapDocumentEditSession& session() { return session_; }

    // Parse + replace; on a parse error the current document is untouched.
    // Returns false with *error set (optional).
    bool load_json(const Json& payload, std::string* error = nullptr);
    LoadStatus load_file(const std::string& path,
                         DocumentIoDiagnostics* diagnostics = nullptr);
    // Atomic write + mark_saved(). Returns false with *error set.
    bool save_file(const std::string& path, std::string* error = nullptr,
                   DocumentIoDiagnostics* diagnostics = nullptr);

    MapDocumentSnapshot snapshot() const {
        return capture_map_document_snapshot(document_, session_.revision());
    }

    bool is_dirty() const { return session_.is_dirty(); }

    // Storage seam injection (defaults to StdFileStore).
    void set_store(std::unique_ptr<DocumentStore> store) { store_ = std::move(store); }

private:
    MapDocument document_;
    MapDocumentEditSession session_;
    std::unique_ptr<DocumentStore> store_;
};

class CompositionDocumentService {
public:
    CompositionDocumentService();

    Composition& document() { return document_; }
    const Composition& document() const { return document_; }
    CompositionEditSession& session() { return session_; }
    CompositionFactory& factory() { return session_factory_; }

    bool load_json(const Json& payload, std::string* error = nullptr);
    LoadStatus load_file(const std::string& path,
                         DocumentIoDiagnostics* diagnostics = nullptr);
    bool save_file(const std::string& path, std::string* error = nullptr,
                   DocumentIoDiagnostics* diagnostics = nullptr);

    // Composition documents have no Python dirty contract; the facade keeps
    // the same latch semantics as the map-document service (revision at
    // save time).
    bool is_dirty() const { return revision_at_save_ != session_.revision(); }
    long long revision_at_save() const { return revision_at_save_; }

    void set_store(std::unique_ptr<DocumentStore> store) { store_ = std::move(store); }

private:
    Composition document_;
    CompositionFactory session_factory_;
    CompositionEditSession session_;
    long long revision_at_save_ = 0;
    std::unique_ptr<DocumentStore> store_;
};

}  // namespace pwb::mapping_document
