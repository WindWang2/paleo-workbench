# UI-11 — ui_review tests. ctest names: ui_review.* — a Qt-free core
# smoke (headless, every semantic core) plus an offscreen Qt widget smoke
# (QTRY-pumped worker seams). No QGIS: the composite prototype lives on
# pwb_ui_review_qgis and is covered manually where the bridge exists.

# --- core smoke (Qt-free) -------------------------------------------------
add_executable(ui_review.core_smoke core_smoke_test.cpp)
target_compile_features(ui_review.core_smoke PRIVATE cxx_std_20)
target_link_libraries(ui_review.core_smoke PRIVATE
    Pwb::UiReview Pwb::Catalog Pwb::Data Pwb::Domain
    Pwb::WorkflowContracts Pwb::UiDataCore)
target_include_directories(ui_review.core_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_review.core_smoke COMMAND ui_review.core_smoke)
set_tests_properties(ui_review.core_smoke PROPERTIES TIMEOUT 120)

# --- Qt widget smoke (offscreen, no QGIS) ---------------------------------
if(TARGET pwb_ui_review_qt)
    # QSignalSpy/QTRY live in Qt6::Test — not part of the platform
    # component list.
    find_package(Qt6 COMPONENTS Test)
    add_executable(ui_review.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_review.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_review.qt_widgets_smoke PROPERTIES
        AUTOMOC ON)
    target_link_libraries(ui_review.qt_widgets_smoke PRIVATE
        Pwb::UiReviewQt Qt6::Widgets Qt6::Test)
    target_include_directories(ui_review.qt_widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_review.qt_widgets_smoke
             COMMAND ui_review.qt_widgets_smoke)
    set_tests_properties(ui_review.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
