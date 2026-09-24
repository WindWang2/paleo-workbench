#include "pwb/qgis_plot/numeric_formats.hpp"

#include <cmath>

#include <qgsreadwritecontext.h>

namespace pwb::qgis_plot {

QString PwbDepthNumericFormat::formatDouble(
    double value, const QgsNumericFormatContext& context) const {
    return QgsBasicNumericFormat::formatDouble(std::fabs(value), context);
}

QgsNumericFormat* PwbDepthNumericFormat::clone() const {
    auto* f = new PwbDepthNumericFormat();
    f->setConfiguration(configuration(QgsReadWriteContext()),
                        QgsReadWriteContext());
    return f;
}

QgsNumericFormat* PwbDepthNumericFormat::create(
    const QVariantMap& configuration,
    const QgsReadWriteContext& context) const {
    auto* f = new PwbDepthNumericFormat();
    f->setConfiguration(configuration, context);
    return f;
}

QVariantMap PwbDepthNumericFormat::configuration(
    const QgsReadWriteContext& context) const {
    return QgsBasicNumericFormat::configuration(context);
}

}  // namespace pwb::qgis_plot
