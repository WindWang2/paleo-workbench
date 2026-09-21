// layout_spec_exec — implementation (moved verbatim from
// QgisMapStack::layoutExport, CONV-29 D-02, plus two documented
// extensions: spec["force_vector"] forces vector PDF/SVG output and the
// report carries PNG dimensions).

#include "layout_spec_exec.hpp"

#include <functional>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <system_error>
#include <filesystem>

#include <QColor>
#include <QCoreApplication>
#include <QFile>
#include <QFont>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QList>
#include <QSet>
#include <QString>
#include <QVariantMap>
#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgslayout.h>
#include <qgslayoutexporter.h>
#include <qgslayoutitemlabel.h>
#include <qgslayoutitemlegend.h>
#include <qgslayoutitemmap.h>
#include <qgslayoutitemmapgrid.h>
#include <qgslayoutitempage.h>
#include <qgslayoutitempicture.h>
#include <qgslayoutitemshape.h>
#include <qgslayoutitemscalebar.h>
#include <qgslayoutpagecollection.h>
#include <qgsmaplayer.h>
#include <qgsprintlayout.h>
#include <qgsproject.h>
#include <qgslayertree.h>
#include <qgstextformat.h>
#include <qgsfillsymbol.h>

namespace pwb::layout_spec_exec {

namespace {

// Vendored QGIS prefix (baked at build time; the macro → std::string hop
// mirrors the bridge's own pattern so both targets can define it).
#ifdef PALEO_QGIS_PREFIX_PATH
const std::string kQgisPrefix(PALEO_QGIS_PREFIX_PATH);
#else
const std::string kQgisPrefix;
#endif

QgsLayoutPoint mmPoint(double x, double y) {
  return QgsLayoutPoint(x, y, Qgis::LayoutUnit::Millimeters);
}

QgsLayoutSize mmSize(double w, double h) {
  return QgsLayoutSize(w, h, Qgis::LayoutUnit::Millimeters);
}

QColor jsonColor(const QJsonObject& obj, const char* key, const QColor& fallback) {
  const QString raw = obj.value(QLatin1String(key)).toString();
  if (raw.isEmpty()) return fallback;
  return QColor(raw);
}

std::unique_ptr<QgsFillSymbol> fillSymbol(const QString& color, bool outline) {
  QVariantMap props;
  props.insert(QStringLiteral("color"), color);
  if (outline) {
    props.insert(QStringLiteral("outline_color"), QStringLiteral("#202020"));
    props.insert(QStringLiteral("outline_width"), QStringLiteral("0.3"));
  } else {
    props.insert(QStringLiteral("outline_style"), QStringLiteral("no"));
  }
  // QGIS 4 returns an owning pointer; the layout item takes ownership on set.
  return QgsFillSymbol::createSimple(props);
}

QgsMapLayer* resolveLayer(const ExecContext& context, const std::string& key) {
  if (context.resolve_layer) {
    if (QgsMapLayer* layer = context.resolve_layer(key)) return layer;
  }
  if (context.project == nullptr) return nullptr;
  if (QgsMapLayer* by_id = context.project->mapLayer(
          QString::fromStdString(key))) {
    return by_id;
  }
  const QList<QgsMapLayer*> by_name =
      context.project->mapLayersByName(QString::fromStdString(key));
  return by_name.isEmpty() ? nullptr : by_name.first();
}

}  // namespace

std::string execute_layout_spec(const ExecContext& context,
                                const std::string& spec_json,
                                const std::string& output_path,
                                const std::string& format, double dpi) {
  if (!QCoreApplication::instance()) {
    throw std::runtime_error(
        "layout export requires an initialised QGIS application (bridge "
        "initialize() must run first)");
  }
  const QJsonDocument doc = QJsonDocument::fromJson(
      QByteArray::fromStdString(spec_json));
  if (!doc.isObject()) {
    throw std::invalid_argument("layout spec must be a JSON object");
  }
  const QJsonObject spec = doc.object();
  const QJsonObject page = spec.value(QStringLiteral("page")).toObject();
  const double page_w = page.value(QStringLiteral("width_mm")).toDouble(297.0);
  const double page_h = page.value(QStringLiteral("height_mm")).toDouble(210.0);
  if (page_w <= 0.0 || page_h <= 0.0) {
    throw std::invalid_argument("page width_mm/height_mm must be positive");
  }

  QgsPrintLayout layout(context.project);
  layout.initializeDefaults();
  QgsLayoutItemPage* page_item = layout.pageCollection()->page(0);
  page_item->setPageSize(mmSize(page_w, page_h));
  const QString background =
      page.value(QStringLiteral("background")).toString();
  if (!background.isEmpty()) {
    page_item->setPageStyleSymbol(
        fillSymbol(background, /*outline=*/false).release());
  }

  std::map<std::string, QgsLayoutItemMap*> maps_by_key;
  int item_count = 0;
  const QJsonArray items = spec.value(QStringLiteral("items")).toArray();
  for (const QJsonValue& value : items) {
    if (!value.isObject()) continue;
    const QJsonObject item = value.toObject();
    const QString type = item.value(QStringLiteral("type")).toString();
    const double x = item.value(QStringLiteral("x")).toDouble();
    const double y = item.value(QStringLiteral("y")).toDouble();
    const double w = item.value(QStringLiteral("w")).toDouble();
    const double h = item.value(QStringLiteral("h")).toDouble();

    if (type == QLatin1String("map")) {
      QgsLayoutItemMap* map = new QgsLayoutItemMap(&layout);
      map->attemptMove(mmPoint(x, y));
      map->attemptResize(mmSize(w, h));
      const QString crs_id = item.value(QStringLiteral("crs")).toString();
      if (!crs_id.isEmpty()) {
        map->setCrs(QgsCoordinateReferenceSystem(crs_id));
      }
      const QJsonArray extent = item.value(QStringLiteral("extent")).toArray();
      if (extent.size() == 4) {
        map->setExtent(QgsRectangle(extent.at(0).toDouble(),
                                    extent.at(1).toDouble(),
                                    extent.at(2).toDouble(),
                                    extent.at(3).toDouble()));
      }
      // Layer order: the host's full-tree top-first order is the same
      // sequence the screen canvas draws. QgsMapSettings::setLayers stores
      // index 0 = TOP ("The layers are stored in the reverse order of how
      // they are rendered"), so the top-first list is passed through
      // as-is — no reversal (#1445; the previous reverse inverted every
      // export's stacking relative to the screen).
      QList<QgsMapLayer*> ordered;
      std::vector<std::string> order;
      if (context.order_top_first) {
        order = context.order_top_first();
      } else if (context.project != nullptr) {
        const QList<QgsMapLayer*> tree_order =
            context.project->layerTreeRoot()->layerOrder();
        for (QgsMapLayer* layer : tree_order) {
          if (layer != nullptr) order.push_back(layer->id().toStdString());
        }
      }
      for (const std::string& id : order) {
        if (QgsMapLayer* layer = resolveLayer(context, id)) {
          ordered.append(layer);
        }
      }
      if (!ordered.isEmpty()) {
        map->setLayers(ordered);
      }
      map->setFrameEnabled(item.value(QStringLiteral("frame")).toBool(true));
      const QJsonObject grid = item.value(QStringLiteral("grid")).toObject();
      if (grid.value(QStringLiteral("enabled")).toBool(false)) {
        QgsLayoutItemMapGrid* map_grid = map->grid();  // first grid (auto-created)
        map_grid->setEnabled(true);
        map_grid->setIntervalX(
            grid.value(QStringLiteral("interval_x")).toDouble());
        map_grid->setIntervalY(
            grid.value(QStringLiteral("interval_y")).toDouble());
        map_grid->setAnnotationEnabled(
            grid.value(QStringLiteral("annotation")).toBool(true));
        if (!crs_id.isEmpty()) {
          map_grid->setCrs(QgsCoordinateReferenceSystem(crs_id));
        }
      }
      layout.addLayoutItem(map);
      const std::string key =
          item.value(QStringLiteral("key")).toString().toStdString();
      maps_by_key[key.empty() ? std::string("map") : key] = map;
      ++item_count;
      continue;
    }

    QgsLayoutItemMap* linked_map = nullptr;
    const std::string map_key =
        item.value(QStringLiteral("map_item")).toString().toStdString();
    if (!map_key.empty() || type == QLatin1String("legend") ||
        type == QLatin1String("scalebar") ||
        type == QLatin1String("north_arrow")) {
      const auto found = maps_by_key.find(
          map_key.empty() ? std::string("map") : map_key);
      if (found == maps_by_key.end()) {
        throw std::invalid_argument(
            "item references unknown map key: " + map_key);
      }
      linked_map = found->second;
    }

    if (type == QLatin1String("legend")) {
      QgsLayoutItemLegend* legend = new QgsLayoutItemLegend(&layout);
      legend->setTitle(item.value(QStringLiteral("title"))
                           .toString(QStringLiteral("图例")));
      if (linked_map) legend->setLinkedMap(linked_map);
      legend->setResizeToContents(
          item.value(QStringLiteral("resize_to_contents")).toBool(true));
      legend->attemptMove(mmPoint(x, y));
      legend->setBackgroundEnabled(
          item.value(QStringLiteral("background")).toBool(true));
      // V8 M8: legend filter（V7 08 §1 的显式 follow-up）。filter_layers 是
      // include 表（doc_id 或 QGIS layer id/name）。经 setSyncMode(Manual)
      // 克隆工程树，在手动树上剪枝不动工程本树。空/缺省 = 不过滤。
      const QJsonArray filter =
          item.value(QStringLiteral("filter_layers")).toArray();
      if (linked_map && !filter.isEmpty()) {
        QSet<QString> keep_ids;
        for (const QJsonValue& v : filter) {
          const QString key = v.toString();
          if (key.isEmpty()) continue;
          if (QgsMapLayer* layer = resolveLayer(context, key.toStdString())) {
            keep_ids.insert(layer->id());
          }
        }
        if (!keep_ids.isEmpty()) {
          legend->setSyncMode(Qgis::LegendSyncMode::Manual);
          // 剪掉不在 include 表里的层与因此变空的组（removeChildNode 连节点
          // 一起销毁——手动树归 legend 所有）；模型监听树信号自动重绘。
          const std::function<void(QgsLayerTreeGroup*)> prune =
              [&](QgsLayerTreeGroup* branch) {
                const QList<QgsLayerTreeNode*> children = branch->children();
                for (QgsLayerTreeNode* child : children) {
                  if (QgsLayerTree::isGroup(child)) {
                    prune(QgsLayerTree::toGroup(child));
                    if (child->children().isEmpty()) {
                      branch->removeChildNode(child);
                    }
                  } else if (QgsLayerTree::isLayer(child)) {
                    auto* layer_node = static_cast<QgsLayerTreeLayer*>(child);
                    if (layer_node->layer() == nullptr
                        || !keep_ids.contains(layer_node->layer()->id())) {
                      branch->removeChildNode(child);
                    }
                  }
                }
              };
          prune(legend->model()->rootGroup());
        }
      }
      layout.addLayoutItem(legend);
      ++item_count;
    } else if (type == QLatin1String("scalebar")) {
      QgsLayoutItemScaleBar* scalebar = new QgsLayoutItemScaleBar(&layout);
      if (!linked_map) {
        throw std::invalid_argument("scalebar requires a linked map item");
      }
      scalebar->setLinkedMap(linked_map);
      scalebar->applyDefaultSettings();
      scalebar->applyDefaultSize(Qgis::DistanceUnit::Meters);
      const int segments = item.value(QStringLiteral("segments")).toInt(0);
      if (segments > 0) scalebar->setNumberOfSegments(segments);
      const double units_per_segment =
          item.value(QStringLiteral("units_per_segment")).toDouble(0.0);
      if (units_per_segment > 0.0) {
        scalebar->setUnitsPerSegment(units_per_segment);
      }
      const QString unit_label =
          item.value(QStringLiteral("unit_label")).toString();
      if (!unit_label.isEmpty()) scalebar->setUnitLabel(unit_label);
      scalebar->attemptMove(mmPoint(x, y));
      layout.addLayoutItem(scalebar);
      ++item_count;
    } else if (type == QLatin1String("north_arrow") ||
               type == QLatin1String("picture")) {
      QString svg_path = item.value(QStringLiteral("svg_path"))
                             .toString(item.value(QStringLiteral("path"))
                                           .toString());
      if (svg_path.isEmpty() && type == QLatin1String("north_arrow")) {
        const QString data_dir = QgsApplication::pkgDataPath();
        QStringList candidates{
            data_dir + QStringLiteral("/svg/arrows/NorthArrow_02.svg"),
            data_dir + QStringLiteral("/data/svg/arrows/NorthArrow_02.svg"),
        };
        if (!kQgisPrefix.empty()) {
          const QString vendor_prefix =
              QString::fromStdString(kQgisPrefix);
          candidates << vendor_prefix +
                            QStringLiteral("/data/svg/arrows/NorthArrow_02.svg")
                     << vendor_prefix +
                            QStringLiteral("/svg/arrows/NorthArrow_02.svg");
        }
        for (const QString& candidate : candidates) {
          if (QFile::exists(candidate)) {
            svg_path = candidate;
            break;
          }
        }
        if (svg_path.isEmpty()) {
          throw std::runtime_error(
              "north arrow SVG not found in the vendored QGIS data dir; "
              "pass svg_path explicitly");
        }
      }
      QgsLayoutItemPicture* picture = new QgsLayoutItemPicture(&layout);
      picture->setPicturePath(svg_path);
      picture->attemptMove(mmPoint(x, y));
      picture->attemptResize(mmSize(w, h));
      layout.addLayoutItem(picture);
      ++item_count;
    } else if (type == QLatin1String("label")) {
      QgsLayoutItemLabel* label = new QgsLayoutItemLabel(&layout);
      label->setText(item.value(QStringLiteral("text")).toString());
      QgsTextFormat text_format;
      QFont font;
      font.setPointSizeF(
          item.value(QStringLiteral("font_size")).toDouble(10.0));
      font.setBold(item.value(QStringLiteral("bold")).toBool(false));
      text_format.setFont(font);
      text_format.setColor(jsonColor(item, "color", QColor(Qt::black)));
      label->setTextFormat(text_format);
      const QString halign =
          item.value(QStringLiteral("halign")).toString();
      if (halign == QLatin1String("center"))
        label->setHAlign(Qt::AlignHCenter);
      else if (halign == QLatin1String("right"))
        label->setHAlign(Qt::AlignRight);
      label->attemptMove(mmPoint(x, y));
      label->attemptResize(mmSize(w, h));
      layout.addLayoutItem(label);
      ++item_count;
    } else if (type == QLatin1String("shape")) {
      QgsLayoutItemShape* shape = new QgsLayoutItemShape(&layout);
      shape->setShapeType(QgsLayoutItemShape::Rectangle);
      const QString fill = item.value(QStringLiteral("fill")).toString();
      // Frame via symbology: outline when framed, no outline otherwise.
      shape->setSymbol(
          fillSymbol(
              fill.isEmpty() ? QStringLiteral("#00000000") : fill,
              item.value(QStringLiteral("frame")).toBool(true))
              .release());
      shape->attemptMove(mmPoint(x, y));
      shape->attemptResize(mmSize(w, h));
      layout.addLayoutItem(shape);
      ++item_count;
    } else {
      throw std::invalid_argument("unknown layout item type: " +
                                  type.toStdString());
    }
  }
  if (item_count == 0) {
    throw std::invalid_argument("layout spec contains no items");
  }

  const bool force_vector =
      spec.value(QStringLiteral("force_vector")).toBool(false);
  QgsLayoutExporter exporter(&layout);
  QgsLayoutExporter::ExportResult result;
  long long width_px = 0;
  long long height_px = 0;
  if (format == QLatin1String("pdf")) {
    QgsLayoutExporter::PdfExportSettings settings;
    settings.dpi = dpi;
    // D10: GeoPDF is available in the vendored QGIS and opt-in per export.
    settings.writeGeoPdf =
        spec.value(QStringLiteral("geo_pdf")).toBool(false);
    // CONV-29: vector preservation opt-in (no rasterised fallback layers).
    settings.forceVectorOutput = force_vector;
    result = exporter.exportToPdf(QString::fromStdString(output_path),
                                  settings);
  } else if (format == QLatin1String("svg")) {
    QgsLayoutExporter::SvgExportSettings settings;
    settings.dpi = dpi;
    settings.forceVectorOutput = force_vector;
    result = exporter.exportToSvg(QString::fromStdString(output_path),
                                  settings);
  } else if (format == QLatin1String("png")) {
    QgsLayoutExporter::ImageExportSettings settings;
    settings.dpi = dpi;
    result = exporter.exportToImage(QString::fromStdString(output_path),
                                    settings);
    if (result == QgsLayoutExporter::Success) {
      const QImage image(QString::fromStdString(output_path));
      if (!image.isNull()) {
        width_px = image.width();
        height_px = image.height();
      }
    }
  } else {
    throw std::invalid_argument("format must be pdf|svg|png, got: " + format);
  }
  if (result != QgsLayoutExporter::Success) {
    // D10/V7 never-fake contract: a failed export (e.g. GeoPDF without a
    // capable GDAL PDF driver — PrintError) must not leave a partial file
    // behind that callers could mistake for the requested product.
    std::error_code remove_error;
    std::filesystem::remove(output_path, remove_error);
    throw std::runtime_error("layout export failed with result code " +
                             std::to_string(static_cast<int>(result)));
  }
  QJsonObject report;
  report.insert(QStringLiteral("ok"), true);
  report.insert(QStringLiteral("path"),
                QString::fromStdString(output_path));
  report.insert(QStringLiteral("format"), QString::fromStdString(format));
  report.insert(QStringLiteral("dpi"), dpi);
  report.insert(QStringLiteral("items"), item_count);
  report.insert(QStringLiteral("page_mm"), QJsonArray{page_w, page_h});
  if (width_px > 0) {
    report.insert(QStringLiteral("width_px"),
                  static_cast<qint64>(width_px));
    report.insert(QStringLiteral("height_px"),
                  static_cast<qint64>(height_px));
  }
  return QJsonDocument(report).toJson(QJsonDocument::Compact).toStdString();
}

}  // namespace pwb::layout_spec_exec
