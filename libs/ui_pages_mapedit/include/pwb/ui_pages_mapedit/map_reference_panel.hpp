// UI-08 — paleo_workbench/ui/pages/map_reference_panel.py port: right-side
// controls for CRS-normalized map reference layers (visibility checks,
// per-layer opacity slider, keyed reconcile).
//
// MapReferenceLayer mirrors the pydantic model's fields (the panel reads
// id/name/visible/opacity/status/external/error_message).
#pragma once

#include <QFrame>
#include <QVariantMap>

#include <QString>
#include <map>
#include <vector>

class QLabel;
class QListWidget;
class QListWidgetItem;
class QSlider;

namespace pwb::ui_pages_mapedit {

// paleo_workbench.project.models.MapReferenceLayer — all declared fields
// (the panel only reads a subset; the struct keeps the full contract).
struct MapReferenceLayer {
    QString id;
    QString name;
    QString source_path;
    QString source_kind;   // "raster" | "vector"
    QString source_crs;
    QString project_crs;
    QString transform_wkt;
    bool visible = true;
    double opacity = 0.65;
    int order = 0;
    bool participates_in_snap = false;
    QString cache_key;
    bool external = false;
    QString status = QStringLiteral("ready");  // ready|offline|failed
    QString error_message;
};

class MapReferencePanel : public QFrame {
    Q_OBJECT
public:
    explicit MapReferencePanel(QWidget* parent = nullptr);

    void set_view_state(const QVariantMap& state) { view_state_ = state; }
    QVariantMap view_state() const { return view_state_; }

    void set_layers(const std::vector<MapReferenceLayer>& layers);

    QListWidget* layer_list() const { return layer_list_; }
    QSlider* opacity_slider() const { return opacity_slider_; }
    QLabel* status_label() const { return status_label_; }

signals:
    void reference_visibility_changed(const QString& layer_id, bool visible);
    void reference_opacity_changed(const QString& layer_id, double opacity);
    void overlay_requested(const QString& layer_id);

private:
    void update_layer_item(QListWidgetItem* item, const QString& key);
    static QString layer_label(const MapReferenceLayer& layer);
    static QString status_summary(
        const std::vector<MapReferenceLayer>& layers);
    void on_item_changed(QListWidgetItem* item);
    void on_opacity_changed(int value);

    QLabel* status_label_ = nullptr;
    QListWidget* layer_list_ = nullptr;
    QSlider* opacity_slider_ = nullptr;
    std::map<QString, MapReferenceLayer> layers_;
    bool suppress_ = false;
    QVariantMap view_state_ = {
        {QStringLiteral("center"), QVariantList{0.0, 0.0}},
        {QStringLiteral("scale"), 1.0},
    };
};

}  // namespace pwb::ui_pages_mapedit
