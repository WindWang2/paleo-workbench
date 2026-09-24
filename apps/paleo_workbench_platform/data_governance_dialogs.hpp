#pragma once

// ws0 数据治理闭环 — 四个治理对话框 + 回收站确认流。
//
// 对话框只做编排：读写全部走 pwb::data::governance 服务（见
// libs/data_suite governance.hpp 的权威/失败契约），成功后 emit
// applied() 并调用注入的 refresh_notify；失败 QMessageBox 如实上屏，
// 绝不出现“假成功”。所有应用动作都是 public 方法 —— offscreen 测试
// 不需要 exec() 即可驱动完整写路径。
//
// Threading: 全部 GUI 线程（与 ws0 既有写路径一致——导入对话框同款
// 同步纪律）。

#include <filesystem>
#include <functional>
#include <string>
#include <vector>

#include <QDialog>

#include <pwb/data/governance.hpp>  // TrashedEntry（entries_ 成员需完整类型）

class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QListWidgetItem;
class QPushButton;
class QTableWidget;

namespace pwb::app::data_governance {

// 把服务的 (ok,error/summary) 翻成用户可见的结果——失败弹窗、成功走
// status 回调（不弹窗打断）。返回 ok。
bool report_outcome(class QWidget* parent, const QString& title,
                    bool ok, const std::string& error,
                    const std::string& summary);

// ---------------------------------------------------------------------------
// 关联到井：选井 + 选角色（词汇表 + 自定义）+ 主数据位；已有链接可解除。
// ---------------------------------------------------------------------------
class LinkWellDialog : public QDialog {
    Q_OBJECT
public:
    LinkWellDialog(const std::filesystem::path& project_file,
                   const std::string& asset_id,
                   const std::string& asset_name,
                   std::function<void()> refresh_notify,
                   QWidget* parent = nullptr);

    // -- test seams (no exec needed) --
    void select_well(const std::string& well_id);
    void set_role_input(const std::string& role);
    void set_primary(bool primary);
    bool apply_link();          // 关联所选井
    bool apply_unlink(int row); // 解除第 row 条已有链接

    std::vector<std::string> linked_entity_ids() const;

Q_SIGNALS:
    void applied();
    void status_message(const QString& text);

private Q_SLOTS:
    void rebuild_well_list();

private:
    void reload_links();

    std::filesystem::path project_file_;
    std::string asset_id_;
    std::function<void()> refresh_notify_;

    QLabel* asset_label_ = nullptr;
    QLineEdit* well_search_ = nullptr;
    QListWidget* well_list_ = nullptr;
    QComboBox* role_combo_ = nullptr;
    QLineEdit* role_custom_ = nullptr;
    QCheckBox* primary_check_ = nullptr;
    QTableWidget* links_table_ = nullptr;
    QPushButton* unlink_button_ = nullptr;
};

// ---------------------------------------------------------------------------
// 设置角色：列出资产全部链接，改其中一条的角色。
// ---------------------------------------------------------------------------
class SetRoleDialog : public QDialog {
    Q_OBJECT
public:
    SetRoleDialog(const std::filesystem::path& project_file,
                  const std::string& asset_id,
                  const std::string& asset_name,
                  std::function<void()> refresh_notify,
                  QWidget* parent = nullptr);

    // -- test seams --
    void select_link(int row);
    void set_role_input(const std::string& role);
    bool apply_role();

Q_SIGNALS:
    void applied();
    void status_message(const QString& text);

private:
    void reload_links();

    std::filesystem::path project_file_;
    std::string asset_id_;
    std::function<void()> refresh_notify_;

    QLabel* asset_label_ = nullptr;
    QTableWidget* links_table_ = nullptr;
    QComboBox* role_combo_ = nullptr;
    QLineEdit* role_custom_ = nullptr;
};

// ---------------------------------------------------------------------------
// 标签管理：多选资产的标签增删（TagStore 正规化）。
// ---------------------------------------------------------------------------
class TagsDialog : public QDialog {
    Q_OBJECT
public:
    TagsDialog(const std::filesystem::path& project_file,
               const std::vector<std::string>& asset_ids,
               const std::vector<std::string>& asset_names,
               std::function<void()> refresh_notify,
               QWidget* parent = nullptr);

    // -- test seams --
    bool apply_add(const std::string& raw_names);   // 逗号/分号分隔多标签
    bool apply_remove(const std::string& tag_name);

Q_SIGNALS:
    void applied();
    void status_message(const QString& text);

private:
    void reload_tags();

    std::filesystem::path project_file_;
    std::vector<std::string> asset_ids_;
    std::function<void()> refresh_notify_;

    QLabel* scope_label_ = nullptr;
    QListWidget* current_tags_ = nullptr;
    QLineEdit* add_input_ = nullptr;
    QPushButton* remove_button_ = nullptr;
};

// ---------------------------------------------------------------------------
// 回收站：trashed 资产列表 + 恢复。非模态（查看型视图）。
// ---------------------------------------------------------------------------
class TrashDialog : public QDialog {
    Q_OBJECT
public:
    TrashDialog(const std::filesystem::path& project_file,
                std::function<void()> refresh_notify,
                QWidget* parent = nullptr);

    void reload();
    // -- test seams --
    bool restore_selected();
    int table_rows() const;
    void select_row_for(const std::string& asset_id);

Q_SIGNALS:
    void applied();
    void status_message(const QString& text);

private:
    std::filesystem::path project_file_;
    std::function<void()> refresh_notify_;
    QTableWidget* table_ = nullptr;
    std::vector<pwb::data::governance::TrashedEntry> entries_;
};

}  // namespace pwb::app::data_governance
