#include <pwb/seismic_viewer/colorbar_widget.hpp>

#include <QColor>
#include <QLinearGradient>
#include <QPaintEvent>
#include <QPainter>
#include <QPen>

#include <cmath>
#include <string>
#include <string_view>

namespace pwb::seismic_viewer {
namespace {

std::string format_label(double value) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%.1f", value);
    return std::string(buf);
}

} // namespace

ColorbarWidget::ColorbarWidget(QWidget* parent) : QWidget(parent) {
    setFixedWidth(60); // frozen with the Python widget
    lut_ = color_lut(name_);
}

void ColorbarWidget::set_colormap(std::string_view name) {
    const ColorLut lut = color_lut(name);
    if (lut.empty()) {
        return; // unknown colormap keeps the current bar (no-op contract)
    }
    name_ = std::string(name);
    lut_ = lut;
    update();
}

void ColorbarWidget::set_range(double min_value, double max_value) {
    min_ = min_value;
    max_ = max_value;
    update();
}

void ColorbarWidget::paintEvent(QPaintEvent*) {
    QPainter painter(this);
    const QRect rect = this->rect();

    QLinearGradient gradient(0, static_cast<double>(rect.bottom()) - 20.0, 0, 20.0);
    const double last = static_cast<double>(lut_.size() - 1);
    for (std::size_t i = 0; i < lut_.size(); ++i) {
        const double pos = last > 0.0 ? static_cast<double>(i) / last : 0.0;
        gradient.setColorAt(pos, QColor(lut_[i][0], lut_[i][1], lut_[i][2], 255));
    }
    const QRectF bar = QRectF(rect).adjusted(10, 20, -30, -20);
    painter.fillRect(bar, gradient);

    painter.setPen(QColor(100, 100, 100));
    painter.drawText(QPointF(bar.right() + 5.0, bar.top() + 10.0),
                     QString::fromStdString(format_label(max_)));
    painter.drawText(QPointF(bar.right() + 5.0, static_cast<double>(bar.bottom())),
                     QString::fromStdString(format_label(min_)));
    painter.drawText(QPointF(bar.right() + 5.0, static_cast<double>(bar.center().y()) + 5.0),
                     QString::fromStdString(format_label((max_ + min_) / 2.0)));
}

} // namespace pwb::seismic_viewer
