#pragma once

#include <string>

#include <welllog/render_gl/export.hpp>

namespace welllog {

struct WELLLOG_RENDER_GL_API CapabilityReport {
  bool initialization_complete{};
  bool graphics_available{};
  bool core_profile{};
  int open_gl_major{};
  int open_gl_minor{};
  int stencil_bits{};
  int maximum_texture_size{};
  std::string vendor;
  std::string renderer;
  std::string open_gl_version;
  std::string glsl_version;
  std::string unavailable_reason;
};

} // namespace welllog
