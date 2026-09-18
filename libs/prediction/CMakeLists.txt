# CPP prediction — tiled ONNX inference geometry ported from
# paleo_workbench/prediction/tiled_onnx.py (full-conversion plan M9 first
# slice). Qt-free, Python-free; the ONNX session itself is a seam
# (pwb::prediction::InferenceSession) so the frozen CPU-stub oracle path
# builds and runs without libonnxruntime.

# ONNX Runtime is an OPTIONAL runtime: discovery is attempted but absence is
# normal — the stub oracle path is the deliverable of this slice and no
# ORT-only translation unit exists yet (13-decisions.md D8).
find_package(onnxruntime CONFIG QUIET)
if(onnxruntime_FOUND)
    message(STATUS "pwb_prediction: onnxruntime found (ORT session adapter pending; stub-only slice)")
endif()

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
        src/model_package.cpp)
    # Pwb::Ingest/Pwb::Interchange are forward references: libs/prediction is
    # added by the CONV-13 block before their own CONV-14/19 blocks run, but
    # CMake resolves link targets at generate time (the root CONV-21 block
    # turns all three on).
    target_link_libraries(pwb_prediction PRIVATE Pwb::Ingest Pwb::Interchange)
endif()
# END CONV-21

if(BUILD_TESTING)
    add_subdirectory(prediction_tests)
endif()
