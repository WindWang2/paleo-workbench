#pragma once

// UI-09 — SeismicAttributePanel Qt shell (seismic_attribute_panel.py).
// QTreeWidget over seismic_attribute_panel_groups(); every enabled leaf
// maps to a wired kernel id — the computable kernel set is injected by the
// host (available_kernels() is engine capability, not catalog data);
// 未实现 leaves are disabled forever.

#include <functional>
#include <string>
#include <unordered_set>

#include <QFrame>
#include <QString>

class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui_wellseis::qt {

class SeismicAttributePanel : public QFrame {
    Q_OBJECT
public:
    // `computable_probe` answers "can the pipeline compute this kernel id?"
    // (Python available_kernels()). Default: treat every catalog kernel as
    // computable — the 未实现 group stays disabled regardless.
    explicit SeismicAttributePanel(
        QWidget* parent = nullptr,
        std::function<bool(const std::string& kernel_id)> computable_probe =
            {});

    void set_selected_attribute(const QString& label);  // suppressed
    [[nodiscard]] QString selected_attribute() const;

signals:
    void attribute_changed(const QString& label);

private:
    void populate();
    bool enabled_leaf(const QString& label) const;

    QTreeWidget* tree_ = nullptr;
    std::function<bool(const std::string&)> computable_probe_;
    bool suppress_ = false;
};

}  // namespace pwb::ui_wellseis::qt
