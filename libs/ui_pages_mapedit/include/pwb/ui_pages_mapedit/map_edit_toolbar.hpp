// UI-08 — paleo_workbench/ui/pages/map_edit_toolbar.py port: exclusive edit
// tools plus snap, undo/redo, preview, and save-draft actions.
#pragma once

#include <QWidget>

#include <QString>
#include <map>
#include <vector>

class QAbstractButton;
class QButtonGroup;
class QFrame;
class QHBoxLayout;
class QPushButton;

namespace pwb::ui_pages_mapedit {

// TOOL_IDS / TOOL_LABELS — declaration order + Chinese labels.
inline const std::vector<QString>& tool_ids() {
    static const std::vector<QString> ids = {
        QStringLiteral("select"), QStringLiteral("move"),
        QStringLiteral("vertex"), QStringLiteral("facies"),
        QStringLiteral("line"),   QStringLiteral("label"),
    };
    return ids;
}
QString tool_label(const QString& tool_id);

class MapEditToolbar : public QWidget {
    Q_OBJECT
public:
    explicit MapEditToolbar(QWidget* parent = nullptr);

    QString current_tool() const { return current_tool_; }
    void set_tool(const QString& tool_id);  // unknown id → std::invalid_argument

    bool is_preview_mode() const { return preview_mode_; }
    void set_preview_mode(bool enabled);

    // Per-tool button handles (Python ``select_btn``/``move_btn``/... attrs).
    QPushButton* tool_button(const QString& tool_id) const;
    QPushButton* select_btn() const { return tool_button(QStringLiteral("select")); }
    QPushButton* move_btn() const { return tool_button(QStringLiteral("move")); }
    QPushButton* vertex_btn() const { return tool_button(QStringLiteral("vertex")); }
    QPushButton* facies_btn() const { return tool_button(QStringLiteral("facies")); }
    QPushButton* line_btn() const { return tool_button(QStringLiteral("line")); }
    QPushButton* label_btn() const { return tool_button(QStringLiteral("label")); }

    QPushButton* snap_btn = nullptr;
    QPushButton* undo_btn = nullptr;
    QPushButton* redo_btn = nullptr;
    QPushButton* preview_btn = nullptr;
    QPushButton* canvas_priority_btn = nullptr;
    QPushButton* topology_btn = nullptr;
    QPushButton* merge_btn = nullptr;
    QPushButton* split_btn = nullptr;
    QPushButton* generate_demo_draft_btn = nullptr;
    QPushButton* save_draft_btn = nullptr;

signals:
    void tool_changed(const QString& tool_id);
    void snap_toggled(bool enabled);
    void preview_toggled(bool enabled);
    void canvas_priority_toggled(bool enabled);
    void topology_rebuild_requested();
    void merge_facies_requested();
    void split_facies_requested();
    void save_draft_requested();
    void generate_demo_draft_requested();
    void undo_requested();
    void redo_requested();

private:
    QFrame* add_separator(QHBoxLayout* layout);
    void on_tool_clicked(QAbstractButton* button);
    void apply_tool(const QString& tool_id);

    QButtonGroup* tool_group_ = nullptr;
    std::map<QString, QPushButton*> tool_buttons_;
    QString current_tool_ = QStringLiteral("select");
    bool preview_mode_ = false;
};

}  // namespace pwb::ui_pages_mapedit
