# CPP seismic_io — native seismic volume IO (Qt-free, Python-free).
#
# Surfaces (see docs/development/cpp-seismic-native-stack/v3-contracts.md):
#   * segy_reader      — frozen whole-volume read (parity-guarded).
#   * segy_layout      — metadata-only SEG-Y inspection + trace->file map.
#   * tile_read        — half-open sub-volume window reads (SEG-Y + PWBVOL1),
#                        cooperative cancellation, never a full-volume copy.
#   * tile_cache       — bounded LRU tile cache with a byte budget.
# Pwb::Domain supplies the canonical JSON codec used by the PWBVOL1 header
# (same codec the payload writer uses — no second parser). Reuse the target
# when the consuming superproject already provides it.
if(NOT TARGET Pwb::Domain)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../domain domain)
endif()
add_library(pwb_seismic_io STATIC
    src/segy_layout.cpp
    src/tile_cache.cpp
    src/tile_read.cpp
    src/segy_reader.cpp)
add_library(Pwb::SeismicIo ALIAS pwb_seismic_io)
target_include_directories(pwb_seismic_io PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_seismic_io PUBLIC cxx_std_20)
target_link_libraries(pwb_seismic_io PUBLIC Pwb::Domain)
