// UI-06 — module_relationship.py Qt shell.
//
// ModuleCard / SubCard / DatabaseModuleCard / LegendWidget /
// ModuleRelationshipCanvas / ModuleRelationshipWidget — the home-page
// workflow map. Status resolution lives in module_map.hpp; painting is a
// direct QPainter port. Seams: PwbBadge (ui.components) → a tone-styled
// QLabel; workstation_icon (ui.workstation.common) → injected icon
// provider (empty pixmap default).
#pragma once

#include <QFrame>
#include <QLabel>
#include <QPixmap>
#include <QString>
#include <QWidget>

#include <functional>
#include <map>
#include <string>
#include <tuple>
#include <vector>

#include <pwb/ui_pages_data/module_map.hpp>

class QGridLayout;
class QPainter;

namespace pwb::ui_pages_data::qt {

// (icon_name, color) → pixmap seam for ui.workstation.common.workstation_icon.
using IconProviderFn =
    std::function<QPixmap(const std::string& icon_name, const QString& color,
                          int size)>;

// Minimal badge seam — text + tone token. ui.components.PwbBadge owns the
// real rendering; this keeps setText/set_tone semantics for the oracle.
class StatusBadge : public QLabel {
    Q_OBJECT
public:
    explicit StatusBadge(QWidget* parent = nullptr);
    void set_tone(const QString& tone);
    QString tone() const { return tone_; }

private:
    QString tone_ = QStringLiteral("neutral");
};

class ModuleCard : public QFrame {
    Q_OBJECT
public:
    ModuleCard(const QString& title, const std::vector<QString>& items,
               const std::vector<QString>& inputs,
               const std::vector<QString>& outputs, bool is_accented,
               int page_index, QWidget* parent = nullptr);

    int page_index() const { return page_index_; }
    void set_status(const QString& status);

Q_SIGNALS:
    void clicked(int page_index);

protected:
    void mousePressEvent(QMouseEvent* event) override;

private:
    int page_index_;
    bool accented_;
    StatusBadge* status_badge_;
};

class SubCard : public QFrame {
    Q_OBJECT
public:
    SubCard(const QString& title, const std::string& icon_name,
            int page_index, QWidget* parent = nullptr);

    int page_index() const { return page_index_; }
    static void set_icon_provider(IconProviderFn fn);

Q_SIGNALS:
    void clicked(int page_index);

protected:
    bool event(QEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;

private:
    void refresh_icon();

    int page_index_;
    std::string icon_name_;
    QLabel* icon_label_;
    static IconProviderFn icon_provider_;
};

class DatabaseModuleCard : public QFrame {
    Q_OBJECT
public:
    DatabaseModuleCard(
        const QString& title,
        const std::vector<std::tuple<QString, std::string, int>>& sub_items,
        QWidget* parent = nullptr);

    void set_status(const QString& status);

Q_SIGNALS:
    void clicked(int page_index);

private:
    StatusBadge* status_badge_;
};

class LegendWidget : public QFrame {
    Q_OBJECT
public:
    explicit LegendWidget(QWidget* parent = nullptr);
};

class ModuleRelationshipCanvas : public QWidget {
    Q_OBJECT
public:
    static constexpr int kMinCanvasWidth = 1080;  // MIN_CANVAS_WIDTH

    explicit ModuleRelationshipCanvas(QWidget* parent = nullptr);

    void update_states(const std::vector<StepLike>& steps);

    ModuleCard* card_sequence() { return card_sequence_; }
    ModuleCard* card_well() { return card_well_; }
    ModuleCard* card_seismic() { return card_seismic_; }
    ModuleCard* card_facies() { return card_facies_; }
    ModuleCard* card_mapping() { return card_mapping_; }
    DatabaseModuleCard* card_data() { return card_data_; }

Q_SIGNALS:
    void navigation_requested(int page_index);

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    void draw_directed_arrow(QPainter& painter, const QPoint& start,
                             const QPoint& end, const QString& text = {},
                             const QString& text_pos = QStringLiteral("top"),
                             bool is_dashed = false,
                             const QString& color_hex = {});
    void draw_parallel_horizontal_arrows(QPainter& painter);
    void draw_vertical_framework_seismic_connection(QPainter& painter);
    void draw_vertical_framework_facies_connection(QPainter& painter);
    void draw_horizontal_facies_mapping_connection(QPainter& painter);
    void draw_database_support_arrows(QPainter& painter);

    ModuleCard* card_sequence_;
    ModuleCard* card_well_;
    ModuleCard* card_seismic_;
    ModuleCard* card_facies_;
    ModuleCard* card_mapping_;
    DatabaseModuleCard* card_data_;
};

class ModuleRelationshipWidget : public QWidget {
    Q_OBJECT
public:
    explicit ModuleRelationshipWidget(QWidget* parent = nullptr);

    void update_states(const std::vector<StepLike>& steps);

    ModuleRelationshipCanvas* canvas() { return canvas_; }

Q_SIGNALS:
    void navigation_requested(int page_index);

private:
    ModuleRelationshipCanvas* canvas_;
};

}  // namespace pwb::ui_pages_data::qt
