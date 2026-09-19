// UI-08 — paleo_workbench/ui/pages/inspector_panel.py port: the tabbed
// data-asset inspector — 概要 / 元数据 / 标签 / 版本 / 血缘 / 完整性.
//
// Data contracts:
//  * ``asset`` — ui_data_core::AssetHandle (the typed-asset variant the
//    host binds; asset_view_from_object builds the AssetView).
//  * lineage chains — catalog::LineageChain (upstream/downstream);
//    std::nullopt mirrors Python ``None``.
//  * asset-carrying signals emit the bound AssetHandle (Python Signal(object)
//    parity); version/tag pairs emit QStrings.
#pragma once

#include "pwb/catalog/lineage_graph.hpp"
#include "pwb/ui_data_core/asset_view.hpp"

#include <QFrame>
#include <QMetaType>
#include <QTableView>
#include <QTreeWidget>
#include <QWidget>

#include <functional>
#include <memory>
#include <optional>
#include <vector>

class QHBoxLayout;
class QLabel;
class QMenu;
class QPushButton;
class QTabWidget;
class QTreeWidgetItem;
class QVBoxLayout;

namespace pwb::ui_widgets {
class ObjectTableModel;
class StableSelection;
}  // namespace pwb::ui_widgets

namespace pwb::ui_pages_mapedit {

class TablePreviewWidget;
class TagContainerWidget;
class TagInputDialog;

// IntegrityState → palette token name (the Python _INTEGRITY_TONE_TOKENS
// dict — resolved through the CURRENT theme palette at render time).
QString integrity_tone_token(ui_data_core::IntegrityState state);

// _VersionsTableView — version table + QTableWidget-compat accessors.
class VersionsTableView : public QTableView {
    Q_OBJECT
public:
    explicit VersionsTableView(QWidget* parent = nullptr);

    int rowCount() const;
    int columnCount() const;
    int currentRow() const;
    QString item_text(int row, int column) const;
    QString horizontal_header_text(int column) const;
};

// LineageTreeWidget — full upstream-to-RAW + downstream tree with
// interleaved run nodes; selection shows version/run details.
class LineageTreeWidget : public QWidget {
    Q_OBJECT
public:
    explicit LineageTreeWidget(QWidget* parent = nullptr);

    void clear_chain(const QString& message = QString());
    void show_loading(const QString& message =
                          QStringLiteral("正在加载血缘链…"));
    // load_chains(view, upstream, downstream) — nullopt = Python None.
    void load_chains(
        const ui_data_core::AssetView& view,
        const std::optional<catalog::LineageChain>& upstream,
        const std::optional<catalog::LineageChain>& downstream);

    // (kind, payload) — Python (kind, dict) tuple parity.
    struct Payload {
        QString kind;
        QVariantMap data;
    };
    std::optional<Payload> selected_payload() const {
        return selected_payload_;
    }

    QTreeWidget* tree = nullptr;
    QLabel* detail_label = nullptr;

signals:
    void version_activated(const QString& version_id,
                           const QString& asset_id);

private:
    QTreeWidgetItem* append_version_node(
        QTreeWidgetItem* parent, const catalog::LineageChainNode& node,
        const QString& direction);
    static void expand_recursive(QTreeWidgetItem* item);
    void on_selection();
    void on_double_clicked(QTreeWidgetItem* item, int column);

    std::optional<Payload> selected_payload_;
};

class InspectorPanel : public QFrame {
    Q_OBJECT
public:
    explicit InspectorPanel(QWidget* parent = nullptr);
    // Out-of-line: unique_ptr<StableSelection> needs the complete type.
    ~InspectorPanel() override;

    // update_asset(asset, lineage_up, lineage_down) — nullptr asset clears
    // the panel (Python ``update_asset(None)``).
    void update_asset(
        const ui_data_core::AssetHandle& asset,
        const std::optional<catalog::LineageChain>& lineage_up =
            std::nullopt,
        const std::optional<catalog::LineageChain>& lineage_down =
            std::nullopt);
    void clear_asset();

    void show_lineage_loading();
    void update_lineage(
        const std::optional<catalog::LineageChain>& lineage_up,
        const std::optional<catalog::LineageChain>& lineage_down);

    // (asset_id) -> VersionUsageReport-shaped dict, or empty QVariantMap.
    using MapUsageProvider =
        std::function<QVariantMap(const QString& asset_id)>;
    void set_map_usage_provider(MapUsageProvider provider) {
        map_usage_provider_ = std::move(provider);
    }

    void set_governance_enabled(bool enabled);
    void set_version_tags_enabled(bool enabled);
    bool version_tags_enabled() const { return version_tags_enabled_; }

    const ui_data_core::AssetView* current_view() const {
        return current_view_.has_value() ? &*current_view_ : nullptr;
    }
    const ui_data_core::AssetHandle& current_asset() const {
        return current_asset_;
    }
    const ui_data_core::VersionView* selected_version() const;

    // Widget handles (Python attribute parity).
    QLabel* title_label = nullptr;
    QLabel* empty_label = nullptr;
    QTabWidget* tabs = nullptr;
    TablePreviewWidget* overview_table = nullptr;
    TablePreviewWidget* governance_table = nullptr;
    TablePreviewWidget* catalog_metadata_table = nullptr;
    TablePreviewWidget* metadata_table = nullptr;
    QPushButton* governance_edit_btn = nullptr;
    QWidget* tags_widget = nullptr;
    TagContainerWidget* tag_container = nullptr;
    VersionsTableView* versions_table = nullptr;
    QWidget* version_tags_bar = nullptr;
    QLabel* version_tags_hint = nullptr;
    QPushButton* version_tag_add_btn = nullptr;
    QPushButton* version_tag_remove_btn = nullptr;
    QPushButton* create_derived_btn = nullptr;
    QLabel* create_derived_hint = nullptr;
    LineageTreeWidget* lineage_tree = nullptr;
    QWidget* integrity_widget = nullptr;
    QLabel* integrity_status_lbl = nullptr;
    QLabel* hash_label = nullptr;
    QPushButton* copy_hash_btn = nullptr;
    QPushButton* verify_btn = nullptr;

signals:
    void tag_added(ui_data_core::AssetHandle asset, const QString& tag_name);
    void tag_removed(ui_data_core::AssetHandle asset, const QString& tag_name);
    void verify_requested(ui_data_core::AssetHandle asset);
    void create_derived_requested(ui_data_core::AssetHandle asset);
    // Version-level tags (F6): (version_id, tag_name).
    void version_tag_added(const QString& version_id, const QString& tag_name);
    void version_tag_removed(const QString& version_id,
                             const QString& tag_name);
    // Governance metadata editing — the page resolves the catalog asset id.
    void governance_edit_requested(ui_data_core::AssetView view);
    // Lineage navigation: double-clicked (version_id, asset_id).
    void lineage_version_activated(const QString& version_id,
                                   const QString& asset_id);

private:
    void populate_overview(const ui_data_core::AssetView& view);
    std::vector<std::pair<QString, QString>> map_usage_rows(
        const ui_data_core::AssetView& view) const;
    void populate_metadata(const ui_data_core::AssetView& view);
    void populate_tags(const ui_data_core::AssetView& view);
    void populate_versions(const ui_data_core::AssetView& view);
    void populate_lineage(
        const ui_data_core::AssetView& view,
        const std::optional<catalog::LineageChain>& lineage_up,
        const std::optional<catalog::LineageChain>& lineage_down);
    void populate_integrity(const ui_data_core::AssetView& view);
    QString render_integrity_status_sheet() const;

    void on_governance_edit_clicked();
    void on_version_selection_changed();
    void sync_version_tag_controls();
    void sync_derived_controls(const ui_data_core::AssetView* view);
    void on_create_derived_clicked();
    void on_version_tag_add();
    void on_version_tag_remove();
    void copy_hash();
    void on_verify_clicked();
    void on_tag_added(const QString& tag_name);
    void on_tag_removed(const QString& tag_name);

    ui_data_core::AssetHandle current_asset_;
    std::optional<ui_data_core::AssetView> current_view_;
    // Row into current_view_->versions (-1 = none) — Python stores the
    // VersionView object; a row index survives the same-view refresh.
    int selected_version_row_ = -1;
    bool version_tags_enabled_ = false;
    QString integrity_color_token_ = QStringLiteral("TEXT_PRIMARY");
    MapUsageProvider map_usage_provider_;

    ui_widgets::ObjectTableModel* versions_model_ = nullptr;
    // Owned helper (not a QObject — cannot use Qt parent ownership).
    std::unique_ptr<ui_widgets::StableSelection> versions_selection_;
    QHBoxLayout* governance_header_layout_ = nullptr;
};

}  // namespace pwb::ui_pages_mapedit

Q_DECLARE_METATYPE(pwb::ui_data_core::AssetHandle)
Q_DECLARE_METATYPE(pwb::ui_data_core::AssetView)
