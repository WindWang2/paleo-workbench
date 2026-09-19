#pragma once

// Port of paleo_workbench/ui/workstation/facies_selector.py (UI-13).
// 相/亚相/微相三级级联选择器 + 选择/换相/词表管理对话框 + 相带画刷
// 上下文。语义权威是 pwb::ui_widgets::core::FaciesTaxonomy（UI-02 已
// 移植）——本文件只做 Qt 呈现，不复制词表逻辑。
//
// 复用面（grill 共识 Q3-d）：绘制相带面完成弹窗、属性表/检查器相字段
// 级联、选中要素「指定相带…」。任一级可停（Q4-b）；取消一律保留几
// 何、属性留空（Q6-a）。

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_widgets/core/facies_taxonomy.hpp>
#include <pwb/ui_widgets/facies_palette_widget.hpp>

#include <QComboBox>
#include <QDialog>
#include <QLineEdit>
#include <QListWidget>
#include <QObject>
#include <QTreeWidget>
#include <QVariantMap>
#include <QWidget>

namespace pwb::ui_composite {

using pwb::domain::Json;
using pwb::ui_widgets::core::FaciesTaxonomy;

// 当前相带画刷（M2）：持续装备状态已在 Pwb::UiWidgets 移植
// （pwb::ui_widgets::FaciesBrushContext，facies_palette_widget.hpp）——
// 本文件复用该权威，不再移植第二份。
using pwb::ui_widgets::FaciesBrushContext;

// 三级级联选择器：相 → 亚相 → 微相，子级随父级过滤；子级首项为空
// （不填）。改父级时清空更细级别。
class FaciesCascadeSelector : public QWidget {
    Q_OBJECT
public:
    FaciesCascadeSelector(const FaciesTaxonomy& taxonomy,
                          QWidget* parent = nullptr);

    std::map<std::string, std::string> selection() const;
    // 按要素三字段恢复选择（非法组合尽量保上级，保不住清空）。
    void set_selection(const Json& attributes);
    // 深度锚定由对话框标题呈现；组合框保持全三段可见。
    void set_default_depth(const std::string& level) { (void)level; }

    std::map<std::string, QComboBox*> combos;

private:
    void repopulate();
    void repopulate_level(const std::string& level);

    const FaciesTaxonomy& taxonomy_;
};

// 绘制完成/指定相带共用的模态对话框。确定返回三字段 + level；取消返
// 回 reject（调用方保留几何、属性留空）。
class FaciesSelectionDialog : public QDialog {
    Q_OBJECT
public:
    FaciesSelectionDialog(const FaciesTaxonomy& taxonomy,
                          const Json& current = Json(),
                          const QString& title = QStringLiteral("指定相带"),
                          const std::string& anchor_level = "facies",
                          QWidget* parent = nullptr);

    std::map<std::string, std::string> selection() const;

private:
    FaciesCascadeSelector* selector_ = nullptr;
};

// 编辑期换相对话框（列表形态）：搜索 + 相列表 + 可选细化行。写入契
// 约与 FaciesSelectionDialog 一致（selection() 三字段 + level）。
class FaciesChangeDialog : public QDialog {
    Q_OBJECT
public:
    FaciesChangeDialog(const FaciesTaxonomy& taxonomy,
                       const Json& current = Json(),
                       const QString& title = QStringLiteral("更改相"),
                       int count = 1,
                       const std::string& anchor_level = "facies",
                       QWidget* parent = nullptr);

    // 读写面（宿主/测试共用）。
    std::vector<QString> listed_facies() const;
    QString selected_facies() const;
    void select_facies(const QString& name);
    void set_search_text(const QString& text);
    std::map<std::string, std::string> selection() const;

private:
    void refill(const QString& preselected = QString());
    void repopulate_lower(const std::string& level);
    std::vector<std::string> selection_chain() const;

    const FaciesTaxonomy& taxonomy_;
    std::string anchor_;
    std::vector<std::string> lower_;
    std::vector<std::string> all_names_;
    QLineEdit* search_ = nullptr;
    QListWidget* list_ = nullptr;
    std::map<std::string, QComboBox*> refine_rows_;
};

// 词表管理（grill Q8-b）：三级树查看 + GeoJSON 导入 + 恢复内置。
// make_builtin 由宿主注入（资源目录知识不进 widget 层）。
class FaciesTaxonomyDialog : public QDialog {
    Q_OBJECT
public:
    FaciesTaxonomyDialog(
        const FaciesTaxonomy& taxonomy,
        std::function<FaciesTaxonomy()> make_builtin,
        QWidget* parent = nullptr);

    bool taxonomy_accepted = false;
    // 用户确认的新词表（未改动/取消返回 nullopt）。
    std::optional<FaciesTaxonomy> result_taxonomy() const;

private:
    void fill_tree(const FaciesTaxonomy& taxonomy);
    void on_import();
    void on_reset();
    void on_accept();

    std::function<FaciesTaxonomy()> make_builtin_;
    std::optional<FaciesTaxonomy> incoming_;
    class QLabel* summary_ = nullptr;
    QTreeWidget* tree_ = nullptr;
};

}  // namespace pwb::ui_composite
