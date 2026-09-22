#include <pwb/ui/layer_properties.hpp>

#include <QDomDocument>
#include <QFile>

#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsmessagebar.h>
#include <qgsrasterlayer.h>
#include <qgsrasterlayerproperties.h>
#include <qgsvectorlayer.h>
#include <qgsvectorlayerproperties.h>

namespace pwb::ui::layer_style {

bool open_layer_properties(QgsMapLayer* layer, QgsMapCanvas* canvas,
                           QWidget* parent) {
    if (layer == nullptr) return false;
    if (auto* vector_layer = qobject_cast<QgsVectorLayer*>(layer)) {
        QgsMessageBar message_bar;
        QgsVectorLayerProperties dialog(
            canvas, &message_bar, vector_layer, parent);
        return dialog.exec() == QDialog::Accepted;
    }
    if (auto* raster_layer = qobject_cast<QgsRasterLayer*>(layer)) {
        QgsRasterLayerProperties dialog(raster_layer, canvas, parent);
        return dialog.exec() == QDialog::Accepted;
    }
    return false;
}

bool open_renderer_properties(QgsVectorLayer* layer, QgsMapCanvas* canvas,
                              QWidget* parent) {
    return open_layer_properties(layer, canvas, parent);
}

QString sidecar_path(const QString& layer_uri) {
    // OGR URIs carry options ("file.gpkg|layername=x") — the sidecar keys
    // off the data FILE only, or the name would be unusable on disk.
    QString file = layer_uri;
    const int pipe = file.indexOf(QLatin1Char('|'));
    if (pipe >= 0) file.truncate(pipe);
    return file + QStringLiteral(".qml");
}

bool save_style_sidecar(QgsMapLayer* layer, const QString& layer_uri) {
    if (layer == nullptr) return false;
    QDomDocument doc;
    QString error;
    layer->exportNamedStyle(doc, error);
    if (!error.isEmpty()) return false;
    QFile out(sidecar_path(layer_uri));
    if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) return false;
    const QByteArray bytes = doc.toString().toUtf8();
    if (out.write(bytes) != bytes.size() || !out.flush()) {
        out.close();
        return false;   // short write (disk full/RO) is NOT a saved style
    }
    out.close();
    return true;
}

bool apply_style_sidecar(QgsMapLayer* layer, const QString& layer_uri) {
    if (layer == nullptr) return false;
    const QString qml = sidecar_path(layer_uri);
    if (!QFile::exists(qml)) return false;
    bool loaded = false;
    // resultFlag is the verdict; the status string is human detail only
    // (localized — never parsed).
    layer->loadNamedStyle(qml, loaded);
    if (!loaded) return false;
    layer->triggerRepaint();
    return true;
}

}  // namespace pwb::ui::layer_style
