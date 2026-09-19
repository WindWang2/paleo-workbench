#include <pwb/ui_pages_preview/qt/json_tree_preview_widget.hpp>

#include <pwb/ui_pages_preview/preview_settings.hpp>

namespace pwb::ui_pages_preview {

JsonTreePreviewWidget::JsonTreePreviewWidget(QWidget* parent)
    : QTreeView(parent) {
    setHeaderHidden(false);
    model_.setHorizontalHeaderLabels({"键", "值/类型"});
    setModel(&model_);
    connect(this, &QTreeView::expanded, this, &JsonTreePreviewWidget::on_expanded);
}

void JsonTreePreviewWidget::apply_settings(const PreviewSettings& settings) {
    const bool reload_needed =
        settings.json_array_collapse_threshold != array_collapse_threshold_ ||
        settings.json_expand_depth != expand_depth_;
    array_collapse_threshold_ = settings.json_array_collapse_threshold;
    expand_depth_ = settings.json_expand_depth;
    QFont f = font();
    f.setPointSize(settings.font_size);
    setFont(f);
    // Font changes apply live; only structure-affecting settings rebuild.
    if (!payload_.is_null() && reload_needed) {
        load_payload(payload_, truncated_);
    }
}

void JsonTreePreviewWidget::load_payload(const domain::Json& payload,
                                         bool truncated) {
    payload_ = payload;
    truncated_ = truncated;
    lazy_nodes_.clear();
    model_.clear();
    model_.setHorizontalHeaderLabels({"键", "值/类型"});
    append_rows(model_.invisibleRootItem(), build_tree(payload, array_collapse_threshold_));
    expand_initial_depth();
}

void JsonTreePreviewWidget::append_rows(QStandardItem* parent,
                                        const std::vector<JsonNode>& nodes) {
    for (const JsonNode& node : nodes) {
        auto* key_item = new QStandardItem(QString::fromStdString(node.key));
        auto* val_item = new QStandardItem(QString::fromStdString(node.label));
        key_item->setEditable(false);
        val_item->setEditable(false);
        parent->appendRow({key_item, val_item});
        switch (node.kind) {
        case JsonNodeKind::object_inline:
        case JsonNodeKind::array_inline:
            append_rows(key_item, node.children);
            break;
        case JsonNodeKind::container_lazy: {
            lazy_nodes_.push_back(std::make_unique<JsonNode>(node));
            key_item->setData(
                static_cast<qint64>(lazy_nodes_.size() - 1), ROLE_CONTAINER);
            break;
        }
        case JsonNodeKind::sentinel: {
            lazy_nodes_.push_back(std::make_unique<JsonNode>(node));
            key_item->setData(
                static_cast<qint64>(lazy_nodes_.size() - 1), ROLE_MORE);
            break;
        }
        case JsonNodeKind::scalar:
        case JsonNodeKind::depth_cap:
            break;
        }
    }
}

void JsonTreePreviewWidget::on_expanded(const QModelIndex& index) {
    QStandardItem* item = model_.itemFromIndex(index);
    if (item == nullptr) return;

    const QVariant more = item->data(ROLE_MORE);
    const QVariant container = item->data(ROLE_CONTAINER);

    if (more.isValid()) {
        // Sentinel expanded → materialize the next batch into the PARENT,
        // drop the sentinel, re-add it if entries remain.
        QStandardItem* parent = item->parent();
        if (parent == nullptr) parent = model_.invisibleRootItem();
        const JsonNode* state = lazy_nodes_[more.toLongLong()].get();
        std::vector<JsonNode> batch;
        const int parent_depth = [&] {
            int d = 0;
            for (QStandardItem* p = parent; p != model_.invisibleRootItem() && p != nullptr;
                 p = p->parent()) ++d;
            return d;
        }();
        const std::size_t next = append_batch(
            state->container, state->offset, array_collapse_threshold_,
            parent_depth, batch);
        append_rows(parent, batch);
        parent->removeRow(item->row());
        if (next < state->container.size()) {
            append_rows(parent, {sentinel_node(state->container, next)});
        }
        return;
    }

    if (container.isValid() && item->rowCount() == 0) {
        const JsonNode* state = lazy_nodes_[container.toLongLong()].get();
        std::vector<JsonNode> batch;
        const int depth = [&] {
            int d = 0;
            for (QModelIndex p = index.parent(); p.isValid(); p = p.parent()) ++d;
            return d;
        }();
        const std::size_t next = append_batch(
            state->container, 0, array_collapse_threshold_, depth, batch);
        append_rows(item, batch);
        if (next < state->container.size()) {
            append_rows(item, {sentinel_node(state->container, next)});
        }
    }
}

void JsonTreePreviewWidget::expand_initial_depth() {
    std::function<void(const QModelIndex&, int)> visit =
        [&](const QModelIndex& parent, int depth) {
            if (depth >= expand_depth_) return;
            for (int row = 0; row < model_.rowCount(parent); ++row) {
                const QModelIndex idx = model_.index(row, 0, parent);
                if (model_.hasChildren(idx)) {
                    expand(idx);
                    visit(idx, depth + 1);
                }
            }
        };
    visit(rootIndex(), 0);
}

}  // namespace pwb::ui_pages_preview
