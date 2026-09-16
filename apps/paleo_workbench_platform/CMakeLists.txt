add_executable(pwb-platform
    main.cpp
    main_window.cpp
)
target_include_directories(pwb-platform PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(pwb-platform PRIVATE cxx_std_20)
target_link_libraries(pwb-platform PRIVATE Pwb::Application Pwb::Ui)

# Runtime closure: QGIS vendor bin + Qt bin (single ABI, no PATH guessing at
# dev time; the deployed package carries its own layout instead).
set_target_properties(pwb-platform PROPERTIES
    BUILD_RPATH "${PALEO_QGIS_RUNTIME}"
    VS_DEBUGGER_ENVIRONMENT "PATH=${PWB_QT_RUNTIME};${PALEO_QGIS_RUNTIME};$ENV{PATH}")
