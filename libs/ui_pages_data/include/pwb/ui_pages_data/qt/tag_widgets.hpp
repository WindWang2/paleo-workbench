// UI-06 — tag_widgets.py Qt shells.
//
// TagBadge / TagContainerWidget / TagInputDialog / BulkAddTagDialog /
// BulkRemoveTagDialog / TagManagerDialog. The catalog service is a seam
// (Core catalog lives outside this slice): TagServiceApi mirrors the
// Python call surface; op errors come back as strings, rename collisions
// keep Python's "already exists"-substring detection.
#pragma once

#include <QDialog>
#include <QLineEdit>
#include <QTableView>
#include <QWidget>

#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

class QCheckBox;
class QHBoxLayout;
class QLabel;
class QPushButton;
class QScrollArea;
class QStandardItemModel;
class QTimer;

namespace pwb::ui_pages_data::qt {

class TagBadge : public QWidget {
    Q_OBJECT
public:
    explicit TagBadge(const QString& tag_name, bool removable = true,
                      QWidget* parent = nullptr);
    QString tag_name() const { return tag_name_; }

Q_SIGNALS:
    void remove_requested(const QString& tag_name);

private:
    QString tag_name_;
};

class TagContainerWidget : public QWidget {
    Q_OBJECT
public:
    explicit TagContainerWidget(bool removable = true,
                                QWidget* parent = nullptr);
    void set_tags(const std::vector<std::string>& tags);
    std::vector<std::string> tags() const { return tags_; }

Q_SIGNALS:
    void tag_added(const QString& tag_name);
    void tag_removed(const QString& tag_name);

private:
    void on_remove_tag(const QString& tag_name);
    void prompt_add_tag();

    std::vector<std::string> tags_;
    bool removable_;
    QHBoxLayout* layout_;
    QPushButton* add_btn_;
};

class TagInputDialog : public QDialog {
    Q_OBJECT
public:
    explicit TagInputDialog(std::vector<std::string> existing_tags = {},
                            QWidget* parent = nullptr);
    QString tag_name() const;
    QLabel* label() { return label_; }
    QLineEdit* input() { return input_; }

private:
    void validate_and_accept();
    std::vector<std::string> existing_;
    QLabel* label_;
    QLineEdit* input_;
    QLabel* error_label_;
};

class BulkAddTagDialog : public QDialog {
    Q_OBJECT
public:
    explicit BulkAddTagDialog(QWidget* parent = nullptr);
    std::vector<std::string> tag_names() const;
    QLineEdit* input() { return input_; }

private:
    void validate_and_accept();
    QLineEdit* input_;
    QLabel* error_label_;
};

class BulkRemoveTagDialog : public QDialog {
    Q_OBJECT
public:
    explicit BulkRemoveTagDialog(std::vector<std::string> candidate_tags,
                                 QWidget* parent = nullptr);
    std::vector<std::string> selected_tags() const;

private:
    std::vector<QCheckBox*> checkboxes_;
};

// --- catalog service seam ------------------------------------------------------

struct TagUsageRow {
    std::string name;
    std::string display_name;
    int assets = 0;
    int versions = 0;
};

// Core catalog service surface used by TagManagerDialog. Every op reports
// failure through `error` (false return / non-empty string), matching the
// Python try/except paths; the caller treats "already exists" inside the
// rename error as the collision branch.
class TagServiceApi {
public:
    virtual ~TagServiceApi() = default;
    // name → usage row. error non-empty → load failure (#897 surface).
    virtual std::vector<TagUsageRow> tag_usage(std::string* error) = 0;
    virtual std::vector<std::string> search_tags(const std::string& text,
                                                 std::string* error) = 0;
    virtual std::vector<std::string> list_tags() = 0;
    virtual bool create_tag(const std::string& name,
                            std::string* error) = 0;
    virtual bool rename_tag(const std::string& old_name,
                            const std::string& new_name,
                            const std::string& on_collision,
                            std::string* error) = 0;
    virtual bool merge_tags(const std::string& source,
                            const std::string& target,
                            std::string* error) = 0;
    virtual bool delete_unused_tag(const std::string& name,
                                   std::string* error) = 0;
    virtual std::vector<std::string> prune_unused_tags(
        std::string* error) = 0;
};

class TagManagerDialog : public QDialog {
    Q_OBJECT
public:
    static constexpr int kSearchDebounceMs = 200;

    // service_provider → nullptr when the catalog is unavailable (the
    // "未连接数据目录" hint state); resolved lazily per call like Python.
    explicit TagManagerDialog(
        std::function<TagServiceApi*()> service_provider,
        QWidget* parent = nullptr);

Q_SIGNALS:
    void tag_selected(const QString& tag_name);
    void tags_changed();

private:
    TagServiceApi* service();
    std::vector<TagUsageRow> usage_rows();
    void reload();
    void reload_table();
    void sync_row_actions();
    const TagUsageRow* current_row() const;
    void notify_changed();
    void on_create();
    void on_rename();
    void on_merge();
    void on_delete_unused();
    void on_prune_unused();
    void on_row_double_clicked(int row);

    std::function<TagServiceApi*()> service_provider_;
    std::vector<TagUsageRow> rows_;
    std::string load_error_;

    QLabel* hint_label_;
    QLineEdit* search_input_;
    QTimer* search_debounce_;
    QStandardItemModel* model_;
    QTableView* table_;
    QPushButton* create_btn_;
    QPushButton* rename_btn_;
    QPushButton* merge_btn_;
    QPushButton* delete_btn_;
    QPushButton* prune_btn_;
    QPushButton* refresh_btn_;
};

}  // namespace pwb::ui_pages_data::qt
