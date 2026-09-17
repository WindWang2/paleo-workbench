# CPP seismic_io — minimal post-stack SEG-Y reader (Qt-free). Feeds the
# attribute kernels (E) and the slice viewer (D) with real survey data.
add_library(pwb_seismic_io STATIC
    src/segy_reader.cpp)
add_library(Pwb::SeismicIo ALIAS pwb_seismic_io)
target_include_directories(pwb_seismic_io PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_seismic_io PUBLIC cxx_std_20)
