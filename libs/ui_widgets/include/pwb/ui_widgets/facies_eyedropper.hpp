#pragma once

// UI-02 — FaciesEyedropper, ported from
// paleo_workbench/ui/components/facies_eyedropper.py (M2): the eyedropper
// session state (active/click/equip-forwarding). Pure coordinator — it
// owns no canvas or tool state; the host routes clicks to handle_click()
// while active. `identify` is injected (identify_all-shaped results).

#include <QObject>
#include <QVariantMap>

#include <nlohmann/json.hpp>

#include "pwb/ui_widgets/core/facies_pick.hpp"

namespace pwb::ui_widgets {

class FaciesEyedropper : public QObject {
    Q_OBJECT
public:
    explicit FaciesEyedropper(QObject* parent = nullptr);

    bool active() const { return active_; }
    void set_active(bool active) { active_ = active; }

    // identify(x, y) -> identify_all-shaped hit list (each hit a dict
    // with attributes/layer_id/feature_id/layer_name, topmost first).
    void bind(core::FaciesIdentifyFn identify);
    // Optional color seam (default: categorized-renderer facies_color).
    void bind_color(core::FaciesColorFn color_of);

    // Handle one map click: hit -> picked (equip forward), miss ->
    // pick_missed (keeps current equip). Returns whether a pick happened.
    bool handle_click(double x, double y);

signals:
    void picked(const QVariantMap& result);
    void pick_missed();

private:
    bool active_ = false;
    core::FaciesIdentifyFn identify_;
    core::FaciesColorFn color_of_;
};

// C++-side convenience: JSON hit -> QVariantMap pick result (the Python
// `picked(dict)` payload shape — color/pattern included when resolvable).
QVariantMap facies_pick_result_to_variant(
    const core::FaciesPickResult& result);

}  // namespace pwb::ui_widgets
