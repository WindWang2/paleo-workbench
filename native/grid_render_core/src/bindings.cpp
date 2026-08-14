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
#include "scalar_grid_layer.hpp"

#include <memory>
#include <stdexcept>
#include <vector>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

namespace py = pybind11;

namespace {

using FloatArray = py::array_t<float, py::array::c_style | py::array::forcecast>;
using U8Array = py::array_t<std::uint8_t, py::array::c_style | py::array::forcecast>;

std::vector<float> grid_values(const FloatArray& grid_z, int* width, int* height) {
    const auto view = grid_z.request();
    if (view.ndim != 2) {
        throw std::invalid_argument("grid_z must be a 2-D (height, width) float32 array");
    }
    *height = static_cast<int>(view.shape[0]);
    *width = static_cast<int>(view.shape[1]);
    const auto* first = static_cast<const float*>(view.ptr);
    return {first, first + static_cast<std::size_t>(*width) * static_cast<std::size_t>(*height)};
}

std::vector<std::uint8_t> mask_values(const py::object& mask_obj, const int width,
                                      const int height) {
    if (mask_obj.is_none()) return {};
    const U8Array mask = U8Array::ensure(mask_obj);
    if (!mask) {
        throw std::invalid_argument("mask must be a uint8 array or None");
    }
    const auto view = mask.request();
    if (view.ndim != 2 || view.shape[0] != height || view.shape[1] != width) {
        throw std::invalid_argument("mask must match grid_z shape");
    }
    const auto* first = static_cast<const std::uint8_t*>(view.ptr);
    return {first, first + static_cast<std::size_t>(width) * static_cast<std::size_t>(height)};
}

std::vector<std::uint8_t> ramp_values(const U8Array& ramp) {
    const auto view = ramp.request();
    if (view.ndim != 2 || view.shape[0] < 1 || view.shape[1] != 4) {
        throw std::invalid_argument("color_ramp must be a (size, 4) RGBA uint8 array");
    }
    const auto* first = static_cast<const std::uint8_t*>(view.ptr);
    return {first, first + static_cast<std::size_t>(view.shape[0]) * 4};
}

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
    // shape[0] >= 1 is required: an empty LUT would make the core renderer
    // return early while the output buffer (allocated unzeroed) still holds
    // raw heap garbage that would be handed back to Python.
    if (lu.ndim != 2 || lu.shape[0] < 1 || lu.shape[1] != 4) {
        throw std::invalid_argument("lut must be a (lut_size, 4) RGBA uint8 array with at least one entry");
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

    py::class_<pwb::grid_render::ScalarGridLayer>(m, "ScalarGridLayer")
        .def(py::init([](FloatArray grid_z, py::object mask_obj) {
                 int width = 0;
                 int height = 0;
                 auto values = grid_values(grid_z, &width, &height);
                 return std::make_unique<pwb::grid_render::ScalarGridLayer>(
                     width, height, std::move(values), mask_values(mask_obj, width, height));
             }),
             py::arg("grid_z"), py::arg("mask") = py::none())
        .def_property_readonly("width", &pwb::grid_render::ScalarGridLayer::width)
        .def_property_readonly("height", &pwb::grid_render::ScalarGridLayer::height)
        .def_property_readonly("data_revision",
                               &pwb::grid_render::ScalarGridLayer::data_revision)
        .def_property_readonly("style_revision",
                               &pwb::grid_render::ScalarGridLayer::style_revision)
        .def_property_readonly("rasterize_count",
                               &pwb::grid_render::ScalarGridLayer::rasterize_count)
        .def("set_grid", [](pwb::grid_render::ScalarGridLayer& layer, FloatArray grid_z) {
            int width = 0;
            int height = 0;
            auto values = grid_values(grid_z, &width, &height);
            if (width != layer.width() || height != layer.height()) {
                throw std::invalid_argument("new grid_z shape must match the layer shape");
            }
            layer.set_grid(std::move(values));
        }, py::arg("grid_z"))
        .def("set_mask", [](pwb::grid_render::ScalarGridLayer& layer, py::object mask_obj) {
            layer.set_mask(mask_values(mask_obj, layer.width(), layer.height()));
        }, py::arg("mask") = py::none())
        .def("set_color_ramp", [](pwb::grid_render::ScalarGridLayer& layer, U8Array ramp) {
            layer.set_color_ramp(ramp_values(ramp));
        }, py::arg("color_ramp"))
        .def("set_color_range", &pwb::grid_render::ScalarGridLayer::set_color_range,
             py::arg("lo"), py::arg("hi"))
        .def("set_gamma", &pwb::grid_render::ScalarGridLayer::set_gamma,
             py::arg("gamma"))
        .def("rasterize", [](pwb::grid_render::ScalarGridLayer& layer) {
            py::array_t<std::uint8_t> out({layer.height(), layer.width(), 4});
            auto* destination = out.mutable_data();
            const auto destination_size = static_cast<std::size_t>(out.nbytes());
            {
                py::gil_scoped_release release;
                layer.rasterize_into(destination, destination_size);
            }
            return out;
        });
}
