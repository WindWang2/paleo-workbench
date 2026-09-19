// map_edit_items.py Qt shell — the QGraphicsItem classes over the Qt-free
// FeatureModel state (pwb/ui_data_core/map_edit_items.hpp). Items own their
// model; the Python FeatureItemMixin surface (feature_id/kind/
// topology_status/to_record/get_property/set_property) forwards to it.
// Painting constants are the tokens.py light-palette literals, matching the
// Python module-level QColors (static, not theme-bound — parity).
#pragma once

#include "pwb/ui_data_core/map_edit_items.hpp"

#include <QGraphicsEllipseItem>
#include <QGraphicsPathItem>
#include <QGraphicsRectItem>
#include <QGraphicsSimpleTextItem>

namespace pwb::ui_data_qt {

// Shared identity surface — the FeatureItemMixin API for scene code that
// handles heterogeneous items (hit dispatch, selection, translate).
class FeatureItemApi {
public:
    virtual ~FeatureItemApi() = default;
    virtual const pwb::ui_data_core::FeatureItemBase& base() const = 0;
    virtual pwb::ui_data_core::FeatureItemBase& base() = 0;
    virtual domain::Json to_record() const = 0;
    virtual domain::Json get_property(std::string_view key) const = 0;
    virtual void set_property(std::string_view key,
                              const domain::Json& value) = 0;
    virtual void translate_by(double dx, double dy) = 0;
};

class VertexHandleItem : public QGraphicsRectItem {
public:
    VertexHandleItem(std::string feature_id, int vertex_index, double x,
                     double y,
                     double half = pwb::ui_data_core::kVertexHandleHalf,
                     QGraphicsItem* parent = nullptr, int part_index = 0,
                     int ring_index = 0);

    std::string feature_id;
    int vertex_index = 0;
    int part_index = 0;
    int ring_index = 0;
};

class FaciesPolygonItem : public QGraphicsPathItem, public FeatureItemApi {
public:
    FaciesPolygonItem(std::string feature_id, const domain::Json& coordinates,
                      std::string name = "",
                      const domain::Json& style = domain::Json(nullptr),
                      const domain::Json& extras = domain::Json(nullptr),
                      std::string geometry_type = "Polygon",
                      const domain::Json* geometry_coordinates = nullptr,
                      QGraphicsItem* parent = nullptr);

    const pwb::ui_data_core::FaciesPolygonModel& model() const {
        return model_;
    }
    pwb::ui_data_core::FaciesPolygonModel& model() { return model_; }
    const pwb::ui_data_core::FeatureItemBase& base() const override {
        return model_;
    }
    pwb::ui_data_core::FeatureItemBase& base() override { return model_; }

    pwb::ui_data_core::MapRing coordinates() const {
        return model_.coordinates();
    }
    bool has_complex_geometry() const {
        return model_.has_complex_geometry();
    }
    domain::Json geometry_coordinates() const {
        return model_.geometry_coordinates();
    }
    std::vector<pwb::ui_data_core::MapRing> all_rings() const {
        return model_.all_rings();
    }
    pwb::ui_data_core::MapRing ring_coordinates(int part_index,
                                                int ring_index) const {
        return model_.ring_coordinates(part_index, ring_index);
    }
    void set_ring_coordinates(int part_index, int ring_index,
                              const domain::Json& coordinates);
    void set_coordinates(const domain::Json& coordinates);

    void translate_by(double dx, double dy) override;
    domain::Json to_record() const override { return model_.to_record(); }
    domain::Json get_property(std::string_view key) const override {
        return model_.get_property(key);
    }
    void set_property(std::string_view key,
                      const domain::Json& value) override {
        model_.set_property(key, value);
    }

private:
    void refresh_path();
    pwb::ui_data_core::FaciesPolygonModel model_;
};

class WellPointItem : public QGraphicsEllipseItem, public FeatureItemApi {
public:
    WellPointItem(std::string feature_id, double x, double y,
                  std::string name = "",
                  double radius = pwb::ui_data_core::kWellRadius,
                  QGraphicsItem* parent = nullptr);

    const pwb::ui_data_core::WellPointModel& model() const { return model_; }
    pwb::ui_data_core::WellPointModel& model() { return model_; }
    const pwb::ui_data_core::FeatureItemBase& base() const override {
        return model_;
    }
    pwb::ui_data_core::FeatureItemBase& base() override { return model_; }

    void translate_by(double dx, double dy) override;
    domain::Json to_record() const override { return model_.to_record(); }
    domain::Json get_property(std::string_view key) const override {
        return model_.get_property(key);
    }
    void set_property(std::string_view key,
                      const domain::Json& value) override {
        model_.set_property(key, value);
    }

private:
    pwb::ui_data_core::WellPointModel model_;
};

class LineItem : public QGraphicsPathItem, public FeatureItemApi {
public:
    LineItem(std::string feature_id,
             const pwb::ui_data_core::MapRing& coordinates,
             std::string name = "", QGraphicsItem* parent = nullptr);

    const pwb::ui_data_core::LineModel& model() const { return model_; }
    pwb::ui_data_core::LineModel& model() { return model_; }
    const pwb::ui_data_core::FeatureItemBase& base() const override {
        return model_;
    }
    pwb::ui_data_core::FeatureItemBase& base() override { return model_; }

    pwb::ui_data_core::MapRing coordinates() const {
        return model_.coordinates();
    }
    void set_coordinates(const domain::Json& coordinates);

    void translate_by(double dx, double dy) override;
    domain::Json to_record() const override { return model_.to_record(); }
    domain::Json get_property(std::string_view key) const override {
        return model_.get_property(key);
    }
    void set_property(std::string_view key,
                      const domain::Json& value) override {
        model_.set_property(key, value);
    }

private:
    void rebuild_path();
    pwb::ui_data_core::LineModel model_;
};

class LabelItem : public QGraphicsSimpleTextItem, public FeatureItemApi {
public:
    LabelItem(std::string feature_id, double x, double y,
              std::string text = "", std::string name = "",
              QGraphicsItem* parent = nullptr);

    const pwb::ui_data_core::LabelModel& model() const { return model_; }
    pwb::ui_data_core::LabelModel& model() { return model_; }
    const pwb::ui_data_core::FeatureItemBase& base() const override {
        return model_;
    }
    pwb::ui_data_core::FeatureItemBase& base() override { return model_; }

    void translate_by(double dx, double dy) override;
    domain::Json to_record() const override { return model_.to_record(); }
    domain::Json get_property(std::string_view key) const override {
        return model_.get_property(key);
    }
    void set_property(std::string_view key,
                      const domain::Json& value) override;

private:
    pwb::ui_data_core::LabelModel model_;
};

}  // namespace pwb::ui_data_qt
