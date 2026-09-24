# CPP prediction — tiled ONNX inference geometry ported from
# paleo_workbench/prediction/tiled_onnx.py (full-conversion plan M9 first
# slice) plus, under PWB_BUILD_PREDICTION_RUNTIME, the native runtime
# closure: the dynamic-loading ONNX Runtime session, model package/input
# runtime, tiled pipeline with bounded outputs, task service and the
# workflow/catalog seams. Qt-free, Python-free.
#
# ONNX Runtime is an OPTIONAL runtime dependency: the session adapter loads
# it at process start (no link-time dependency), so this library builds and
# the non-ORT oracle tests run without an ONNX Runtime SDK.

# Optional compile-time hint baked into the binary (production also honors
# PALEO_ONNXRUNTIME_LIBRARY and the platform loader search). Tests wire it
# through the ctest environment.
set(PWB_ONNXRUNTIME_LIBRARY "" CACHE FILEPATH
    "Optional ONNX Runtime shared library path baked into the prediction runtime")

add_library(pwb_prediction STATIC
    src/tiled_inference.cpp)
add_library(Pwb::Prediction ALIAS pwb_prediction)
target_include_directories(pwb_prediction PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_prediction PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_prediction requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
target_link_libraries(pwb_prediction PUBLIC Pwb::Domain)
# Bit-exact FP parity with the Python oracle: never contract a*b+c into FMA.
if(NOT MSVC)
    target_compile_options(pwb_prediction PRIVATE -ffp-contract=off)
endif()

# BEGIN CONV-21 — prediction contract cores (postprocess / spatial_result /
# input_contract / model_package pure halves), frozen against the Python
# oracle. Reuses the ingest py_compat/well-tops parser and the interchange
# casefold table instead of duplicating CPython semantics.
if(PWB_BUILD_CONV_21)
    target_sources(pwb_prediction PRIVATE
        src/python_compat.cpp
        src/postprocess.cpp
        src/spatial_result.cpp
        src/input_contract.cpp
        src/model_package.cpp
        src/run_spec.cpp)
    # Pwb::Ingest/Pwb::Interchange are forward references: libs/prediction is
    # added by the CONV-13 block before their own CONV-14/19 blocks run, but
    # CMake resolves link targets at generate time (the root CONV-21 block
    # turns all three on).
    target_link_libraries(pwb_prediction PRIVATE Pwb::Ingest Pwb::Interchange)
endif()
# END CONV-21

# BEGIN PREDICTION-RUNTIME — native runtime closure. The ONNX Runtime C API
# header is vendored (third_party/onnxruntime) so no SDK is needed to
# compile; the shared library is discovered at run time.
if(PWB_BUILD_PREDICTION_RUNTIME)
    target_sources(pwb_prediction PRIVATE
        src/runtime_io.cpp
        src/onnx_session.cpp
        src/model_package_runtime.cpp
        src/prediction_input.cpp
        src/prediction_pipeline.cpp
        src/prediction_service.cpp
        src/integration_seams.cpp)
    target_include_directories(pwb_prediction PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/third_party/onnxruntime")
    target_link_libraries(pwb_prediction PRIVATE Pwb::Interchange)
    if(PWB_ONNXRUNTIME_LIBRARY)
        file(TO_CMAKE_PATH "${PWB_ONNXRUNTIME_LIBRARY}" _pwb_ort_library)
        target_compile_definitions(pwb_prediction PRIVATE
            "PWB_ONNXRUNTIME_LIBRARY=\"${_pwb_ort_library}\"")
        message(STATUS
            "pwb_prediction: ONNX Runtime hint ${_pwb_ort_library}")
    endif()
endif()
# END PREDICTION-RUNTIME

if(BUILD_TESTING)
    add_subdirectory(prediction_tests)
endif()
