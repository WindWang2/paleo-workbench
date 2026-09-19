#include "pwb/ui_review/qt/lineage_explorer_dialog.hpp"

#include "pwb/ui_review/tokens.hpp"

#include <QApplication>
#include <QBrush>
#include <QClipboard>
#include <QColor>
#include <QFrame>
#include <QHBoxLayout>
#include <QPoint>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace pwb::ui_review::qt {

LineageExplorerDialog::LineageExplorerDialog(
    QWidget* parent, std::function<ICatalogApi*()> service_provider,
    const QString& version_id)
    : QDialog(parent), service_provider_(std::move(service_provider)) {
    setWindowTitle(QStringLiteral("血缘 / 溯源浏览器 (Lineage Explorer)"));
    resize(860, 680);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(tokens::kSpace2);

    // -- version locator -------------------------------------------------
    auto* locator_row = new QHBoxLayout();
    locator_row->setSpacing(tokens::kSpace2);
    locator_row->addWidget(new QLabel(QStringLiteral("版本 ID:"), this));
    version_edit_ = new QLineEdit(this);
    version_edit_->setPlaceholderText(
        QStringLiteral("输入版本 ID (ver_…) 后回车或点击「定位」"));
    connect(version_edit_, &QLineEdit::returnPressed, this, [this]() {
        recenter(version_edit_->text());
    });
    locator_row->addWidget(version_edit_, 1);
    locate_btn_ = new QPushButton(QStringLiteral("定位"), this);
    locate_btn_->setObjectName(QStringLiteral("PrimaryButton"));
    connect(locate_btn_, &QPushButton::clicked, this, [this]() {
        recenter(version_edit_->text());
    });
    locator_row->addWidget(locate_btn_);
    layout->addLayout(locator_row);

    locate_warning_ = new QLabel(QString(), this);
    locate_warning_->setStyleSheet(
        QStringLiteral("color: %1; font-size: 11px;")
            .arg(QString::fromUtf8(tokens::kWarning.data(),
                                   int(tokens::kWarning.size()))));
    locate_warning_->setWordWrap(true);
    locate_warning_->hide();
    layout->addWidget(locate_warning_);

    // -- summary card -----------------------------------------------------
    auto* summary_card = new QFrame(this);
    summary_card->setObjectName(QStringLiteral("LineageSummaryCard"));
    auto* summary_layout = new QVBoxLayout(summary_card);
    summary_layout->setContentsMargins(tokens::kSpace2, tokens::kSpace2,
                                       tokens::kSpace2, tokens::kSpace2);
    summary_layout->setSpacing(tokens::kSpace1);
    summary_title_label_ =
        new QLabel(QStringLiteral("未选择版本"), summary_card);
    summary_title_label_->setWordWrap(true);
    summary_layout->addWidget(summary_title_label_);
    summary_meta_label_ = new QLabel(QString(), summary_card);
    summary_meta_label_->setWordWrap(true);
    summary_layout->addWidget(summary_meta_label_);
    summary_path_label_ = new QLabel(QString(), summary_card);
    summary_path_label_->setWordWrap(true);
    summary_layout->addWidget(summary_path_label_);
    layout->addWidget(summary_card);

    // -- run card -----------------------------------------------------------
    auto* run_card = new QFrame(this);
    run_card->setObjectName(QStringLiteral("LineageRunCard"));
    auto* run_layout = new QVBoxLayout(run_card);
    run_layout->setContentsMargins(tokens::kSpace2, tokens::kSpace2,
                                   tokens::kSpace2, tokens::kSpace2);
    run_layout->setSpacing(tokens::kSpace1);
    run_title_label_ = new QLabel(QStringLiteral("—"), run_card);
    run_title_label_->setWordWrap(true);
    run_layout->addWidget(run_title_label_);
    run_meta_label_ = new QLabel(QString(), run_card);
    run_meta_label_->setWordWrap(true);
    run_layout->addWidget(run_meta_label_);
    run_params_view_ = new QPlainTextEdit(run_card);
    run_params_view_->setReadOnly(true);
    run_params_view_->setMaximumHeight(110);
    run_params_view_->setPlaceholderText(
        QStringLiteral("运行参数 (JSON)"));
    run_layout->addWidget(run_params_view_);
    layout->addWidget(run_card);

    // -- lazy lineage tree ----------------------------------------------------
    tree_ = new QTreeWidget(this);
    tree_->setHeaderLabel(
        QStringLiteral("血缘链（懒加载：展开节点查询一层）"));
    tree_->setColumnCount(1);
    tree_->setSelectionMode(QTreeWidget::SingleSelection);
    tree_->setEditTriggers(QTreeWidget::NoEditTriggers);
    connect(tree_, &QTreeWidget::itemExpanded, this,
            &LineageExplorerDialog::populate_lazy);
    connect(tree_, &QTreeWidget::itemDoubleClicked, this,
            [this](QTreeWidgetItem* item, int) {
                const LineageNodeSpec* spec = spec_of(item);
                if (spec != nullptr &&
                    (spec->kind == LineageNodeSpec::Kind::Version ||
                     spec->kind == LineageNodeSpec::Kind::Current)) {
                    emit version_activated(
                        QString::fromStdString(spec->version_id));
                }
            });
    tree_->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(tree_, &QTreeWidget::customContextMenuRequested, this,
            &LineageExplorerDialog::show_context_menu);
    layout->addWidget(tree_, 1);

    status_label_ = new QLabel(QString(), this);
    status_label_->setWordWrap(true);
    layout->addWidget(status_label_);

    auto* buttons = new QHBoxLayout();
    buttons->setSpacing(tokens::kSpace2);
    expand_raw_btn_ =
        new QPushButton(QStringLiteral("展开至 RAW 根"), this);
    expand_raw_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    expand_raw_btn_->setEnabled(false);
    connect(expand_raw_btn_, &QPushButton::clicked, this,
            &LineageExplorerDialog::on_expand_raw);
    buttons->addWidget(expand_raw_btn_);
    locate_in_page_btn_ =
        new QPushButton(QStringLiteral("在数据页定位"), this);
    locate_in_page_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    locate_in_page_btn_->setEnabled(false);
    connect(locate_in_page_btn_, &QPushButton::clicked, this, [this]() {
        const QString vid = selected_or_current_version_id();
        if (!vid.isEmpty()) {
            emit version_activated(vid);
        }
    });
    buttons->addWidget(locate_in_page_btn_);
    copy_id_btn_ =
        new QPushButton(QStringLiteral("复制版本 ID"), this);
    copy_id_btn_->setObjectName(QStringLiteral("SecondaryButton"));
    copy_id_btn_->setEnabled(false);
    connect(copy_id_btn_, &QPushButton::clicked, this, [this]() {
        const QString vid = selected_or_current_version_id();
        if (!vid.isEmpty()) {
            QClipboard* clipboard = QApplication::clipboard();
            if (clipboard != nullptr) {
                clipboard->setText(vid);
            }
        }
    });
    buttons->addWidget(copy_id_btn_);
    buttons->addStretch();
    auto* close_btn = new QPushButton(QStringLiteral("关闭"), this);
    connect(close_btn, &QPushButton::clicked, this, &QDialog::accept);
    buttons->addWidget(close_btn);
    layout->addLayout(buttons);

    if (!version_id.isEmpty()) {
        recenter(version_id);
    } else {
        show_empty_state();
    }
}

ICatalogApi* LineageExplorerDialog::service() const {
    return service_provider_ ? service_provider_() : nullptr;
}

std::optional<LineageHop>
LineageExplorerDialog::get_lineage(const std::string& vid) const {
    ICatalogApi* svc = service();
    if (svc == nullptr) {
        return std::nullopt;
    }
    return svc->get_lineage(vid);  // nullopt = CatalogError parity
}

std::string
LineageExplorerDialog::asset_name(const std::string& asset_id) const {
    ICatalogApi* svc = service();
    if (svc == nullptr) {
        return asset_id;
    }
    const auto asset = svc->get_asset(asset_id);
    return asset ? asset->name : asset_id;  // purged zombie → raw id
}

void LineageExplorerDialog::warn(const QString& message) {
    locate_warning_->setText(message);
    locate_warning_->show();
}

bool LineageExplorerDialog::recenter(const QString& version_id) {
    const QString vid = version_id.trimmed();
    if (vid.isEmpty()) {
        warn(QStringLiteral("请输入版本 ID"));
        return false;
    }
    ICatalogApi* svc = service();
    if (svc == nullptr) {
        warn(QStringLiteral("未连接数据目录（请先打开项目）"));
        return false;
    }
    const auto version = svc->get_version(vid.toStdString());
    if (!version) {
        warn(QStringLiteral("未找到版本：") + vid);
        return false;
    }
    locate_warning_->hide();
    load_version(*version);
    return true;
}

void LineageExplorerDialog::load_version(
    const catalog::DataVersion& version) {
    ICatalogApi* svc = service();
    if (svc == nullptr) {  // defensive: callers already guard
        return;
    }
    current_version_id_ = QString::fromStdString(version.id.str());
    current_asset_id_ = QString::fromStdString(version.asset_id.str());
    const std::string name = asset_name(version.asset_id.str());
    // _fill_summary
    const auto resolved = svc->resolve_path(version);
    const SummaryCardText card =
        summary_card_text(version, name, resolved.is_file);
    summary_title_label_->setText(QString::fromStdString(card.title));
    summary_meta_label_->setText(QString::fromStdString(card.meta));
    summary_path_label_->setText(QString::fromStdString(card.path));
    // _fill_run_card — one hop for the producing run.
    const auto hop = get_lineage(version.id.str());
    const RunCardText run_card =
        run_card_text(hop && hop->run ? &*hop->run : nullptr);
    run_title_label_->setText(QString::fromStdString(run_card.title));
    run_meta_label_->setText(QString::fromStdString(run_card.meta));
    if (run_card.has_run) {
        run_params_view_->setPlainText(
            QString::fromStdString(run_card.params));
        run_params_view_->show();
    } else {
        run_params_view_->hide();
    }
    rebuild_tree(version, name);
}

void LineageExplorerDialog::rebuild_tree(
    const catalog::DataVersion& version, const std::string& asset_name) {
    tree_->clear();
    specs_.clear();
    up_branch_ = nullptr;
    down_branch_ = nullptr;
    const LineageNodeSpec current_spec =
        current_item_spec(version, asset_name);
    auto* current_item = new QTreeWidgetItem(
        tree_, {QString::fromStdString(current_spec.label)});
    specs_[current_item] = current_spec;
    current_item->setChildIndicatorPolicy(
        QTreeWidgetItem::DontShowIndicator);
    up_branch_ = make_branch(current_item, QStringLiteral("⬆ 上游 (← RAW)"),
                             "up", version.id.str());
    down_branch_ =
        make_branch(current_item, QStringLiteral("⬇ 下游 (→ 产物)"), "down",
                    version.id.str());
    current_item->setExpanded(true);
    // Pre-expand one lazy hop upstream; downstream stays collapsed.
    up_branch_->setExpanded(true);
    tree_->setCurrentItem(current_item);
    expand_raw_btn_->setEnabled(true);
    locate_in_page_btn_->setEnabled(true);
    copy_id_btn_->setEnabled(true);
}

QTreeWidgetItem* LineageExplorerDialog::make_branch(
    QTreeWidgetItem* parent, const QString& label,
    const std::string& direction, const std::string& version_id) {
    auto* branch = new QTreeWidgetItem(parent, {label});
    specs_[branch] = branch_spec(direction, version_id);
    branch->setChildIndicatorPolicy(QTreeWidgetItem::ShowIndicator);
    branch->setFlags(branch->flags() & ~Qt::ItemIsSelectable);
    return branch;
}

void LineageExplorerDialog::show_empty_state() {
    current_version_id_.clear();
    current_asset_id_.clear();
    up_branch_ = nullptr;
    down_branch_ = nullptr;
    summary_title_label_->setText(QStringLiteral("未选择版本"));
    summary_meta_label_->setText(QStringLiteral(
        "请在上方输入版本 ID 并点击「定位」查看血缘。"));
    summary_path_label_->setText(QString());
    run_title_label_->setText(QStringLiteral("—"));
    run_meta_label_->setText(QString());
    run_params_view_->hide();
    tree_->clear();
    specs_.clear();
    auto* placeholder = new QTreeWidgetItem(
        tree_, {QStringLiteral("（未定位到版本 — 请输入版本 ID）")});
    placeholder->setFlags(placeholder->flags() & ~Qt::ItemIsSelectable);
    expand_raw_btn_->setEnabled(false);
    locate_in_page_btn_->setEnabled(false);
    copy_id_btn_->setEnabled(false);
}

// -- lazy population ---------------------------------------------------------

const LineageNodeSpec*
LineageExplorerDialog::spec_of(QTreeWidgetItem* item) const {
    const auto it = specs_.find(item);
    return it != specs_.end() ? &it->second : nullptr;
}

LineageNodeSpec* LineageExplorerDialog::spec_of(QTreeWidgetItem* item) {
    const auto it = specs_.find(item);
    return it != specs_.end() ? &it->second : nullptr;
}

void LineageExplorerDialog::populate_lazy(QTreeWidgetItem* item) {
    LineageNodeSpec* spec = spec_of(item);
    if (spec == nullptr || !spec->lazy) {
        return;
    }
    spec->lazy = false;
    const bool is_up = spec->direction == "up";
    const bool is_down = spec->direction == "down";
    if (!is_up && !is_down) {
        return;
    }
    const auto hop = get_lineage(spec->version_id);
    const LineageHop* hop_ptr = hop ? &*hop : nullptr;
    const auto name_fn = [this](const std::string& id) {
        return asset_name(id);
    };
    attach_nodes(item, is_up ? expand_inputs(hop_ptr, spec->ancestors,
                                             name_fn)
                             : expand_outputs(hop_ptr, spec->ancestors,
                                              name_fn));
}

void LineageExplorerDialog::attach_nodes(
    QTreeWidgetItem* holder, const std::vector<LineageNodeSpec>& specs) {
    QTreeWidgetItem* parent_holder = holder;
    for (const auto& spec : specs) {
        if (spec.kind == LineageNodeSpec::Kind::Run) {
            auto* run_item = new QTreeWidgetItem(
                holder, {QString::fromStdString(spec.label)});
            specs_[run_item] = spec;
            run_item->setChildIndicatorPolicy(
                QTreeWidgetItem::DontShowIndicator);
            parent_holder = run_item;
            continue;
        }
        auto* item = new QTreeWidgetItem(
            parent_holder, {QString::fromStdString(spec.label)});
        specs_[item] = spec;
        if (spec.red) {
            item->setForeground(0, QBrush(Qt::red));
        } else if (spec.kind == LineageNodeSpec::Kind::Note ||
                   spec.kind == LineageNodeSpec::Kind::Overflow) {
            item->setForeground(
                0, QBrush(QColor(QString::fromUtf8(
                       tokens::kTextSecondary.data(),
                       int(tokens::kTextSecondary.size())))));
        }
        if (!spec.selectable) {
            item->setFlags(item->flags() & ~Qt::ItemIsSelectable);
        }
        if (spec.disabled) {
            item->setDisabled(true);
        }
        item->setChildIndicatorPolicy(spec.show_indicator
                                          ? QTreeWidgetItem::ShowIndicator
                                          : QTreeWidgetItem::DontShowIndicator);
    }
}

// -- expand to RAW -------------------------------------------------------------

QTreeWidgetItem*
LineageExplorerDialog::input_holder(QTreeWidgetItem* item) {
    for (int i = 0; i < item->childCount(); ++i) {
        QTreeWidgetItem* child = item->child(i);
        const LineageNodeSpec* spec = spec_of(child);
        if (spec != nullptr && spec->kind == LineageNodeSpec::Kind::Run) {
            return child;
        }
    }
    return item;
}

std::vector<QTreeWidgetItem*>
LineageExplorerDialog::version_children(QTreeWidgetItem* holder) {
    std::vector<QTreeWidgetItem*> out;
    for (int i = 0; i < holder->childCount(); ++i) {
        QTreeWidgetItem* child = holder->child(i);
        const LineageNodeSpec* spec = spec_of(child);
        if (spec == nullptr) {
            continue;
        }
        if (spec->kind == LineageNodeSpec::Kind::Version) {
            out.push_back(child);
        } else if (spec->kind == LineageNodeSpec::Kind::Run) {
            // descend through run rows (OUTPUT → Run → INPUT idiom)
            auto nested = version_children(child);
            out.insert(out.end(), nested.begin(), nested.end());
        }
    }
    return out;
}

void LineageExplorerDialog::on_expand_raw() {
    if (current_version_id_.isEmpty() || up_branch_ == nullptr) {
        return;
    }
    expand_raw_btn_->setEnabled(false);
    std::set<std::string> visited{current_version_id_.toStdString()};
    int roots = 0;
    bool capped = false;
    populate_lazy(up_branch_);
    up_branch_->setExpanded(true);
    std::deque<std::pair<QTreeWidgetItem*, int>> pending;
    for (auto* child : version_children(up_branch_)) {
        pending.emplace_back(child, 1);
    }
    while (!pending.empty()) {
        auto [item, depth] = pending.front();
        pending.pop_front();
        const LineageNodeSpec* spec = spec_of(item);
        if (spec == nullptr ||
            spec->kind != LineageNodeSpec::Kind::Version) {
            continue;
        }
        const std::string& vid = spec->version_id;
        if (vid.empty() || visited.count(vid)) {
            continue;
        }
        if (depth > kMaxExpandDepth ||
            int(visited.size()) >= kMaxExpandNodes) {
            capped = true;
            break;
        }
        visited.insert(vid);
        populate_lazy(item);
        item->setExpanded(true);
        if (spec->stage == "raw") {
            ++roots;
            continue;  // a RAW root stops the upward walk
        }
        QTreeWidgetItem* holder = input_holder(item);
        holder->setExpanded(true);
        for (auto* child : version_children(holder)) {
            pending.emplace_back(child, depth + 1);
        }
    }
    if (capped) {
        status_label_->setText(
            QString::fromStdString(expand_raw_capped_status()));
    } else {
        status_label_->setText(QString::fromStdString(expand_raw_done_status(
            roots, int(visited.size()) - 1)));
        expand_raw_btn_->setEnabled(true);
    }
}

// -- activation --------------------------------------------------------------

QString LineageExplorerDialog::selected_or_current_version_id() const {
    const auto items = tree_->selectedItems();
    for (auto* item : items) {
        const LineageNodeSpec* spec = spec_of(item);
        if (spec != nullptr &&
            (spec->kind == LineageNodeSpec::Kind::Version ||
             spec->kind == LineageNodeSpec::Kind::Current)) {
            return QString::fromStdString(spec->version_id);
        }
    }
    return current_version_id_;
}

void LineageExplorerDialog::show_context_menu(const QPoint& pos) {
    QTreeWidgetItem* item = tree_->itemAt(pos);
    if (item == nullptr) {
        return;
    }
    const LineageNodeSpec* spec = spec_of(item);
    if (spec == nullptr ||
        (spec->kind != LineageNodeSpec::Kind::Version &&
         spec->kind != LineageNodeSpec::Kind::Current)) {
        return;
    }
    const QString vid = QString::fromStdString(spec->version_id);
    QMenu menu(this);
    QAction* locate_action = menu.addAction(QStringLiteral("在数据页定位"));
    QAction* copy_action = menu.addAction(QStringLiteral("复制版本 ID"));
    QAction* chosen =
        menu.exec(tree_->viewport()->mapToGlobal(pos));
    if (chosen == locate_action) {
        emit version_activated(vid);
    } else if (chosen == copy_action) {
        QClipboard* clipboard = QApplication::clipboard();
        if (clipboard != nullptr) {
            clipboard->setText(vid);
        }
    }
}

}  // namespace pwb::ui_review::qt
