#pragma once

// ws2 右栏「参考」签（设计稿：岩性图例 + 界面线型图例）。
// 岩性色块取色与剖面渲染器同一权威 —— viz::facies_color_for
// （FACIES_COLORS 冻结表 + 最长子串匹配）；词汇无条目时诚实回退
// 中性色，不伪造「真值色」。界面图例是静态线型展示（非功能开关）。

#include <QWidget>

namespace pwb::app {

class ReferenceLegendPanel : public QWidget {
    Q_OBJECT

  public:
    explicit ReferenceLegendPanel(QWidget* parent = nullptr);
};

}  // namespace pwb::app
