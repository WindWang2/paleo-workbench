# pwb-bench — Qt-free native benchmark harness (cpp-close wave line 14).
# Measures the library closure's real entry points only; mounted by the
# root LINE-14 block when PWB_BUILD_BENCH=ON. Not a test double and not
# wired into production targets — evidence tooling.
add_executable(pwb-bench
    bench_common.cpp
    bench_catalog.cpp
    bench_seismic.cpp
    bench_project.cpp
    bench_tiled.cpp
    main.cpp)
target_compile_features(pwb-bench PRIVATE cxx_std_20)
target_link_libraries(pwb-bench PRIVATE
    Pwb::Prediction Pwb::Catalog Pwb::SeismicIo Pwb::Project)
target_compile_definitions(pwb-bench PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
if(PWB_BUILD_PREDICTION_RUNTIME)
    target_compile_definitions(pwb-bench PRIVATE PWB_BENCH_PREDICTION_RUNTIME=1)
endif()
# POSIX-only evidence tool: bench sources use unistd.h / sys/utsname.h /
# /proc/self/io for RSS+IO counters — no MSVC port is provided.
install(TARGETS pwb-bench RUNTIME DESTINATION tools)
