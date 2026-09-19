#include "pwb/ui_data_qt/map_edit_items.hpp"

#include <QBrush>
#include <QColor>
#include <QFont>
#include <QPen>

namespace pwb::ui_data_qt {
namespace {

// tokens.py literals — the Python module constructs these QColors once at
// import from the static (light) token constants, so they are not
// theme-bound. Same values here.
QBrush facies_fill() {
    QColor c(QStringLiteral("#0b5563"));  // PRIMARY, alpha 70
    c.setAlpha(70);
    return QBrush(c);
}
QPen facies_pen() {
    return QPen(QColor(QStringLiteral("#0b5563")), 0);  // cosmetic
}
QBrush teal_fill() {
    return QBrush(QColor(QStringLiteral("#0f766e")));  // TEAL
}
QPen dark_pen() {
    return QPen(QColor(QStringLiteral("#101820")), 0);  // TEXT_DARK
}
QPen line_pen() {
    QPen p(QColor(QStringLiteral("#a65313")), 0);  // ACCENT
    p.setCosmetic(true);
    p.setWidth(2);
    return p;
}
QColor label_color() { return QColor(QStringLiteral("#101820")); }

}  // namespace

VertexHandleItem::VertexHandleItem(std::string feature_id_, int vertex_index_,
                                   double x, double y, double half,
                                   QGraphicsItem* parent, int part_index_,
                                   int ring_index_)
    : QGraphicsRectItem(QRectF(-half, -half, 2 * half, 2 * half), parent),
      feature_id(std::move(feature_id_)),
      vertex_index(vertex_index_),
      part_index(part_index_),
      ring_index(ring_index_) {
    setPos(x, y);
    setBrush(teal_fill());
    setPen(dark_pen());
    setZValue(100);
    setFlag(GraphicsItemFlag::ItemIsSelectable, true);
    setFlag(GraphicsItemFlag::ItemIsMovable, false);
    setAcceptedMouseButtons(Qt::MouseButton::LeftButton);
}

FaciesPolygonItem::FaciesPolygonItem(
    std::string feature_id, const domain::Json& coordinates,
    std::string name, const domain::Json& style, const domain::Json& extras,
    std::string geometry_type, const domain::Json* geometry_coordinates,
    QGraphicsItem* parent)
    : QGraphicsPathItem(parent),
      model_(std::move(feature_id), coordinates, std::move(name), style,
             extras, std::move(geometry_type), geometry_coordinates) {
    refresh_path();
    setBrush(facies_fill());
    setPen(facies_pen());
    setZValue(10);
    setFlag(GraphicsItemFlag::ItemIsSelectable, true);
}

void FaciesPolygonItem::refresh_path() {
    QPainterPath path;
    path.setFillRule(Qt::FillRule::OddEvenFill);
    for (const auto& polygon : model_.polygons) {
        for (const auto& ring : polygon) {
            if (ring.size() < 3) continue;
            path.moveTo(ring[0][0], ring[0][1]);
            for (std::size_t i = 1; i < ring.size(); ++i)
                path.lineTo(ring[i][0], ring[i][1]);
            path.closeSubpath();
        }
    }
    setPath(path);
}

void FaciesPolygonItem::set_ring_coordinates(
    int part_index, int ring_index, const domain::Json& coordinates) {
    model_.set_ring_coordinates(part_index, ring_index, coordinates);
    refresh_path();
    setPos(0.0, 0.0);
}

void FaciesPolygonItem::set_coordinates(const domain::Json& coordinates) {
    model_.set_coordinates(coordinates);
    refresh_path();
    setPos(0.0, 0.0);
}

void FaciesPolygonItem::translate_by(double dx, double dy) {
    model_.translate_by(dx, dy);
    refresh_path();
    setPos(0.0, 0.0);
}

WellPointItem::WellPointItem(std::string feature_id, double x, double y,
                             std::string name, double radius,
                             QGraphicsItem* parent)
    : QGraphicsEllipseItem(QRectF(x - radius, y - radius, 2 * radius,
                                  2 * radius),
                           parent),
      model_(std::move(feature_id), x, y, std::move(name), radius) {
    setBrush(teal_fill());
    setPen(dark_pen());
    setZValue(20);
    setFlag(GraphicsItemFlag::ItemIsSelectable, true);
}

void WellPointItem::translate_by(double dx, double dy) {
    model_.translate_by(dx, dy);
    const double r = model_.radius;
    setRect(QRectF(model_.x - r, model_.y - r, 2 * r, 2 * r));
    setPos(0.0, 0.0);
}

LineItem::LineItem(std::string feature_id,
                   const pwb::ui_data_core::MapRing& coordinates,
                   std::string name, QGraphicsItem* parent)
    : QGraphicsPathItem(parent),
      model_(std::move(feature_id), coordinates, std::move(name)) {
    setPen(line_pen());
    setBrush(QBrush(Qt::BrushStyle::NoBrush));
    setZValue(15);
    setFlag(GraphicsItemFlag::ItemIsSelectable, true);
    rebuild_path();
}

void LineItem::rebuild_path() {
    QPainterPath path;
    const auto& pts = model_.points;
    if (!pts.empty()) {
        path.moveTo(pts[0][0], pts[0][1]);
        for (std::size_t i = 1; i < pts.size(); ++i)
            path.lineTo(pts[i][0], pts[i][1]);
    }
    setPath(path);
}

void LineItem::set_coordinates(const domain::Json& coordinates) {
    model_.set_coordinates(coordinates);
    rebuild_path();
    setPos(0.0, 0.0);
}

void LineItem::translate_by(double dx, double dy) {
    model_.translate_by(dx, dy);
    rebuild_path();
    setPos(0.0, 0.0);
}

LabelItem::LabelItem(std::string feature_id, double x, double y,
                     std::string text, std::string name,
                     QGraphicsItem* parent)
    : QGraphicsSimpleTextItem(
          QString::fromStdString(!text.empty() ? text : name), parent),
      model_(std::move(feature_id), x, y, std::move(text), std::move(name)) {
    setBrush(QBrush(label_color()));
    QFont font;
    font.setPointSize(10);
    setFont(font);
    setZValue(30);
    setFlag(GraphicsItemFlag::ItemIsSelectable, true);
    setPos(x, y);
}

void LabelItem::translate_by(double dx, double dy) {
    model_.translate_by(dx, dy);
    setPos(model_.x, model_.y);
}

void LabelItem::set_property(std::string_view key, const domain::Json& value) {
    model_.set_property(key, value);
    if (key == "text") setText(QString::fromStdString(model_.text));
}

}  // namespace pwb::ui_data_qt
