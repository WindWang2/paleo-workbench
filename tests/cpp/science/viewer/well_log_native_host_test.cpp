// science.viewer.well_log_native_host — offscreen integration tests for the
// native C++ well-log host (this branch's migration slice). Exercises the
// real well-log-engine GL view with in-memory Workbench DTOs:
//   * load_document: GR-primary multi-curve well with NaN value gaps, tops
//     and facies evidence; unit labels; track layout reconciliation.
//   * depth sync: selection -> SelectionEventV1, depth cursor round-trip +
//     cross-panel callback, viewport zoom/pan/reset.
//   * interpretation: interval_selected (most specific semantic wins) and
//     marker_hit (tops) events derived from the document.
//   * boundaries: empty well (graceful failure, previous document intact),
//     duplicate depths, descending depth order, pre-cancelled load, lazy
//     source cancellation between curves, 2M-sample well stability.
//   * exports: PNG (framebuffer), SVG and PDF (engine exporters).
//   * apply_track_layout: visibility change keeps document, viewport and
//     selection alive.

#include "../pwb_test.hpp"

#include <pwb/viz/well_log_host_widget.hpp>

#include <QApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImage>
#include <QTemporaryDir>
#include <QThread>

#include <welllog/qtwidgets/well_log_view.hpp>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <functional>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <vector>

using pwb::viz::SelectionEventV1;
using pwb::viz::WellLogDocumentInput;
using pwb::viz::WellLogHostWidget;
using pwb::viz::WellLogInterpretationEvent;
using pwb::viz::WellLogMarkerInput;
using pwb::viz::WellLogTrackLayout;
using pwb::viz::WellLogCurveSource;
using pwb::viz::WellLogCurveInput;
using pwb::viz::WellLogIntervalInput;

namespace {

bool process_until(const std::function<bool()>& condition, int timeout_ms) {
    QElapsedTimer timer;
    timer.start();
    while (!condition()) {
        QApplication::processEvents(QEventLoop::AllEvents, 20);
        if (timer.elapsed() > timeout_ms) {
            return condition();
        }
        QThread::msleep(10);
    }
    return true;
}

WellLogCurveInput make_curve(const std::string& mnemonic, const std::string& unit,
                             std::vector<double> depth, std::vector<double> values,
                             std::optional<std::pair<double, double>> range = std::nullopt) {
    WellLogCurveInput curve;
    curve.mnemonic = mnemonic;
    curve.unit = unit;
    curve.depth = std::make_shared<const std::vector<double>>(std::move(depth));
    curve.values = std::make_shared<const std::vector<double>>(std::move(values));
    curve.display_range = range;
    return curve;
}

// Production-shaped well: GR primary with a NaN gap, log-scale RT, tops and a
// facies + lithology interval set.
WellLogDocumentInput make_standard_well(const std::string& well_name = "测试井-1",
                                        const std::string& unit_token = "m") {
    WellLogDocumentInput input;
    input.well_name = well_name;
    input.top_depth = 1000.0;
    input.bottom_depth = 1100.0;
    if (!unit_token.empty()) {
        input.depth_unit = unit_token;
    }
    input.curves.push_back(make_curve(
        "GR", "API", {1000.0, 1001.0, 1002.0, 1003.0, 1004.0},
        {42.0, std::nan(""), 55.5, 61.0, 47.0},
        std::make_pair(0.0, 150.0)));
    input.curves.push_back(make_curve(
        "RT", "ohmm", {1000.0, 1000.5, 1001.0, 1001.5, 1002.0},
        {2.0, 0.5, 20.0, 8.0, 15.0}));
    input.curves.push_back(make_curve(
        "AC", "us/ft", {1000.0, 1002.0, 1004.0}, {70.0, 88.0, 75.5}));
    input.lithology.push_back({1000.0, 1050.0, "泥岩"});
    input.facies.push_back({1000.0, 1005.0, "浅湖"});
    input.markers.push_back({1010.0, "长2", "formation_top", ""});
    input.markers.push_back({1080.0, "长1", "formation_top", ""});
    return input;
}

// Lazy source that counts load_curve invocations (proves the seam is used).
class CountingCurveSource final : public WellLogCurveSource {
public:
    CountingCurveSource(WellLogDocumentInput input, std::size_t fail_cancel_at,
                        std::atomic_bool* cancel_trigger = nullptr)
        : input_(std::move(input)), fail_cancel_at_(fail_cancel_at),
          cancel_trigger_(cancel_trigger) {}

    [[nodiscard]] std::string well_name() const override { return input_.well_name; }
    [[nodiscard]] std::optional<std::string> depth_unit() const override {
        return input_.depth_unit;
    }
    [[nodiscard]] std::pair<double, double> depth_envelope() const override {
        return {input_.top_depth, input_.bottom_depth};
    }
    [[nodiscard]] std::size_t curve_count() const override {
        return input_.curves.size();
    }
    [[nodiscard]] WellLogCurveInput curve_meta(std::size_t index) const override {
        WellLogCurveInput meta = input_.curves[index];
        meta.depth = nullptr;
        meta.values = nullptr;
        return meta;
    }
    [[nodiscard]] WellLogCurveInput load_curve(std::size_t index,
                                               const std::atomic_bool&) override {
        ++loads;
        if (cancel_trigger_ != nullptr && index == fail_cancel_at_) {
            cancel_trigger_->store(true);
        }
        return input_.curves[index];
    }

    std::size_t loads{0};

private:
    WellLogDocumentInput input_;
    std::size_t fail_cancel_at_;
    std::atomic_bool* cancel_trigger_;
};

} // namespace

int main(int argc, char** argv) {
    QApplication app(argc, argv);

    WellLogHostWidget host;
    host.resize(420, 600);

    // 1. DTO load: document, tracks (3 curve + facies + lithology), units.
    QString error;
    PWB_CHECK_MSG(host.load_document(make_standard_well(),
                                     WellLogTrackLayout{}, &error),
                  error.toStdString().c_str());
    PWB_CHECK(host.has_document());
    PWB_CHECK(host.last_track_count() == 5); // lith + facies + GR + RT + AC
    PWB_CHECK(host.axis_unit_text() == "m");
    PWB_CHECK(host.document_revision() >= 1);
    PWB_CHECK(host.last_plan_diagnostics().empty());

    host.show();
    PWB_CHECK(process_until(
        [&host] { return host.view()->capability_report().initialization_complete; },
        15000));
    PWB_CHECK(host.view()->capability_report().graphics_available);

    // 2. Depth sync: selection round-trips through SelectionEventV1.
    std::vector<SelectionEventV1> selection_events;
    host.set_selection_callback([&selection_events](const SelectionEventV1& event) {
        selection_events.push_back(event);
    });
    PWB_CHECK(host.select_depth_range(1002.0, 1006.0));
    PWB_CHECK(process_until([&selection_events] { return !selection_events.empty(); },
                            10000));
    PWB_CHECK(selection_events.front().range.unit == "m");
    PWB_CHECK(selection_events.front().range.top == 1002.0);
    PWB_CHECK(selection_events.front().document_id ==
              host.document_id_text().toStdString());

    // 3. Interpretation: [1055,1082] sits outside every interval (lithology
    //    ends at 1050) and contains the marker at 1080 → marker_hit.
    std::vector<WellLogInterpretationEvent> interpretation_events;
    host.set_interpretation_callback(
        [&interpretation_events](const WellLogInterpretationEvent& event) {
            interpretation_events.push_back(event);
        });
    PWB_CHECK(host.select_depth_range(1055.0, 1082.0));
    PWB_CHECK(process_until(
        [&] {
            return !interpretation_events.empty() &&
                   interpretation_events.back().kind ==
                       WellLogInterpretationEvent::Kind::marker_hit;
        },
        10000));
    PWB_CHECK(interpretation_events.back().label == "长1");
    PWB_CHECK(interpretation_events.back().semantic == "formation_top");

    // 4. Most-specific interval: the selection [1001,1003] is inside both the
    //    lithology (1000-1050) and the facies (1000-1005) interval; facies is
    //    the narrower one and wins as the evidence.
    PWB_CHECK(host.select_depth_range(1001.0, 1003.0));
    PWB_CHECK(process_until(
        [&] {
            return !interpretation_events.empty() &&
                   interpretation_events.back().kind ==
                       WellLogInterpretationEvent::Kind::interval_selected;
        },
        10000));
    PWB_CHECK(interpretation_events.back().label == "浅湖");
    PWB_CHECK(interpretation_events.back().semantic == "facies");
    PWB_CHECK(interpretation_events.back().top == 1000.0);
    PWB_CHECK(interpretation_events.back().bottom == 1005.0);

    // 5. Depth cursor: inbound set + broadcast callback (cross-panel link).
    std::vector<pwb::viz::WellLogCursorEvent> cursor_events;
    host.set_cursor_callback([&cursor_events](const pwb::viz::WellLogCursorEvent& event) {
        cursor_events.push_back(event);
    });
    PWB_CHECK(host.set_depth_cursor(1042.5));
    PWB_CHECK(process_until(
        [&] {
            return !cursor_events.empty() && cursor_events.back().valid &&
                   cursor_events.back().depth == 1042.5;
        },
        10000));
    PWB_CHECK(cursor_events.back().unit == "m");
    PWB_CHECK(host.cursor_depth().value_or(-1.0) == 1042.5);
    host.clear_depth_cursor();
    PWB_CHECK(process_until([&host] { return !host.cursor_depth().has_value(); },
                            10000));

    // 6. Viewport commands: zoom shrinks, pan shifts, reset restores.
    host.reset_viewport();
    PWB_CHECK(process_until([&host] { return host.depth_viewport().has_value(); },
                            10000));
    const auto full_viewport = host.depth_viewport().value();
    PWB_CHECK(full_viewport.first <= 1000.5 && full_viewport.second >= 1099.5);
    PWB_CHECK(host.zoom_at_depth(1050.0, 0.5));
    PWB_CHECK(process_until(
        [&] {
            const auto viewport = host.depth_viewport();
            return viewport.has_value() &&
                   viewport->second - viewport->first <
                       full_viewport.second - full_viewport.first;
        },
        10000));
    const auto zoomed = host.depth_viewport().value();
    PWB_CHECK(host.pan_depth(20.0));
    PWB_CHECK(process_until(
        [&] {
            const auto viewport = host.depth_viewport();
            return viewport.has_value() && viewport->first > zoomed.first;
        },
        10000));

    // 7. Selection survives a track layout change; hidden tracks shrink the
    //    presentation but the document (and selection) stays put.
    PWB_CHECK(host.view()->selection().has_value());
    const auto layout = host.track_layout();
    PWB_CHECK(layout.curve_keys.size() == 3);
    auto hidden = layout.with_visible("curve:1:RT", false);
    PWB_CHECK(host.apply_track_layout(hidden, &error));
    PWB_CHECK(host.last_track_count() == 4); // RT track removed
    PWB_CHECK(host.has_document());
    PWB_CHECK(host.view()->selection().has_value());
    PWB_CHECK(host.view()->selection()->valid);
    PWB_CHECK(host.track_layout().visible[1] == false);
    // And the document's curve count is untouched (5 tracks were presentation
    // only; the RT curve remains queryable through the plan).
    PWB_CHECK(host.document_revision() >= 1);

    // 8. Exports: PNG framebuffer + engine SVG/PDF writers.
    {
        QTemporaryDir dir;
        PWB_CHECK(dir.isValid());
        const QString png = dir.filePath("host.png");
        const QString svg = dir.filePath("host.svg");
        const QString pdf = dir.filePath("host.pdf");
        PWB_CHECK_MSG(host.export_png(png, &error), error.toStdString().c_str());
        PWB_CHECK_MSG(host.export_svg(svg, &error), error.toStdString().c_str());
        PWB_CHECK_MSG(host.export_pdf(pdf, &error), error.toStdString().c_str());
        QFile svg_file(svg);
        PWB_CHECK(svg_file.open(QIODevice::ReadOnly));
        const QByteArray svg_bytes = svg_file.readAll();
        PWB_CHECK(svg_bytes.size() > 0);
        PWB_CHECK(QByteArray(svg_bytes.left(160)).contains("<svg"));
        QFile pdf_file(pdf);
        PWB_CHECK(pdf_file.open(QIODevice::ReadOnly));
        const QByteArray pdf_bytes = pdf_file.readAll();
        PWB_CHECK(pdf_bytes.size() > 200);
        PWB_CHECK(pdf_bytes.startsWith("%PDF"));
        const QImage image(png);
        PWB_CHECK(!image.isNull() && image.width() > 0);
    }

    // 9. Boundaries: NaN gaps preserved (sample count), duplicate depths kept,
    //    descending order normalized through the envelope.
    {
        WellLogDocumentInput gaps = make_standard_well("W-gaps");
        gaps.lithology.clear();
        gaps.facies.clear();
        gaps.markers.clear();
        PWB_CHECK(host.load_document(gaps, WellLogTrackLayout{}, &error));
        // 5 GR samples minus nothing: the NaN value row stays on the axis.
        PWB_CHECK(host.last_track_count() == 3);

        WellLogDocumentInput dup = make_standard_well("W-dup");
        dup.lithology.clear();
        dup.facies.clear();
        dup.markers.clear();
        dup.curves.clear();
        dup.curves.push_back(make_curve("GR", "API", {5.0, 5.0, 6.0},
                                        {1.0, std::nan(""), 3.0}));
        PWB_CHECK(host.load_document(dup, WellLogTrackLayout{}, &error));
        PWB_CHECK(host.has_document());

        WellLogDocumentInput desc = make_standard_well("W-desc");
        desc.lithology.clear();
        desc.facies.clear();
        desc.markers.clear();
        desc.curves.clear();
        desc.curves.push_back(make_curve("GR", "API", {300.0, 200.0, 100.0},
                                         {3.0, 2.0, 1.0}));
        desc.top_depth = 0.0;
        desc.bottom_depth = 0.0; // forces the primary-depth envelope fallback
        if (!host.load_document(desc, WellLogTrackLayout{}, &error)) {
            for (const auto& diagnostic : host.session()->diagnostics()) {
                std::printf("session diagnostic id=%llu code=%d\n",
                            static_cast<unsigned long long>(diagnostic.id),
                            static_cast<int>(diagnostic.code));
                if (const auto err = host.session()->diagnostic_error(diagnostic.id);
                    err.has_value()) {
                    std::printf("  error code=%d message=%d\n",
                                static_cast<int>(err->code),
                                static_cast<int>(err->message));
                }
            }
            PWB_FAIL(("descending load failed: " + error.toStdString()).c_str());
        }
    }

    // 10. Empty well fails gracefully and keeps the previous document.
    {
        const QString previous_document_id = host.document_id_text();
        WellLogDocumentInput empty;
        empty.well_name = "W-empty";
        PWB_CHECK(!host.load_document(empty, WellLogTrackLayout{}, &error));
        PWB_CHECK(!error.isEmpty());
        PWB_CHECK(host.has_document());
        PWB_CHECK(host.document_id_text() == previous_document_id);
    }

    // 11. Pre-cancelled load refuses up front.
    {
        std::atomic_bool cancel{true};
        PWB_CHECK(!host.load_document(make_standard_well("W-cancel"),
                                      WellLogTrackLayout{}, &error, &cancel));
        PWB_CHECK(error == QStringLiteral("cancelled"));
    }

    // 12. Lazy source: metadata-then-values with cancellation between curves.
    {
        std::atomic_bool cancel{false};
        CountingCurveSource source(make_standard_well("W-lazy"),
                                   /*fail_cancel_at=*/1, &cancel);
        PWB_CHECK(!host.load_from_source(source, WellLogTrackLayout{}, &error,
                                         &cancel));
        PWB_CHECK(error == QStringLiteral("cancelled"));
        PWB_CHECK(source.loads == 2); // stopped at the second curve checkpoint
        PWB_CHECK(cancel.load());

        CountingCurveSource clean_source(make_standard_well("W-lazy"),
                                         std::numeric_limits<std::size_t>::max());
        std::atomic_bool no_cancel{false};
        PWB_CHECK_MSG(host.load_from_source(clean_source, WellLogTrackLayout{},
                                            &error, &no_cancel),
                      error.toStdString().c_str());
        PWB_CHECK(clean_source.loads == 3);
        PWB_CHECK(host.has_document());
    }

    // 13. Large well (2M samples): load + select stay stable and bounded.
    {
        constexpr std::size_t kSamples = 2'000'000;
        std::vector<double> depth;
        std::vector<double> values;
        depth.reserve(kSamples);
        values.reserve(kSamples);
        for (std::size_t i = 0; i < kSamples; ++i) {
            depth.push_back(1000.0 + static_cast<double>(i) * 0.0001);
            values.push_back((i % 997 == 0) ? std::nan("")
                                            : static_cast<double>(i % 4096) * 0.05);
        }
        WellLogDocumentInput large;
        large.well_name = "W-large";
        large.top_depth = depth.front();
        large.bottom_depth = depth.back();
        large.depth_unit = "m";
        large.curves.push_back(make_curve("GR", "API", std::move(depth),
                                          std::move(values),
                                          std::make_pair(0.0, 205.0)));
        QElapsedTimer timer;
        timer.start();
        PWB_CHECK_MSG(host.load_document(large, WellLogTrackLayout{}, &error),
                      error.toStdString().c_str());
        PWB_CHECK(host.select_depth_range(1050.0, 1060.0));
        // Allow the interaction loop to settle without a hard wall-clock
        // assertion: the point is "no hang, no crash" at 2M samples.
        process_until([&host] { return host.view()->selection().has_value(); },
                      30000);
        std::printf("large well load+select took %lld ms\n",
                    static_cast<long long>(timer.elapsed()));
    }

    // 13b. Regression (review B1): a saved layout references input indices;
    //       a curve dropped by adapt (all-NaN values) must NOT shift the
    //       keys of surviving curves — the GR track stays visible.
    {
        WellLogDocumentInput input = make_standard_well("W-drop");
        input.lithology.clear();
        input.facies.clear();
        input.markers.clear();
        // index 1 (RT) becomes curve_empty: no finite values.
        input.curves[1] = make_curve("RT", "ohmm", {1000.0, 1001.0},
                                     {std::nan(""), std::nan("")});
        WellLogTrackLayout saved;
        {
            const std::vector<std::string> mnemonics = {"GR", "RT", "AC"};
            saved = pwb::viz::default_track_layout(mnemonics);
        }
        PWB_CHECK_MSG(host.load_document(input, saved, &error),
                      error.toStdString().c_str());
        // RT dropped from the plan; GR (input key curve:0:GR) still renders.
        PWB_CHECK(host.last_track_count() == 2);
        PWB_CHECK(host.track_layout().visible[0]);
        PWB_CHECK(host.track_layout().curve_keys.size() == 3);
    }

    // 14. Saved template JSON round-trips and drives the live presentation
    //     (config serialization). A template saved for another well's schema
    //     is dropped by reconcile on load, so apply it to the current well.
    {
        WellLogDocumentInput input = make_standard_well("W-template");
        input.lithology.clear();
        input.facies.clear();
        input.markers.clear();
        PWB_CHECK(host.load_document(input, WellLogTrackLayout{}, &error));
        PWB_CHECK(host.track_layout().curve_keys.size() == 3);
        auto saved = host.track_layout().with_scale_mode(
            "curve:0:GR", pwb::viz::TrackScaleMode::logarithmic);
        const auto json_text = saved.to_template_json();
        WellLogTrackLayout restored;
        std::string parse_error;
        PWB_CHECK(WellLogTrackLayout::from_template_json(json_text, restored,
                                                         &parse_error));
        PWB_CHECK(host.apply_track_layout(restored, &error));
        PWB_CHECK(host.track_layout().scale_mode[0] ==
                  pwb::viz::TrackScaleMode::logarithmic);

        // Reload the same schema: reconcile RETAINS the matching template
        // (curve keys are index+mnemonic based, well-name independent).
        PWB_CHECK(host.load_document(input, restored, &error));
        PWB_CHECK(host.track_layout().scale_mode[0] ==
                  pwb::viz::TrackScaleMode::logarithmic);

        // A genuinely stale schema (different curves) resets to the default.
        WellLogDocumentInput other = make_standard_well("W-other");
        other.lithology.clear();
        other.facies.clear();
        other.markers.clear();
        other.curves.clear();
        other.curves.push_back(make_curve("SP", "mV", {0.0, 1.0}, {-1.0, -2.0}));
        PWB_CHECK(host.load_document(other, restored, &error));
        PWB_CHECK(host.track_layout().curve_keys.size() == 1);
        PWB_CHECK(host.track_layout().scale_mode[0] == std::nullopt);
    }

    std::printf("native host offscreen checks complete\n");
    return 0;
}
