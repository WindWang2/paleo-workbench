#include "gui_service.hpp"

#include <QApplication>
#include <QCoreApplication>
#include <QDialog>
#include <QFileInfo>
#include <QObject>
#include <QString>
#include <QTemporaryDir>
#include <QThread>

#include <stdexcept>

#include <qgsapplication.h>
#include <qgsfeature.h>
#include <qgsfillsymbol.h>
#include <qgsgui.h>
#include <qgsreadwritecontext.h>
#include <qgsrenderer.h>
#include <qgsstyle.h>
#include <qgssymbollayerutils.h>
#include <qgssymbol.h>
#include <qgsvectordataprovider.h>
#include <qgsvectorlayer.h>

#include <qgsrendererpropertiesdialog.h>
#include <qgssymbolselectordialog.h>
#include <qgsstylemanagerdialog.h>

#include "qgis_render_bridge.hpp"
#include "style_codec.hpp"

namespace pwb::qgis_render {
namespace {

void assert_gui_thread() {
    QCoreApplication* application = QCoreApplication::instance();
    if (application == nullptr) {
        throw std::runtime_error("QGIS symbology dialogs require a running Qt application");
    }
    if (qobject_cast<QApplication*>(application) == nullptr) {
        throw std::runtime_error("QGIS symbology dialogs require QApplication (GUI host)");
    }
    if (application->thread() != QThread::currentThread()) {
        throw std::runtime_error("QGIS symbology dialogs must run on the Qt GUI thread");
    }
}

/// One dialog session: temporary mirror layer + managed style database.
class DialogSession {
  public:
    explicit DialogSession(const GuiDialogRequest& request) : request_(request) {
        layer_ = make_dialog_layer(request.geometry_type, request.crs, fields());
        if (!request.style_db_path.empty()) {
            style_ = std::make_unique<QgsStyle>();
            style_->setFileName(QString::fromStdString(request.style_db_path));
            if (!QFileInfo::exists(style_->fileName())) {
                style_->createDatabase(style_->fileName());
            }
            if (!style_->load(style_->fileName())) {
                throw std::runtime_error("QGIS style database could not be loaded: "
                                         + request.style_db_path);
            }
        } else {
            // Throwaway in-memory library keeps the dialog fully functional
            // without touching any on-disk state.
            if (!temp_dir_.isValid()) {
                throw std::runtime_error("QGIS symbology session could not create a temporary style database");
            }
            const QString path = temp_dir_.filePath(QStringLiteral("paleo-style.sqlite"));
            style_ = std::make_unique<QgsStyle>();
            if (!style_->createDatabase(path)) {
                throw std::runtime_error("QGIS temporary style database could not be created");
            }
            if (!style_->load(path)) {
                throw std::runtime_error("QGIS temporary style database could not be loaded");
            }
        }
        // Touch the lazy GUI singleton so every registry the symbology widgets
        // rely on exists before any dialog is constructed.
        (void)QgsGui::instance();
    }

    QgsVectorLayer* layer() { return layer_.get(); }
    QgsStyle* style() { return style_.get(); }

    /// Install the current renderer payload onto the mirror layer.
    void install_current_renderer() {
        std::unique_ptr<QgsFeatureRenderer> renderer;
        if (!request_.renderer_xml.empty()) {
            renderer = renderer_from_xml(request_.renderer_xml);
            if (!renderer) {
                throw std::runtime_error("current renderer payload is not valid QGIS renderer XML");
            }
        } else {
            VectorLayerSpec spec;
            spec.fill = request_.fill;
            spec.stroke = request_.stroke;
            spec.stroke_width = request_.stroke_width;
            spec.marker_size = request_.marker_size;
            renderer = build_renderer_from_spec(layer_->geometryType(), spec);
            if (!renderer) {
                throw std::runtime_error("a default renderer could not be built for this geometry type");
            }
        }
        layer_->setRenderer(renderer.release());
    }

  private:
    std::vector<std::pair<std::string, std::string>> fields() const {
        std::vector<std::pair<std::string, std::string>> result;
        result.reserve(request_.field_names.size());
        for (const std::string& name : request_.field_names) {
            result.emplace_back(name, std::string());
        }
        return result;
    }

    GuiDialogRequest request_;
    QTemporaryDir temp_dir_;
    std::unique_ptr<QgsVectorLayer> layer_;
    std::unique_ptr<QgsStyle> style_;
};

GuiDialogResult collect_result(QgsVectorLayer& layer, bool ok) {
    GuiDialogResult result;
    result.ok = ok;
    if (ok && layer.renderer() != nullptr) {
        result.renderer_xml = renderer_to_xml(*layer.renderer());
        result.opacity = layer.opacity();
    }
    return result;
}

}  // namespace

GuiDialogResult run_renderer_properties_dialog(const GuiDialogRequest& request) {
    assert_gui_thread();
    DialogSession session(request);
    session.install_current_renderer();

    QgsRendererPropertiesDialog dialog(session.layer(), session.style(), false, nullptr);
    if (!request.title.empty()) {
        dialog.setWindowTitle(QString::fromStdString(request.title));
    }
    dialog.exec();
    return collect_result(*session.layer(), dialog.result() == QDialog::Accepted);
}

GuiDialogResult run_symbol_selector_dialog(const GuiDialogRequest& request,
                                            const int symbol_index) {
    assert_gui_thread();
    DialogSession session(request);
    session.install_current_renderer();

    QgsVectorLayer& mirror = *session.layer();
    const int index = symbol_index;
    if (mirror.renderer() == nullptr || index < 0) {
        throw std::invalid_argument("symbol index is outside the current renderer");
    }
    // The selector mutates the symbol in place; operate on a clone of the whole
    // renderer so cancelling can never corrupt the caller's payload.
    std::unique_ptr<QgsFeatureRenderer> working(mirror.renderer()->clone());
    QgsRenderContext context;
    const QgsSymbolList working_symbols = working->symbols(context);
    if (index >= working_symbols.size()) {
        throw std::invalid_argument("symbol index is outside the current renderer");
    }
    QgsSymbol* symbol = working_symbols[index];
    if (symbol == nullptr) {
        throw std::invalid_argument("renderer symbol slot is empty");
    }

    QgsSymbolSelectorDialog dialog(symbol, session.style(), session.layer(), nullptr, false);
    if (!request.title.empty()) {
        dialog.setWindowTitle(QString::fromStdString(request.title));
    }
    dialog.exec();
    if (dialog.result() != QDialog::Accepted) {
        GuiDialogResult cancelled;
        cancelled.ok = false;
        return cancelled;
    }
    // Write the edited symbol back through the layer's renderer so the
    // serialized payload reflects the full symbol-layer tree.
    session.layer()->setRenderer(working.release());
    return collect_result(*session.layer(), true);
}

bool run_style_manager_dialog(const std::string& style_db_path) {
    assert_gui_thread();
    if (style_db_path.empty()) {
        throw std::invalid_argument("a managed style database path is required");
    }
    auto style = std::make_unique<QgsStyle>();
    style->setFileName(QString::fromStdString(style_db_path));
    if (!QFileInfo::exists(style->fileName())) {
        if (!style->createDatabase(style->fileName())) {
            throw std::runtime_error("QGIS style database could not be created: " + style_db_path);
        }
    }
    if (!style->load(style->fileName())) {
        throw std::runtime_error("QGIS style database could not be loaded: " + style_db_path);
    }
    (void)QgsGui::instance();
    QgsStyleManagerDialog dialog(style.get(), nullptr);
    dialog.exec();
    return dialog.result() == QDialog::Accepted;
}

}  // namespace pwb::qgis_render
