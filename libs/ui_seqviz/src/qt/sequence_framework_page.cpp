#include <pwb/ui_seqviz/qt/sequence_framework_page.hpp>

#include <QVBoxLayout>

#include <pwb/ui_seqviz/qt/panel_float_button.hpp>
#include <pwb/ui_seqviz/qt/sequence_panels.hpp>
#include <pwb/ui_shell/dock_manager.hpp>
#include <pwb/ui_shell/float_controller.hpp>

namespace pwb::ui_seqviz::qt {

namespace {
constexpr const char* kTargetPanelKey = "sequence-target-panel";
constexpr const char* kSummaryPanelKey = "sequence-summary-panel";
}  // namespace

SequenceFrameworkPage::SequenceFrameworkPage(QWidget* parent)
    : QWidget(parent) {
    setObjectName("SequenceFrameworkPage");
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    splitter_ = new QSplitter(Qt::Horizontal, this);
    layout->addWidget(splitter_);

    target_panel_ = new SequenceTargetPanel(this);
    splitter_->addWidget(target_panel_);
    boundary_table_ = new SequenceBoundaryTable(this);
    splitter_->addWidget(boundary_table_);
    scheme_summary_ = new SequenceSchemeSummary(this);
    splitter_->addWidget(scheme_summary_);

    splitter_->setStretchFactor(0, 0);
    splitter_->setStretchFactor(1, 1);
    splitter_->setStretchFactor(2, 0);
    splitter_->setSizes({280, 900, 260});

    connect(target_panel_, &SequenceTargetPanel::target_changed, this,
            &SequenceFrameworkPage::on_target_changed);
    connect(target_panel_, &SequenceTargetPanel::scheme_changed, this,
            &SequenceFrameworkPage::on_scheme_changed);
    connect(boundary_table_, &SequenceBoundaryTable::boundary_activated,
            this, &SequenceFrameworkPage::on_boundary_activated);
    connect(scheme_summary_, &SequenceSchemeSummary::save_requested, this,
            [this] { save_scheme(); });
}

SequenceFrameworkPage::~SequenceFrameworkPage() = default;

const StratigraphySlice& SequenceFrameworkPage::stratigraphy() const {
    static const StratigraphySlice kEmpty;
    return project_ != nullptr ? project_->stratigraphy : kEmpty;
}

void SequenceFrameworkPage::set_project(
    StratigraphyProjectSlice* project) {
    project_ = project;
}

void SequenceFrameworkPage::set_float_controller(
    ui_shell::LayoutPersistence* persistence) {
    ui_shell::dock_manager().register_panel(kTargetPanelKey, "层序格架设置");
    ui_shell::dock_manager().register_panel(kSummaryPanelKey, "层序方案摘要");

    auto resolver = [this](const std::string& key) -> QWidget* {
        if (key == kTargetPanelKey) {
            return target_panel_;
        }
        if (key == kSummaryPanelKey) {
            return scheme_summary_;
        }
        return nullptr;
    };
    auto title_for = [](const std::string& key) -> QString {
        return key == kTargetPanelKey
                   ? QStringLiteral("层序格架设置")
                   : QStringLiteral("层序方案摘要");
    };
    float_controller_ = std::make_unique<ui_shell::FloatController>(
        std::move(resolver), persistence, std::move(title_for), this);

    // Owned by their panels; kept alive by the panel parent chain.
    new PanelFloatButton(kTargetPanelKey, target_panel_,
                         float_controller_.get());
    new PanelFloatButton(kSummaryPanelKey, scheme_summary_,
                         float_controller_.get());
    float_controller_->restore_saved(kTargetPanelKey);
    float_controller_->restore_saved(kSummaryPanelKey);
}

void SequenceFrameworkPage::update_state(
    const StratigraphySlice& stratigraphy) {
    target_panel_->update_state(stratigraphy);
    boundary_table_->update_state(stratigraphy);
    scheme_summary_->update_state(stratigraphy);
}

bool SequenceFrameworkPage::save_scheme() {
    if (project_ == nullptr) {
        return false;
    }
    const QString scheme = target_panel_->current_scheme();
    if (scheme.isEmpty()) {
        emit warning_requested(QStringLiteral("缺少体系域方案"),
                               QStringLiteral("请输入体系域方案"));
        return false;
    }
    const QString target = target_panel_->current_target();
    const StratigraphySlice& strat = apply_stratigraphy_scheme(
        *project_, target.isEmpty() ? std::nullopt
                                    : std::optional<std::string>(
                                          target.toStdString()),
        scheme.toStdString(), std::nullopt, std::nullopt,
        /*bind_downstream=*/true);
    update_state(strat);
    scheme_summary_->set_bind_status(
        QStringLiteral("已保存到项目（%1）").arg(scheme));
    emit stratigraphy_updated();
    return true;
}

void SequenceFrameworkPage::on_target_changed(const QString& target) {
    if (project_ == nullptr || target.trimmed().isEmpty()) {
        return;
    }
    const StratigraphySlice& strat = apply_stratigraphy_scheme(
        *project_, target.trimmed().toStdString(), std::nullopt,
        std::nullopt, std::nullopt, /*bind_downstream=*/true);
    update_state(strat);
    scheme_summary_->set_bind_status(
        QStringLiteral("已应用到项目（%1）").arg(target.trimmed()));
    emit stratigraphy_updated();
}

void SequenceFrameworkPage::on_scheme_changed(const QString& scheme) {
    if (project_ == nullptr || scheme.trimmed().isEmpty()) {
        return;
    }
    const StratigraphySlice& strat = apply_stratigraphy_scheme(
        *project_, std::nullopt, scheme.trimmed().toStdString(),
        std::nullopt, std::nullopt, /*bind_downstream=*/true);
    update_state(strat);
    scheme_summary_->set_bind_status(
        QStringLiteral("已应用到项目（%1）").arg(scheme.trimmed()));
    emit stratigraphy_updated();
}

void SequenceFrameworkPage::on_boundary_activated(const QString& name) {
    if (project_ == nullptr || name.trimmed().isEmpty()) {
        return;
    }
    const StratigraphySlice& strat = set_target_from_boundary(
        *project_, name.toStdString(), /*bind_downstream=*/true);
    update_state(strat);
    scheme_summary_->set_bind_status(
        QStringLiteral("已设为目标层位（%1）").arg(name.trimmed()));
    emit stratigraphy_updated();
}

}  // namespace pwb::ui_seqviz::qt
