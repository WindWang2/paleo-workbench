#include <pwb/ui_wellseis/qt/well_log_track_settings.hpp>

#include <QDialogButtonBox>
#include <QDropEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QMimeData>
#include <QPushButton>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

}  // namespace

CurveLayoutTree::CurveLayoutTree(QWidget* parent) : QTreeWidget(parent) {
    setDragDropMode(QAbstractItemView::InternalMove);
    setDefaultDropAction(Qt::MoveAction);
    setSelectionMode(QAbstractItemView::SingleSelection);
}

void CurveLayoutTree::dropEvent(QDropEvent* event) {
    // A drop onto another curve item means "merge", never a reparent.
    QTreeWidgetItem* target = itemAt(event->position().toPoint());
    QTreeWidgetItem* source = currentItem();
    const QString target_key =
        target != nullptr
            ? target->data(0, CurveKeyRole).toString()
            : QString();
    const QString source_key =
        source != nullptr
            ? source->data(0, CurveKeyRole).toString()
            : QString();
    event->setDropAction(Qt::IgnoreAction);
    event->ignore();  // never let the default reparent rows
    if (!target_key.isEmpty() && !source_key.isEmpty() &&
        target_key != source_key) {
        emit merge_requested(source_key, target_key);
        event->accept();
    }
}

CurveTrackSettingsDialog::CurveTrackSettingsDialog(
    const std::vector<std::string>& mnemonics,
    pwb::viz::WellLogTrackLayout layout, QWidget* parent)
    : QDialog(parent),
      mnemonics_(mnemonics),
      layout_(std::move(layout)) {
    setObjectName(QStringLiteral("CurveTrackSettingsDialog"));
    setWindowTitle(QStringLiteral("井道显示设置"));
    setMinimumWidth(440);
    curve_keys_.reserve(mnemonics_.size());
    for (std::size_t i = 0; i < mnemonics_.size(); ++i) {
        curve_keys_.push_back(
            pwb::viz::curve_key_for(i, mnemonics_[i]));
    }

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(16, 16, 16, 16);
    outer->setSpacing(8);

    auto* help_text = new QLabel(
        QStringLiteral("默认显示 6 个井道（包含 GR）。勾选控制显示；"
                       "将一条曲线拖到另一条曲线上即可合并，每组最多 3 条。"),
        this);
    help_text->setWordWrap(true);
    help_text->setObjectName(QStringLiteral("WorkFieldLabel"));
    outer->addWidget(help_text);

    tree_ = new CurveLayoutTree(this);
    tree_->setObjectName(QStringLiteral("CurveTrackSettingsTree"));
    tree_->setHeaderLabels({QStringLiteral("井道 / 合并组"),
                            QStringLiteral("显示")});
    connect(tree_, &QTreeWidget::itemChanged, this,
            [this](QTreeWidgetItem* item, int column) {
                if (rebuilding_ || column != 1 || item == nullptr) {
                    return;
                }
                const std::string key =
                    item->data(0, CurveLayoutTree::CurveKeyRole)
                        .toString()
                        .toStdString();
                if (key.empty()) {
                    return;
                }
                try {
                    layout_ = layout_.with_visible(
                        key,
                        item->checkState(1) == Qt::Checked);
                } catch (const std::out_of_range&) {
                    // Unknown key — the tree only ever shows real keys.
                }
            });
    connect(tree_, &CurveLayoutTree::merge_requested, this,
            [this](const QString& source, const QString& target) {
                merge_curve(source.toStdString(), target.toStdString());
            });
    outer->addWidget(tree_, 1);

    status_label_ =
        new QLabel(QStringLiteral("选择一条合并组后可解除合并。"), this);
    status_label_->setObjectName(QStringLiteral("WorkFieldValue"));
    outer->addWidget(status_label_);

    auto* actions = new QHBoxLayout();
    unmerge_btn_ = new QPushButton(QStringLiteral("解除合并"), this);
    unmerge_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    unmerge_btn_->setToolTip(
        QStringLiteral("把当前合并组恢复为独立井道"));
    connect(unmerge_btn_, &QPushButton::clicked, this, [this] {
        QTreeWidgetItem* item = tree_->currentItem();
        const std::string key =
            item != nullptr
                ? item->data(0, CurveLayoutTree::CurveKeyRole)
                      .toString()
                      .toStdString()
                : std::string();
        if (key.empty()) {
            status_label_->setText(
                QStringLiteral("请选择需要解除的合并井道。"));
            return;
        }
        unmerge_curve(key);
    });
    actions->addWidget(unmerge_btn_);
    reset_btn_ = new QPushButton(QStringLiteral("恢复默认"), this);
    reset_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    connect(reset_btn_, &QPushButton::clicked, this, [this] {
        layout_ = pwb::viz::default_track_layout(mnemonics_);
        status_label_->setText(
            QStringLiteral("已恢复默认 6 个井道。"));
        rebuild_tree();
    });
    actions->addWidget(reset_btn_);
    actions->addStretch(1);
    outer->addLayout(actions);

    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    outer->addWidget(buttons);

    rebuild_tree();
}

const pwb::viz::WellLogTrackLayout& CurveTrackSettingsDialog::layout()
    const {
    return layout_;
}

QString CurveTrackSettingsDialog::status_text() const {
    return status_label_->text();
}

QTreeWidgetItem* CurveTrackSettingsDialog::make_curve_item(
    const std::string& key) {
    // Display name = the mnemonic for the key's index (Python
    // `_names[key] = curve.name or "未命名曲线"`).
    std::string name = "未命名曲线";
    for (std::size_t i = 0; i < curve_keys_.size(); ++i) {
        if (curve_keys_[i] == key) {
            name = mnemonics_[i].empty() ? "未命名曲线" : mnemonics_[i];
            break;
        }
    }
    auto* item = new QTreeWidgetItem({qs(name), QString()});
    item->setData(0, CurveLayoutTree::CurveKeyRole, qs(key));
    item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable |
                   Qt::ItemIsUserCheckable | Qt::ItemIsDragEnabled |
                   Qt::ItemIsDropEnabled);
    bool visible = false;
    try {
        const std::size_t index = layout_.key_index(key);
        visible = index < layout_.visible.size() && layout_.visible[index];
    } catch (const std::out_of_range&) {
        // Unknown key — renders unchecked.
    }
    item->setCheckState(1, visible ? Qt::Checked : Qt::Unchecked);
    return item;
}

void CurveTrackSettingsDialog::rebuild_tree() {
    rebuilding_ = true;
    tree_->clear();
    for (const auto& group : layout_.groups) {
        if (group.size() == 1) {
            tree_->addTopLevelItem(make_curve_item(group.front()));
            continue;
        }
        // A merged group is a real parent; children keep the curve names.
        std::string title;
        for (std::size_t i = 0; i < group.size(); ++i) {
            if (i != 0) {
                title += "+";
            }
            const auto& key = group[i];
            const auto second = key.find(
                ':', key.find(':') == std::string::npos
                       ? 0
                       : key.find(':') + 1);
            title += second == std::string::npos ? key
                                               : key.substr(second + 1);
        }
        auto* group_item = new QTreeWidgetItem({qs(title), QString()});
        group_item->setData(0, CurveLayoutTree::CurveKeyRole,
                            qs(group.front()));
        group_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable |
                             Qt::ItemIsDropEnabled);
        for (const auto& key : group) {
            group_item->addChild(make_curve_item(key));
        }
        tree_->addTopLevelItem(group_item);
        group_item->setExpanded(true);
    }
    rebuilding_ = false;
}

bool CurveTrackSettingsDialog::merge_curve(const std::string& curve_key,
                                           const std::string& onto_key) {
    try {
        layout_ = layout_.merge(curve_key, onto_key);
    } catch (const pwb::viz::curve_group_limit_error& exc) {
        status_label_->setText(qs(exc.what()));
        return false;
    } catch (const std::out_of_range&) {
        return false;
    }
    status_label_->setText(QStringLiteral("已合并井道。"));
    rebuild_tree();
    return true;
}

bool CurveTrackSettingsDialog::unmerge_curve(const std::string& curve_key) {
    std::size_t before = 1;
    try {
        before = layout_.group_for(curve_key).size();
        layout_ = layout_.unmerge(curve_key);
    } catch (const std::out_of_range&) {
        return false;
    }
    if (before <= 1) {
        status_label_->setText(QStringLiteral("当前井道尚未合并。"));
        return false;
    }
    status_label_->setText(QStringLiteral("已解除合并。"));
    rebuild_tree();
    return true;
}

}  // namespace pwb::ui_wellseis::qt
