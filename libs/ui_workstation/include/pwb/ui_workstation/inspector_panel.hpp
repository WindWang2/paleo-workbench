#pragma once

// Qt shell over inspector_spec (UI-12) — port of
// paleo_workbench/ui/workstation/inspector.py's widget layer: four
// tabs (属性/解释/样式/历史), form rows in read-only QLineEdits with the
// "missing" property, style summary + edit button, history list.
// Renders an InspectorDocument — it never reads domain objects.

#include <QFormLayout>
#include <QFrame>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QTabWidget>
#include <QVariantMap>

#include <pwb/ui_workstation/inspector_spec.hpp>

namespace pwb::ui_workstation {

class WorkstationInspector : public QFrame {
    Q_OBJECT
public:
    explicit WorkstationInspector(QWidget* parent = nullptr);

    // Project-context facts the builders read from self._project.
    void set_target_horizon(const std::string& horizon);
    void set_seam_rows(
        std::vector<std::pair<std::string, std::string>> rows);

    // The payload entry point (Python show_payload). `payload.object`
    // is forwarded verbatim in assign_facies_requested.
    void show_payload(const InspectorPayload& payload);
    void show_empty();
    const InspectorPayload& current_payload() const {
        return current_payload_;
    }

    QTabWidget* tabs() const { return tabs_; }

signals:
    void style_changed(const QVariantMap& style);  // 兼容保留
    void assign_facies_requested(const QVariantMap& payload);
    void edit_style_requested(const QString& layer_id);

private:
    void render(const InspectorDocument& doc);
    void clear_form(QFormLayout* form);
    void fill_form(QFormLayout* form,
                   const std::vector<std::pair<std::string, std::string>>&
                       rows);

    InspectorPayload current_payload_;
    std::string target_horizon_;
    std::vector<std::pair<std::string, std::string>> seam_rows_;
    std::string style_layer_id_;

    QLabel* header_ = nullptr;
    QTabWidget* tabs_ = nullptr;
    QFormLayout* properties_form_ = nullptr;
    QFormLayout* interpretation_form_ = nullptr;
    QLabel* style_summary_ = nullptr;
    QPushButton* style_edit_button_ = nullptr;
    QListWidget* history_list_ = nullptr;
    QPushButton* assign_button_ = nullptr;
};

}  // namespace pwb::ui_workstation
