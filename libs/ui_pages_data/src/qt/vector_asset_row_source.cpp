// CLOSURE-PREVIEW (task 04) — see qt/vector_asset_row_source.hpp.
#include <pwb/ui_pages_data/qt/vector_asset_row_source.hpp>

#include <pwb/ui_pages_data/vocab.hpp>

namespace pwb::ui_pages_data::qt {

namespace {

// Column cell text, keyed by the shared column vocabulary. Unknown keys
// render empty (the column-settings UI never offers them).
QString cell_text(const AssetView& v, const std::string& key) {
    if (key == "name") return QString::fromStdString(v.name);
    if (key == "type") return QString::fromStdString(v.type);
    if (key == "stage") return QString::fromStdString(v.stage);
    if (key == "version") return QString::fromStdString(v.version_label);
    if (key == "lineage") return QString::fromStdString(v.lineage_label);
    if (key == "tags") {
        QString joined;
        for (const auto& tag : v.tags) {
            if (!joined.isEmpty()) joined += QLatin1String(", ");
            joined += QString::fromStdString(tag);
        }
        return joined;
    }
    if (key == "managed") {
        return QString::fromStdString(
            !v.managed_label.empty()
                ? v.managed_label
                : (v.managed ? std::string("受管") : std::string("外部")));
    }
    if (key == "integrity") return QString::fromStdString(v.integrity);
    if (key == "format") return QString::fromStdString(v.format);
    if (key == "status") return QString::fromStdString(v.status);
    if (key == "role") return QString::fromStdString(v.role);
    if (key == "review_status") {
        return QString::fromStdString(v.review_status);
    }
    if (key == "size") return QString::fromStdString(v.size_label);
    if (key == "linked") {
        return v.linked_label.empty()
                   ? QStringLiteral("—")
                   : QString::fromStdString(v.linked_label);
    }
    if (key == "horizon") {
        return v.horizon_label.empty()
                   ? QStringLiteral("—")
                   : QString::fromStdString(v.horizon_label);
    }
    if (key == "modified") return QString::fromStdString(v.modified_label);
    if (key == "source") return QString::fromStdString(v.source_label);
    if (key == "path") return QString::fromStdString(v.path);
    return QString();
}

}  // namespace

VectorAssetRowSource::VectorAssetRowSource(QObject* parent)
    : AssetRowSource(parent) {}

void VectorAssetRowSource::set_rows(const std::vector<AssetRow>& rows) {
    beginResetModel();
    rows_ = rows;
    endResetModel();
}

const AssetRow* VectorAssetRowSource::asset_at(int row) const {
    if (row < 0 || row >= static_cast<int>(rows_.size())) return nullptr;
    return &rows_[static_cast<std::size_t>(row)];
}

int VectorAssetRowSource::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(rows_.size());
}

int VectorAssetRowSource::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0
                            : static_cast<int>(column_definitions().size());
}

QVariant VectorAssetRowSource::data(const QModelIndex& index,
                                    int role) const {
    if (!index.isValid() || role != Qt::DisplayRole) return QVariant();
    const AssetRow* asset = asset_at(index.row());
    if (asset == nullptr) return QVariant();
    const auto& defs = column_definitions();
    if (index.column() >= static_cast<int>(defs.size())) return QVariant();
    return cell_text(asset->view, std::string(defs[static_cast<std::size_t>(
                                      index.column())].key));
}

QVariant VectorAssetRowSource::headerData(int section,
                                          Qt::Orientation orientation,
                                          int role) const {
    if (role != Qt::DisplayRole) return QVariant();
    const auto& defs = column_definitions();
    if (orientation == Qt::Horizontal &&
        section < static_cast<int>(defs.size())) {
        return QString::fromStdString(
            std::string(defs[static_cast<std::size_t>(section)].label));
    }
    return section + 1;
}

}  // namespace pwb::ui_pages_data::qt
