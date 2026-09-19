#pragma once

// UI-10 — Qt shell for composition_panel.py: the authoring surface for
// one composition document (template → components → export).
//
// The session/document/factory stay in mapping_document; the panel owns
// the widget tree (template row, history row, keyed element list, schema
// -driven property form, preview, export row) and forwards every registry
// /renderer/export call through injected seams. View decisions come from
// the Qt-free composition_state core.

#include <QFrame>

#include <any>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <pwb/ui_seqviz/composition_state.hpp>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QFormLayout;
class QLabel;
class QLineEdit;
class QListWidget;
class QListWidgetItem;
class QPushButton;
class QSpinBox;
class QTableWidget;
class QTextEdit;
class QToolButton;

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// Registry/renderer/export seams — everything composition_panel.py reads
// from the composer registry, renderer, layout exporter and artifact
// ledger stays injected (the C++ kernel deliberately ships no registry
// data or SVG renderer).
// ---------------------------------------------------------------------------

// TEMPLATE_LIBRARY entry — {template_id, label, description}.
struct CompositionTemplateEntry {
    std::string template_id;
    std::string label;
    std::string description;
};

// One add-menu group — a registry category with its element specs.
struct CompositionMenuGroup {
    std::string category_label;             // CATEGORY_LABELS value
    std::vector<std::pair<std::string, std::string>> specs;  // (type, label)
};

// export_composition_reported result slice (engine + path + warnings).
struct CompositionExportResult {
    bool ok = false;
    std::string engine;
    std::string path;
    std::string message;
    std::vector<std::string> warnings;
};

struct CompositionRegistrySeams {
    // TEMPLATE_LIBRARY.values() in registry order.
    std::function<std::vector<CompositionTemplateEntry>()>
        template_library;
    // instantiate_template(template_id) -> Composition — absent ⇒ the
    // panel keeps an empty factory document (the honest no-template
    // path; Python's library is never fabricated here).
    std::function<mapping_document::Composition(const std::string&)>
        instantiate_template;

    // categories() + CATEGORY_LABELS + specs_by_category — the ＋组件
    // menu structure in registry order.
    std::function<std::vector<CompositionMenuGroup>()> element_menu;

    // get_spec(element_type).property_schema — Json list of prop dicts.
    std::function<domain::Json(const std::string& element_type)>
        property_schema;

    // ELEMENT_TYPE_LABELS.get(type, raw) + CHART_SERIES_SCHEMAS.
    ElementLabelFn element_label_fn;
    std::map<std::string, std::string> chart_series_schemas;

    // composer_renderer.render_to_svg(document) — absent ⇒ the
    // "预览渲染失败" honest fallback (never a fabricated preview).
    std::function<std::string(const Composition& document)> render_svg;

    // export_composition_reported(doc, path, fmt, dpi).
    std::function<CompositionExportResult(
        const Composition& document, const std::string& path,
        const std::string& fmt, double dpi)>
        export_fn;

    // project_provider() -> live project (for record_export); absent or
    // null ⇒ the provenance write is skipped (best-effort parity).
    std::function<std::any()> project_provider;
    std::function<void(const std::any& project,
                       const std::string& path)>
        record_export;

    // set_main_map — bind a live map document into the MAIN_MAP element's
    // properties["map_document"]. The binding is host-side (a live doc
    // cannot ride inside Json properties); absent ⇒ false.
    std::function<bool(CompositionEditSession& session,
                       Composition& document, const std::any& map_doc)>
        main_map_bind_fn;
};

// ---------------------------------------------------------------------------
// CompositionPanel — the QFrame workbench panel.
// ---------------------------------------------------------------------------
class CompositionPanel : public QFrame {
    Q_OBJECT
public:
    explicit CompositionPanel(QWidget* parent = nullptr);

    // The factory (spec provider + id generator) the host configured.
    void set_factory(mapping_document::CompositionFactory factory);
    void set_registry(CompositionRegistrySeams seams);

    // set_document — owns a copy of `doc`, opens a fresh edit session.
    void set_document(const Composition& doc);
    Composition* document();
    CompositionEditSession* session() const { return session_.get(); }

    // apply_bindings — bind_template + preview refresh; resolved count.
    long long apply_bindings(const domain::Json& binding_context);
    // set_main_map — bind/unbind the live map document (map_doc empty ⇒
    // unbind — the seam decides how the unbind is expressed).
    bool set_main_map(const std::any& map_document);

    // -- Python member surfaces ------------------------------------------
    QComboBox* template_combo() const { return template_combo_; }
    QListWidget* element_list() const { return element_list_; }
    QLineEdit* title_edit() const { return title_edit_; }
    QLabel* preview_label() const { return preview_label_; }
    QLabel* lock_hint() const { return lock_hint_; }
    QDoubleSpinBox* x_spin() const { return x_spin_; }
    QDoubleSpinBox* y_spin() const { return y_spin_; }
    QDoubleSpinBox* w_spin() const { return w_spin_; }
    QDoubleSpinBox* h_spin() const { return h_spin_; }
    QComboBox* export_combo() const { return export_combo_; }
    QSpinBox* dpi_spin() const { return dpi_spin_; }

    // Repaint entry — _refresh_all.
    void refresh_all();

signals:
    void composition_changed(long long revision);
    void composition_exported(const QString& path);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void build_add_menu();
    void new_from_template();
    std::string selected_element_id() const;
    mapping_document::ComposerElement* selected_element();
    void add_element(const std::string& element_type);
    void delete_selected();
    void duplicate_selected();
    void toggle_lock(const std::string& element_id);
    void reorder(const std::string& mode);
    void undo();
    void redo();
    void apply_title();
    void apply_geometry(const std::string& field, double value);
    void on_schema_value_changed(const std::string& name,
                                 const domain::Json& value);
    void on_schema_json_changed(const std::string& name,
                                const QString& text);
    void mark_schema_dirty(const std::string& name);
    void commit_schema_edits();
    void on_element_selected(int row);
    void on_element_menu(const QPoint& pos);
    void refresh_list();
    void refresh_history_state();
    void clear_schema_rows();
    void refresh_property_editor();
    void refresh_preview();
    void save_json();
    void load_json();
    void do_export();
    void register_catalog_export(const std::string& path);
    void select_element(const std::string& element_id);
    // _make_editor — returns the editor widget; the getter it installs
    // lands in schema_getters_[name].
    QWidget* make_editor(const SchemaEditorDesc& desc,
                         const domain::Json& value,
                         const ComposerElement& element);
    QWidget* make_series_table_editor(const ComposerElement& element);
    domain::Json series_collect(QTableWidget* table) const;

    mapping_document::CompositionFactory factory_;
    CompositionRegistrySeams seams_;
    std::unique_ptr<Composition> document_;
    std::unique_ptr<CompositionEditSession> session_;

    bool suppress_item_signals_ = false;
    bool suppress_geometry_signals_ = false;
    bool suppress_schema_signals_ = false;
    // name -> (editor, getter) — the dynamic schema rows.
    std::map<std::string, QWidget*> schema_editors_;
    std::map<std::string, std::function<domain::Json()>> schema_getters_;
    std::set<std::string> schema_dirty_;

    QComboBox* template_combo_ = nullptr;
    QPushButton* new_from_template_btn_ = nullptr;
    QToolButton* undo_btn_ = nullptr;
    QToolButton* redo_btn_ = nullptr;
    QToolButton* save_btn_ = nullptr;
    QToolButton* load_btn_ = nullptr;
    QListWidget* element_list_ = nullptr;
    QToolButton* add_btn_ = nullptr;
    QToolButton* delete_btn_ = nullptr;
    QToolButton* duplicate_btn_ = nullptr;
    QToolButton* front_btn_ = nullptr;
    QToolButton* back_btn_ = nullptr;
    QFormLayout* property_form_ = nullptr;
    QLineEdit* title_edit_ = nullptr;
    QDoubleSpinBox* x_spin_ = nullptr;
    QDoubleSpinBox* y_spin_ = nullptr;
    QDoubleSpinBox* w_spin_ = nullptr;
    QDoubleSpinBox* h_spin_ = nullptr;
    QLabel* lock_hint_ = nullptr;
    QLabel* preview_label_ = nullptr;
    QComboBox* export_combo_ = nullptr;
    QSpinBox* dpi_spin_ = nullptr;
    QPushButton* export_btn_ = nullptr;
};

}  // namespace pwb::ui_seqviz::qt
