#include <welllog/qtwidgets/well_log_view.hpp>

#include <QApplication>
#include <QColor>
#include <QImage>
#include <QMouseEvent>
#include <QSignalSpy>
#include <QSurfaceFormat>
#include <QTest>
#include <QVBoxLayout>
#include <QWheelEvent>
#include <QWidget>

#include <cmath>
#include <cstdint>
#include <memory>
#include <string_view>
#include <vector>

namespace {

using namespace welllog;

class WellLogViewTest final : public QObject {
  Q_OBJECT

private slots:
  void native_view_embeds_and_reports_capabilities();
  void prepared_curve_renders_into_the_widget_fbo();
  void pointer_interaction_updates_session_and_semantic_picks();
  void pointer_pan_zoom_and_reset_use_session_commands();
  void widget_rebuild_restores_curve_from_session_cpu_state();
  void top_level_reparent_restores_curve_after_context_recreation();
};

struct PreparedViewFixture {
  EntityId document_id;
  EntityId curve_id;
  std::shared_ptr<WellLogSession> session;
};

EntityId id(std::string_view text) {
  const auto parsed = EntityId::parse(text);
  Q_ASSERT(parsed.has_value());
  return *parsed;
}

PreparedViewFixture prepared_view_fixture() {
  const auto document_id = id("60000000-0000-4000-8000-000000000001");
  const auto axis_id = id("60000000-0000-4000-8000-000000000002");
  const auto curve_id = id("60000000-0000-4000-8000-000000000003");
  const auto track_id = id("60000000-0000-4000-8000-000000000004");
  const auto scale_id = id("60000000-0000-4000-8000-000000000005");
  const auto layer_id = id("60000000-0000-4000-8000-000000000006");
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1000.0, 1050.0, 1100.0});
  auto values = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{0.0, 50.0, 100.0});

  WellLogDocumentBuilder document_builder(document_id, DocumentRevision{1});
  document_builder.add_sampling_axis(SamplingAxis{
      .id = axis_id,
      .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth,
      .unit = "m",
      .direction = AxisDirection::increasing,
  });
  document_builder.add_curve(Curve{
      .id = curve_id,
      .mnemonic = "GR",
      .display_name = "Gamma Ray",
      .unit = "API",
      .sampling_axis_id = axis_id,
      .values = BufferView::from_vector(values),
      .nulls = {},
  });

  auto session = std::make_shared<WellLogSession>();
  Q_ASSERT(session->execute(SetDocumentCommand{document_builder.build()})
               .has_value());
  ScenePresentationBuilder presentation_builder(
      document_id,
      ReferenceDepthRange{
          .domain = DepthDomain::measured_depth,
          .unit = "m",
          .top = 1000.0,
          .bottom = 1100.0,
      },
      Millimetres{100.0}, "font-fixture-v1");
  presentation_builder.add_track(
      TrackSpec{.id = track_id, .width = Millimetres{30.0}, .z_order = 0});
  presentation_builder.add_scale(TrackScaleSpec{
      .id = scale_id,
      .track_id = track_id,
      .mode = ScaleMode::linear,
      .minimum = 0.0,
      .maximum = 100.0,
      .direction = ScaleDirection::left_to_right,
      .unit = "API",
  });
  presentation_builder.add_curve_layer(CurveLayerSpec{
      .id = layer_id,
      .track_id = track_id,
      .curve_id = curve_id,
      .scale_id = scale_id,
      .color = RgbaColor{.red = 0x12, .green = 0x34, .blue = 0x56},
      .line_width = Millimetres{0.5},
      .z_order = 0,
  });
  Q_ASSERT(
      session->execute(SetPresentationCommand{presentation_builder.build()})
          .has_value());
  return PreparedViewFixture{
      .document_id = document_id,
      .curve_id = curve_id,
      .session = std::move(session),
  };
}

void WellLogViewTest::native_view_embeds_and_reports_capabilities() {
  QWidget host;
  auto *layout = new QVBoxLayout(&host);
  auto *view = new WellLogView(&host);
  layout->addWidget(view);
  view->resize(320, 240);

  const auto requested = view->format();
  QCOMPARE(requested.renderableType(), QSurfaceFormat::OpenGL);
  QCOMPARE(requested.profile(), QSurfaceFormat::CoreProfile);
  QVERIFY((requested.version() >= std::pair{3, 3}));
  QVERIFY(requested.stencilBufferSize() >= 8);

  host.resize(320, 240);
  host.show();
  QVERIFY(QTest::qWaitForWindowExposed(&host));
  QTRY_VERIFY_WITH_TIMEOUT(view->capability_report().initialization_complete,
                           5000);

  const auto &report = view->capability_report();
  QVERIFY2(report.graphics_available, report.unavailable_reason.c_str());
  QVERIFY(report.core_profile);
  QVERIFY(report.open_gl_major > 3 ||
          (report.open_gl_major == 3 && report.open_gl_minor >= 3));
  QVERIFY(report.stencil_bits >= 8);
  QVERIFY(!report.vendor.empty());
  QVERIFY(!report.renderer.empty());
  QVERIFY(!report.open_gl_version.empty());
  QVERIFY(!report.glsl_version.empty());
  QCOMPARE(view->parentWidget(), &host);
}

void WellLogViewTest::prepared_curve_renders_into_the_widget_fbo() {
  auto fixture = prepared_view_fixture();
  WellLogView view(fixture.session);
  view.set_document_id(fixture.document_id);
  view.resize(200, 200);
  view.show();
  QVERIFY(QTest::qWaitForWindowExposed(&view));
  QTRY_VERIFY_WITH_TIMEOUT(view.capability_report().initialization_complete,
                           5000);
  QVERIFY2(view.capability_report().graphics_available,
           view.capability_report().unavailable_reason.c_str());

  QImage image;
  QTRY_VERIFY_WITH_TIMEOUT(
      (image = view.grabFramebuffer(),
       image.pixelColor(image.width() / 2, image.height() / 2) !=
           QColor{Qt::white}),
      5000);
  QCOMPARE(image.pixelColor(image.width() - 20, 20), QColor{Qt::white});

  qsizetype curve_pixel_count{};
  for (int top = 0; top < image.height(); ++top) {
    for (int left = 0; left < image.width(); ++left) {
      const auto color = image.pixelColor(left, top);
      if (color.red() < 128 && color.green() < 128 && color.blue() < 160) {
        ++curve_pixel_count;
      }
    }
  }
  QVERIFY(curve_pixel_count >= 200);
  QVERIFY(curve_pixel_count <= 2000);

  view.set_document_id(EntityId{});
  QTRY_COMPARE_WITH_TIMEOUT(
      (image = view.grabFramebuffer(),
       image.pixelColor(image.width() / 2, image.height() / 2)),
      QColor{Qt::white}, 5000);
}

void WellLogViewTest::pointer_interaction_updates_session_and_semantic_picks() {
  auto fixture = prepared_view_fixture();
  WellLogView view(fixture.session);
  view.set_document_id(fixture.document_id);
  view.resize(200, 200);
  QSignalSpy hover_spy(&view, &WellLogView::hoverChanged);
  QSignalSpy click_spy(&view, &WellLogView::curveClicked);
  QSignalSpy crosshair_spy(&view, &WellLogView::crosshairChanged);
  view.show();
  QVERIFY(QTest::qWaitForWindowExposed(&view));
  QTRY_VERIFY_WITH_TIMEOUT(view.capability_report().graphics_available, 5000);

  const auto local_position = QPointF{100.0, 100.0};
  QMouseEvent hover_event(QEvent::MouseMove, local_position,
                          QPointF{view.mapToGlobal(local_position.toPoint())},
                          Qt::NoButton, Qt::NoButton, Qt::NoModifier);
  QApplication::sendEvent(&view, &hover_event);
  QTRY_VERIFY_WITH_TIMEOUT(hover_spy.count() >= 1, 5000);
  QVERIFY(crosshair_spy.count() >= 1);
  const auto crosshair = fixture.session->crosshair(fixture.document_id);
  QVERIFY(crosshair.has_value());
  QVERIFY(std::abs(crosshair->track_fraction - 0.5) < 0.01);
  QVERIFY(std::abs(crosshair->display_depth - 1050.0) < 1.0);

  const auto hover = view.hover_pick();
  QVERIFY(hover.has_value());
  QCOMPARE(hover->curve_id, fixture.curve_id);
  QCOMPARE(hover->sample_index, std::uint64_t{1});
  QVERIFY(std::abs(hover->reference_depth - 1050.0) < 1.0);
  QVERIFY(std::abs(hover->display_depth - 1050.0) < 1.0);
  QVERIFY(std::abs(hover->value - 50.0) < 1.0);
  QVERIFY(hover->distance.value <= 2.0);

  QTest::mouseClick(&view, Qt::LeftButton, Qt::NoModifier, QPoint{100, 100});
  QTRY_COMPARE_WITH_TIMEOUT(click_spy.count(), 1, 5000);
  const auto clicked = view.click_pick();
  QVERIFY(clicked.has_value());
  QCOMPARE(clicked->curve_id, fixture.curve_id);

  const auto image = view.grabFramebuffer();
  const auto center = image.pixelColor(image.width() / 2, image.height() / 2);
  QVERIFY(center.red() > center.green() * 2);
}

void WellLogViewTest::pointer_pan_zoom_and_reset_use_session_commands() {
  auto fixture = prepared_view_fixture();
  WellLogView view(fixture.session);
  view.set_document_id(fixture.document_id);
  view.resize(200, 200);
  QSignalSpy viewport_spy(&view, &WellLogView::viewportChanged);
  view.show();
  QVERIFY(QTest::qWaitForWindowExposed(&view));
  QTRY_VERIFY_WITH_TIMEOUT(view.capability_report().graphics_available, 5000);

  QTest::mousePress(&view, Qt::LeftButton, Qt::NoModifier, QPoint{100, 100});
  QTest::mouseMove(&view, QPoint{100, 120}, 20);
  QTest::mouseRelease(&view, Qt::LeftButton, Qt::NoModifier, QPoint{100, 120});
  auto viewport = fixture.session->viewport(fixture.document_id);
  QVERIFY(viewport.has_value());
  QVERIFY(std::abs(viewport->top - 990.0) < 1.0);
  QVERIFY(std::abs(viewport->bottom - 1090.0) < 1.0);

  const auto local_position = QPointF{100.0, 100.0};
  QWheelEvent wheel_event(
      local_position, view.mapToGlobal(local_position.toPoint()), QPoint{},
      QPoint{0, 120}, Qt::NoButton, Qt::NoModifier, Qt::NoScrollPhase, false);
  QApplication::sendEvent(&view, &wheel_event);
  viewport = fixture.session->viewport(fixture.document_id);
  QVERIFY(viewport->bottom - viewport->top < 100.0);
  QVERIFY(viewport_spy.count() >= 2);

  view.reset_viewport();
  viewport = fixture.session->viewport(fixture.document_id);
  QCOMPARE(viewport->top, 1000.0);
  QCOMPARE(viewport->bottom, 1100.0);
}

void WellLogViewTest::widget_rebuild_restores_curve_from_session_cpu_state() {
  auto fixture = prepared_view_fixture();
  const auto render_once = [&fixture]() {
    WellLogView view(fixture.session);
    view.set_document_id(fixture.document_id);
    view.resize(200, 200);
    view.show();
    if (!QTest::qWaitForWindowExposed(&view)) {
      return false;
    }
    QImage image;
    for (auto attempt = 0; attempt < 50; ++attempt) {
      QApplication::processEvents();
      if (view.capability_report().graphics_available) {
        image = view.grabFramebuffer();
        if (image.pixelColor(image.width() / 2, image.height() / 2) !=
            QColor{Qt::white}) {
          return true;
        }
      }
      QTest::qWait(20);
    }
    return false;
  };

  QVERIFY(render_once());
  QVERIFY(fixture.session->prepared_scene(fixture.document_id) != nullptr);
  QVERIFY(render_once());
}

void WellLogViewTest::
    top_level_reparent_restores_curve_after_context_recreation() {
  auto fixture = prepared_view_fixture();
  QWidget first_host;
  QWidget second_host;
  auto *first_layout = new QVBoxLayout(&first_host);
  auto *second_layout = new QVBoxLayout(&second_host);
  auto *view = new WellLogView(fixture.session);
  view->set_document_id(fixture.document_id);
  first_layout->addWidget(view);
  first_host.resize(200, 200);
  first_host.show();
  QVERIFY(QTest::qWaitForWindowExposed(&first_host));
  QTRY_VERIFY_WITH_TIMEOUT(view->capability_report().graphics_available, 5000);
  auto image = view->grabFramebuffer();
  QVERIFY(image.pixelColor(image.width() / 2, image.height() / 2) !=
          QColor{Qt::white});

  view->setParent(&second_host);
  second_layout->addWidget(view);
  second_host.resize(200, 200);
  second_host.show();
  view->show();
  QVERIFY(QTest::qWaitForWindowExposed(&second_host));
  QTRY_VERIFY_WITH_TIMEOUT(view->capability_report().graphics_available, 5000);
  QTRY_VERIFY_WITH_TIMEOUT(
      (image = view->grabFramebuffer(),
       image.pixelColor(image.width() / 2, image.height() / 2) !=
           QColor{Qt::white}),
      5000);
}

} // namespace

int main(int argc, char **argv) {
  configure_well_log_surface_format();
  QApplication application(argc, argv);
  WellLogViewTest test;
  return QTest::qExec(&test, argc, argv);
}

#include "well_log_view_test.moc"
