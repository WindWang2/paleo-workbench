#pragma once

// UI-05 — MappingPage (mapping_page.py, constrained port): the mapping
// workspace shell — dock rails + panels around a central canvas stack,
// the bottom workbench, mode/visibility rules, float integration, and
// splitter persistence.
//
// DELIBERATELY CONSTRAINED (see ledgers/ui-05-findings.md):
//   * The authoring surface is the read-only DisplayMapCanvas preview;
//     MapEditView/MapEditScene authoring, MapActionController/MapEditToolbar,
//     MapWorkbenchBottom internals (attribute table, factor shelf,
//     topology panel), MapReferencePanel and CompositionPanel are other
//     slices — their dock slots exist as placeholders so rail/menu/float
//     behaviour is identical.
//   * Signals reduced to the shell vocabulary: draft_saved,
//     mapping_context_changed. Tool actions, snapping, topology,
//     attribute-table sync, reference layers, composition, factor/contour
//     jobs, export and undo/redo are deferred.

#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <QPointer>
#include <QWidget>

#include <pwb/ui_map/map_chrome_core.hpp>
#include <pwb/ui_map/qt_meta.hpp>

class QFrame;
class QSplitter;
class QStackedWidget;
class QToolButton;
class QVBoxLayout;

namespace pwb::ui_shell {
class FloatController;
class LayoutPersistence;
class MapStatusBar;
}  // namespace pwb::ui_shell

namespace pwb::ui_map {

class DisplayMapCanvas;
class MapCanvasPanel;
class MapChromePanel;
class MapDockManager;
class MapLayerTree;

class MappingPage : public QWidget {
    Q_OBJECT
public:
    explicit MappingPage(QWidget* parent = nullptr);
    ~MappingPage() override;

    // ------------------------------------------------------------------
    // mode flags (set_preview_mode / set_canvas_priority parity)
    // ------------------------------------------------------------------

    bool is_preview_mode() const { return preview_mode_; }
    void set_preview_mode(bool enabled);
    bool is_canvas_priority() const { return canvas_priority_; }
    void set_canvas_priority(bool enabled);
    bool is_dirty() const;

    // ------------------------------------------------------------------
    // documents
    // ------------------------------------------------------------------

    // update_state(documents, active_id): reconcile the document panel +
    // layer tree + chrome panel + preview payload against the document
    // list; prefer_id keeps the active row (falls back to the last
    // document — active_map_document parity).
    void update_state(const std::vector<Json>& documents,
                      const std::string& prefer_id = "");

    const Json* active_document() const { return active_document_; }
    // mapping_context(): {"map","horizon","dirty","preview"} sidebar record.
    Json mapping_context() const;

    // ------------------------------------------------------------------
    // sub-component access (integration + tests)
    // ------------------------------------------------------------------

    MapDockManager* dock_manager() { return dock_manager_; }
    pwb::ui_shell::FloatController* float_controller() {
        return float_controller_;
    }
    MapLayerTree* layer_tree() { return layer_tree_; }
    MapChromePanel* chrome_panel() { return chrome_panel_; }
    MapCanvasPanel* canvas_panel() { return canvas_panel_; }
    DisplayMapCanvas* unified_canvas() { return unified_canvas_; }
    QWidget* bottom_workbench() { return bottom_workbench_; }
    QSplitter* mid_splitter() { return mid_splitter_; }
    QStackedWidget* center_stack() { return center_stack_; }
    QStackedWidget* preview_canvas_stack() { return preview_canvas_stack_; }
    pwb::ui_shell::MapStatusBar* status_bar() { return status_bar_; }

    // _apply_mode_ui: center index + preview canvas + bottom visibility.
    void apply_mode_ui();
    // _saved_dock_splitter_sizes three-level fallback, exposed for tests.
    std::vector<int> saved_dock_splitter_sizes() const;

signals:
    void draft_saved(const Json& document);
    void mapping_context_changed(const Json& context);

protected:
    void showEvent(QShowEvent* event) override;

private:
    void wire_float_controller();
    void on_float_changed(const QString& float_key, bool floating);
    void save_dock_splitter_sizes();
    void set_bottom_height_cap(int height);
    void on_document_selected(const Json& document);
    void on_chrome_changed(const Json& payload);
    void emit_mapping_context();
    void refresh_preview();
    Json unified_overlay_state() const;

    MapDockManager* dock_manager_ = nullptr;              // child QObject
    pwb::ui_shell::FloatController* float_controller_ = nullptr;
    std::unique_ptr<pwb::ui_shell::LayoutPersistence> persistence_;

    MapLayerTree* layer_tree_ = nullptr;
    QStackedWidget* layer_tree_stack_ = nullptr;
    QStackedWidget* center_stack_ = nullptr;
    QStackedWidget* preview_canvas_stack_ = nullptr;
    MapCanvasPanel* canvas_panel_ = nullptr;
    DisplayMapCanvas* unified_canvas_ = nullptr;
    MapChromePanel* chrome_panel_ = nullptr;
    QWidget* reference_panel_ = nullptr;    // placeholder (other slice)
    QWidget* composition_panel_ = nullptr;  // placeholder (other slice)
    QFrame* edit_view_ = nullptr;           // placeholder (other slice)
    QWidget* bottom_workbench_ = nullptr;   // placeholder (other slice)
    QSplitter* mid_splitter_ = nullptr;
    pwb::ui_shell::MapStatusBar* status_bar_ = nullptr;
    QToolButton* panels_button_ = nullptr;

    std::vector<Json> documents_;
    const Json* active_document_ = nullptr;  // points into documents_
    bool preview_mode_ = false;
    bool canvas_priority_ = false;
    bool presentation_dirty_ = false;
    std::vector<int> last_dock_sizes_{300, 1000, 280};
    std::map<std::string, QPointer<QWidget>> float_widgets_;
    std::map<std::string, QPointer<QWidget>> float_hosts_;
};

}  // namespace pwb::ui_map
