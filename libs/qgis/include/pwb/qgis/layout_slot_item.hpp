#pragma once

// PwbLayoutSlotItem — the *only* custom QgsLayoutItem in the Paleo platform.
//
// QGIS native items own the standard furniture (map/legend/scalebar/label/
// picture/shape/table…). This item covers the Paleo professional decorations
// QGIS has no native equivalent for:
//   - statistical charts driven by *domain series* (the QGIS 4 native chart
//     item is layer/expression driven, which cannot host computed domain
//     series like per-horizon misfits or provenance rose sectors);
//   - continuous colorbars bound to factor ranges;
//   - geological timescale strips, profile boxes, fault-symbol legends and
//     lithology legends;
//   - honest placeholders for unknown legacy elements during migration.
//
// Everything except the *content drawing* stays native: geometry, z-order,
// rotation, selection, lock/visibility, undo commands, copy/paste, XML
// persistence and all export paths are inherited from QgsLayoutItem. The
// item draws its content with plain QPainter from a persisted JSON payload
// (writePropertiesToElement/readPropertiesFromElement).
//
// Registered into QgsApplication::layoutItemRegistry() by
// pwb::qgis::ensure_slot_item_registered() (see layout_slot_item.cpp) with a
// stable type id; layout XML written by one build reads back on another.

#include <pwb/domain/json.hpp>

#include <QIcon>
#include <QString>

#include <string>

#include <qgslayoutitem.h>
#include <qgslayoutitemregistry.h>

class QDomDocument;
class QDomElement;
class QgsLayoutItemRenderContext;
class QgsReadWriteContext;
class QgsRenderContext;

namespace pwb::qgis {

class PwbLayoutSlotItem final : public QgsLayoutItem {
    Q_OBJECT

public:
    // Stable registry type: first plugin slot after QgsLayoutItemRegistry's
    // own plugin base (Paleo owns this offset; never renumber).
    static constexpr int ItemTypeId = QgsLayoutItemRegistry::PluginItem + 1;

    // Content kinds. `kind` is persisted verbatim — extend, never rename.
    enum class Kind {
        StatChart,        // properties: chart_type/title/series|data_binding
        Colorbar,         // properties: title/min/max/discrete/stops/units
        Timescale,        // properties: intervals
        Profile,          // properties: title/axes hints
        FaultSymbols,     // properties: title/items[{label,pattern}]
        LithologyLegend,  // properties: title/entries[{label,pattern}]
        Placeholder,      // properties: label  (unknown legacy element)
    };

    static const char* kind_key(Kind kind) noexcept;
    static std::optional<Kind> kind_from_string(const std::string& text);

    explicit PwbLayoutSlotItem(QgsLayout* layout);
    ~PwbLayoutSlotItem() override;

    static QgsLayoutItem* create(QgsLayout* layout);

    int type() const override { return ItemTypeId; }
    QIcon icon() const override;

    void set_kind(Kind kind) { kind_ = kind; }
    Kind kind() const { return kind_; }
    std::string kind_string() const;

    // Slot tag shown by the editor (e.g. "statistics_chart"); also persisted
    // so slot metadata survives copy/paste independent of pwb/item_slots.
    void set_slot_name(const std::string& name) { slot_name_ = name; }
    std::string slot_name() const { return slot_name_; }

    // Content payload: chart series, colorbar stops, legend entries …
    // Must be a JSON object; drawn by draw() and persisted with the item.
    void set_slot_properties(domain::Json properties);
    const domain::Json& slot_properties() const { return properties_; }

    // Registry admission (idempotent; GUI-thread only because it touches
    // QgsApplication). Safe to call before every instantiate/migrate.
    static void ensure_registered();

protected:
    void draw(QgsLayoutItemRenderContext& context) override;
    bool writePropertiesToElement(QDomElement& element, QDomDocument& document,
                                  const QgsReadWriteContext& context) const override;
    bool readPropertiesFromElement(const QDomElement& element,
                                   const QDomDocument& document,
                                   const QgsReadWriteContext& context) override;

private:
    // `s` is painter pixels per mm for the current render context.
    void draw_stat_chart(QPainter& painter, QgsRenderContext& context, double s,
                         double w_mm, double h_mm);
    void draw_colorbar(QPainter& painter, QgsRenderContext& context, double s,
                       double w_mm, double h_mm);
    void draw_symbol_legend(QPainter& painter, QgsRenderContext& context, double s,
                            double w_mm, double h_mm);  // fault/lithology
    void draw_placeholder(QPainter& painter, double s, double w_mm, double h_mm);
    void draw_timescale(QPainter& painter, QgsRenderContext& context, double s,
                        double w_mm, double h_mm);
    void draw_profile(QPainter& painter, double s, double w_mm, double h_mm);

    Kind kind_ = Kind::Placeholder;
    std::string slot_name_;
    domain::Json properties_ = domain::Json::object();
};

}  // namespace pwb::qgis
