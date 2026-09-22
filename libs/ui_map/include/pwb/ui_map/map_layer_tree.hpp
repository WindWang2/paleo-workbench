#pragma once

// UI-05 — MapLayerTree (map_layer_tree.py): the document list plus the
// four editable-layer visibility/lock rows of the legacy mapping surface,
// kept as the compatibility view over the same domain documents.
// Keyed-diff reconciliation (item_reconcile) preserves item identity,
// expanded state, selection and scroll position across rebuilds — the
// Python clear+rebuild replacement.
//
// Documents are Json records (field_value/getattr parity); the active
// document's subtree carries the four layer rows plus the reference-layer
// group when the document has any. Non-active documents never carry
// layer subtrees (Python behavior verbatim).

#include <map>
#include <string>
#include <vector>

#include <QFrame>
#include <QVariant>

#include <pwb/ui_map/map_chrome_core.hpp>
#include <pwb/ui_map/qt_meta.hpp>

class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui_map {

class MapLayerTree : public QFrame {
    Q_OBJECT
public:
    explicit MapLayerTree(QWidget* parent = nullptr);

    void set_documents(const std::vector<Json>& documents);

    // The active document by VALUE identity (same Json object content) —
    // Python `doc is active` identity parity: the caller passes the same
    // Json it placed in set_documents; pointer identity keys the populate
    // path exactly like Python's `is`.
    void set_active_document(const Json* document);

    void set_layer_locked(const std::string& layer_key, bool locked);
    bool layer_is_visible(const std::string& layer_key) const;
    bool layer_is_locked(const std::string& layer_key) const;

    QTreeWidget* tree() const { return tree_; }

    // Test readback: top-level document keys and populated layer rows.
    std::vector<std::string> document_keys() const;
    std::vector<std::string> layer_item_keys() const;

signals:
    // The selected document's Json payload (verbatim object — the host
    // resolves the document it owns by id).
    void document_selected(const pwb::ui_map::Json& document);
    void layer_visibility_changed(const QString& layer_key, bool visible);
    void layer_lock_changed(const QString& layer_key, bool locked);

private:
    void rebuild_tree();
    void reconcile_document_children(QTreeWidgetItem* parent,
                                     const Json& document);
    void on_current_item_changed(QTreeWidgetItem* current);
    void on_item_changed(QTreeWidgetItem* item, int column);

    // Per-document identity tag for keys (stable while the Json lives in
    // documents_ — pointer bytes = Python id() parity).
    const void* identity_of(const Json& document) const;

    std::vector<Json> documents_;
    // Store the active document BY VALUE (review R2-7): a raw pointer
    // dangled into freed documents_ storage after set_documents
    // reallocated the vector, and into MappingPage::documents_ before
    // set_documents ran — a deep compare over freed heap.
    std::optional<Json> active_document_ = nullptr;
    // The document currently carrying the layer subtree (fallback path may
    // differ from the active document — Python _populated_document parity).
    const Json* populated_document_ = nullptr;
    std::vector<QTreeWidgetItem*> doc_items_;
    std::map<std::string, QTreeWidgetItem*> layer_items_;
    std::map<std::string, bool> layer_locked_;
    std::map<std::string, bool> layer_visible_;
    bool suppress_item_changed_ = false;
    QTreeWidget* tree_ = nullptr;
};

}  // namespace pwb::ui_map
