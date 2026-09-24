#pragma once

// UI-05 — MapChromePanel (map_chrome_panel.py): the right-hand map
// decoration summary — current title, enabled elements, the title edit +
// element checkboxes that emit chrome_changed, and the save/review
// buttons the page wires.

#include <map>
#include <string>

#include <QFrame>

#include <pwb/ui_map/map_chrome_core.hpp>
#include <pwb/ui_map/qt_meta.hpp>

class QCheckBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QVBoxLayout;

namespace pwb::ui_map {

class MapChromePanel : public QFrame {
    Q_OBJECT
public:
    explicit MapChromePanel(QWidget* parent = nullptr);

    // update_state(document): read map_chrome/name, refresh the summary +
    // controls without emitting (blockSignals parity).
    void update_state(const Json& document);

    QPushButton* save_button() const { return save_btn_; }
    QPushButton* review_button() const { return review_btn_; }

    // Test readback.
    std::string title_text() const;
    std::string elements_text() const;
    Json current_chrome() const;

signals:
    void chrome_changed(const pwb::ui_map::Json& chrome);

private:
    void emit_changed();

    QLabel* title_value_ = nullptr;
    QLabel* elements_value_ = nullptr;
    QLineEdit* title_edit_ = nullptr;
    std::map<std::string, QCheckBox*> element_checks_;
    QPushButton* save_btn_ = nullptr;
    QPushButton* review_btn_ = nullptr;
};

}  // namespace pwb::ui_map
