#include <pwb/ui_wellseis/qt/well_map_panel.hpp>

#include <QHBoxLayout>
#include <QLabel>
#include <QToolButton>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/page_state.hpp>
#include <pwb/ui_wellseis/qt/project_well_map_page.hpp>

namespace pwb::ui_wellseis::qt {

WellMapPanel::WellMapPanel(QWidget* parent, ProjectWellMapPage* map_page)
    : QFrame(parent), map_page_(map_page) {
    setObjectName(QStringLiteral("WellMapPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    header_ = new QWidget(this);
    header_layout_ = new QHBoxLayout(header_);
    header_layout_->setContentsMargins(8, 4, 8, 4);
    header_layout_->setSpacing(8);

    toggle_button_ = new QToolButton(header_);
    toggle_button_->setText(QStringLiteral("井位地图"));
    toggle_button_->setCheckable(true);
    toggle_button_->setChecked(true);
    toggle_button_->setArrowType(Qt::DownArrow);
    connect(toggle_button_, &QToolButton::toggled, this,
            [this](bool checked) { set_collapsed(!checked); });
    header_layout_->addWidget(toggle_button_);

    count_label_ = new QLabel(header_);
    count_label_->setStyleSheet(QStringLiteral("color: #6b6f76;"));
    header_layout_->addWidget(count_label_);
    header_layout_->addStretch(1);
    layout->addWidget(header_);

    body_ = new QWidget(this);
    auto* body_layout = new QVBoxLayout(body_);
    body_layout->setContentsMargins(0, 0, 0, 0);
    if (map_page_ == nullptr) {
        map_page_ = new ProjectWellMapPage(body_);
    }
    body_layout->addWidget(map_page_);
    layout->addWidget(body_, 1);
}

WellMapPanel::~WellMapPanel() = default;

void WellMapPanel::set_collapsed(bool collapsed) {
    collapsed_ = collapsed;
    body_->setVisible(!collapsed);
    toggle_button_->setChecked(!collapsed);
    toggle_button_->setArrowType(collapsed ? Qt::RightArrow
                                           : Qt::DownArrow);
}

bool WellMapPanel::is_collapsed() const {
    return collapsed_;
}

void WellMapPanel::set_header_visible(bool visible) {
    header_->setVisible(visible);
}

void WellMapPanel::add_header_button(QToolButton* button) {
    header_layout_->insertWidget(header_layout_->count() - 1, button);
}

void WellMapPanel::expand_and_focus(const std::string& well_id) {
    set_collapsed(false);
    map_page_->focus_well(well_id);
}

void WellMapPanel::refresh_domain(const ProjectSlice& project) {
    map_page_->set_project(project);
    count_label_->setText(QString::fromStdString(
        well_map_counts_text(well_map_counts(project.wells))));
}

ProjectWellMapPage* WellMapPanel::map_page() const {
    return map_page_;
}

QString WellMapPanel::count_text() const {
    return count_label_->text();
}

}  // namespace pwb::ui_wellseis::qt
