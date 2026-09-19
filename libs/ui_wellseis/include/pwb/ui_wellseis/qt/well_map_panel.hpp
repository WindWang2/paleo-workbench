#pragma once

// UI-09 — WellMapPanel Qt shell (well_map_panel.py).
// Collapsible header around ProjectWellMapPage: toggle button, count label
// ("N 口测区井 · M 口参考井" / "N 口井"), extra header buttons, expanded
// state, expand_and_focus delegation.

#include <QFrame>
#include <QString>

#include <pwb/ui_wellseis/slices.hpp>

class QHBoxLayout;
class QLabel;
class QToolButton;

namespace pwb::ui_wellseis::qt {

class ProjectWellMapPage;

class WellMapPanel : public QFrame {
    Q_OBJECT
public:
    // `map_page` is borrowed (caller keeps ownership); nullptr builds the
    // page in place — matches the Python default.
    explicit WellMapPanel(QWidget* parent = nullptr,
                          ProjectWellMapPage* map_page = nullptr);
    ~WellMapPanel() override;

    void set_collapsed(bool collapsed);
    [[nodiscard]] bool is_collapsed() const;
    void set_header_visible(bool visible);
    void add_header_button(QToolButton* button);
    void expand_and_focus(const std::string& well_id);

    // refresh_domain parity — rebuilds the count label + delegates.
    void refresh_domain(const ProjectSlice& project);
    [[nodiscard]] ProjectWellMapPage* map_page() const;
    [[nodiscard]] QString count_text() const;

private:
    QToolButton* toggle_button_ = nullptr;
    QLabel* count_label_ = nullptr;
    QHBoxLayout* header_layout_ = nullptr;
    QWidget* header_ = nullptr;
    QWidget* body_ = nullptr;
    ProjectWellMapPage* map_page_ = nullptr;
    bool collapsed_ = false;
};

}  // namespace pwb::ui_wellseis::qt
