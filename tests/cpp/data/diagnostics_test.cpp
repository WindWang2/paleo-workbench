// data.diagnostics — corrupt/future/missing inputs produce diagnostics,
// never crashes or silent repairs (test-plan.md §2, row 10).
#include "pwb_test.hpp"

#include "pwb/data/facade.hpp"
#include "pwb/domain/errors.hpp"

namespace {

namespace fs = std::filesystem;

fs::path fixture(const char* name, const char* file) {
    return fs::path(PWB_DATA_FIXTURE_DIR) / name / file;
}

bool has_code(const pwb::domain::DiagnosticList& diagnostics,
              const std::string& code) {
    for (const auto& diagnostic : diagnostics) {
        if (diagnostic.code == code) return true;
    }
    return false;
}

}  // namespace

PWB_TEST(minimal_opens_clean) {
    pwb::data::DataFacade facade(fixture("minimal", "minimal.paleo.json"));
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    PWB_CHECK(!snapshot.value().read_only);
}

PWB_TEST(corrupt_json_fails_honestly) {
    pwb::data::DataFacade facade(
        fixture("corrupt_json", "typical.paleo.json"));
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(!snapshot.is_ok());
    PWB_CHECK(snapshot.error().code ==
              pwb::domain::ErrorCode::CorruptJson);
}

PWB_TEST(corrupt_db_stays_diagnostic) {
    pwb::data::DataFacade facade(fixture("corrupt_db", "typical.paleo.json"));
    // Must not throw or abort; the project itself still opens.
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    PWB_CHECK(has_code(snapshot.value().diagnostics, "catalog_unreadable"));
}

PWB_TEST(future_schema_read_only) {
    pwb::data::DataFacade facade(
        fixture("future_schema", "typical.paleo.json"));
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    PWB_CHECK(snapshot.value().read_only);
    PWB_CHECK(
        has_code(snapshot.value().diagnostics, "future_schema"));
}

PWB_TEST(missing_resource_warned) {
    pwb::data::DataFacade facade(
        fixture("missing_resource", "typical.paleo.json"));
    auto snapshot = facade.open_snapshot();
    PWB_CHECK(snapshot.is_ok());
    PWB_CHECK(
        has_code(snapshot.value().diagnostics, "resource_missing"));
}
