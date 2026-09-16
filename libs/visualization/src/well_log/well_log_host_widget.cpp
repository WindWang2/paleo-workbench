#include "well_log_host_widget.hpp"

#include <QFile>
#include <QString>
#include <QVBoxLayout>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/core/units.hpp>
#include <welllog/io/las.hpp>
#include <welllog/qtwidgets/well_log_view.hpp>
#include <welllog/scene/scene.hpp>
#include <welllog/session/session.hpp>

#include <algorithm>
#include <cmath>
#include <utility>
#include <vector>

namespace pwb::viz {

using welllog::EntityId;

namespace {

constexpr double kTrackWidthMm = 30.0;
constexpr double kSurfaceWidthMm = 120.0;

DepthDomainKind to_contract_domain(welllog::DepthDomain domain) {
    return domain == welllog::DepthDomain::time ? DepthDomainKind::time
                                                : DepthDomainKind::measured_depth;
}

const welllog::RgbaColor kCurvePalette[] = {
    {0x1f, 0x77, 0xb4, 0xff}, // blue
    {0xd6, 0x27, 0x28, 0xff}, // red
    {0x2c, 0xa0, 0x2c, 0xff}, // green
    {0x94, 0x46, 0xbd, 0xff}, // purple
    {0xff, 0x7f, 0x0e, 0xff}, // orange
};

} // namespace

struct WellLogHostWidget::State {
    std::shared_ptr<welllog::WellLogSession> session;
    welllog::WellLogView* view{nullptr}; // Qt child of the host widget
    SelectionCallback selection_callback;
    bool has_document{false};
    std::uint64_t revision{0};
    std::string document_id_text_value;
    std::string axis_unit;
    DepthDomainKind axis_domain{DepthDomainKind::measured_depth};
    EntityId document_id;
    EntityId axis_id;
    std::size_t diagnostics{0};
    // Shared guard so view signals firing late in shutdown cannot reach a
    // destroyed State through the captured raw pointer.
    std::shared_ptr<bool> alive = std::make_shared<bool>(true);

    ~State() { *alive = false; }
};

WellLogHostWidget::WellLogHostWidget(QWidget* parent) : QWidget(parent) {
    state_ = std::make_unique<State>();
    state_->session = std::make_shared<welllog::WellLogSession>();
    // Surface format must be requested before the first GL context exists.
    welllog::configure_well_log_surface_format();
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    state_->view = new welllog::WellLogView(state_->session, this);
    layout->addWidget(state_->view);

    const std::weak_ptr<bool> alive = state_->alive;
    QObject::connect(state_->view, &welllog::WellLogView::selectionChanged, this,
                     [this, alive]() {
                         const auto guard = alive.lock();
                         if (!guard || !*guard || state_->view == nullptr) {
                             return;
                         }
                         const std::optional<welllog::SelectionState> selection =
                             state_->view->selection();
                         if (!selection.has_value() || !selection->valid) {
                             return;
                         }
                         if (state_->selection_callback == nullptr) {
                             return;
                         }
                         SelectionEventV1 event;
                         event.document_id = state_->document_id_text_value;
                         event.origin = "pwb.viz.well_log_host";
                         event.revision = selection->document_revision.value;
                         event.domain = state_->axis_domain;
                         event.range.top = selection->reference_depth_range.top;
                         event.range.bottom = selection->reference_depth_range.bottom;
                         event.range.unit = state_->axis_unit;
                         state_->selection_callback(event);
                     });
}

WellLogHostWidget::~WellLogHostWidget() {
    // Explicit teardown order: the view (GL context) goes first, then the
    // session state; the callback guard makes any late signal a no-op.
    if (state_ != nullptr && state_->view != nullptr) {
        state_->view->setParent(nullptr);
        delete state_->view;
        state_->view = nullptr;
    }
}

bool WellLogHostWidget::load_las(const QString& path, QString* error) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        if (error != nullptr) {
            *error = QStringLiteral("cannot open ") + path;
        }
        return false;
    }
    const QByteArray raw = file.readAll();
    const std::string text(raw.constData(), static_cast<std::size_t>(raw.size()));

    welllog::BufferSourceReference source;
    source.uri = path.toStdString();
    const auto parsed = welllog::LasSourceAdapter::parse(text, source);
    if (!parsed.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("LAS parse failed (engine error)");
        }
        return false;
    }
    welllog::WellLogDocument document = std::move(parsed.value().document);
    state_->diagnostics = parsed.value().diagnostics.size();

    if (document.sampling_axes().empty() || document.curves().empty()) {
        if (error != nullptr) {
            *error = QStringLiteral("LAS has no sampling axis or no curves");
        }
        return false;
    }
    const welllog::SamplingAxis& axis = document.sampling_axes().front();
    const std::uint64_t axis_length = axis.coordinates.length();
    if (axis_length < 2) {
        if (error != nullptr) {
            *error = QStringLiteral("sampling axis has fewer than two samples");
        }
        return false;
    }
    const auto first = axis.coordinates.value_as_double(0);
    const auto last = axis.coordinates.value_as_double(axis_length - 1);
    if (!first.has_value() || !last.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("sampling axis coordinates unreadable");
        }
        return false;
    }
    const double top = std::min(*first, *last);
    const double bottom = std::max(*first, *last);

    // One track per curve, linear scale from the curve's finite value range.
    welllog::ScenePresentationBuilder presentation(
        document.id(),
        welllog::ReferenceDepthRange{axis.domain, axis.unit, top, bottom},
        welllog::Millimetres{kSurfaceWidthMm}, "pwb-science-host-v1");
    int palette_index = 0;
    for (const welllog::Curve& curve : document.curves()) {
        double value_min = 0.0;
        double value_max = 1.0;
        bool have_finite = false;
        for (std::uint64_t i = 0; i < curve.values.length(); ++i) {
            const auto value = curve.values.value_as_double(i);
            if (!value.has_value() || !std::isfinite(*value)) {
                continue;
            }
            if (!have_finite) {
                value_min = value_max = *value;
                have_finite = true;
            } else {
                value_min = std::min(value_min, *value);
                value_max = std::max(value_max, *value);
            }
        }
        if (!have_finite || !(value_min < value_max)) {
            value_min = 0.0;
            value_max = 1.0; // degenerate curves get a neutral scale
        }
        const EntityId track_id = EntityId::generate();
        const EntityId scale_id = EntityId::generate();
        const EntityId layer_id = EntityId::generate();
        presentation.add_track(
            welllog::TrackSpec{.id = track_id,
                               .width = welllog::Millimetres{kTrackWidthMm},
                               .z_order = palette_index});
        presentation.add_scale(welllog::TrackScaleSpec{
            .id = scale_id,
            .track_id = track_id,
            .mode = welllog::ScaleMode::linear,
            .minimum = value_min,
            .maximum = value_max,
            .direction = welllog::ScaleDirection::left_to_right,
            .unit = curve.unit});
        presentation.add_curve_layer(welllog::CurveLayerSpec{
            .id = layer_id,
            .track_id = track_id,
            .curve_id = curve.id,
            .scale_id = scale_id,
            .color = kCurvePalette[palette_index % 5],
            .line_width = welllog::Millimetres{0.4},
            .z_order = palette_index});
        ++palette_index;
    }

    state_->document_id = document.id();
    state_->axis_id = axis.id;
    state_->revision = document.revision().value;
    state_->document_id_text_value = document.id().to_string();
    state_->axis_unit = axis.unit;
    state_->axis_domain = to_contract_domain(axis.domain);

    const auto document_ok =
        state_->session->execute(welllog::SetDocumentCommand{std::move(document)});
    if (!document_ok.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("SetDocumentCommand rejected by engine");
        }
        return false;
    }
    const auto presentation_ok =
        state_->session->execute(welllog::SetPresentationCommand{presentation.build()});
    if (!presentation_ok.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("SetPresentationCommand rejected by engine");
        }
        return false;
    }
    state_->view->set_document_id(state_->document_id);
    state_->has_document = true;
    return true;
}

void WellLogHostWidget::set_selection_callback(SelectionCallback callback) {
    state_->selection_callback = std::move(callback);
}

bool WellLogHostWidget::select_depth_range(double top, double bottom) {
    if (!state_->has_document || !(top <= bottom)) {
        return false;
    }
    state_->view->set_selection(state_->axis_id, welllog::SelectionDepthRange{top, bottom});
    return true;
}

void WellLogHostWidget::clear_selection() {
    if (state_->has_document) {
        state_->view->clear_selection();
    }
}

void WellLogHostWidget::reset_viewport() {
    state_->view->reset_viewport();
}

welllog::WellLogView* WellLogHostWidget::view() const noexcept { return state_->view; }

welllog::WellLogSession* WellLogHostWidget::session() const noexcept {
    return state_->session.get();
}

bool WellLogHostWidget::has_document() const noexcept { return state_->has_document; }

QString WellLogHostWidget::document_id_text() const {
    return QString::fromStdString(state_->document_id_text_value);
}

std::uint64_t WellLogHostWidget::document_revision() const noexcept {
    return state_->revision;
}

std::size_t WellLogHostWidget::last_load_diagnostics() const noexcept {
    return state_->diagnostics;
}

} // namespace pwb::viz
