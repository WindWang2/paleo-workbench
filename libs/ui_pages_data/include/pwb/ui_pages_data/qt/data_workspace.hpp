// UI-06 — data_workspace.py :: DataWorkspace Qt shell.
//
// Three-column splitter: navigation | center stack (table / overview /
// well detail) + well map | reader + inspector. WellMapPanel /
// InspectorPanel / WellDetailPanel / FloatController / LayoutPersistence
// are other slices' components — injected seams.
#pragma once

#include <QPointer>
#include <QSplitter>
#include <QStackedWidget>
#include <QToolButton>
#include <QWidget>

#include <functional>
#include <map>
#include <string>

class QVBoxLayout;
class QTimer;

namespace pwb::ui_pages_data::qt {

class DataAssetTable;
class DataReaderPanel;
class NavigationTree;
class ProjectOverviewPanel;

// ui.panel_float_controller.FloatController seam.
class FloatControllerApi : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;
    virtual void toggle(const QString& key) = 0;
    virtual bool is_floating(const QString& key) const = 0;
    virtual void restore_saved(const QString& key) = 0;
Q_SIGNALS:
    void float_changed(const QString& key, bool floating);
};

// ui.pages.well_map_panel.WellMapPanel seam (collapse + header chrome).
class WellMapPanelApi : public QWidget {
    Q_OBJECT
public:
    using QWidget::QWidget;
    virtual bool is_collapsed() const = 0;
    virtual void set_collapsed(bool collapsed) = 0;
    virtual void set_header_visible(bool visible) = 0;
    virtual void add_header_button(QWidget* button) = 0;
};

// Corner float button (PanelFloatButton parity). pin=true overlays the
// panel's top-right via an event filter; pin=false goes into the map's
// own header strip.
class PanelFloatButton : public QToolButton {
    Q_OBJECT
public:
    PanelFloatButton(const QString& key, QWidget* panel,
                     FloatControllerApi* controller, bool pin = true,
                     QWidget* parent = nullptr);

protected:
    bool eventFilter(QObject* obj, QEvent* event) override;

private:
    void reposition();

    QString key_;
    QWidget* panel_;
    FloatControllerApi* controller_;
    bool pinned_;
};

class DataWorkspace : public QWidget {
    Q_OBJECT
public:
    explicit DataWorkspace(QWidget* parent = nullptr);

    // Seams (call BEFORE make_floatable wiring is exercised).
    void set_float_controller(FloatControllerApi* controller);
    // LayoutPersistence.save_docked_sizes seam.
    void set_save_docked_sizes_fn(
        std::function<void(const QString& key, const QList<int>& sizes)> fn);
    void set_well_map_panel(WellMapPanelApi* panel);
    void set_inspector_panel(QWidget* panel);
    void set_well_detail_panel(QWidget* panel);

    // Python attribute parity.
    NavigationTree* navigation_tree() { return navigation_tree_; }
    DataAssetTable* asset_table() { return asset_table_; }
    ProjectOverviewPanel* overview_panel() { return overview_panel_; }
    DataReaderPanel* reader_panel() { return reader_panel_; }
    QWidget* inspector_panel() { return inspector_panel_; }
    WellMapPanelApi* well_map_panel() { return well_map_panel_; }
    QSplitter* main_splitter() { return main_splitter_; }
    QSplitter* right_splitter() { return right_splitter_; }

    void show_overview(bool visible);
    bool overview_visible() const;
    void show_well_detail(bool visible);
    bool well_detail_visible() const;
    void set_right_visible(bool visible);

    static constexpr int kDockedSizesDelayMs = 400;

private:
    void make_floatable(const QString& key, QWidget* panel,
                        const QString& title);
    void on_map_float_changed(const QString& key, bool floating);
    void persist_docked_sizes();

    QSplitter* main_splitter_;
    QSplitter* right_splitter_;
    QStackedWidget* center_stack_;
    QWidget* map_center_host_;
    QVBoxLayout* center_layout_;
    NavigationTree* navigation_tree_;
    DataAssetTable* asset_table_;
    ProjectOverviewPanel* overview_panel_;
    QWidget* well_detail_panel_;
    DataReaderPanel* reader_panel_;
    QWidget* inspector_panel_;
    WellMapPanelApi* well_map_panel_;

    FloatControllerApi* float_controller_ = nullptr;
    std::function<void(const QString&, const QList<int>&)>
        save_docked_sizes_fn_;
    // #1389: QPointer auto-nulls when a panel is destroyed (e.g. the
    // inspector replaced by set_inspector_panel's deleteLater) — a raw
    // pointer here would dangle into persist_docked_sizes' deferred timer.
    std::map<QString, QPointer<QWidget>> floatable_;
    bool map_collapsed_before_overview_ = true;
    bool map_collapsed_before_float_ = true;
    QTimer* float_sizes_timer_;
};

}  // namespace pwb::ui_pages_data::qt
