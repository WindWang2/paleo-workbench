#include <pwb/ui/layer_properties.hpp>

#include <QDomDocument>
#include <QFile>

#include <qgsmapcanvas.h>
#include <qgsmaplayer.h>
#include <qgsrendererpropertiesdialog.h>
#include <qgsstyle.h>
#include <qgsvectorlayer.h>

namespace pwb::ui::layer_style {

bool open_renderer_properties(QgsVectorLayer* layer, QgsMapCanvas* canvas,
                              QWidget* parent) {
    if (layer == nullptr) return false;
    QgsRendererPropertiesDialog dialog(
        layer, QgsStyle::defaultStyle(), /*embedded*/ false, parent);
    if (canvas != nullptr) dialog.setMapCanvas(canvas);
    // QGIS applies the configured renderer to the layer on OK.
    return dialog.exec() == QDialog::Accepted;
}

QString sidecar_path(const QString& layer_uri) {
    return layer_uri + QStringLiteral(".qml");
}

bool save_style_sidecar(QgsMapLayer* layer, const QString& layer_uri) {
    if (layer == nullptr) return false;
    QDomDocument doc;
    QString error;
    layer->exportNamedStyle(doc, error);
    if (!error.isEmpty()) return false;
    QFile out(sidecar_path(layer_uri));
    if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) return false;
    out.write(doc.toString().toUtf8());
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
