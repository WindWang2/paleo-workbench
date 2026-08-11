// bindings.cpp — pybind11 wrapper around the pure-C++ rasteriser in grid_render_core.cpp.
//
// Built by setup.py (Pybind11Extension); verified numerically by standalone_test.cpp
// (plain g++, no Python). Exposes one function:
//
//   grid_render_core.render_grid_rgba(grid_z, lut, lo, hi, mask=None, gamma=1.0, opacity=255)
//     -> numpy.ndarray uint8 (H, W, 4)
//
// The heavy loop releases the GIL.
#include "grid_render_core.hpp"

#include <stdexcept>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

namespace py = pybind11;

namespace {

using FloatArray = py::array_t<float, py::array::c_style | py::array::forcecast>;
using U8Array = py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast>;

py::array_t<std::uint8_t> render_grid_rgba_py(
    FloatArray grid_z, py::object mask_obj, U8Array lut, float lo, float hi,
    float gamma, std::uint8_t opacity) {
    auto gz = grid_z.request();
    if (gz.ndim != 2) {
        throw std::invalid_argument("grid_z must be a 2-D (height, width) float32 array");
    }
    const int height = static_cast<int>(gz.shape[0]);
    const int width = static_cast<int>(gz.shape[1]);

    auto lu = lut.request();
    if (lu.ndim != 2 || lu.shape[1] != 4) {
        throw std::invalid_argument("lut must be a (lut_size, 4) RGBA uint8 array");
    }
    const int lut_size = static_cast<int>(lu.shape[0]);

    const std::uint8_t* mask_ptr = nullptr;
    U8Array mask_arr;
    if (!mask_obj.is_none()) {
        mask_arr = U8Array::ensure(mask_obj);
        if (!mask_arr) {
            throw std::invalid_argument("mask must be a uint8 array or None");
        }
        auto m = mask_arr.request();
        if (m.ndim != 2 || m.shape[0] != height || m.shape[1] != width) {
            throw std::invalid_argument("mask must match grid_z shape");
        }
        mask_ptr = static_cast<const std::uint8_t*>(m.ptr);
    }

    py::array_t<std::uint8_t> out({height, width, 4});
    auto o = out.request();
    {
        py::gil_scoped_release release;
        pwb::grid_render::render_grid_rgba(
            width, height,
            static_cast<const float*>(gz.ptr),
            mask_ptr,
            static_cast<const std::uint8_t*>(lu.ptr),
            lut_size, lo, hi, gamma, opacity,
            static_cast<std::uint8_t*>(o.ptr));
    }
    return out;
}

}  // namespace

PYBIND11_MODULE(grid_render_core, m) {
    m.doc() = "Native scalar-grid rasterisation hot path for paleo-workbench factor maps.";
    m.def(
        "render_grid_rgba",
        &render_grid_rgba_py,
        py::arg("grid_z"),
        py::arg("mask") = py::none(),
        py::arg("lut"),
        py::arg("lo"),
        py::arg("hi"),
        py::arg("gamma") = 1.0f,
        py::arg("opacity") = 255);
}
