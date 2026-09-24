#pragma once

// ws2 连井剖面窗格左列「剖面设置」卡（设计稿：剖面井勾选 + 显示设置）。
// 纯展示/请求部件：勾选变化只发信号，状态由 VizBCrossWellDock 持有
// （剖面井过滤 → SectionCanvas::set_wells 子集投影；地层格架 →
// set_show_tops）。沉积相/测井曲线无渲染开关 —— 固定勾选禁用并注明。

#include <QSet>
#include <QStringList>
#include <QWidget>

class QVBoxLayout;

namespace pwb::app {

class ProfileSettingsPanel : public QWidget {
    Q_OBJECT

  public:
    explicit ProfileSettingsPanel(QWidget* parent = nullptr);

    // 重建剖面井清单（默认全勾；同名井的勾选态跨刷新保留）。
    void set_well_names(const QStringList& names);

  signals:
    // 勾选集为空 = 显示全部井（dock 语义一致）。
    void well_filter_changed(const QSet<QString>& visible);
    void frame_toggled(bool show);

  private:
    void emit_filter();

    QVBoxLayout* wells_box_ = nullptr;
    QStringList names_;
    QSet<QString> checked_;
    bool syncing_ = false;
};

}  // namespace pwb::app
