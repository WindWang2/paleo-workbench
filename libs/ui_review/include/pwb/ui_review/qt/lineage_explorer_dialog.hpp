#pragma once

// UI-11 — lineage_explorer_dialog.py Qt shell: lazy one-hop provenance
// tree centered on ONE version (OUTPUT → ⚙ Run → INPUT idiom, cycle
// notes, red 断链 rows, bounded overflow rows, expand-to-RAW BFS with
// depth/node caps, version_activated signal). Read-only: the catalog is
// never mutated.

#include "pwb/ui_review/catalog_api.hpp"
#include "pwb/ui_review/lineage_expand.hpp"

#include <QDialog>

#include <deque>
#include <functional>
#include <set>
#include <unordered_map>

class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QPushButton;
class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui_review::qt {

class LineageExplorerDialog : public QDialog {
    Q_OBJECT
public:
    LineageExplorerDialog(
        QWidget* parent,
        std::function<ICatalogApi*()> service_provider,
        const QString& version_id = QString());

    // _recenter — center on version_id (inline warning on unknown id;
    // the previous node stays). Returns True on success.
    bool recenter(const QString& version_id);
    QString current_version_id() const { return current_version_id_; }

    // Python attribute surface.
    QTreeWidget* tree() const { return tree_; }
    QLineEdit* version_edit() const { return version_edit_; }
    QLabel* locate_warning() const { return locate_warning_; }
    QLabel* status_label() const { return status_label_; }
    QLabel* summary_title_label() const { return summary_title_label_; }
    QLabel* summary_meta_label() const { return summary_meta_label_; }
    QLabel* summary_path_label() const { return summary_path_label_; }
    QLabel* run_title_label() const { return run_title_label_; }
    QLabel* run_meta_label() const { return run_meta_label_; }
    QPlainTextEdit* run_params_view() const { return run_params_view_; }
    QPushButton* expand_raw_btn() const { return expand_raw_btn_; }
    QPushButton* locate_in_page_btn() const { return locate_in_page_btn_; }
    QPushButton* copy_id_btn() const { return copy_id_btn_; }
    QTreeWidgetItem* up_branch() const { return up_branch_; }
    QTreeWidgetItem* down_branch() const { return down_branch_; }

signals:
    void version_activated(const QString& version_id);

private:
    ICatalogApi* service() const;
    void warn(const QString& message);
    void load_version(const catalog::DataVersion& version);
    void rebuild_tree(const catalog::DataVersion& version,
                      const std::string& asset_name);
    void show_empty_state();
    QTreeWidgetItem* make_branch(QTreeWidgetItem* parent,
                                 const QString& label,
                                 const std::string& direction,
                                 const std::string& version_id);

    // lazy population — one get_lineage hop per expand.
    void populate_lazy(QTreeWidgetItem* item);
    void attach_nodes(QTreeWidgetItem* holder,
                      const std::vector<LineageNodeSpec>& specs);

    // expand-to-RAW BFS.
    void on_expand_raw();
    QTreeWidgetItem* input_holder(QTreeWidgetItem* item);
    std::vector<QTreeWidgetItem*>
    version_children(QTreeWidgetItem* holder);

    // activation.
    QString selected_or_current_version_id() const;
    void show_context_menu(const QPoint& pos);

    const LineageNodeSpec* spec_of(QTreeWidgetItem* item) const;
    LineageNodeSpec* spec_of(QTreeWidgetItem* item);
    std::string asset_name(const std::string& asset_id) const;
    std::optional<LineageHop> get_lineage(const std::string& vid) const;

    std::function<ICatalogApi*()> service_provider_;
    QString current_version_id_;
    QString current_asset_id_;
    QTreeWidgetItem* up_branch_ = nullptr;
    QTreeWidgetItem* down_branch_ = nullptr;
    std::unordered_map<QTreeWidgetItem*, LineageNodeSpec> specs_;

    QLineEdit* version_edit_ = nullptr;
    QPushButton* locate_btn_ = nullptr;
    QLabel* locate_warning_ = nullptr;
    QLabel* summary_title_label_ = nullptr;
    QLabel* summary_meta_label_ = nullptr;
    QLabel* summary_path_label_ = nullptr;
    QLabel* run_title_label_ = nullptr;
    QLabel* run_meta_label_ = nullptr;
    QPlainTextEdit* run_params_view_ = nullptr;
    QTreeWidget* tree_ = nullptr;
    QLabel* status_label_ = nullptr;
    QPushButton* expand_raw_btn_ = nullptr;
    QPushButton* locate_in_page_btn_ = nullptr;
    QPushButton* copy_id_btn_ = nullptr;
};

}  // namespace pwb::ui_review::qt
