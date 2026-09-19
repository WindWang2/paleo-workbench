#include <pwb/viz/well_tie/qt/report_export.hpp>

#include <QColor>
#include <QDate>
#include <QFileInfo>
#include <QFont>
#include <QPageSize>
#include <QPainter>
#include <QPen>
#include <QPrinter>
#include <QRectF>
#include <QSvgGenerator>

#include <cmath>

namespace pwb::viz::well_tie::qt {

namespace {

QString dash(const QString& value) {
    return value.isEmpty() ? QStringLiteral("—") : value;
}

QString dash_num(double value, const QString& suffix, char format = 'f',
                 int precision = 3) {
    if (std::isnan(value)) return QStringLiteral("—");
    return QString::number(value, format, precision) + suffix;
}

void render_report_page(QPainter* painter, const WellTieReportInputs& inputs,
                        double w, double h) {
    painter->fillRect(QRectF(0, 0, w, h), Qt::white);
    // Title.
    QFont title_font = painter->font();
    title_font.setFamily("SimSun");
    title_font.setPointSize(16);
    title_font.setBold(true);
    painter->setFont(title_font);
    painter->setPen(QPen(QColor(31, 102, 212), 1.0));
    painter->drawText(QRectF(20, 20, w - 40, 40),
                      Qt::AlignLeft | Qt::AlignVCenter,
                      QStringLiteral("油田井震精细标定与相关性分析报告"));
    // Title block: three equal columns at the bottom (60 px tall).
    const QRectF block(20, h - 80, w - 40, 60);
    painter->setPen(QPen(QColor(88, 104, 120), 1.5));
    painter->setBrush(Qt::NoBrush);
    painter->drawRect(block);
    painter->drawLine(QPointF(block.left() + block.width() / 3, block.top()),
                      QPointF(block.left() + block.width() / 3,
                              block.bottom()));
    painter->drawLine(
        QPointF(block.left() + 2 * block.width() / 3, block.top()),
        QPointF(block.left() + 2 * block.width() / 3, block.bottom()));
    QFont block_font = painter->font();
    block_font.setFamily("SimSun");
    block_font.setPointSize(9);
    block_font.setBold(false);
    painter->setFont(block_font);
    painter->setPen(QPen(QColor(40, 40, 40), 1.0));
    const double row_h = block.height() / 2;
    const QString date =
        inputs.date_str.isEmpty()
            ? QDate::currentDate().toString(Qt::ISODate)
            : inputs.date_str;
    const QString col1 =
        QString("井名: %1 | 区块: %2\n层位: %3")
            .arg(dash(inputs.well_name), dash(inputs.block),
                 dash(inputs.horizon));
    const QString col2 =
        QString("子波: %1\n相关系数 R: %2 | 偏置: %3")
            .arg(dash(inputs.wavelet), dash_num(inputs.r_score, ""),
                 dash_num(inputs.lag_ms, " ms", 'f', 1));
    const QString col3 =
        QString("编制单位: %1\n日期: %2 | 比例尺: —")
            .arg(inputs.org.isEmpty()
                     ? QStringLiteral("GeoViz Research Engine")
                     : inputs.org,
                 date);
    const QRectF c1(block.left(), block.top(), block.width() / 3, row_h * 2);
    const QRectF c2(c1.right(), block.top(), block.width() / 3, row_h * 2);
    const QRectF c3(c2.right(), block.top(), block.width() / 3, row_h * 2);
    painter->drawText(c1, Qt::AlignCenter, col1);
    painter->drawText(c2, Qt::AlignCenter, col2);
    painter->drawText(c3, Qt::AlignCenter, col3);
}

}  // namespace

bool export_well_tie_report(const WellTieReportInputs& inputs,
                            const QString& output_path) {
    const QString suffix = output_path.section('.', -1).toLower();
    if (suffix == "svg") {
        QSvgGenerator generator;
        generator.setFileName(output_path);
        generator.setSize(QSize(3508, 2480));
        generator.setViewBox(QRectF(0, 0, 3508, 2480));
        QPainter painter(&generator);
        if (!painter.isActive()) return false;
        render_report_page(&painter, inputs, 3508.0, 2480.0);
        painter.end();
        return QFileInfo::exists(output_path);
    }
    QPrinter printer(QPrinter::HighResolution);
    printer.setOutputFormat(QPrinter::PdfFormat);
    printer.setOutputFileName(output_path);
    printer.setResolution(300);
    printer.setPageSize(QPageSize(QPageSize::A4));
    printer.setPageOrientation(QPageLayout::Landscape);
    QPainter painter(&printer);
    if (!painter.isActive()) return false;
    const QSizeF points =
        printer.pageLayout().pageSize().size(QPageSize::Point);
    render_report_page(&painter, inputs, points.width(), points.height());
    painter.end();
    return QFileInfo::exists(output_path);
}

}  // namespace pwb::viz::well_tie::qt
