// QGIS-plot convergence — numeric format for depth axes.
//
// Depth increases downward; plot Y increases upward, so depth series are fed
// negated (y = -depth) while labels must read positive. PwbDepthNumericFormat
// formats |value| with QgsBasicNumericFormat semantics and is installed on an
// axis via setNumericFormat (not registered globally).
#pragma once

#include <qgsbasicnumericformat.h>

namespace pwb::qgis_plot {

class PwbDepthNumericFormat : public QgsBasicNumericFormat {
public:
    PwbDepthNumericFormat() { setShowThousandsSeparator(false); }
    QString id() const override { return QStringLiteral("pwb_depth"); }
    QString visibleName() const override { return QStringLiteral("Depth"); }
    int sortKey() override { return DEFAULT_SORT_KEY + 1; }
    QString formatDouble(double value,
                         const QgsNumericFormatContext& context) const override;
    QgsNumericFormat* clone() const override;
    QgsNumericFormat* create(const QVariantMap& configuration,
                             const QgsReadWriteContext& context) const override;
    QVariantMap configuration(const QgsReadWriteContext& context) const override;
};

}  // namespace pwb::qgis_plot
