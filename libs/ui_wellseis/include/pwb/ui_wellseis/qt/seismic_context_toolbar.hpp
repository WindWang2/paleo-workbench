#pragma once

// UI-09 — SeismicContextToolbar Qt shell (seismic_context_toolbar.py).
// Single-row compact context toolbar: source-volume combo, attribute combo,
// settings popover (task/horizon/attribute/mode/shape/output-nature card +
// mode actions + attribute submenu), status label, demo + run buttons.
// Catalog + output-nature semantics live in the Qt-free cores.

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <QFrame>
#include <QString>

#include <pwb/domain/json.hpp>
#include <pwb/ui_wellseis/resource_sources.hpp>
#include <pwb/ui_wellseis/slices.hpp>

class QActionGroup;
class QComboBox;
class QLabel;
class QMenu;
class QPushButton;
class QToolButton;

namespace pwb::ui_wellseis::qt {

class SeismicContextToolbar : public QFrame {
    Q_OBJECT
public:
    explicit SeismicContextToolbar(QWidget* parent = nullptr);

    // set_context parity — nullopt shape/nature leaves those fields
    // untouched (Python only writes them when not None).
    void set_context(const PredictionTaskSlice* task,
                     const std::string& horizon,
                     const std::string& attribute_label,
                     const std::string& mode_label,
                     std::optional<std::array<std::int64_t, 3>> volume_shape,
                     const std::optional<std::string>& mock_nature);
    void set_status(const QString& text);
    void set_inferring(bool inferring);

    // Source combo = resource slices (id userData); refresh keeps the
    // previous selection by id (resolved_source_index parity).
    void set_source_entries(const std::vector<SourceComboEntry>& entries);
    [[nodiscard]] std::string selected_source_id() const;
    void set_selected_attribute(const QString& label);
    void set_display_mode(const QString& mode);

signals:
    void run_requested();
    void demo_requested();
    void attribute_changed(const QString& label);
    void display_mode_changed(const QString& mode);
    void source_changed(const QString& resource_id);

private:
    void build_settings_menu();

    QComboBox* source_combo_ = nullptr;
    QComboBox* attribute_combo_ = nullptr;
    QToolButton* settings_btn_ = nullptr;
    QMenu* settings_menu_ = nullptr;
    QActionGroup* mode_group_ = nullptr;
    QLabel* status_value_ = nullptr;
    QLabel* task_value_ = nullptr;
    QLabel* horizon_value_ = nullptr;
    QLabel* attribute_value_ = nullptr;
    QLabel* mode_value_ = nullptr;
    QLabel* shape_value_ = nullptr;
    QLabel* mock_value_ = nullptr;
    QPushButton* demo_btn_ = nullptr;
    QPushButton* run_btn_ = nullptr;
    bool suppress_signals_ = false;
};

}  // namespace pwb::ui_wellseis::qt
