#pragma once

// M5-2 — 综合编图 (ws3) 的版式轻量面板 (design F:66-70):
//
//   * 模板/纸张/方向/图例/指北针/比例尺/标题栏控件 —— 仅进入版式模式时
//     显示（AppShell 的 ws3 底部栈第 2 页；默认画布组版原样，F:70）；
//   * 模板清单来自 mapping_document::composer_template_library()（9 个
//     真实内置模板），预览用模板的真实 mm 几何矢量重绘（不是截图）；
//   * 图例/指北针/比例尺/标题栏状态 = 活动编图文档的 map_chrome 载荷
//     （与 MapChromePanel 同一形状、同一文档状态——单一权威，F:69）；
//   * 导出入口复用宿主注入的 governed map_export QAction（D4，无平行
//     实现）；导出确认/真实写入结果由该动作既有路径负责。

#include <functional>

#include <QAction>
#include <QImage>
#include <QMap>
#include <QWidget>

#include <pwb/domain/json.hpp>

class QCheckBox;
class QComboBox;
class QLabel;

namespace pwb::app {

class LayoutComposePanel : public QWidget {
    Q_OBJECT
public:
    explicit LayoutComposePanel(QWidget* parent = nullptr);

    // ---- host seams (the M5 compose install binds these) -------------------
    // chrome reader/writer ride the ACTIVE map document's map_chrome —
    // the same {"title", "elements": [...]} payload MapChromePanel emits.
    void set_chrome_reader(std::function<pwb::domain::Json()> reader);
    void set_chrome_writer(
        std::function<void(const pwb::domain::Json&)> writer);
    // The governed export action (the SAME QAction the menus carry).
    void set_export_action(QAction* action);
    // BEGIN qgis-native-layout-convergence
    // Real-layout seams: template selection materializes a persistent
    // QgsPrintLayout through the session authority; the preview renders
    // that layout through the same QgsLayoutExporter the export path
    // uses (no self-painted second visual scene). Unbound seams keep the
    // honest placeholder text.
    void set_layout_instantiate_fn(
        std::function<bool(const std::string&)> fn);
    void set_layout_preview_fn(std::function<QImage()> fn);
    // END qgis-native-layout-convergence
    // Re-read the chrome state from the document (project open/switch).
    void refresh_chrome();

    // ---- state / test surface ----------------------------------------------
    QComboBox* template_selector() const { return template_; }
    QComboBox* paper_selector() const { return paper_; }
    QComboBox* orientation_selector() const { return orientation_; }
    QWidget* preview() const { return preview_; }
    QList<QCheckBox*> chrome_checks() const { return checks_.values(); }
    bool chrome_checked(const QString& element) const;
    QString selected_template_id() const;
    // The draft layout spec (template/paper/orientation/chrome) — what
    // the writer persists into the active document.
    pwb::domain::Json draft() const;

signals:
    void status_message(const QString& message);

private:
    void rebuild_template_selector();
    void sync_chrome_checks();
    void emit_chrome();
    void update_preview();
    void instantiate_selected_template();

    std::function<pwb::domain::Json()> chrome_reader_;
    std::function<void(const pwb::domain::Json&)> chrome_writer_;
    QMap<QString, QCheckBox*> checks_;  // 图例/指北针/比例尺/标题栏
    QComboBox* template_ = nullptr;
    QComboBox* paper_ = nullptr;
    QComboBox* orientation_ = nullptr;
    QWidget* preview_ = nullptr;
    QLabel* hint_ = nullptr;
    QAction* export_action_ = nullptr;
    // qgis-native-layout-convergence seams (see setters).
    std::function<bool(const std::string&)> layout_instantiate_fn_;
    std::function<QImage()> layout_preview_fn_;
    QLabel* preview_label_ = nullptr;
    bool syncing_ = false;
};

}  // namespace pwb::app
