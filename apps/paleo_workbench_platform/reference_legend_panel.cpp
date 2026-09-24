#include "reference_legend_panel.hpp"

#include <algorithm>

#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QPainter>
#include <QVBoxLayout>

#include <pwb/viz/facies_colors.hpp>

namespace pwb::app {

namespace {

// 界面线型样例行 —— 水平线样 + 名称（纯图例展示）。
class LineSample : public QWidget {
  public:
    LineSample(QColor color, Qt::PenStyle style, QWidget* parent)
        : QWidget(parent), color_(std::move(color)), style_(style) {
        setFixedHeight(14);
        setMinimumWidth(36);
    }

  protected:
    void paintEvent(QPaintEvent*) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing);
        QPen pen(color_);
        pen.setWidth(2);
        pen.setStyle(style_);
        painter.setPen(pen);
        const int y = height() / 2;
        painter.drawLine(2, y, width() - 2, y);
    }

  private:
    QColor color_;
    Qt::PenStyle style_;
};

QColor swatch_color(const QString& name) {
    // 取色与剖面渲染器同一权威：冻结 FACIES_COLORS 表 + 最长子串匹配
    // （interval_color 同款规则——精确命中优先，否则取能包含在名称里
    // 的最长词条）。
    const auto& table = pwb::viz::facies_colors();
    const std::string key = name.toStdString();
    const auto exact = std::find_if(
        table.begin(), table.end(),
        [&key](const auto& entry) { return entry.first == key; });
    std::string hex;
    if (exact != table.end()) {
        hex = exact->second;
    } else {
        std::size_t best_len = 0;
        for (const auto& entry : table) {
            if (entry.first.size() > best_len &&
                key.find(entry.first) != std::string::npos) {
                best_len = entry.first.size();
                hex = entry.second;
            }
        }
    }
    // 词汇无条目（如「煤层」）→ 中性回退，不冒称权威色。
    return hex.empty() ? QColor(QStringLiteral("#666666"))
                       : QColor(QString::fromStdString(hex));
}

QWidget* swatch(const QString& name, QWidget* parent) {
    auto* row = new QWidget(parent);
    auto* layout = new QHBoxLayout(row);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(5);
    auto* chip = new QFrame(row);
    chip->setFixedSize(18, 12);
    chip->setStyleSheet(QStringLiteral(
        "background:%1;border:1px solid #a0a0a0;")
                            .arg(swatch_color(name).name()));
    layout->addWidget(chip);
    layout->addWidget(new QLabel(name, row), 1);
    return row;
}

}  // namespace

ReferenceLegendPanel::ReferenceLegendPanel(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ReferenceLegendPanel"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(6, 6, 6, 6);
    outer->setSpacing(6);

    auto* litho_title = new QLabel(QStringLiteral("岩性图例"), this);
    litho_title->setObjectName(QStringLiteral("LithoLegendTitle"));
    outer->addWidget(litho_title);

    auto* grid_host = new QWidget(this);
    auto* grid = new QGridLayout(grid_host);
    grid->setContentsMargins(0, 0, 0, 0);
    grid->setHorizontalSpacing(10);
    grid->setVerticalSpacing(3);
    // 稿序两列：砂岩|粉砂岩 / 泥岩|粉砂质泥岩 / 灰岩|泥质灰岩 / 煤层
    const QStringList names = {
        QStringLiteral("砂岩"),   QStringLiteral("粉砂岩"),
        QStringLiteral("泥岩"),   QStringLiteral("粉砂质泥岩"),
        QStringLiteral("灰岩"),   QStringLiteral("泥质灰岩"),
        QStringLiteral("煤层"),
    };
    for (int i = 0; i < names.size(); ++i) {
        grid->addWidget(swatch(names[i], grid_host), i / 2, i % 2);
    }
    outer->addWidget(grid_host);

    auto* rule = new QFrame(this);
    rule->setFrameShape(QFrame::HLine);
    rule->setStyleSheet(QStringLiteral("color:#d0d0d0;"));
    outer->addWidget(rule);

    auto* iface_title = new QLabel(QStringLiteral("界面"), this);
    iface_title->setObjectName(QStringLiteral("InterfaceLegendTitle"));
    outer->addWidget(iface_title);

    const struct {
        const char* name;
        QColor color;
        Qt::PenStyle style;
    } lines[] = {
        {"地层界面", QColor(QStringLiteral("#0078D4")), Qt::SolidLine},
        {"砂体顶界", QColor(QStringLiteral("#d43c3c")), Qt::DashLine},
        {"砂体底界", QColor(QStringLiteral("#3ca03c")), Qt::DashLine},
        {"对比连线", QColor(QStringLiteral("#d43c3c")), Qt::DotLine},
    };
    for (const auto& entry : lines) {
        auto* row = new QWidget(this);
        auto* layout = new QHBoxLayout(row);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(6);
        layout->addWidget(
            new LineSample(entry.color, entry.style, row));
        layout->addWidget(
            new QLabel(QString::fromUtf8(entry.name), row), 1);
        outer->addWidget(row);
    }
    outer->addStretch(1);
}

}  // namespace pwb::app
