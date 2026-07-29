#include "render_gl/renderer.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstring>
#include <limits>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace welllog::detail {
namespace {

#if defined(_WIN32)
#define WELLLOG_GL_CALL __stdcall
#else
#define WELLLOG_GL_CALL
#endif

using GlBoolean = unsigned char;
using GlChar = char;
using GlEnum = unsigned int;
using GlFloat = float;
using GlInt = int;
using GlSize = int;
using GlSizePointer = std::ptrdiff_t;
using GlUInt = unsigned int;

constexpr GlEnum gl_array_buffer = 0x8892;
constexpr GlEnum gl_static_draw = 0x88E4;
constexpr GlEnum gl_float = 0x1406;
constexpr GlEnum gl_false = 0;
constexpr GlEnum gl_vertex_shader = 0x8B31;
constexpr GlEnum gl_fragment_shader = 0x8B30;
constexpr GlEnum gl_compile_status = 0x8B81;
constexpr GlEnum gl_link_status = 0x8B82;
constexpr GlEnum gl_framebuffer = 0x8D40;
constexpr GlEnum gl_color_buffer_bit = 0x00004000;
constexpr GlEnum gl_stencil_buffer_bit = 0x00000400;
constexpr GlEnum gl_depth_test = 0x0B71;
constexpr GlEnum gl_blend = 0x0BE2;
constexpr GlEnum gl_cull_face = 0x0B44;
constexpr GlEnum gl_stencil_test = 0x0B90;
constexpr GlEnum gl_scissor_test = 0x0C11;
constexpr GlEnum gl_triangles = 0x0004;
constexpr GlEnum gl_src_alpha = 0x0302;
constexpr GlEnum gl_one_minus_src_alpha = 0x0303;
constexpr GlEnum gl_one = 1;

using GlGenVertexArrays = void(WELLLOG_GL_CALL *)(GlSize, GlUInt *);
using GlBindVertexArray = void(WELLLOG_GL_CALL *)(GlUInt);
using GlDeleteVertexArrays = void(WELLLOG_GL_CALL *)(GlSize, const GlUInt *);
using GlGenBuffers = void(WELLLOG_GL_CALL *)(GlSize, GlUInt *);
using GlBindBuffer = void(WELLLOG_GL_CALL *)(GlEnum, GlUInt);
using GlBufferData = void(WELLLOG_GL_CALL *)(GlEnum, GlSizePointer,
                                             const void *, GlEnum);
using GlDeleteBuffers = void(WELLLOG_GL_CALL *)(GlSize, const GlUInt *);
using GlCreateShader = GlUInt(WELLLOG_GL_CALL *)(GlEnum);
using GlShaderSource = void(WELLLOG_GL_CALL *)(GlUInt, GlSize,
                                               const GlChar *const *,
                                               const GlInt *);
using GlCompileShader = void(WELLLOG_GL_CALL *)(GlUInt);
using GlGetShaderiv = void(WELLLOG_GL_CALL *)(GlUInt, GlEnum, GlInt *);
using GlDeleteShader = void(WELLLOG_GL_CALL *)(GlUInt);
using GlCreateProgram = GlUInt(WELLLOG_GL_CALL *)();
using GlAttachShader = void(WELLLOG_GL_CALL *)(GlUInt, GlUInt);
using GlLinkProgram = void(WELLLOG_GL_CALL *)(GlUInt);
using GlGetProgramiv = void(WELLLOG_GL_CALL *)(GlUInt, GlEnum, GlInt *);
using GlDeleteProgram = void(WELLLOG_GL_CALL *)(GlUInt);
using GlUseProgram = void(WELLLOG_GL_CALL *)(GlUInt);
using GlEnableVertexAttribArray = void(WELLLOG_GL_CALL *)(GlUInt);
using GlVertexAttribPointer = void(WELLLOG_GL_CALL *)(GlUInt, GlInt, GlEnum,
                                                      GlBoolean, GlSize,
                                                      const void *);
using GlGetUniformLocation = GlInt(WELLLOG_GL_CALL *)(GlUInt, const GlChar *);
using GlUniform1f = void(WELLLOG_GL_CALL *)(GlInt, GlFloat);
using GlUniform2f = void(WELLLOG_GL_CALL *)(GlInt, GlFloat, GlFloat);
using GlUniform4f = void(WELLLOG_GL_CALL *)(GlInt, GlFloat, GlFloat, GlFloat,
                                            GlFloat);
using GlBindFramebuffer = void(WELLLOG_GL_CALL *)(GlEnum, GlUInt);
using GlViewport = void(WELLLOG_GL_CALL *)(GlInt, GlInt, GlSize, GlSize);
using GlClearColor = void(WELLLOG_GL_CALL *)(GlFloat, GlFloat, GlFloat,
                                             GlFloat);
using GlClearStencil = void(WELLLOG_GL_CALL *)(GlInt);
using GlClear = void(WELLLOG_GL_CALL *)(GlEnum);
using GlEnable = void(WELLLOG_GL_CALL *)(GlEnum);
using GlDisable = void(WELLLOG_GL_CALL *)(GlEnum);
using GlBlendFuncSeparate = void(WELLLOG_GL_CALL *)(GlEnum, GlEnum, GlEnum,
                                                    GlEnum);
using GlColorMask = void(WELLLOG_GL_CALL *)(GlBoolean, GlBoolean, GlBoolean,
                                            GlBoolean);
using GlStencilMask = void(WELLLOG_GL_CALL *)(GlUInt);
using GlScissor = void(WELLLOG_GL_CALL *)(GlInt, GlInt, GlSize, GlSize);
using GlDrawArrays = void(WELLLOG_GL_CALL *)(GlEnum, GlInt, GlSize);

template <typename Function>
[[nodiscard]] Function load(GlProcResolver resolver, void *resolver_context,
                            const char *name) noexcept {
  return reinterpret_cast<Function>(resolver(resolver_context, name));
}

struct GlFunctions {
  GlGenVertexArrays gen_vertex_arrays{};
  GlBindVertexArray bind_vertex_array{};
  GlDeleteVertexArrays delete_vertex_arrays{};
  GlGenBuffers gen_buffers{};
  GlBindBuffer bind_buffer{};
  GlBufferData buffer_data{};
  GlDeleteBuffers delete_buffers{};
  GlCreateShader create_shader{};
  GlShaderSource shader_source{};
  GlCompileShader compile_shader{};
  GlGetShaderiv get_shader_iv{};
  GlDeleteShader delete_shader{};
  GlCreateProgram create_program{};
  GlAttachShader attach_shader{};
  GlLinkProgram link_program{};
  GlGetProgramiv get_program_iv{};
  GlDeleteProgram delete_program{};
  GlUseProgram use_program{};
  GlEnableVertexAttribArray enable_vertex_attrib_array{};
  GlVertexAttribPointer vertex_attrib_pointer{};
  GlGetUniformLocation get_uniform_location{};
  GlUniform1f uniform_1f{};
  GlUniform2f uniform_2f{};
  GlUniform4f uniform_4f{};
  GlBindFramebuffer bind_framebuffer{};
  GlViewport viewport{};
  GlClearColor clear_color{};
  GlClearStencil clear_stencil{};
  GlClear clear{};
  GlEnable enable{};
  GlDisable disable{};
  GlBlendFuncSeparate blend_func_separate{};
  GlColorMask color_mask{};
  GlStencilMask stencil_mask{};
  GlScissor scissor{};
  GlDrawArrays draw_arrays{};

  [[nodiscard]] bool complete() const noexcept {
    return gen_vertex_arrays != nullptr && bind_vertex_array != nullptr &&
           delete_vertex_arrays != nullptr && gen_buffers != nullptr &&
           bind_buffer != nullptr && buffer_data != nullptr &&
           delete_buffers != nullptr && create_shader != nullptr &&
           shader_source != nullptr && compile_shader != nullptr &&
           get_shader_iv != nullptr && delete_shader != nullptr &&
           create_program != nullptr && attach_shader != nullptr &&
           link_program != nullptr && get_program_iv != nullptr &&
           delete_program != nullptr && use_program != nullptr &&
           enable_vertex_attrib_array != nullptr &&
           vertex_attrib_pointer != nullptr &&
           get_uniform_location != nullptr && uniform_1f != nullptr &&
           uniform_2f != nullptr && uniform_4f != nullptr &&
           bind_framebuffer != nullptr && viewport != nullptr &&
           clear_color != nullptr && clear_stencil != nullptr &&
           clear != nullptr && enable != nullptr && disable != nullptr &&
           blend_func_separate != nullptr && color_mask != nullptr &&
           stencil_mask != nullptr && scissor != nullptr &&
           draw_arrays != nullptr;
  }
};

[[nodiscard]] GlFunctions load_functions(GlProcResolver resolver,
                                         void *resolver_context) noexcept {
  return GlFunctions{
      .gen_vertex_arrays = load<GlGenVertexArrays>(resolver, resolver_context,
                                                   "glGenVertexArrays"),
      .bind_vertex_array = load<GlBindVertexArray>(resolver, resolver_context,
                                                   "glBindVertexArray"),
      .delete_vertex_arrays = load<GlDeleteVertexArrays>(
          resolver, resolver_context, "glDeleteVertexArrays"),
      .gen_buffers =
          load<GlGenBuffers>(resolver, resolver_context, "glGenBuffers"),
      .bind_buffer =
          load<GlBindBuffer>(resolver, resolver_context, "glBindBuffer"),
      .buffer_data =
          load<GlBufferData>(resolver, resolver_context, "glBufferData"),
      .delete_buffers =
          load<GlDeleteBuffers>(resolver, resolver_context, "glDeleteBuffers"),
      .create_shader =
          load<GlCreateShader>(resolver, resolver_context, "glCreateShader"),
      .shader_source =
          load<GlShaderSource>(resolver, resolver_context, "glShaderSource"),
      .compile_shader =
          load<GlCompileShader>(resolver, resolver_context, "glCompileShader"),
      .get_shader_iv =
          load<GlGetShaderiv>(resolver, resolver_context, "glGetShaderiv"),
      .delete_shader =
          load<GlDeleteShader>(resolver, resolver_context, "glDeleteShader"),
      .create_program =
          load<GlCreateProgram>(resolver, resolver_context, "glCreateProgram"),
      .attach_shader =
          load<GlAttachShader>(resolver, resolver_context, "glAttachShader"),
      .link_program =
          load<GlLinkProgram>(resolver, resolver_context, "glLinkProgram"),
      .get_program_iv =
          load<GlGetProgramiv>(resolver, resolver_context, "glGetProgramiv"),
      .delete_program =
          load<GlDeleteProgram>(resolver, resolver_context, "glDeleteProgram"),
      .use_program =
          load<GlUseProgram>(resolver, resolver_context, "glUseProgram"),
      .enable_vertex_attrib_array = load<GlEnableVertexAttribArray>(
          resolver, resolver_context, "glEnableVertexAttribArray"),
      .vertex_attrib_pointer = load<GlVertexAttribPointer>(
          resolver, resolver_context, "glVertexAttribPointer"),
      .get_uniform_location = load<GlGetUniformLocation>(
          resolver, resolver_context, "glGetUniformLocation"),
      .uniform_1f =
          load<GlUniform1f>(resolver, resolver_context, "glUniform1f"),
      .uniform_2f =
          load<GlUniform2f>(resolver, resolver_context, "glUniform2f"),
      .uniform_4f =
          load<GlUniform4f>(resolver, resolver_context, "glUniform4f"),
      .bind_framebuffer = load<GlBindFramebuffer>(resolver, resolver_context,
                                                  "glBindFramebuffer"),
      .viewport = load<GlViewport>(resolver, resolver_context, "glViewport"),
      .clear_color =
          load<GlClearColor>(resolver, resolver_context, "glClearColor"),
      .clear_stencil =
          load<GlClearStencil>(resolver, resolver_context, "glClearStencil"),
      .clear = load<GlClear>(resolver, resolver_context, "glClear"),
      .enable = load<GlEnable>(resolver, resolver_context, "glEnable"),
      .disable = load<GlDisable>(resolver, resolver_context, "glDisable"),
      .blend_func_separate = load<GlBlendFuncSeparate>(
          resolver, resolver_context, "glBlendFuncSeparate"),
      .color_mask =
          load<GlColorMask>(resolver, resolver_context, "glColorMask"),
      .stencil_mask =
          load<GlStencilMask>(resolver, resolver_context, "glStencilMask"),
      .scissor = load<GlScissor>(resolver, resolver_context, "glScissor"),
      .draw_arrays =
          load<GlDrawArrays>(resolver, resolver_context, "glDrawArrays"),
  };
}

constexpr std::string_view vertex_shader_source = R"(#version 330 core
layout(location = 0) in vec4 endpoints;
layout(location = 1) in vec2 corner;
uniform vec2 viewportPixels;
uniform float viewportCenter;
uniform float viewportHalfSpan;
uniform float halfWidthPixels;

vec2 mapPoint(vec2 pointValue) {
    float x = pointValue.x * 2.0 - 1.0;
    float y = -(pointValue.y - viewportCenter) / viewportHalfSpan;
    return vec2(x, y);
}

void main() {
    vec2 first = mapPoint(endpoints.xy);
    vec2 second = mapPoint(endpoints.zw);
    vec2 deltaPixels = (second - first) * viewportPixels * 0.5;
    float segmentLength = max(length(deltaPixels), 0.0001);
    vec2 normalPixels =
        vec2(-deltaPixels.y, deltaPixels.x) / segmentLength;
    vec2 position = mix(first, second, corner.x);
    position += normalPixels * corner.y * halfWidthPixels *
                2.0 / viewportPixels;
    gl_Position = vec4(position, 0.0, 1.0);
}
)";

constexpr std::string_view fragment_shader_source = R"(#version 330 core
uniform vec4 curveColor;
out vec4 fragmentColor;

void main() {
    fragmentColor = curveColor;
}
)";

[[nodiscard]] GlUInt compile_shader(const GlFunctions &gl, GlEnum type,
                                    std::string_view source) noexcept {
  const auto shader = gl.create_shader(type);
  if (shader == 0) {
    return 0;
  }
  const auto *source_pointer = source.data();
  const auto source_length = static_cast<GlInt>(source.size());
  gl.shader_source(shader, 1, &source_pointer, &source_length);
  gl.compile_shader(shader);
  GlInt status{};
  gl.get_shader_iv(shader, gl_compile_status, &status);
  if (status == 0) {
    gl.delete_shader(shader);
    return 0;
  }
  return shader;
}

struct CurveVertex {
  GlFloat first_left{};
  GlFloat first_depth{};
  GlFloat second_left{};
  GlFloat second_depth{};
  GlFloat along{};
  GlFloat side{};
};

struct CurveBatch {
  GlInt first_vertex{};
  GlSize vertex_count{};
  RgbaColor color;
  Millimetres line_width;
  PhysicalRect clip;
};

void append_segment_vertices(std::vector<CurveVertex> &vertices,
                             const PreparedCurvePoint &first,
                             const PreparedCurvePoint &second,
                             double physical_width, double scene_depth_center) {
  const auto first_left =
      static_cast<GlFloat>(first.position.left.value / physical_width);
  const auto second_left =
      static_cast<GlFloat>(second.position.left.value / physical_width);
  const auto first_depth =
      static_cast<GlFloat>(first.reference_depth - scene_depth_center);
  const auto second_depth =
      static_cast<GlFloat>(second.reference_depth - scene_depth_center);
  constexpr std::array<std::array<GlFloat, 2>, 6> corners{{
      {0.0F, -1.0F},
      {0.0F, 1.0F},
      {1.0F, -1.0F},
      {1.0F, -1.0F},
      {0.0F, 1.0F},
      {1.0F, 1.0F},
  }};
  for (const auto &corner : corners) {
    vertices.push_back(CurveVertex{
        .first_left = first_left,
        .first_depth = first_depth,
        .second_left = second_left,
        .second_depth = second_depth,
        .along = corner[0],
        .side = corner[1],
    });
  }
}

} // namespace

struct GlRenderer::Impl {
  GlFunctions gl;
  std::thread::id owner_thread;
  GlUInt vertex_array{};
  GlUInt vertex_buffer{};
  GlUInt program{};
  GlInt viewport_pixels_uniform{-1};
  GlInt viewport_center_uniform{-1};
  GlInt viewport_half_span_uniform{-1};
  GlInt half_width_uniform{-1};
  GlInt color_uniform{-1};
  double physical_width{};
  double scene_depth_center{};
  std::vector<CurveBatch> batches;
};

GlRenderer::GlRenderer() : impl_(std::make_unique<Impl>()) {}
GlRenderer::~GlRenderer() = default;
GlRenderer::GlRenderer(GlRenderer &&) noexcept = default;
GlRenderer &GlRenderer::operator=(GlRenderer &&) noexcept = default;

bool GlRenderer::initialize(GlProcResolver resolver,
                            void *resolver_context) noexcept {
  if (resolver == nullptr) {
    return false;
  }
  try {
    impl_->gl = load_functions(resolver, resolver_context);
    if (!impl_->gl.complete()) {
      return false;
    }
    const auto vertex =
        compile_shader(impl_->gl, gl_vertex_shader, vertex_shader_source);
    const auto fragment =
        compile_shader(impl_->gl, gl_fragment_shader, fragment_shader_source);
    if (vertex == 0 || fragment == 0) {
      if (vertex != 0) {
        impl_->gl.delete_shader(vertex);
      }
      if (fragment != 0) {
        impl_->gl.delete_shader(fragment);
      }
      return false;
    }
    impl_->program = impl_->gl.create_program();
    if (impl_->program == 0) {
      impl_->gl.delete_shader(vertex);
      impl_->gl.delete_shader(fragment);
      return false;
    }
    impl_->gl.attach_shader(impl_->program, vertex);
    impl_->gl.attach_shader(impl_->program, fragment);
    impl_->gl.link_program(impl_->program);
    impl_->gl.delete_shader(vertex);
    impl_->gl.delete_shader(fragment);
    GlInt linked{};
    impl_->gl.get_program_iv(impl_->program, gl_link_status, &linked);
    if (linked == 0) {
      impl_->gl.delete_program(impl_->program);
      impl_->program = 0;
      return false;
    }

    impl_->owner_thread = std::this_thread::get_id();
    impl_->gl.gen_vertex_arrays(1, &impl_->vertex_array);
    impl_->gl.gen_buffers(1, &impl_->vertex_buffer);
    if (impl_->vertex_array == 0 || impl_->vertex_buffer == 0) {
      release();
      return false;
    }
    impl_->gl.bind_vertex_array(impl_->vertex_array);
    impl_->gl.bind_buffer(gl_array_buffer, impl_->vertex_buffer);
    impl_->gl.enable_vertex_attrib_array(0);
    impl_->gl.vertex_attrib_pointer(
        0, 4, gl_float, static_cast<GlBoolean>(gl_false),
        static_cast<GlSize>(sizeof(CurveVertex)), nullptr);
    impl_->gl.enable_vertex_attrib_array(1);
    impl_->gl.vertex_attrib_pointer(
        1, 2, gl_float, static_cast<GlBoolean>(gl_false),
        static_cast<GlSize>(sizeof(CurveVertex)),
        reinterpret_cast<const void *>(offsetof(CurveVertex, along)));
    impl_->viewport_pixels_uniform =
        impl_->gl.get_uniform_location(impl_->program, "viewportPixels");
    impl_->viewport_center_uniform =
        impl_->gl.get_uniform_location(impl_->program, "viewportCenter");
    impl_->viewport_half_span_uniform =
        impl_->gl.get_uniform_location(impl_->program, "viewportHalfSpan");
    impl_->half_width_uniform =
        impl_->gl.get_uniform_location(impl_->program, "halfWidthPixels");
    impl_->color_uniform =
        impl_->gl.get_uniform_location(impl_->program, "curveColor");
    return initialized();
  } catch (...) {
    abandon();
    return false;
  }
}

bool GlRenderer::upload(const PreparedScene &scene) noexcept {
  if (!initialized() || std::this_thread::get_id() != impl_->owner_thread ||
      scene.physical_width().value <= 0.0) {
    return false;
  }
  try {
    std::vector<CurveVertex> vertices;
    std::vector<CurveBatch> batches;
    const auto depth_range = scene.reference_depth_range();
    const auto scene_depth_center =
        depth_range.top + (depth_range.bottom - depth_range.top) * 0.5;
    for (const auto &layer : scene.curve_layers()) {
      const auto first_vertex = vertices.size();
      for (std::uint64_t segment_offset = 0;
           segment_offset < layer.segment_count; ++segment_offset) {
        const auto &segment = scene.curve_segments()[static_cast<std::size_t>(
            layer.first_segment + segment_offset)];
        for (std::uint64_t point_offset = 1; point_offset < segment.point_count;
             ++point_offset) {
          const auto first_point =
              static_cast<std::size_t>(segment.first_point + point_offset - 1);
          const auto second_point =
              static_cast<std::size_t>(segment.first_point + point_offset);
          append_segment_vertices(vertices, scene.curve_points()[first_point],
                                  scene.curve_points()[second_point],
                                  scene.physical_width().value,
                                  scene_depth_center);
        }
      }
      const auto track =
          std::find_if(scene.tracks().begin(), scene.tracks().end(),
                       [&](const PreparedTrack &candidate) {
                         return candidate.id == layer.track_id;
                       });
      if (track != scene.tracks().end() && vertices.size() > first_vertex) {
        const auto count = vertices.size() - first_vertex;
        if (first_vertex >
                static_cast<std::size_t>(std::numeric_limits<GlInt>::max()) ||
            count >
                static_cast<std::size_t>(std::numeric_limits<GlSize>::max())) {
          return false;
        }
        batches.push_back(CurveBatch{
            .first_vertex = static_cast<GlInt>(first_vertex),
            .vertex_count = static_cast<GlSize>(count),
            .color = layer.color,
            .line_width = layer.line_width,
            .clip = track->clip,
        });
      }
    }
    if (vertices.size() >
        static_cast<std::size_t>(
            std::numeric_limits<GlSizePointer>::max() /
            static_cast<GlSizePointer>(sizeof(CurveVertex)))) {
      return false;
    }
    impl_->gl.bind_vertex_array(impl_->vertex_array);
    impl_->gl.bind_buffer(gl_array_buffer, impl_->vertex_buffer);
    impl_->gl.buffer_data(
        gl_array_buffer,
        static_cast<GlSizePointer>(vertices.size() * sizeof(CurveVertex)),
        vertices.empty() ? nullptr : vertices.data(), gl_static_draw);
    impl_->physical_width = scene.physical_width().value;
    impl_->scene_depth_center = scene_depth_center;
    impl_->batches = std::move(batches);
    return true;
  } catch (...) {
    return false;
  }
}

bool GlRenderer::render(const GlRenderFrame &frame) noexcept {
  if (!initialized() || std::this_thread::get_id() != impl_->owner_thread ||
      frame.framebuffer == 0 || frame.pixel_width <= 0 ||
      frame.pixel_height <= 0 ||
      !std::isfinite(frame.physical_pixels_per_millimetre) ||
      frame.physical_pixels_per_millimetre <= 0.0 ||
      !std::isfinite(frame.viewport.top) ||
      !std::isfinite(frame.viewport.bottom) ||
      frame.viewport.top >= frame.viewport.bottom) {
    return false;
  }
  const auto viewport_center =
      frame.viewport.top + (frame.viewport.bottom - frame.viewport.top) * 0.5;
  const auto viewport_half_span =
      (frame.viewport.bottom - frame.viewport.top) * 0.5;
  if (!std::isfinite(viewport_center) || !std::isfinite(viewport_half_span) ||
      viewport_half_span <= 0.0) {
    return false;
  }

  impl_->gl.bind_framebuffer(gl_framebuffer, frame.framebuffer);
  impl_->gl.viewport(0, 0, frame.pixel_width, frame.pixel_height);
  impl_->gl.disable(gl_depth_test);
  impl_->gl.disable(gl_cull_face);
  impl_->gl.disable(gl_stencil_test);
  impl_->gl.disable(gl_scissor_test);
  impl_->gl.color_mask(static_cast<GlBoolean>(1), static_cast<GlBoolean>(1),
                       static_cast<GlBoolean>(1), static_cast<GlBoolean>(1));
  impl_->gl.stencil_mask(std::numeric_limits<GlUInt>::max());
  impl_->gl.clear_color(1.0F, 1.0F, 1.0F, 1.0F);
  impl_->gl.clear_stencil(0);
  impl_->gl.clear(gl_color_buffer_bit | gl_stencil_buffer_bit);
  impl_->gl.enable(gl_blend);
  impl_->gl.blend_func_separate(gl_src_alpha, gl_one_minus_src_alpha, gl_one,
                                gl_one_minus_src_alpha);
  impl_->gl.use_program(impl_->program);
  impl_->gl.bind_vertex_array(impl_->vertex_array);
  impl_->gl.uniform_2f(impl_->viewport_pixels_uniform,
                       static_cast<GlFloat>(frame.pixel_width),
                       static_cast<GlFloat>(frame.pixel_height));
  impl_->gl.uniform_1f(
      impl_->viewport_center_uniform,
      static_cast<GlFloat>(viewport_center - impl_->scene_depth_center));
  impl_->gl.uniform_1f(impl_->viewport_half_span_uniform,
                       static_cast<GlFloat>(viewport_half_span));
  impl_->gl.enable(gl_scissor_test);
  if (frame.draw_scene) {
    for (const auto &batch : impl_->batches) {
      const auto scissor_left = static_cast<int>(
          std::floor(batch.clip.left.value / impl_->physical_width *
                     static_cast<double>(frame.pixel_width)));
      const auto scissor_width = static_cast<int>(
          std::ceil(batch.clip.width.value / impl_->physical_width *
                    static_cast<double>(frame.pixel_width)));
      impl_->gl.scissor(std::max(0, scissor_left), 0,
                        std::max(0, scissor_width), frame.pixel_height);
      impl_->gl.uniform_1f(
          impl_->half_width_uniform,
          static_cast<GlFloat>(
              std::max(0.5, batch.line_width.value *
                                frame.physical_pixels_per_millimetre * 0.5)));
      impl_->gl.uniform_4f(impl_->color_uniform,
                           static_cast<GlFloat>(batch.color.red) / 255.0F,
                           static_cast<GlFloat>(batch.color.green) / 255.0F,
                           static_cast<GlFloat>(batch.color.blue) / 255.0F,
                           static_cast<GlFloat>(batch.color.alpha) / 255.0F);
      impl_->gl.draw_arrays(gl_triangles, batch.first_vertex,
                            batch.vertex_count);
    }
  }
  if (frame.crosshair.has_value() &&
      std::isfinite(frame.crosshair->horizontal_fraction) &&
      std::isfinite(frame.crosshair->display_depth)) {
    const auto horizontal_fraction =
        std::clamp(frame.crosshair->horizontal_fraction, 0.0, 1.0);
    const auto vertical_fraction =
        (frame.crosshair->display_depth - frame.viewport.top) /
        (frame.viewport.bottom - frame.viewport.top);
    if (vertical_fraction >= 0.0 && vertical_fraction <= 1.0) {
      const auto crosshair_left =
          std::clamp(static_cast<int>(std::lround(
                         horizontal_fraction *
                         static_cast<double>(frame.pixel_width - 1))),
                     0, frame.pixel_width - 1);
      const auto crosshair_bottom =
          std::clamp(static_cast<int>(std::lround(
                         (1.0 - vertical_fraction) *
                         static_cast<double>(frame.pixel_height - 1))),
                     0, frame.pixel_height - 1);
      impl_->gl.clear_color(0.85F, 0.1F, 0.1F, 1.0F);
      impl_->gl.scissor(crosshair_left, 0, 1, frame.pixel_height);
      impl_->gl.clear(gl_color_buffer_bit);
      impl_->gl.scissor(0, crosshair_bottom, frame.pixel_width, 1);
      impl_->gl.clear(gl_color_buffer_bit);
    }
  }
  impl_->gl.disable(gl_scissor_test);
  return true;
}

void GlRenderer::release() noexcept {
  if (std::this_thread::get_id() != impl_->owner_thread) {
    abandon();
    return;
  }
  if (impl_->vertex_buffer != 0) {
    impl_->gl.delete_buffers(1, &impl_->vertex_buffer);
  }
  if (impl_->vertex_array != 0) {
    impl_->gl.delete_vertex_arrays(1, &impl_->vertex_array);
  }
  if (impl_->program != 0) {
    impl_->gl.delete_program(impl_->program);
  }
  abandon();
}

void GlRenderer::abandon() noexcept {
  impl_->vertex_buffer = 0;
  impl_->vertex_array = 0;
  impl_->program = 0;
  impl_->batches.clear();
  impl_->owner_thread = {};
}

bool GlRenderer::initialized() const noexcept {
  return impl_ != nullptr && impl_->program != 0 && impl_->vertex_array != 0 &&
         impl_->vertex_buffer != 0;
}

} // namespace welllog::detail
