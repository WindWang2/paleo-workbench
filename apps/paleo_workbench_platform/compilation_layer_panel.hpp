#pragma once

// mockup-faithful-2026-09-24 — ws1「图层」/ ws3「编图图层」tab 容器。
// 稿把图层 tab 分成两节 + ws3 底部整饰行：
//
//   ┌ 主要图层 ▾ ────────────────────────────┐
//   │  <adopted LayerTreePanel / tree view>  │
//   ├ 参考图 ▾ (ws3) / 参考图层 ▾ (ws1) ─────┤
//   │  ☑名称  [====|----] 40%   ← 每参考图层一行 │
//   └ ☑图例  ☑指北针与比例尺   (ws3 only) ───┘
//
// 权威约定（与壳层其余缝一致，本面板只做呈现+发信号）：
//   * 参考行 = 宿主喂入的真实图层行（QgsProject 栅格图层），
//     空集 = 诚实空态行，不伪造图层；
//   * 行勾选 → reference_visibility_changed(layer_id, on) ——
//     宿主写回 QgsLayerTree（唯一可见性权威）；
//   * 滑杆 → reference_opacity_changed(layer_id, pct) ——
//     宿主写回 QgsMapLayer::setOpacity；
//   * 底部整饰勾选 → chrome_element_toggled(element, on) ——
//     宿主写回 map_chrome 文档节（与 MapChromePanel 同一权威）。

#include <QString>
#include <QVector>
#include <QWidget>

class QCheckBox;
class QLabel;
class QVBoxLayout;

namespace pwb::app {

class CompilationLayerPanel : public QWidget {
    Q_OBJECT
public:
    // ws1「图层」= 勾选清单形态（参考图层节只有勾选行）；
    // ws3「编图图层」= 稿式整饰形态（参考图节带透明度滑杆 + 底部
    // 图例/指北针与比例尺勾选行）。
    enum class Mode { Checklist, Compilation };

    explicit CompilationLayerPanel(QWidget* parent = nullptr);

    // 被收编的图层树部件（LayerTreePanel 或裸 QgsLayerTreeView）——
    // 面板取得其父子关系，放在「主要图层」节内。
    void set_tree_widget(QWidget* tree);

    void set_mode(Mode mode);
    Mode mode() const { return mode_; }

    struct ReferenceRow {
        QString layer_id;
        QString label;
        bool visible = true;
        int opacity_pct = 100;
    };
    // 宿主从 QgsProject 投影行集（图层增删时重喂）。
    void set_reference_rows(const QVector<ReferenceRow>& rows);

    // 底部整饰勾选的当前态（宿主从 map_chrome 文档节投影）。
    void set_chrome_state(bool legend, bool north_arrow_scale);

    // Test readback.
    int reference_row_count() const { return reference_row_count_; }
    bool chrome_row_visible() const;

signals:
    void reference_visibility_changed(const QString& layer_id, bool on);
    void reference_opacity_changed(const QString& layer_id, int pct);
    void chrome_element_toggled(const QString& element, bool on);

private:
    void rebuild_rows();

    Mode mode_ = Mode::Checklist;
    QWidget* tree_slot_ = nullptr;
    QLabel* reference_title_ = nullptr;
    QVBoxLayout* reference_box_ = nullptr;
    QWidget* chrome_row_ = nullptr;
    QCheckBox* legend_check_ = nullptr;
    QCheckBox* north_scale_check_ = nullptr;
    QVector<ReferenceRow> rows_;
    int reference_row_count_ = 0;
};

}  // namespace pwb::app
