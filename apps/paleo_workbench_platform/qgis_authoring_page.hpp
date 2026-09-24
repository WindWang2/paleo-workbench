#pragma once

// QgisAuthoringPage — 编图页：照搬 QGIS QgisApp 的窗口组成惯例
// (third_party/qgis/src/app/qgisapp.cpp):
//
//   * 页本身就是一个 QMainWindow —— QGIS 的 dock 面板归「图窗」管，
//     不归外层应用窗管（左栏图层/浏览 tab 化停靠是原版布局）。
//   * 中央区 = QgsMessageBar（画布上缘消息条，无消息时自隐）
//             + 会话 QgsMapCanvas（宿主经 set_canvas 注入）。
//   * 左右/底部 dock 区收编宿主建的 QgsDockWidget/QDockWidget
//     （图层树、数据浏览器……）—— adopt_dock 是唯一入口。
//
// 本页不承载业务功能：智能预测/单因素/编图三模式的命令面走 Ribbon
// 上下文组，功能面板后续按需以 adopt_dock 收编——页面只提供
// QGIS 原版框架。

#include <QMainWindow>
#include <QPointer>
#include <QWidget>

class QDockWidget;
class QgsMessageBar;

namespace pwb::app {

class QgisAuthoringPage : public QMainWindow {
    Q_OBJECT
public:
    explicit QgisAuthoringPage(QWidget* parent = nullptr);

    // 收编会话画布为中央部件（外层包 QgsMessageBar）。重复调用
    // 只替换槽内部件；画布所有权随 Qt 父子链。
    void set_canvas(QWidget* canvas);
    QWidget* canvas() const { return canvas_; }
    QgsMessageBar* message_bar() const { return message_bar_; }

    // QGIS idiom: 把外部建好的 dock 停靠进本页（自动重设父对象）。
    // tabify_on 非空时与既有 dock tab 化同区。
    void adopt_dock(QDockWidget* dock, Qt::DockWidgetArea area,
                    QDockWidget* tabify_on = nullptr);

private:
    QgsMessageBar* message_bar_ = nullptr;
    QWidget* canvas_slot_ = nullptr;  // 画布槽位（中央容器内）
    QPointer<QWidget> canvas_;
};

}  // namespace pwb::app
