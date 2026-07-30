#include <welllog/qtwidgets/well_log_view.hpp>

#include "render_gl/capability_probe.hpp"
#include "render_gl/renderer.hpp"

#ifdef WELLLOG_WITH_TEXT
#include <welllog/text/harfbuzz_text_engine.hpp>
#endif

#include <QKeyEvent>
#include <QLabel>
#include <QMetaObject>
#include <QMouseEvent>
#include <QOpenGLContext>
#include <QOpenGLExtraFunctions>
#include <QOpenGLFunctions>
#include <QResizeEvent>
#include <QShowEvent>
#include <QString>
#include <QSurfaceFormat>
#include <QThread>
#include <QTimer>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>
#include <utility>

namespace welllog {
namespace {

[[nodiscard]] QSurfaceFormat well_log_surface_format() {
  QSurfaceFormat format;
  format.setRenderableType(QSurfaceFormat::OpenGL);
  format.setVersion(3, 3);
  format.setProfile(QSurfaceFormat::CoreProfile);
  format.setDepthBufferSize(24);
  format.setStencilBufferSize(8);
  format.setSwapBehavior(QSurfaceFormat::DoubleBuffer);
  format.setSamples(0);
  return format;
}

[[nodiscard]] std::string gl_string(QOpenGLFunctions &functions,
                                    unsigned int name) {
  const auto *value = functions.glGetString(name);
  return value == nullptr ? std::string{}
                          : std::string{reinterpret_cast<const char *>(value)};
}

[[nodiscard]] CapabilityReport failed_capability_report(std::string reason) {
  CapabilityReport report;
  report.initialization_complete = true;
  report.unavailable_reason = std::move(reason);
  return report;
}

[[nodiscard]] detail::GlProcAddress resolve_gl_proc(void *context,
                                                    const char *name) noexcept {
  if (context == nullptr || name == nullptr) {
    return nullptr;
  }
  return static_cast<QOpenGLContext *>(context)->getProcAddress(name);
}

[[nodiscard]] QString diagnostic_code(DiagnosticCode code) {
  switch (code) {
  case DiagnosticCode::missing_samples:
    return QStringLiteral("missing_samples");
  case DiagnosticCode::asynchronous_preparation_failed:
    return QStringLiteral("asynchronous_preparation_failed");
  case DiagnosticCode::missing_glyphs:
    return QStringLiteral("missing_glyphs");
  case DiagnosticCode::fallback_font_used:
    return QStringLiteral("fallback_font_used");
  case DiagnosticCode::text_engine_unavailable:
    return QStringLiteral("text_engine_unavailable");
  case DiagnosticCode::nonpositive_log_values:
    return QStringLiteral("nonpositive_log_values");
  case DiagnosticCode::scale_readability_hint:
    return QStringLiteral("scale_readability_hint");
  }
  return QStringLiteral("unknown_diagnostic");
}

[[nodiscard]] QString asynchronous_error_reason(ErrorCode code) {
  if (code == ErrorCode::resource_exhausted) {
    return QStringLiteral("resource_exhausted");
  }
  if (code == ErrorCode::operation_cancelled) {
    return QStringLiteral("operation_cancelled");
  }
  if (code == ErrorCode::internal_error) {
    return QStringLiteral("internal_error");
  }
  return QStringLiteral("well_log_error_%1").arg(static_cast<quint16>(code));
}

} // namespace

void configure_well_log_surface_format() {
  QSurfaceFormat::setDefaultFormat(well_log_surface_format());
}

struct WellLogView::Impl {
  std::shared_ptr<WellLogSession> session;
  std::optional<EntityId> document_id;
  CapabilityReport capability_report;
  detail::GlRenderer renderer;
  std::shared_ptr<const PreparedScene> uploaded_scene;
  std::shared_ptr<const PreparedScene> queued_scene;
  QMetaObject::Connection context_cleanup_connection;
  std::optional<CurvePick> hover_pick;
  std::optional<CurvePick> click_pick;
  double drag_last_top{};
  bool dragging{};
  bool drag_moved{};
  bool framebuffer_stencil_verified{};
  QLabel *capability_overlay{};
  QTimer *signal_timer{};
  ViewEventObserverId session_observer_id{};
  std::uint64_t last_diagnostic_id{};
  bool viewport_signal_pending{};
  bool crosshair_signal_pending{};
  // Host image-tile resolver (ADR 0045); applied to the renderer on the GL
  // thread once initialized, and re-applied after context recovery.
  std::function<Result<RasterTile>(const ImageTileRequest &)> image_resolver;
  bool image_resolver_dirty{};
  bool hover_signal_pending{};
};

WellLogView::WellLogView(QWidget *parent)
    : WellLogView(std::make_shared<WellLogSession>(), parent) {}

WellLogView::WellLogView(std::shared_ptr<WellLogSession> session,
                         QWidget *parent)
    : QOpenGLWidget(parent), impl_(std::make_unique<Impl>()) {
  impl_->session = session == nullptr ? std::make_shared<WellLogSession>()
                                      : std::move(session);
#ifdef WELLLOG_WITH_TEXT
  if (impl_->session != nullptr) {
    impl_->session->set_text_engine(
        std::make_shared<HarfBuzzTextEngine>());
  }
#endif
  setFormat(well_log_surface_format());
  setMouseTracking(true);
  setFocusPolicy(Qt::StrongFocus);
  setUpdateBehavior(QOpenGLWidget::NoPartialUpdate);
  impl_->capability_overlay = new QLabel(tr("Initializing OpenGL view…"), this);
  impl_->capability_overlay->setAlignment(Qt::AlignCenter);
  impl_->capability_overlay->setWordWrap(true);
  impl_->capability_overlay->setStyleSheet(
      QStringLiteral("QLabel { color: #ebebeb; background: #232629; "
                     "padding: 16px; }"));
  impl_->capability_overlay->setGeometry(rect());
  impl_->capability_overlay->raise();
  impl_->signal_timer = new QTimer(this);
  impl_->signal_timer->setInterval(16);
  impl_->signal_timer->setSingleShot(true);
  connect(impl_->signal_timer, &QTimer::timeout, this, [this]() {
    if (impl_->viewport_signal_pending) {
      impl_->viewport_signal_pending = false;
      emit viewportChanged();
    }
    if (impl_->crosshair_signal_pending) {
      impl_->crosshair_signal_pending = false;
      emit crosshairChanged();
    }
    if (impl_->hover_signal_pending) {
      impl_->hover_signal_pending = false;
      emit hoverChanged();
    }
  });
  impl_->session_observer_id =
      impl_->session->subscribe_view_events([this](const ViewEvent &event) {
        QMetaObject::invokeMethod(
            this, [this, event]() { handle_session_event(event); },
            Qt::QueuedConnection);
      });
}

WellLogView::~WellLogView() {
  impl_->session->unsubscribe_view_events(impl_->session_observer_id);
  cleanup_context();
}

WellLogSession &WellLogView::session() noexcept { return *impl_->session; }

void WellLogView::set_text_engine(
    std::shared_ptr<TextEngine> text_engine) noexcept {
  if (impl_->session != nullptr) {
    impl_->session->set_text_engine(std::move(text_engine));
  }
}

void WellLogView::set_image_tile_resolver(
    std::function<Result<RasterTile>(const ImageTileRequest &)> resolver)
    noexcept {
  impl_->image_resolver = std::move(resolver);
  impl_->image_resolver_dirty = true;
}
const WellLogSession &WellLogView::session() const noexcept {
  return *impl_->session;
}

void WellLogView::publish_fatal_error() {
  const auto capability_failure =
      impl_->capability_report.initialization_complete &&
      !impl_->capability_report.graphics_available;
  const auto code = capability_failure
                        ? QStringLiteral("capability_unavailable")
                        : QStringLiteral("render_failure");
  const auto message =
      impl_->capability_report.unavailable_reason.empty()
          ? QStringLiteral("WellLogView rendering failed")
          : QString::fromStdString(impl_->capability_report.unavailable_reason);
  emit viewError(code, message);
  emit fatalViewError();
}

void WellLogView::set_document_id(EntityId document_id) noexcept {
  if (QThread::currentThread() != thread()) {
    QMetaObject::invokeMethod(
        this, [this, document_id]() { set_document_id(document_id); },
        Qt::QueuedConnection);
    return;
  }
  impl_->document_id =
      document_id.is_nil() ? std::nullopt : std::optional{document_id};
  for (const auto &diagnostic : impl_->session->diagnostics()) {
    impl_->last_diagnostic_id =
        std::max(impl_->last_diagnostic_id, diagnostic.id);
  }
  impl_->uploaded_scene.reset();
  impl_->queued_scene.reset();
  const auto had_hover = impl_->hover_pick.has_value();
  impl_->hover_pick.reset();
  impl_->click_pick.reset();
  if (had_hover) {
    impl_->hover_signal_pending = true;
    schedule_coalesced_signals();
  }
  update();
}

std::optional<EntityId> WellLogView::document_id() const noexcept {
  return impl_->document_id;
}

const CapabilityReport &WellLogView::capability_report() const noexcept {
  return impl_->capability_report;
}

std::optional<CurvePick> WellLogView::hover_pick() const noexcept {
  return impl_->hover_pick;
}

std::optional<CurvePick> WellLogView::click_pick() const noexcept {
  return impl_->click_pick;
}

void WellLogView::initializeGL() {
  try {
    auto *current = QOpenGLContext::currentContext();
    if (current == nullptr || current != context()) {
      impl_->capability_report =
          failed_capability_report("no current OpenGL context is available");
      publish_fatal_error();
      return;
    }
    auto *functions = current->functions();
    if (functions == nullptr) {
      impl_->capability_report =
          failed_capability_report("OpenGL functions are unavailable");
      publish_fatal_error();
      return;
    }
    functions->initializeOpenGLFunctions();

    int maximum_texture_size{};
    functions->glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maximum_texture_size);
    int maximum_combined_texture_units{};
    functions->glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS,
                             &maximum_combined_texture_units);
    int maximum_vertex_attributes{};
    functions->glGetIntegerv(GL_MAX_VERTEX_ATTRIBS, &maximum_vertex_attributes);
    int maximum_uniform_block_size{};
    functions->glGetIntegerv(GL_MAX_UNIFORM_BLOCK_SIZE,
                             &maximum_uniform_block_size);
    const auto format = current->format();
    impl_->capability_report =
        detail::evaluate_capabilities(detail::OpenGlContextCapabilities{
            .core_profile = format.profile() == QSurfaceFormat::CoreProfile,
            .open_gl_major = format.majorVersion(),
            .open_gl_minor = format.minorVersion(),
            .stencil_bits = format.stencilBufferSize(),
            .maximum_texture_size = maximum_texture_size,
            .maximum_combined_texture_units = maximum_combined_texture_units,
            .maximum_vertex_attributes = maximum_vertex_attributes,
            .maximum_uniform_block_size = maximum_uniform_block_size,
            .buffer_storage_supported = current->hasExtension(
                QByteArrayLiteral("GL_ARB_buffer_storage")),
            .timer_query_supported =
                current->hasExtension(QByteArrayLiteral("GL_ARB_timer_query")),
            .vendor = gl_string(*functions, GL_VENDOR),
            .renderer = gl_string(*functions, GL_RENDERER),
            .open_gl_version = gl_string(*functions, GL_VERSION),
            .glsl_version = gl_string(*functions, GL_SHADING_LANGUAGE_VERSION),
        });
    if (impl_->capability_report.graphics_available &&
        !impl_->renderer.initialize(resolve_gl_proc, current)) {
      impl_->capability_report.graphics_available = false;
      impl_->capability_report.unavailable_reason =
          "OpenGL shader or buffer initialization failed";
    } else if (impl_->capability_report.graphics_available) {
      // (Re)install the host image-tile decoder + budget on the GL thread
      // (ADR 0045). On context recovery the renderer is freshly initialized,
      // so this re-applies the resolver for texture regeneration.
      impl_->image_resolver_dirty = true;
    }
    impl_->context_cleanup_connection = connect(
        current, &QOpenGLContext::aboutToBeDestroyed, this,
        [this]() { cleanup_context(); }, Qt::DirectConnection);
    update_capability_overlay();
    emit capabilityChanged();
    if (!impl_->capability_report.graphics_available) {
      publish_fatal_error();
    }
  } catch (...) {
    impl_->capability_report =
        failed_capability_report("OpenGL capability detection failed");
    update_capability_overlay();
    publish_fatal_error();
  }
}

void WellLogView::resizeGL(int width, int height) {
  Q_UNUSED(width)
  Q_UNUSED(height)
}

void WellLogView::paintGL() {
  const auto pixel_ratio = devicePixelRatioF();
  const auto pixel_width =
      static_cast<int>(static_cast<double>(width()) * pixel_ratio);
  const auto pixel_height =
      static_cast<int>(static_cast<double>(height()) * pixel_ratio);
  if (impl_->document_id.has_value()) {
    const auto current_viewport = impl_->session->viewport(*impl_->document_id);
    const auto current_pixel_height =
        impl_->session->viewport_pixel_height(*impl_->document_id);
    const auto desired_pixel_height =
        static_cast<std::uint32_t>(std::max(1, pixel_height));
    if (current_viewport.has_value() &&
        current_pixel_height !=
            std::optional<std::uint32_t>{desired_pixel_height}) {
      static_cast<void>(impl_->session->execute(SetViewportMetricsCommand{
          .document_id = *impl_->document_id,
          .viewport = *current_viewport,
          .pixel_height = desired_pixel_height,
      }));
    }
    impl_->session->poll_async();
    const auto snapshot =
        impl_->session->performance_snapshot(*impl_->document_id);
    if (snapshot.has_value() &&
        (snapshot->preparation_state == PreparationState::pending ||
         snapshot->frame_preparation_pending)) {
      QTimer::singleShot(1, this, [this]() { update(); });
    }
  }
  if (impl_->capability_report.graphics_available &&
      !impl_->framebuffer_stencil_verified) {
    auto *current = QOpenGLContext::currentContext();
    auto *functions = current == nullptr ? nullptr : current->extraFunctions();
    if (current != context() || functions == nullptr) {
      impl_->capability_report.graphics_available = false;
      impl_->capability_report.unavailable_reason =
          "the widget framebuffer could not be validated";
    } else {
      int stencil_bits{};
      functions->glGetFramebufferAttachmentParameteriv(
          GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT,
          GL_FRAMEBUFFER_ATTACHMENT_STENCIL_SIZE, &stencil_bits);
      impl_->capability_report.stencil_bits = stencil_bits;
      if (stencil_bits < 8) {
        impl_->capability_report.graphics_available = false;
        impl_->capability_report.unavailable_reason =
            "an 8-bit stencil buffer is required";
      }
    }
    impl_->framebuffer_stencil_verified = true;
    update_capability_overlay();
    emit capabilityChanged();
    if (!impl_->capability_report.graphics_available) {
      publish_fatal_error();
    }
  }
  if (!impl_->capability_report.graphics_available) {
    return;
  }
  try {
    auto *current = QOpenGLContext::currentContext();
    if (current == nullptr || current != context()) {
      publish_fatal_error();
      return;
    }
    std::shared_ptr<const PreparedScene> scene;
    std::optional<DepthViewport> viewport;
    std::optional<CrosshairState> crosshair;
    if (impl_->document_id.has_value()) {
      scene = impl_->session->prepared_scene(*impl_->document_id);
      viewport = impl_->session->viewport(*impl_->document_id);
      crosshair = impl_->session->crosshair(*impl_->document_id);
    }
    if (scene != nullptr && scene != impl_->uploaded_scene &&
        scene != impl_->queued_scene) {
      const auto budgets = impl_->session->performance_budgets();
      // Push the host image resolver + texture budget onto the renderer when
      // it changes (or after context recovery) so image tiles can be decoded
      // and uploaded (ADR 0045).
      if (impl_->image_resolver_dirty) {
        impl_->renderer.set_image_tile_resolver(impl_->image_resolver,
                                                budgets.maximum_image_texture_bytes);
        impl_->image_resolver_dirty = false;
      }
      if (!impl_->renderer.queue_upload(
              *scene,
              GpuUploadBudgets{
                  .maximum_cache_bytes = budgets.maximum_gpu_cache_bytes,
                  .maximum_bytes_per_frame =
                      budgets.maximum_upload_bytes_per_frame,
              })) {
        publish_fatal_error();
        return;
      }
      impl_->queued_scene = scene;
    }
    if (impl_->queued_scene != nullptr) {
      const auto progress = impl_->renderer.upload_next();
      if (progress.completed) {
        impl_->uploaded_scene = std::move(impl_->queued_scene);
      } else if (progress.pending) {
        QTimer::singleShot(1, this, [this]() { update(); });
      } else {
        publish_fatal_error();
        return;
      }
    }
    const auto fallback_viewport =
        scene == nullptr ? DepthViewport{.top = 0.0, .bottom = 1.0}
                         : DepthViewport{
                               .top = scene->reference_depth_range().top,
                               .bottom = scene->reference_depth_range().bottom,
                           };
    if (!impl_->renderer.render(detail::GlRenderFrame{
            .framebuffer = defaultFramebufferObject(),
            .pixel_width = pixel_width,
            .pixel_height = pixel_height,
            .physical_pixels_per_millimetre =
                logicalDpiX() / 25.4 * pixel_ratio,
            .viewport =
                [&]() {
                  const auto current_viewport =
                      viewport.value_or(fallback_viewport);
                  return detail::GlDepthViewport{
                      .top = current_viewport.top,
                      .bottom = current_viewport.bottom,
                  };
                }(),
            .crosshair =
                crosshair.has_value()
                    ? std::optional<detail::GlCrosshair>{detail::GlCrosshair{
                          .horizontal_fraction = crosshair->track_fraction,
                          .display_depth = crosshair->display_depth,
                      }}
                    : std::nullopt,
            .draw_scene = impl_->uploaded_scene != nullptr,
        })) {
      publish_fatal_error();
    }
  } catch (...) {
    publish_fatal_error();
  }
}

void WellLogView::showEvent(QShowEvent *event) {
  QOpenGLWidget::showEvent(event);
  QTimer::singleShot(500, this, [this]() {
    if (impl_->capability_report.initialization_complete || !isVisible()) {
      return;
    }
    impl_->capability_report = failed_capability_report(
        "an OpenGL 3.3 Core context could not be created");
    update_capability_overlay();
    emit capabilityChanged();
    publish_fatal_error();
  });
}

void WellLogView::resizeEvent(QResizeEvent *event) {
  QOpenGLWidget::resizeEvent(event);
  impl_->capability_overlay->setGeometry(rect());
}

void WellLogView::mousePressEvent(QMouseEvent *event) {
  if (event->button() == Qt::LeftButton) {
    impl_->dragging = true;
    impl_->drag_moved = false;
    impl_->drag_last_top = event->position().y();
    update_pointer(event->position().x(), event->position().y());
    event->accept();
    return;
  }
  QOpenGLWidget::mousePressEvent(event);
}

void WellLogView::mouseMoveEvent(QMouseEvent *event) {
  if (impl_->dragging && impl_->document_id.has_value() && height() > 0) {
    const auto delta = event->position().y() - impl_->drag_last_top;
    const auto viewport = impl_->session->viewport(*impl_->document_id);
    if (viewport.has_value() && delta != 0.0) {
      const auto depth_delta = -delta / static_cast<double>(height()) *
                               (viewport->bottom - viewport->top);
      if (impl_->session
              ->execute(PanDepthCommand{
                  .document_id = *impl_->document_id,
                  .display_depth_delta = depth_delta,
              })
              .has_value()) {
        impl_->drag_moved = true;
        impl_->drag_last_top = event->position().y();
        update();
      }
    }
  }
  update_pointer(event->position().x(), event->position().y());
  event->accept();
}

void WellLogView::mouseReleaseEvent(QMouseEvent *event) {
  if (event->button() == Qt::LeftButton && impl_->dragging) {
    update_pointer(event->position().x(), event->position().y());
    if (!impl_->drag_moved) {
      impl_->click_pick = impl_->hover_pick;
      if (impl_->click_pick.has_value()) {
        emit curveClicked();
      }
    }
    impl_->dragging = false;
    event->accept();
    return;
  }
  QOpenGLWidget::mouseReleaseEvent(event);
}

void WellLogView::wheelEvent(QWheelEvent *event) {
  if (!impl_->document_id.has_value() || height() <= 0) {
    QOpenGLWidget::wheelEvent(event);
    return;
  }
  const auto viewport = impl_->session->viewport(*impl_->document_id);
  if (!viewport.has_value() || event->angleDelta().y() == 0) {
    QOpenGLWidget::wheelEvent(event);
    return;
  }
  const auto top_fraction = std::clamp(
      event->position().y() / static_cast<double>(height()), 0.0, 1.0);
  const auto anchor =
      viewport->top + top_fraction * (viewport->bottom - viewport->top);
  const auto factor =
      std::exp(-static_cast<double>(event->angleDelta().y()) * 0.0015);
  if (impl_->session
          ->execute(ZoomDepthAtCommand{
              .document_id = *impl_->document_id,
              .anchor_display_depth = anchor,
              .span_factor = factor,
          })
          .has_value()) {
    update_pointer(event->position().x(), event->position().y());
    update();
  }
  event->accept();
}

void WellLogView::leaveEvent(QEvent *event) {
  if (impl_->document_id.has_value()) {
    static_cast<void>(impl_->session->execute(SetCrosshairCommand{
        .document_id = *impl_->document_id,
        .crosshair = std::nullopt,
    }));
  }
  if (impl_->hover_pick.has_value()) {
    impl_->hover_pick.reset();
    impl_->hover_signal_pending = true;
    schedule_coalesced_signals();
  }
  update();
  QOpenGLWidget::leaveEvent(event);
}

void WellLogView::keyPressEvent(QKeyEvent *event) {
  if (event->key() == Qt::Key_Home) {
    reset_viewport();
    event->accept();
    return;
  }
  QOpenGLWidget::keyPressEvent(event);
}

void WellLogView::reset_viewport() {
  if (QThread::currentThread() != thread()) {
    QMetaObject::invokeMethod(
        this, [this]() { reset_viewport(); }, Qt::QueuedConnection);
    return;
  }
  if (!impl_->document_id.has_value()) {
    return;
  }
  if (impl_->session
          ->execute(ResetViewportCommand{.document_id = *impl_->document_id})
          .has_value()) {
    update();
  }
}

void WellLogView::update_pointer(double left, double top) noexcept {
  try {
    if (!impl_->document_id.has_value() || width() <= 0 || height() <= 0) {
      return;
    }
    const auto scene = impl_->session->prepared_scene(*impl_->document_id);
    const auto viewport = impl_->session->viewport(*impl_->document_id);
    if (scene == nullptr || !viewport.has_value()) {
      return;
    }
    const auto horizontal_fraction =
        std::clamp(left / static_cast<double>(width()), 0.0, 1.0);
    const auto vertical_fraction =
        std::clamp(top / static_cast<double>(height()), 0.0, 1.0);
    const auto display_depth =
        viewport->top + vertical_fraction * (viewport->bottom - viewport->top);
    static_cast<void>(impl_->session->execute(SetCrosshairCommand{
        .document_id = *impl_->document_id,
        .crosshair =
            CrosshairState{
                .track_fraction = horizontal_fraction,
                .display_depth = display_depth,
            },
    }));

    const auto reference_range = scene->reference_depth_range();
    const auto reference_span = reference_range.bottom - reference_range.top;
    const auto viewport_span = viewport->bottom - viewport->top;
    const auto physical_width = scene->physical_width().value;
    const auto physical_height = scene->physical_height().value;
    if (reference_span <= 0.0 || viewport_span <= 0.0 ||
        physical_width <= 0.0 || physical_height <= 0.0) {
      return;
    }
    const auto reference_depth = display_depth;
    const auto next_hover = scene->pick_curve(CurvePickQuery{
        .scene_position =
            PhysicalPoint{
                .left = Millimetres{horizontal_fraction * physical_width},
                .top = Millimetres{(reference_depth - reference_range.top) /
                                   reference_span * physical_height},
            },
        .tolerance = DeviceIndependentPixels{6.0},
        .horizontal_device_independent_pixels_per_millimetre =
            static_cast<double>(width()) / physical_width,
        .vertical_device_independent_pixels_per_millimetre =
            static_cast<double>(height()) /
            (physical_height * viewport_span / reference_span),
    });
    impl_->hover_pick = next_hover;
    impl_->hover_signal_pending = true;
    schedule_coalesced_signals();
    update();
  } catch (...) {
    publish_fatal_error();
  }
}

void WellLogView::handle_session_event(ViewEvent event) noexcept {
  if (!impl_->document_id.has_value() ||
      event.document_id != *impl_->document_id) {
    return;
  }
  switch (event.kind) {
  case ViewEventKind::viewport_changed:
    impl_->viewport_signal_pending = true;
    update();
    break;
  case ViewEventKind::crosshair_changed:
    impl_->crosshair_signal_pending = true;
    update();
    break;
  case ViewEventKind::documents_changed:
    emit documentChanged(QString::fromStdString(event.document_id.to_string()),
                         static_cast<quint64>(event.document_revision.value));
    update();
    break;
  case ViewEventKind::presentation_changed:
  case ViewEventKind::frame_ready:
    update();
    break;
  case ViewEventKind::diagnostic_published: {
    const Diagnostic *published{};
    for (const auto &diagnostic : impl_->session->diagnostics()) {
      if (diagnostic.id > impl_->last_diagnostic_id &&
          diagnostic.document_id == event.document_id &&
          diagnostic.document_revision == event.document_revision &&
          (published == nullptr || diagnostic.id < published->id)) {
        published = &diagnostic;
      }
    }
    if (published != nullptr) {
      impl_->last_diagnostic_id = published->id;
      const auto code = diagnostic_code(published->code);
      emit diagnosticPublished(
          code, QString::fromStdString(event.document_id.to_string()),
          static_cast<quint64>(event.document_revision.value));
      if (published->code == DiagnosticCode::asynchronous_preparation_failed) {
        const auto error = impl_->session->diagnostic_error(published->id);
        const auto reason = error.has_value()
                                ? asynchronous_error_reason(error->code)
                                : QStringLiteral("details_unavailable");
        emit viewError(
            code, tr("Asynchronous scene preparation failed: %1").arg(reason));
      }
    }
  } break;
  }
  schedule_coalesced_signals();
}

void WellLogView::schedule_coalesced_signals() noexcept {
  if (!impl_->signal_timer->isActive()) {
    impl_->signal_timer->start();
  }
}

void WellLogView::update_capability_overlay() noexcept {
  if (impl_->capability_overlay == nullptr) {
    return;
  }
  if (impl_->capability_report.graphics_available &&
      impl_->framebuffer_stencil_verified) {
    impl_->capability_overlay->hide();
    return;
  }
  const auto reason =
      impl_->capability_report.initialization_complete
          ? QString::fromStdString(impl_->capability_report.unavailable_reason)
          : tr("Initializing OpenGL view…");
  impl_->capability_overlay->setText(
      impl_->capability_report.initialization_complete
          ? tr("OpenGL view unavailable\n%1").arg(reason)
          : reason);
  impl_->capability_overlay->show();
  impl_->capability_overlay->raise();
}

void WellLogView::cleanup_context() noexcept {
  QObject::disconnect(impl_->context_cleanup_connection);
  impl_->context_cleanup_connection = {};
  auto *gl_context = context();
  if (gl_context != nullptr && gl_context->isValid()) {
    makeCurrent();
    if (QOpenGLContext::currentContext() == gl_context) {
      impl_->renderer.release();
      doneCurrent();
    } else {
      impl_->renderer.abandon();
    }
  } else {
    impl_->renderer.abandon();
  }
  impl_->uploaded_scene.reset();
  impl_->queued_scene.reset();
  impl_->framebuffer_stencil_verified = false;
  impl_->capability_report = {};
  update_capability_overlay();
}

} // namespace welllog
