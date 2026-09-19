#pragma once

// Port of paleo_workbench/ui/workstation/topology_checker_panel.py
// (UI-13). Error list + rule filter + click zoom/highlight + ignored
// graying (restorable) + single/all fix. Lightweight QWidget usable as
// an inspector tab or standalone; authority stays in the controller's
// TopologyChecker (QGIS geometry-checker semantics).

#include <map>
#include <set>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/topology_checker.hpp>

#include <QComboBox>
#include <QLabel>
#include <QListWidget>
#include <QMenu>
#include <QPushButton>
#include <QWidget>

namespace pwb::ui_composite {

class CompositeEditController;

class TopologyCheckerPanel : public QWidget {
    Q_OBJECT
public:
    explicit TopologyCheckerPanel(QWidget* parent = nullptr);

    // 绑定综合编修控制器（检查/修复走其 TopologyChecker）。传入
    // nullptr 时面板退化为纯信号发射（check_requested）。
    void bind(CompositeEditController* controller);
    void set_errors(const std::vector<Json>& errors,
                    const std::set<IgnoreKey>& ignored_keys = {},
                    const std::string& last_run_at = "");
    // 单条右键：check 声明的方法列表（含预览描述）。
    QMenu* menu_for(const Json& error);

    QLabel* badge = nullptr;
    QComboBox* rule_filter = nullptr;
    QListWidget* error_list = nullptr;
    QPushButton* check_button = nullptr;
    QPushButton* fix_button = nullptr;
    QPushButton* fix_all_button = nullptr;
    QPushButton* ignore_button = nullptr;
    QPushButton* restore_button = nullptr;

signals:
    void zoom_requested(const QList<double>& bbox);
    void highlight_requested(const QString& error_id);
    void check_requested();
    void fix_requested(const QString& error_id, int method);
    void fix_all_requested();
    void ignore_requested(const QVariantMap& error);
    void restore_requested(const QVariantMap& error);

private:
    void rebuild();
    Json current_error() const;
    void on_item_clicked(QListWidgetItem* item);
    void on_check();
    void on_menu(const QPoint& pos);
    void on_fix();
    void on_ignore();
    void on_restore();

    std::vector<Json> all_errors_;
    std::set<IgnoreKey> ignored_keys_;
    CompositeEditController* controller_ = nullptr;
    std::string last_run_at_;
};

}  // namespace pwb::ui_composite
