#pragma once

// LayoutEditorPanel — the Stage 3 layout editing surface hosting *native*
// QGIS layout editing (docs/development/qgis-native-layout-convergence/01
// §03). It is a thin host: the view, rulers, selection/move/resize tools,
// copy/paste, alignment and per-item property widgets are QGIS public GUI
// classes; the panel only provides layout/document chrome (list, template
// menu, undo toolbar) around them. There is no Paleo-side scene editor and
// no second element model.

#include <pwb/qgis/layout_authority.hpp>

#include <QWidget>

#include <memory>

class QgsLayoutView;
class QgsLayoutViewToolSelect;
class QgsLayoutRuler;
class QgsMapCanvas;
class QgsPrintLayout;
class QListWidget;
class QStackedWidget;
class QToolBar;
class QUndoStack;
class QVBoxLayout;
class QLabel;
class QPushButton;

namespace pwb::qgis {

class LayoutEditorPanel : public QWidget {
    Q_OBJECT

public:
    // `canvas` feeds the map item property widget's "match canvas" actions
    // (registerGuiForKnownItemTypes captures it); may be the shared main
    // canvas. `authority` must outlive the panel.
    LayoutEditorPanel(LayoutAuthority& authority, QgsMapCanvas* canvas,
                      QWidget* parent = nullptr);
    ~LayoutEditorPanel() override;

    void set_active_layout(QgsPrintLayout* layout);
    QgsPrintLayout* active_layout() const { return active_; }

    // Re-read the authority's layout list (project open/switch, restore).
    void refresh();

signals:
    void active_layout_changed(QgsPrintLayout* layout);
    void layouts_modified();  // any layout's undo stack moved (project dirty)
    void export_requested(QgsPrintLayout* layout);

private slots:
    void refresh_layout_list();
    void on_layout_selected(int row);
    void on_new_from_template();
    void on_duplicate();
    void on_remove();
    void on_export();
    void refresh_selection();
    void refresh_undo_actions();
    void emit_modified();

private:
    void build_ui(QgsMapCanvas* canvas);
    void attach_layout(QgsPrintLayout* layout);
    void detach_active_layout();

    LayoutAuthority& authority_;
    QgsPrintLayout* active_ = nullptr;
    QToolBar* toolbar_ = nullptr;
    QgsLayoutView* view_ = nullptr;
    QgsLayoutViewToolSelect* select_tool_ = nullptr;
    QgsLayoutRuler* h_ruler_ = nullptr;
    QgsLayoutRuler* v_ruler_ = nullptr;
    QListWidget* layout_list_ = nullptr;
    QWidget* properties_host_ = nullptr;
    QVBoxLayout* properties_box_ = nullptr;
    QLabel* empty_label_ = nullptr;
    QPushButton* template_button_ = nullptr;
    class ToolActions;
    std::unique_ptr<ToolActions> tools_;
};

}  // namespace pwb::qgis
