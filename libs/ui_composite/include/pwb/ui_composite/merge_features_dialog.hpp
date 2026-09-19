#pragma once

// Port of paleo_workbench/ui/workstation/merge_features_dialog.py
// (UI-13). 无缝合并确认对话框: prefills the largest-area feature's
// attributes (combo can switch the source feature), highlights
// conflicting fields (facies fields brighter). After acceptance the
// caller hands ``result_payload()`` to the bridge merge path.

#include <map>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>

#include <QComboBox>
#include <QDialog>
#include <QFormLayout>
#include <QLineEdit>

namespace pwb::ui_composite {

using pwb::domain::Json;

class MergeFeaturesDialog : public QDialog {
    Q_OBJECT
public:
    MergeFeaturesDialog(
        std::vector<Json> records,
        std::vector<std::string> facies_fields = {"facies"},
        QWidget* parent = nullptr);

    // 桥 merge_mirror_features 的 attrs_json 对象。
    Json result_payload() const;
    // 测试/调用方改值入口（同步到编辑框）。
    void set_field_value(const std::string& field, const Json& value);

private:
    std::set<std::string> conflicts() const;
    std::set<std::string> facies_field_names() const;
    void rebuild_form();
    void on_source_changed(int index);

    std::vector<Json> records_;
    Json plan_;
    Json attributes_;
    QComboBox* source_ = nullptr;
    QFormLayout* form_ = nullptr;
    std::map<std::string, QLineEdit*> edits_;
};

}  // namespace pwb::ui_composite
