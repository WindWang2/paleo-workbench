#include "pwb/ui_widgets/facies_eyedropper.hpp"

#include "pwb/ui_widgets/facies_palette_widget.hpp"  // facies_color

namespace pwb::ui_widgets {

QVariantMap facies_pick_result_to_variant(
    const core::FaciesPickResult& result) {
    QVariantMap out;
    out.insert("facies", QString::fromStdString(result.facies));
    out.insert("sub_facies", QString::fromStdString(result.sub_facies));
    out.insert("micro_facies", QString::fromStdString(result.micro_facies));
    out.insert("level", QString::fromStdString(result.level));
    out.insert("layer_id", QString::fromStdString(result.layer_id));
    out.insert("feature_id", QString::fromStdString(result.feature_id));
    out.insert("layer_name", QString::fromStdString(result.layer_name));
    out.insert("color", QString::fromStdString(result.color));
    // Python emits None for unmapped patterns — QVariant() (invalid).
    out.insert("pattern",
               result.pattern
                   ? QVariant(QString::fromStdString(*result.pattern))
                   : QVariant());
    return out;
}

FaciesEyedropper::FaciesEyedropper(QObject* parent) : QObject(parent) {
    color_of_ = [](const std::string& name) {
        return facies_color(QString::fromStdString(name)).toStdString();
    };
}

void FaciesEyedropper::bind(core::FaciesIdentifyFn identify) {
    identify_ = std::move(identify);
}

void FaciesEyedropper::bind_color(core::FaciesColorFn color_of) {
    if (color_of) color_of_ = std::move(color_of);
}

bool FaciesEyedropper::handle_click(double x, double y) {
    if (!active_ || !identify_) return false;
    const auto result = core::pick_facies_at(x, y, identify_, color_of_);
    if (!result) {
        emit pick_missed();
        return false;
    }
    emit picked(facies_pick_result_to_variant(*result));
    return true;
}

}  // namespace pwb::ui_widgets
