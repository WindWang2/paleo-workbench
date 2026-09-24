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

    // 程序化镜像（联动 map→剖面 的选中投影）：把勾选态设为 visible 集
    // （不重发 well_filter_changed——调用方已持有该状态，避免回环）。
    // 空 visible 集 = 全部取消勾选（与用户手办一致，dock 侧显示无井）。
    void set_well_filter(const QSet<QString>& visible);

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
