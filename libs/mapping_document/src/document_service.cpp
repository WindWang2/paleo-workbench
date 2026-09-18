#include <pwb/mapping_document/document_service.hpp>

namespace pwb::mapping_document {

MapDocumentService::MapDocumentService()
    : session_(document_), store_(make_std_file_store()) {}

bool MapDocumentService::load_json(const Json& payload, std::string* error) {
    try {
        MapDocument parsed = parse_map_document(payload);
        document_ = std::move(parsed);
    } catch (const std::exception& e) {
        if (error != nullptr) *error = e.what();
        return false;
    }
    // New document, new history (Python host contract): revisions and the
    // undo/redo stacks reset, saved baseline latches at the clean state.
    session_ = MapDocumentEditSession(document_);
    session_.mark_saved();
    return true;
}

LoadStatus MapDocumentService::load_file(const std::string& path,
                                         DocumentIoDiagnostics* diagnostics) {
    MapDocument parsed;
    LoadResult result =
        load_map_document_file(*store_, path, parsed, diagnostics);
    if (result.status == LoadStatus::kOk
        || result.status == LoadStatus::kRecoveredFromBackup
        || result.status == LoadStatus::kRecoveredCorrupt) {
        document_ = std::move(parsed);
        session_ = MapDocumentEditSession(document_);
        session_.mark_saved();
    }
    return result.status;
}

bool MapDocumentService::save_file(const std::string& path, std::string* error,
                                   DocumentIoDiagnostics* diagnostics) {
    std::string write_error;
    (void)diagnostics;  // save-side warnings are kernel-level; none today
    if (!save_map_document_file(*store_, path, document_, write_error)) {
        if (error != nullptr) *error = write_error;
        return false;
    }
    session_.mark_saved();
    return true;
}

CompositionDocumentService::CompositionDocumentService()
    : session_(document_, session_factory_), store_(make_std_file_store()) {}

bool CompositionDocumentService::load_json(const Json& payload,
                                           std::string* error) {
    try {
        Composition parsed = parse_composition(payload);
        document_ = std::move(parsed);
    } catch (const std::exception& e) {
        if (error != nullptr) *error = e.what();
        return false;
    }
    session_ = CompositionEditSession(document_, session_factory_);
    revision_at_save_ = session_.revision();
    return true;
}

LoadStatus CompositionDocumentService::load_file(const std::string& path,
                                                 DocumentIoDiagnostics* diagnostics) {
    Composition parsed;
    LoadResult result =
        load_composition_file(*store_, path, parsed, diagnostics);
    if (result.status == LoadStatus::kOk
        || result.status == LoadStatus::kRecoveredFromBackup
        || result.status == LoadStatus::kRecoveredCorrupt) {
        document_ = std::move(parsed);
        session_ = CompositionEditSession(document_, session_factory_);
        revision_at_save_ = session_.revision();
    }
    return result.status;
}

bool CompositionDocumentService::save_file(const std::string& path,
                                           std::string* error,
                                           DocumentIoDiagnostics* /*diagnostics*/) {
    std::string write_error;
    if (!save_composition_file(*store_, path, document_, write_error)) {
        if (error != nullptr) *error = write_error;
        return false;
    }
    revision_at_save_ = session_.revision();
    return true;
}

}  // namespace pwb::mapping_document
