// qgis_data_workspace_install — see the header for the contract. The dock
// owns nothing but the view: the browser model lives for the window's
// lifetime as a child of the dock, layer admission goes through the
// provider registry (QgsLayerItem names the provider + URI; layer_factory
// validates and attaches the domain join key), and domain facts reuse the
// same module-only grant the shell's own layer-open path uses.

#include "qgis_data_workspace_install.hpp"

#include <QDockWidget>
#include <QStatusBar>
#include <QString>
#include <QTreeView>

#include <qgsbrowserguimodel.h>
#include <qgsbrowsertreeview.h>
#include <qgsdataitem.h>
#include <qgslayeritem.h>
#include <qgsmaplayer.h>
#include <qgsvectorlayer.h>

#include <pwb/qgis/layer_factory.hpp>

#include "app_context.hpp"
#include "main_window.hpp"

namespace pwb::app::qgis_data_workspace {

namespace {

constexpr const char* kDockName = "qgis-data-browser-dock";

void admit_browser_layer(::pwb::app::MainWindow& window, QgsLayerItem* item) {
    if (item == nullptr) return;
    pwb::qgis::layer_factory::ProposedSublayer sublayer;
    sublayer.uri = item->uri().toStdString();
    sublayer.provider_key = item->providerKey().toStdString();
    sublayer.name = item->name().toStdString();
    sublayer.type = item->mapLayerType();
    sublayer.kind = sublayer.type == Qgis::LayerType::Raster
                        ? std::string("raster")
                        : std::string("vector");

    pwb::qgis::LayerBinding binding{item->name().toStdString(), "", "",
                                    sublayer.kind};
    std::string error;
    QgsMapLayer* layer = pwb::qgis::layer_factory::add_sublayer(
        window.context().session().map(), sublayer, binding, &error);
    if (layer == nullptr) {
        // Provider said no: surface it, never fabricate the layer.
        window.statusBar()->showMessage(
            MainWindow::tr("QGIS 浏览器：%1").arg(QString::fromStdString(
                error)),
            8000);
        return;
    }
    if (auto* vector = qobject_cast<QgsVectorLayer*>(layer)) {
        pwb::application::DomainLayerFacts facts;
        facts.layer_id = item->name().toStdString();
        facts.role = "facies_boundary";
        facts.role_label = item->name().toStdString();
        facts.artifact_maturity = "draft";
        // Module-only grant: the shell's own opened layers carry write
        // here; a store binding becomes the authority at commit time.
        facts.write_granted = true;
        window.noteDomainLayerFacts(facts);
        if (!window.context().session().active_layer().has_value()) {
            window.context().session().set_active_layer(facts);
        }
    }
}

}  // namespace

void install_data_browser(::pwb::app::MainWindow& window) {
    if (window.findChild<QDockWidget*>(kDockName) != nullptr) return;

    auto* dock = new QDockWidget(MainWindow::tr("QGIS 数据浏览器"), &window);
    dock->setObjectName(QString::fromLatin1(kDockName));
    // The GUI browser model (provider items + gui providers' context);
    // browser models are NOT auto-populated — initialize() is required
    // (deferred init is QGIS's own contract).
    auto* model = new QgsBrowserGuiModel(dock);
    model->initialize();
    auto* view = new QgsBrowserTreeView(dock);
    view->setModel(model);
    view->setHeaderHidden(true);
    dock->setWidget(view);
    window.addDockWidget(Qt::LeftDockWidgetArea, dock);
    // Keep the left area usable: tabify behind the layer tree dock when
    // it exists (no layout fight with the shell's own docks).
    if (QDockWidget* layer_dock =
            window.findChild<QDockWidget*>(QStringLiteral("layer-tree-dock"))) {
        window.tabifyDockWidget(layer_dock, dock);
        dock->hide();
    }

    MainWindow::connect(
        view, &QTreeView::doubleClicked, &window,
        [&window, model](const QModelIndex& index) {
            QgsDataItem* item = model->dataItem(index);
            if (auto* layer_item = qobject_cast<QgsLayerItem*>(item)) {
                admit_browser_layer(window, layer_item);
            }
        });
}

}  // namespace pwb::app::qgis_data_workspace
