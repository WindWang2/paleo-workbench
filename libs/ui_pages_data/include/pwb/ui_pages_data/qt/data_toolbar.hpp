// UI-06 — data_toolbar.py :: DataToolbar Qt shell.
//
// Button row + debounced search box + tag-filter menu + verify-state
// toggle. Timings/verify text come from timings.hpp; icons are an injected
// seam (ui.workstation.common.tinted_map_icon is another slice).
#pragma once

#include <QWidget>

#include <functional>
#include <string>
#include <vector>

class QAction;
class QActionGroup;
class QIcon;
class QLabel;
class QLineEdit;
class QMenu;
class QPushButton;
class QTimer;

namespace pwb::ui_pages_data::qt {

// (icon_name) → QIcon seam; default empty icons.
using ToolbarIconFn = std::function<QIcon(const std::string& name)>;

class DataToolbar : public QWidget {
    Q_OBJECT
public:
    explicit DataToolbar(QWidget* parent = nullptr);

    static void set_icon_provider(ToolbarIconFn fn);
    // Seam read for the shell's icon resolution (anonymous helpers in the
    // .cpp go through this — the provider itself stays private).
    static const ToolbarIconFn& icon_provider() { return icon_provider_; }

    // data_toolbar.set_verify_running — text/tooltip swap only; the
    // 取消导入 button's visibility is the PAGE's import state, not this.
    void set_verify_running(bool running);
    bool verify_running() const { return verify_running_; }

    void set_column_settings_button(QPushButton* button);

    // --- tag filter panel ---------------------------------------------------
    void set_tag_candidates(const std::vector<std::string>& tags);
    std::vector<std::string> tag_candidates() const { return tag_candidates_; }
    void set_tag_operator(const std::string& op);
    std::vector<std::string> current_tag_selection() const {
        return selected_tags_;
    }
    std::string current_tag_operator() const { return tag_operator_; }
    // Programmatic apply (Tag Manager 查看关联数据 / saved filter).
    void apply_tag_selection(const std::vector<std::string>& tags,
                             const std::string& op = "and");
    void clear_tag_filter();

    // Programmatic sync WITHOUT re-emitting search_changed (#feedback loop).
    void set_search_text_silent(const QString& text);

    QPushButton* import_button() { return import_btn_; }
    QPushButton* verify_button() { return verify_btn_; }
    QPushButton* cancel_import_button() { return cancel_import_btn_; }
    QPushButton* reader_button() { return reader_btn_; }
    QLineEdit* search_box() { return search_box_; }
    QLabel* operation_status_label() { return operation_status_label_; }
    QTimer* search_timer() { return search_timer_; }

Q_SIGNALS:
    void import_files_requested();
    void import_folder_requested();
    void plan_import_requested();
    void rescan_requested();
    void remove_requested();
    void open_folder_requested();
    void visualize_requested();
    void clear_preview_cache_requested();
    void verify_requested();
    void health_check_requested();
    void reader_toggled();
    void search_changed(const QString& text);
    void tag_filter_changed(const QStringList& tags, const QString& op);
    void tag_manager_requested();
    void cancel_import_requested();

private:
    void rebuild_tag_filter_menu();
    void on_tag_toggled(const std::string& tag, bool checked);
    void on_operator_changed(const std::string& op, bool checked);
    void emit_tag_filter();
    void emit_debounced_search();

    QPushButton* import_btn_;
    QPushButton* import_folder_btn_;
    QPushButton* plan_import_btn_;
    QPushButton* cancel_import_btn_;
    QPushButton* verify_btn_;
    QPushButton* health_btn_;
    QPushButton* rescan_btn_;
    QPushButton* remove_btn_;
    QPushButton* open_folder_btn_;
    QPushButton* visualize_btn_;
    QPushButton* clear_preview_cache_btn_;
    QPushButton* tag_filter_btn_;
    QPushButton* tag_manager_btn_;
    QLabel* operation_status_label_;
    QLineEdit* search_box_;
    QWidget* column_settings_slot_;
    QPushButton* reader_btn_;
    QMenu* tag_filter_menu_;
    QTimer* search_timer_;

    bool verify_running_ = false;
    bool search_sync_ = false;
    QString pending_search_;
    std::vector<std::string> tag_candidates_;
    std::vector<std::string> selected_tags_;
    std::string tag_operator_ = "and";
    std::vector<QAction*> tag_check_actions_;

    static ToolbarIconFn icon_provider_;
};

}  // namespace pwb::ui_pages_data::qt
