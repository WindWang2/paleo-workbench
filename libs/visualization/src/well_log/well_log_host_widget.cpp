#include <pwb/viz/well_log_host_widget.hpp>

#include <QCursor>
#include <QFile>
#include <QImage>
#include <QToolTip>
#include <QString>
#include <QVBoxLayout>

#include <welllog/core/document.hpp>
#include <welllog/core/result.hpp>
#include <welllog/core/units.hpp>
#include <welllog/export/pdf.hpp>
#include <welllog/export/pdf_scene.hpp>
#include <welllog/export/pagination.hpp>
#include <welllog/export/svg.hpp>
#include <welllog/io/las.hpp>
#include <welllog/qtwidgets/well_log_view.hpp>
#include <welllog/scene/scene.hpp>
#include <welllog/session/session.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <utility>
#include <vector>

namespace pwb::viz {

using welllog::EntityId;

namespace {

constexpr double kTrackWidthMm = 30.0;
constexpr double kCurveTrackWidthMm = 40.0;
constexpr double kIntervalTrackWidthMm = 24.0;
constexpr double kSurfaceWidthMm = 120.0;
constexpr double kTrackHeaderHeightMm = 8.0;
constexpr const char* kFontFingerprint = "pwb-native-host-v1";

// The engine's DepthDomain has no time member: TIME-indexed logs surface as
// source_index with a time unit. The v1 contract distinguishes only depth
// vs time, so depth-family domains collapse to measured_depth and
// source_index maps by unit.
DepthDomainKind to_contract_domain(welllog::DepthDomain domain, const std::string& unit) {
    switch (domain) {
    case welllog::DepthDomain::measured_depth:
    case welllog::DepthDomain::true_vertical_depth:
    case welllog::DepthDomain::true_vertical_depth_subsea:
        return DepthDomainKind::measured_depth;
    case welllog::DepthDomain::source_index:
        return (unit == "ms" || unit == "s" || unit == "us") ? DepthDomainKind::time
                                                             : DepthDomainKind::measured_depth;
    }
    return DepthDomainKind::measured_depth;
}

const welllog::RgbaColor kCurvePalette[] = {
    {0x1f, 0x77, 0xb4, 0xff}, // blue
    {0xd6, 0x27, 0x28, 0xff}, // red
    {0x2c, 0xa0, 0x2c, 0xff}, // green
    {0x94, 0x46, 0xbd, 0xff}, // purple
    {0xff, 0x7f, 0x0e, 0xff}, // orange
};

welllog::RgbaColor palette_color(std::size_t index) {
    return kCurvePalette[index % (sizeof(kCurvePalette) / sizeof(kCurvePalette[0]))];
}

std::optional<welllog::RgbaColor> parse_hex_color(const std::string& hex) {
    if (hex.size() != 7 || hex.front() != '#') {
        return std::nullopt;
    }
    const auto nibble = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    const int r1 = nibble(hex[1]), r0 = nibble(hex[2]);
    const int g1 = nibble(hex[3]), g0 = nibble(hex[4]);
    const int b1 = nibble(hex[5]), b0 = nibble(hex[6]);
    if (r1 < 0 || r0 < 0 || g1 < 0 || g0 < 0 || b1 < 0 || b0 < 0) {
        return std::nullopt;
    }
    return welllog::RgbaColor{static_cast<std::uint8_t>(r1 * 16 + r0),
                              static_cast<std::uint8_t>(g1 * 16 + g0),
                              static_cast<std::uint8_t>(b1 * 16 + b0), 0xff};
}

std::string lowercase(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}

std::string uppercase(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(),
                   [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return text;
}

welllog::MarkerSemantic marker_semantic_from(const std::string& semantic) {
    if (semantic == "fault") {
        return welllog::MarkerSemantic::fault;
    }
    if (semantic == "shoe") {
        return welllog::MarkerSemantic::casing_shoe;
    }
    if (semantic == "fluid_contact") {
        return welllog::MarkerSemantic::fluid_contact;
    }
    return welllog::MarkerSemantic::formation_top;
}

// Builds the in-memory engine document from an adapted plan: private axis +
// curve per submission (zero-copy shared buffers), intervals and markers as
// document entities. Returns false with *error on cancellation.
bool build_document(const EngineLoadPlan& plan,
                    const std::atomic_bool* cancel,
                    welllog::WellLogDocument& out,
                    EntityId& out_axis_id,
                    QString* error) {
    const auto* main_curve = plan.primary();
    if (main_curve == nullptr) {
        if (error != nullptr) {
            *error = QStringLiteral("engine load plan has no submittable curves");
        }
        return false;
    }
    const auto document_id_opt = EntityId::parse(plan.document_id().value_or(""));
    if (!document_id_opt.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("plan document id is not a valid EntityId");
        }
        return false;
    }
    welllog::WellLogDocumentBuilder builder(*document_id_opt,
                                            welllog::DocumentRevision{1});
    EntityId first_axis_id{};
    bool have_first_axis = false;
    for (const auto& curve : plan.curves) {
        if (cancel != nullptr && cancel->load()) {
            if (error != nullptr) {
                *error = QStringLiteral("cancelled");
            }
            return false;
        }
        auto axis_id = EntityId::parse(curve.axis_id);
        auto curve_id = EntityId::parse(curve.curve_id);
        if (!axis_id.has_value() || !curve_id.has_value()) {
            continue; // defensive: ids come from our own uuid5 encoder
        }
        welllog::SamplingAxis axis;
        axis.id = *axis_id;
        axis.coordinates = welllog::BufferView::from_vector(curve.depth);
        axis.domain = welllog::DepthDomain::measured_depth;
        axis.unit = curve.depth_unit;
        // The engine validates direction against the coordinates: declare
        // what the buffer actually does (descending LAS curves are normal).
        if (curve.depth != nullptr && curve.depth->size() >= 2 &&
            curve.depth->back() < curve.depth->front()) {
            axis.direction = welllog::AxisDirection::decreasing;
        }
        builder.add_sampling_axis(axis);
        if (!have_first_axis) {
            first_axis_id = *axis_id;
            have_first_axis = true;
        }
        welllog::Curve entity;
        entity.id = *curve_id;
        entity.mnemonic = curve.mnemonic;
        entity.display_name = curve.mnemonic;
        entity.unit = curve.value_unit;
        entity.sampling_axis_id = *axis_id;
        entity.values = welllog::BufferView::from_vector(curve.values);
        builder.add_curve(entity);
    }
    for (const auto& interval : plan.intervals) {
        auto id = EntityId::parse(interval.interval_id);
        if (!id.has_value()) {
            continue;
        }
        welllog::Interval entity;
        entity.id = *id;
        entity.top_reference_depth = interval.top;
        entity.bottom_reference_depth = interval.bottom;
        entity.semantic = interval.semantic == "lithology"
                              ? welllog::IntervalSemantic::lithology
                              : welllog::IntervalSemantic::facies;
        entity.label = interval.label;
        if (const auto color = parse_hex_color(interval.fill_color);
            color.has_value()) {
            entity.fill_color = *color;
        }
        builder.add_interval(entity);
    }
    for (const auto& marker : plan.markers) {
        auto id = EntityId::parse(marker.marker_id);
        if (!id.has_value()) {
            continue;
        }
        welllog::Marker entity;
        entity.id = *id;
        entity.reference_depth = marker.depth;
        entity.semantic = marker_semantic_from(marker.semantic);
        entity.label = marker.label;
        builder.add_marker(entity);
    }
    out = builder.build();
    out_axis_id = first_axis_id;
    return true;
}

// Shared presentation builder: interval tracks first (one per present
// semantic), then one track per visible layout group; every curve layer gets
// its own scale (log per layout override or the RT/RXO mnemonic default with
// a 1e-10 floor), and every curve track renders document markers (tops).
welllog::ScenePresentation
build_presentation(const EngineLoadPlan& plan,
                   const WellLogTrackLayout& layout,
                   const EntityId& document_id,
                   const welllog::SamplingAxis& axis,
                   std::size_t& out_track_count,
                   std::vector<std::string>& diagnostics) {
    auto envelope = submit_depth_envelope(plan);
    if (!envelope.has_value()) {
        // No curve survived adaptation: build a degenerate presentation only
        // when callers still request one (they normally reject earlier).
        envelope = std::make_pair(plan.top_depth, plan.bottom_depth);
    }
    welllog::ScenePresentationBuilder presentation(
        document_id,
        welllog::ReferenceDepthRange{axis.domain, axis.unit, envelope->first,
                                     envelope->second},
        welllog::Millimetres{kSurfaceWidthMm}, kFontFingerprint);

    // Mnemonic → per-key curve lookup for layout overrides.
    std::vector<const EngineCurveSubmission*> curve_by_key(layout.curve_keys.size(),
                                                           nullptr);
    for (std::size_t i = 0; i < plan.curves.size(); ++i) {
        const auto& curve = plan.curves[i];
        const auto key = curve_key_for(i, curve.mnemonic);
        for (std::size_t k = 0; k < layout.curve_keys.size(); ++k) {
            if (layout.curve_keys[k] == key) {
                curve_by_key[k] = &curve;
            }
        }
    }

    std::size_t z_order = 0;
    bool has_lithology = false;
    bool has_facies = false;
    for (const auto& interval : plan.intervals) {
        if (interval.semantic == "lithology") has_lithology = true;
        if (interval.semantic == "facies") has_facies = true;
    }
    const auto add_interval_track = [&](const char* semantic) {
        const EntityId track_id = EntityId::generate();
        presentation.add_track(welllog::TrackSpec{
            .id = track_id,
            .width = welllog::Millimetres{kIntervalTrackWidthMm},
            .z_order = static_cast<std::int32_t>(z_order++)});
        presentation.add_interval_layer(welllog::IntervalLayerSpec{
            .id = EntityId::generate(),
            .track_id = track_id,
            .z_order = 0,
            .semantic_filter = semantic == std::string("lithology")
                                   ? welllog::IntervalSemantic::lithology
                                   : welllog::IntervalSemantic::facies});
        ++out_track_count;
    };
    if (has_lithology) {
        add_interval_track("lithology");
    }
    if (has_facies) {
        add_interval_track("facies");
    }

    for (const auto& group : layout.groups) {
        struct GroupMember {
            const EngineCurveSubmission* curve;
            EntityId curve_id;
        };
        std::vector<GroupMember> members;
        for (const auto& key : group) {
            for (std::size_t k = 0; k < layout.curve_keys.size(); ++k) {
                if (layout.curve_keys[k] == key && layout.visible[k] &&
                    curve_by_key[k] != nullptr) {
                    auto parsed = EntityId::parse(curve_by_key[k]->curve_id);
                    if (parsed.has_value()) {
                        members.push_back({curve_by_key[k], *parsed});
                    }
                }
            }
        }
        if (members.empty()) {
            continue;
        }
        const EntityId track_id = EntityId::generate();
        presentation.add_track(welllog::TrackSpec{
            .id = track_id,
            .width = welllog::Millimetres{group.size() > 1 ? kCurveTrackWidthMm + 10.0
                                                           : kCurveTrackWidthMm},
            .z_order = static_cast<std::int32_t>(z_order++),
            .header = welllog::TrackHeaderSpec{
                .height = welllog::Millimetres{kTrackHeaderHeightMm}}});
        for (std::size_t m = 0; m < members.size(); ++m) {
            const auto& curve = *members[m].curve;
            double lower = curve.display_range.first;
            double upper = curve.display_range.second;
            if (!(upper > lower)) {
                upper = lower + 1.0;
            }
            // Layout override wins; otherwise the mnemonic default (RT/RXO).
            std::optional<TrackScaleMode> mode_override;
            std::string color_override;
            for (std::size_t k = 0; k < layout.curve_keys.size(); ++k) {
                if (curve_by_key[k] == &curve) {
                    mode_override = layout.scale_mode[k];
                    color_override = layout.color[k];
                    break;
                }
            }
            bool is_log = false;
            if (mode_override.has_value()) {
                is_log = *mode_override == TrackScaleMode::logarithmic;
            } else {
                const std::string folded = uppercase(curve.mnemonic);
                is_log = folded == "RT" || folded == "RXO";
            }
            if (is_log) {
                bool has_positive = false;
                if (curve.values != nullptr) {
                    for (const double value : *curve.values) {
                        if (value > 0.0 && std::isfinite(value)) {
                            has_positive = true;
                            break;
                        }
                    }
                }
                if (has_positive) {
                    lower = std::max(lower, 1e-10);
                } else {
                    is_log = false;
                    diagnostics.push_back("log_scale_fallback:" + curve.mnemonic);
                }
            }
            const EntityId scale_id = EntityId::generate();
            const EntityId layer_id = EntityId::generate();
            presentation.add_scale(welllog::TrackScaleSpec{
                .id = scale_id,
                .track_id = track_id,
                .mode = is_log ? welllog::ScaleMode::logarithmic
                               : welllog::ScaleMode::linear,
                .minimum = lower,
                .maximum = upper,
                .direction = welllog::ScaleDirection::left_to_right,
                .unit = curve.value_unit});
            welllog::RgbaColor color = palette_color(members.size() > 1 ? m : 0);
            if (!color_override.empty()) {
                if (const auto parsed = parse_hex_color(color_override);
                    parsed.has_value()) {
                    color = *parsed;
                }
            } else if (!curve.color.empty()) {
                if (const auto parsed = parse_hex_color(curve.color);
                    parsed.has_value()) {
                    color = *parsed;
                }
            }
            presentation.add_curve_layer(welllog::CurveLayerSpec{
                .id = layer_id,
                .track_id = track_id,
                .curve_id = members[m].curve_id,
                .scale_id = scale_id,
                .color = color,
                .line_width = welllog::Millimetres{0.4},
                .z_order = static_cast<std::int32_t>(m)});
        }
        // Tops ride on every curve track (zero-thickness labelled lines).
        if (!plan.markers.empty()) {
            presentation.add_marker_layer(welllog::MarkerLayerSpec{
                .id = EntityId::generate(),
                .track_id = track_id,
                .z_order = 90,
                .draw_symbols = true});
        }
        ++out_track_count;
    }
    return presentation.build();
}

bool write_text_file(const std::filesystem::path& path, std::string_view text,
                     QString* error) {
    std::ofstream stream(path, std::ios::binary | std::ios::trunc);
    if (!stream.good()) {
        if (error != nullptr) {
            *error = QStringLiteral("cannot open output file");
        }
        return false;
    }
    stream.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!stream.good()) {
        if (error != nullptr) {
            *error = QStringLiteral("write failed");
        }
        return false;
    }
    return true;
}

} // namespace

struct WellLogHostWidget::State {
    std::shared_ptr<welllog::WellLogSession> session;
    welllog::WellLogView* view{nullptr}; // Qt child of the host widget
    SelectionCallback selection_callback;
    CursorCallback cursor_callback;
    InterpretationCallback interpretation_callback;
    bool has_document{false};
    std::uint64_t revision{0};
    std::string document_id_text_value;
    std::string axis_unit;
    DepthDomainKind axis_domain{DepthDomainKind::measured_depth};
    // Raw engine tokens, needed to rebuild ReferenceDepthRange when only the
    // presentation changes (apply_track_layout).
    welllog::DepthDomain engine_axis_domain{welllog::DepthDomain::measured_depth};
    std::string engine_axis_unit;
    EntityId document_id;
    EntityId axis_id;
    std::size_t diagnostics{0};
    std::size_t track_count{0};
    WellLogTrackLayout layout;
    EngineLoadPlan plan;
    std::vector<std::string> plan_diagnostics;
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
                         if (state_->selection_callback != nullptr) {
                             SelectionEventV1 event;
                             event.document_id = state_->document_id_text_value;
                             event.origin = "pwb.viz.well_log_host";
                             event.revision = selection->document_revision.value;
                             event.domain = state_->axis_domain;
                             event.range.top = selection->reference_depth_range.top;
                             event.range.bottom =
                                 selection->reference_depth_range.bottom;
                             event.range.unit = state_->axis_unit;
                             state_->selection_callback(event);
                         }
                         // Interpretation hit-test: intervals containing the
                         // selection (most specific first), then markers at or
                         // inside the selection.
                         if (state_->interpretation_callback != nullptr) {
                             const double top = selection->reference_depth_range.top;
                             const double bottom =
                                 selection->reference_depth_range.bottom;
                             const EngineIntervalSubmission* best = nullptr;
                             for (const auto& interval : state_->plan.intervals) {
                                 if (interval.top <= top && bottom <= interval.bottom &&
                                     (best == nullptr ||
                                      (interval.bottom - interval.top) <
                                          (best->bottom - best->top))) {
                                     best = &interval;
                                 }
                             }
                             if (best != nullptr) {
                                 WellLogInterpretationEvent event;
                                 event.kind = WellLogInterpretationEvent::Kind::
                                     interval_selected;
                                 event.document_id = state_->document_id_text_value;
                                 event.semantic = best->semantic;
                                 event.label = best->label;
                                 event.top = best->top;
                                 event.bottom = best->bottom;
                                 event.unit = state_->axis_unit;
                                 state_->interpretation_callback(event);
                             } else {
                                 for (const auto& marker : state_->plan.markers) {
                                     if (top - 1e-9 <= marker.depth &&
                                         marker.depth <= bottom + 1e-9) {
                                         WellLogInterpretationEvent event;
                                         event.kind =
                                             WellLogInterpretationEvent::Kind::
                                                 marker_hit;
                                         event.document_id =
                                             state_->document_id_text_value;
                                         event.semantic = marker.semantic;
                                         event.label = marker.label;
                                         event.top = marker.depth;
                                         event.bottom = marker.depth;
                                         event.unit = state_->axis_unit;
                                         state_->interpretation_callback(event);
                                         break;
                                     }
                                 }
                             }
                         }
                     });
    QObject::connect(state_->view, &welllog::WellLogView::crosshairChanged, this,
                     [this, alive]() {
                         const auto guard = alive.lock();
                         if (!guard || !*guard || state_->view == nullptr) {
                             return;
                         }
                         if (state_->cursor_callback == nullptr) {
                             return;
                         }
                         const auto crosshair = state_->session->crosshair(
                             state_->document_id);
                         WellLogCursorEvent event;
                         event.document_id = state_->document_id_text_value;
                         event.unit = state_->axis_unit;
                         if (crosshair.has_value()) {
                             // No depth transform is installed by this host,
                             // so display depth equals reference depth.
                             event.depth = crosshair->display_depth;
                             event.valid = true;
                         }
                         state_->cursor_callback(event);
                     });
    QObject::connect(state_->view, &welllog::WellLogView::hoverChanged, this,
                     [this, alive]() {
                         const auto guard = alive.lock();
                         if (!guard || !*guard || state_->view == nullptr) {
                             return;
                         }
                         const auto pick = state_->view->hover_pick();
                         if (!pick.has_value()) {
                             QToolTip::hideText();
                             return;
                         }
                         std::string mnemonic;
                         for (const auto& curve : state_->plan.curves) {
                             auto id = EntityId::parse(curve.curve_id);
                             if (id.has_value() && *id == pick->curve_id) {
                                 mnemonic = curve.mnemonic;
                                 break;
                             }
                         }
                         QString label;
                         if (!mnemonic.empty()) {
                             label = QStringLiteral("%1 = %2 @ %3 %4")
                                         .arg(QString::fromStdString(mnemonic))
                                         .arg(pick->value)
                                         .arg(pick->reference_depth)
                                         .arg(QString::fromStdString(
                                             state_->axis_unit));
                         } else {
                             label = QStringLiteral("%1 %2")
                                         .arg(pick->reference_depth)
                                         .arg(QString::fromStdString(
                                             state_->axis_unit));
                         }
                         QToolTip::showText(QCursor::pos(), label, state_->view);
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
    state_->track_count = static_cast<std::size_t>(palette_index);

    // Host state is captured before the document move and applied only
    // after BOTH commands were accepted: a rejected reload leaves the
    // previously loaded document fully intact. The axis unit is
    // canonicalized to lowercase for SelectionEventV1 (the contract
    // vocabulary is "m"/"ms"/...; the engine passes the LAS token through
    // verbatim, e.g. "M").
    const auto presentation_document_id = document.id();
    const auto axis_id = axis.id;
    const auto presentation_revision = document.revision().value;
    auto presentation_document_text = document.id().to_string();
    auto axis_unit = lowercase(axis.unit);
    const auto axis_domain = to_contract_domain(axis.domain, axis.unit);

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

    state_->document_id = presentation_document_id;
    state_->axis_id = axis_id;
    state_->revision = presentation_revision;
    state_->document_id_text_value = std::move(presentation_document_text);
    state_->axis_unit = std::move(axis_unit);
    state_->axis_domain = axis_domain;
    state_->view->set_document_id(state_->document_id);
    state_->has_document = true;
    return true;
}

bool WellLogHostWidget::load_document(const WellLogDocumentInput& input,
                                      const WellLogTrackLayout& saved_layout,
                                      QString* error,
                                      const std::atomic_bool* cancel) {
    if (cancel != nullptr && cancel->load()) {
        if (error != nullptr) {
            *error = QStringLiteral("cancelled");
        }
        return false;
    }
    EngineLoadPlan plan = adapt_well_log_data(input);
    state_->plan_diagnostics = plan.diagnostics;
    const auto envelope = submit_depth_envelope(plan);
    if (!envelope.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("engine load plan has no submittable curves");
        }
        return false;
    }
    welllog::WellLogDocument document;
    EntityId axis_id{};
    if (!build_document(plan, cancel, document, axis_id, error)) {
        return false;
    }
    const auto& axis = document.sampling_axes().front();
    WellLogTrackLayout layout = reconcile_track_layout(
        saved_layout, [&] {
            std::vector<std::string> mnemonics;
            mnemonics.reserve(input.curves.size());
            for (std::size_t i = 0; i < input.curves.size(); ++i) {
                mnemonics.push_back(
                    input.curves[i].mnemonic.empty()
                        ? "CURVE_" + std::to_string(i)
                        : input.curves[i].mnemonic);
            }
            return mnemonics;
        }());

    std::size_t track_count = 0;
    std::vector<std::string> presentation_diagnostics;
    auto presentation = build_presentation(plan, layout, document.id(), axis,
                                           track_count, presentation_diagnostics);
    for (const auto& diagnostic : presentation_diagnostics) {
        plan.diagnostics.push_back(diagnostic);
    }
    state_->plan_diagnostics = plan.diagnostics;

    const auto presentation_document_id = document.id();
    const auto presentation_revision = document.revision().value;
    auto presentation_document_text = document.id().to_string();
    auto axis_unit = lowercase(axis.unit);
    const auto axis_domain = to_contract_domain(axis.domain, axis.unit);

    const auto document_ok =
        state_->session->execute(welllog::SetDocumentCommand{std::move(document)});
    if (!document_ok.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("SetDocumentCommand rejected by engine");
        }
        return false;
    }
    if (cancel != nullptr && cancel->load()) {
        if (error != nullptr) {
            *error = QStringLiteral("cancelled");
        }
        return false;
    }
    const auto presentation_ok =
        state_->session->execute(welllog::SetPresentationCommand{std::move(presentation)});
    if (!presentation_ok.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("SetPresentationCommand rejected by engine");
        }
        return false;
    }

    state_->document_id = presentation_document_id;
    state_->axis_id = axis_id;
    state_->revision = presentation_revision;
    state_->document_id_text_value = std::move(presentation_document_text);
    state_->axis_unit = std::move(axis_unit);
    state_->axis_domain = axis_domain;
    state_->engine_axis_domain = axis.domain;
    state_->engine_axis_unit = axis.unit;
    state_->layout = std::move(layout);
    state_->plan = std::move(plan);
    state_->track_count = track_count;
    state_->view->set_document_id(state_->document_id);
    state_->has_document = true;
    return true;
}

bool WellLogHostWidget::load_from_source(WellLogCurveSource& source,
                                         const WellLogTrackLayout& saved_layout,
                                         QString* error,
                                         const std::atomic_bool* cancel) {
    static const auto kNeverCancelled = std::atomic_bool{false};
    const std::atomic_bool& token =
        cancel != nullptr ? *cancel : kNeverCancelled;
    if (token.load()) {
        if (error != nullptr) {
            *error = QStringLiteral("cancelled");
        }
        return false;
    }
    WellLogDocumentInput input;
    input.well_name = source.well_name();
    input.depth_unit = source.depth_unit();
    const auto envelope = source.depth_envelope();
    input.top_depth = envelope.first;
    input.bottom_depth = envelope.second;
    input.curves.reserve(source.curve_count());
    for (std::size_t i = 0; i < source.curve_count(); ++i) {
        if (token.load()) {
            if (error != nullptr) {
                *error = QStringLiteral("cancelled");
            }
            return false;
        }
        input.curves.push_back(source.load_curve(i, token));
    }
    return load_document(input, saved_layout, error, cancel);
}

bool WellLogHostWidget::apply_track_layout(const WellLogTrackLayout& layout,
                                           QString* error) {
    if (!state_->has_document) {
        if (error != nullptr) {
            *error = QStringLiteral("no document loaded");
        }
        return false;
    }
    const auto* main_curve = state_->plan.primary();
    if (main_curve == nullptr) {
        if (error != nullptr) {
            *error = QStringLiteral("no adapted plan for current document");
        }
        return false;
    }
    auto envelope = submit_depth_envelope(state_->plan);
    if (!envelope.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("no depth envelope for current document");
        }
        return false;
    }
    // A stub axis carries only the reference metadata the presentation
    // builder reads (domain, unit and the depth envelope); the document
    // itself is untouched by SetPresentationCommand.
    welllog::SamplingAxis axis;
    axis.id = state_->axis_id;
    axis.domain = state_->engine_axis_domain;
    axis.unit = state_->engine_axis_unit;
    std::size_t track_count = 0;
    std::vector<std::string> diagnostics;
    auto presentation = build_presentation(state_->plan, layout,
                                           state_->document_id, axis,
                                           track_count, diagnostics);
    const auto presentation_ok = state_->session->execute(
        welllog::SetPresentationCommand{std::move(presentation)});
    if (!presentation_ok.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("SetPresentationCommand rejected by engine");
        }
        return false;
    }
    state_->layout = layout;
    state_->track_count = track_count;
    for (const auto& diagnostic : diagnostics) {
        state_->plan_diagnostics.push_back(diagnostic);
    }
    return true;
}

WellLogTrackLayout WellLogHostWidget::track_layout() const {
    return state_->layout;
}

void WellLogHostWidget::set_selection_callback(SelectionCallback callback) {
    state_->selection_callback = std::move(callback);
}

void WellLogHostWidget::set_cursor_callback(CursorCallback callback) {
    state_->cursor_callback = std::move(callback);
}

bool WellLogHostWidget::set_depth_cursor(double depth) {
    if (!state_->has_document) {
        return false;
    }
    return state_->session
        ->execute(welllog::SetCrosshairCommand{
            state_->document_id,
            welllog::CrosshairState{0.5, depth}})
        .has_value();
}

void WellLogHostWidget::clear_depth_cursor() {
    if (state_->has_document) {
        (void)state_->session->execute(
            welllog::SetCrosshairCommand{state_->document_id, std::nullopt});
    }
}

std::optional<double> WellLogHostWidget::cursor_depth() const {
    if (!state_->has_document) {
        return std::nullopt;
    }
    const auto crosshair = state_->session->crosshair(state_->document_id);
    if (!crosshair.has_value()) {
        return std::nullopt;
    }
    return crosshair->display_depth;
}

void WellLogHostWidget::set_interpretation_callback(
    InterpretationCallback callback) {
    state_->interpretation_callback = std::move(callback);
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

bool WellLogHostWidget::zoom_at_depth(double anchor_depth, double span_factor) {
    if (!state_->has_document || !(span_factor > 0.0)) {
        return false;
    }
    return state_->session
        ->execute(welllog::ZoomDepthAtCommand{state_->document_id,
                                              anchor_depth, span_factor})
        .has_value();
}

bool WellLogHostWidget::pan_depth(double display_depth_delta) {
    if (!state_->has_document) {
        return false;
    }
    return state_->session
        ->execute(welllog::PanDepthCommand{state_->document_id,
                                           display_depth_delta})
        .has_value();
}

std::optional<std::pair<double, double>>
WellLogHostWidget::depth_viewport() const {
    if (!state_->has_document) {
        return std::nullopt;
    }
    const auto viewport = state_->session->viewport(state_->document_id);
    if (!viewport.has_value()) {
        return std::nullopt;
    }
    return std::make_pair(viewport->top, viewport->bottom);
}

bool WellLogHostWidget::export_png(const QString& path, QString* error) {
    if (!state_->has_document) {
        if (error != nullptr) {
            *error = QStringLiteral("no document loaded");
        }
        return false;
    }
    const QImage grabbed = state_->view->grabFramebuffer();
    if (grabbed.isNull() || grabbed.width() == 0 || grabbed.height() == 0) {
        if (error != nullptr) {
            *error = QStringLiteral("framebuffer is empty");
        }
        return false;
    }
    if (!grabbed.save(path, "PNG")) {
        if (error != nullptr) {
            *error = QStringLiteral("PNG save failed");
        }
        return false;
    }
    return true;
}

bool WellLogHostWidget::export_svg(const QString& path, QString* error) {
    if (!state_->has_document) {
        if (error != nullptr) {
            *error = QStringLiteral("no document loaded");
        }
        return false;
    }
    auto scene = state_->session->prepare_for_export(state_->document_id, 2048);
    if (!scene.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("scene prepare failed");
        }
        return false;
    }
    const auto svg = welllog::SvgExporter::write(scene.value());
    if (!svg.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("SVG export rejected by engine");
        }
        return false;
    }
    return write_text_file(std::filesystem::path(path.toStdString()),
                           svg.value().text(), error);
}

bool WellLogHostWidget::export_pdf(const QString& path, QString* error) {
    if (!state_->has_document) {
        if (error != nullptr) {
            *error = QStringLiteral("no document loaded");
        }
        return false;
    }
    auto scene = state_->session->prepare_for_export(state_->document_id, 2048);
    if (!scene.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("scene prepare failed");
        }
        return false;
    }
    welllog::ExportSnapshot snapshot;
    snapshot.document_id = state_->document_id;
    snapshot.document_revision = welllog::DocumentRevision{state_->revision};
    snapshot.page.well_name = state_->plan.well_name;
    snapshot.page.show_depth_ruler = true;
    const auto pdf = welllog::PdfSceneExporter::write(scene.value(), snapshot);
    if (!pdf.has_value()) {
        if (error != nullptr) {
            *error = QStringLiteral("PDF export rejected by engine");
        }
        return false;
    }
    return write_text_file(std::filesystem::path(path.toStdString()),
                           pdf.value().bytes(), error);
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

std::size_t WellLogHostWidget::last_track_count() const noexcept {
    return state_->track_count;
}

std::vector<std::string> WellLogHostWidget::last_plan_diagnostics() const {
    return state_->plan_diagnostics;
}

QString WellLogHostWidget::axis_unit_text() const {
    return QString::fromStdString(state_->axis_unit);
}

} // namespace pwb::viz
